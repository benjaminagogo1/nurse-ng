"""Repeatable PostgreSQL learning migration and concurrency verification.

Run with NURSE_NG_TEST_POSTGRES_URL pointing at a loopback PostgreSQL database
named exactly nurse_ng_learning_test. Each invocation creates two unique schemas
and drops only those schemas afterward. Fresh and historical migration checks
therefore neither depend on prior runs nor erase other tests' records.

Media transport is mocked; browser grants contain synthetic signed credentials
and are never printed. This runner verifies real PostgreSQL row locks through
the same route helpers used for classroom grants, starts and staff revocation.
It cannot establish the health of a deployed LiveKit server or physical devices.
The reminder volume check traverses more than one fetch batch while writing the
real notification outbox, then repeats the pass to verify committed deduplication.
"""

import argparse
import json
import os
import secrets
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from ipaddress import ip_address
from pathlib import Path
from threading import Barrier, Event
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def isolated_database():
    """Refuse production names, remote hosts and libpq query overrides."""
    value = os.environ.get("NURSE_NG_TEST_POSTGRES_URL", "")
    try:
        url = make_url(value)
    except Exception:
        raise RuntimeError("Set a plain loopback PostgreSQL test database URL.") from None
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg")
    if (
        url.get_backend_name() != "postgresql"
        or url.database != "nurse_ng_learning_test"
        or url.host not in {"127.0.0.1", "::1", "localhost"}
        or url.query
    ):
        raise RuntimeError(
            "Use a plain loopback PostgreSQL URL for the database nurse_ng_learning_test."
        )
    return url


def environment(database, storage):
    """Disable outbound services and override private development dotenv settings."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("NURSE_NG_")}
    env.update(
        {
            "NURSE_NG_ENVIRONMENT": "development",
            "NURSE_NG_DATABASE_URL": database,
            "NURSE_NG_SECRET_KEY": secrets.token_urlsafe(32),
            "NURSE_NG_ALLOWED_HOSTS": "localhost,127.0.0.1,::1",
            "NURSE_NG_PUBLIC_BASE_URL": "http://localhost",
            "NURSE_NG_ACCOUNT_MAIL_BACKEND": "disabled",
            "NURSE_NG_REQUIRED_WORKERS": "",
            "NURSE_NG_RECRUITMENT_SEARXNG_URLS": "",
            "NURSE_NG_RECRUITMENT_SEARCH_KEY": "",
            "NURSE_NG_RECRUITMENT_SEARCH_PERMISSION_REFERENCE": "",
            "NURSE_NG_LIVEKIT_URL": "wss://learning.example.test",
            "NURSE_NG_LIVEKIT_API_KEY": "synthetic-postgres-provider",
            "NURSE_NG_LIVEKIT_API_SECRET": "synthetic-provider-secret-" * 3,
            "NURSE_NG_LEARNING_RECORDING_S3_BUCKET": "",
            "NURSE_NG_LEARNING_RECORDING_S3_ACCESS_KEY": "",
            "NURSE_NG_LEARNING_RECORDING_S3_SECRET_KEY": "",
            "NURSE_NG_LEARNING_RECORDING_S3_ENDPOINT": "",
            "NURSE_NG_AVATAR_DIR": str(storage / "avatars"),
            "NURSE_NG_COMMUNITY_MEDIA_DIR": str(storage / "community"),
            "NURSE_NG_EVIDENCE_DIR": str(storage / "evidence"),
            "NURSE_NG_MESSAGE_MEDIA_DIR": str(storage / "messages"),
            "NURSE_NG_ACCOUNT_MAIL_DIR": str(storage / "mail"),
        }
    )
    return env


def migrate(env, *arguments):
    """Exercise the deployment's Alembic entry point against one isolated schema."""
    result = subprocess.run(
        [str(ROOT / "venv/bin/alembic"), *arguments],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)


def learning_checks(engine):
    """Use independent transactions for capacity and educator revocation races."""
    from app.models.education import LearningSession, SessionRegistration
    from app.models.notifications import Notification
    from app.models.user import User
    from app.services import education, education_live
    from app.services.education_notifications import queue_learning_reminders
    from app.web.education_classroom_routes import _lock_educator, _token, _transition
    from app.web.education_routes import _review_educator

    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with sessions() as db:
        users = {
            role: User(
                phone=f"+23489998881{number:02}",
                hashed_password="unused-isolated-postgres-hash",
                is_staff=role == "staff",
            )
            for number, role in enumerate(("teacher", "staff", "first", "second"), 1)
        }
        db.add_all(users.values())
        db.commit()
        ids = {role: user.id for role, user in users.items()}
        education.apply_educator(
            db,
            users["teacher"],
            {
                "display_name": "Isolated educator",
                "headline": "PostgreSQL learning checks",
                "bio": "Synthetic teaching profile for isolated verification.",
            },
        )
        education.review_educator(db, users["staff"], ids["teacher"], "approved")

    def create_session(*, capacity=2):
        with sessions() as db:
            starts = datetime.now(UTC) - timedelta(minutes=5)
            row = education.create_session(
                db,
                db.get(User, ids["teacher"]),
                {
                    "title": "Isolated classroom",
                    "description": "Synthetic concurrency check.",
                    "starts_at": starts,
                    "ends_at": starts + timedelta(hours=1),
                    "timezone": "Africa/Lagos",
                    "capacity": capacity,
                    "status": "scheduled",
                },
            )
            return row.id

    capacity_session = create_session(capacity=1)
    competing = Barrier(2)

    def reserve(role):
        with sessions() as db:
            user = db.get(User, ids[role])
            competing.wait(timeout=10)
            try:
                education.register_session(db, user, capacity_session)
                return "reserved"
            except education.EducationError:
                db.rollback()
                return "full"

    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(reserve, ("first", "second")))
    assert sorted(outcomes) == ["full", "reserved"], outcomes
    with sessions() as db:
        assert db.get(LearningSession, capacity_session).reserved_count == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(SessionRegistration)
                .where(SessionRegistration.session_id == capacity_session)
            )
            == 1
        )

    # A first-batch LIMIT can repeatedly revisit already-reminded sessions and
    # starve later lectures. More than 200 due rows also exercises PostgreSQL's
    # streaming cursor alongside outbox inserts and the final transaction commit.
    now = datetime.now(UTC)
    with sessions() as db:
        due = [
            LearningSession(
                educator_id=ids["teacher"],
                title="Isolated reminder-volume lecture",
                description="Synthetic reminder fetch-batch verification.",
                starts_at=now + timedelta(minutes=30),
                ends_at=now + timedelta(minutes=90),
                timezone="Africa/Lagos",
                capacity=10,
                reserved_count=1,
                status="scheduled",
            )
            for _ in range(202)
        ]
        db.add_all(due)
        db.flush()
        due_ids = {row.id for row in due}
        db.add_all(
            SessionRegistration(session_id=row.id, user_id=ids["first"], status="reserved")
            for row in due
        )
        db.commit()
        assert queue_learning_reminders(db, now=now) == 202
    with sessions() as db:
        # A fresh worker transaction must deduplicate the persisted notices,
        # independently of ORM identities retained by the first queueing pass.
        assert queue_learning_reminders(db, now=now) == 202
    with sessions() as db:
        reminders = list(
            db.scalars(
                select(Notification).where(
                    Notification.kind == "learning_reminder",
                    Notification.recipient_id == ids["first"],
                    Notification.learning_session_id.in_(due_ids),
                )
            )
        )
        assert len(reminders) == 202
        assert {notice.learning_session_id for notice in reminders} == due_ids
        assert all(notice.email_state == "skipped" for notice in reminders)

    created_rooms, closed_rooms = [], []

    def revocation_race(session_id, operation):
        """Hold the real educator lock while a competing grant/start reaches it."""
        locked, attempting, completed, release = (Event() for _ in range(4))

        def revoke():
            with sessions() as db:
                _lock_educator(db, ids["teacher"])
                locked.set()
                assert release.wait(timeout=10)
                _review_educator(
                    db, db.get(User, ids["staff"]), ids["teacher"], "paused", "Isolated race"
                )

        def attempt():
            with sessions() as db:
                role = "first" if operation == "token" else "teacher"
                user = db.get(User, ids[role])
                attempting.set()
                try:
                    if operation == "token":
                        _token(db, user, session_id, {})
                    else:
                        _transition(db, user, session_id, "live")
                    return "unexpectedly allowed"
                except education.EducationError:
                    db.rollback()
                    return "permission revoked"
                finally:
                    completed.set()

        with ThreadPoolExecutor(max_workers=2) as workers:
            revocation = workers.submit(revoke)
            assert locked.wait(timeout=10)
            contender = workers.submit(attempt)
            try:
                assert attempting.wait(timeout=10)
                # Without the shared row lock this contender finishes before
                # revocation. The short bounded wait makes that regression visible.
                blocked = not completed.wait(timeout=0.25)
            finally:
                release.set()
            revocation.result(timeout=15)
            assert contender.result(timeout=15) == "permission revoked"
            assert blocked, f"{operation} did not wait for the educator decision"

    with (
        patch.object(
            education_live,
            "create_room",
            side_effect=lambda sid, **kw: created_rooms.append(sid) or {},
        ),
        patch.object(
            education_live, "delete_room", side_effect=lambda sid: closed_rooms.append(sid) or {}
        ),
    ):
        token_session = create_session()
        with sessions() as db:
            education.register_session(db, db.get(User, ids["first"]), token_session)
            _transition(db, db.get(User, ids["teacher"]), token_session, "live")
        revocation_race(token_session, "token")
        with sessions() as db:
            assert db.get(LearningSession, token_session).status == "ended"
            education.review_educator(db, db.get(User, ids["staff"]), ids["teacher"], "approved")
        assert token_session in closed_rooms
        start_session = create_session()
        before = len(created_rooms)
        revocation_race(start_session, "start")
        assert len(created_rooms) == before
        with sessions() as db:
            assert db.get(LearningSession, start_session).status == "scheduled"

    return {
        "concurrent_capacity": "one reservation for one seat",
        "reminder_volume_and_dedupe": (
            "202 due sessions; 202 committed notices after repeated passes"
        ),
        "token_vs_revocation": "blocked, then denied after closure and approval change",
        "start_vs_revocation": "blocked, then denied before provider room creation",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Write the verification summary as JSON.")
    args = parser.parse_args()
    url = isolated_database()
    admin = create_engine(url)
    schemas = ["learning_fresh_" + uuid4().hex, "learning_historical_" + uuid4().hex]
    created = []
    engines = []
    try:
        with admin.connect() as conn:
            name, address = conn.execute(
                text("SELECT current_database(), host(inet_server_addr())")
            ).one()
            assert name == "nurse_ng_learning_test" and ip_address(address).is_loopback
        with admin.begin() as conn:
            for schema in schemas:
                conn.execute(CreateSchema(schema))
                created.append(schema)
        with tempfile.TemporaryDirectory(prefix="nurse-learning-postgres-") as storage:
            urls = [
                url.update_query_dict({"options": f"-csearch_path={schema}"}) for schema in schemas
            ]
            envs = [
                environment(value.render_as_string(hide_password=False), Path(storage))
                for value in urls
            ]
            fresh_env, historical_env = envs
            migrate(historical_env, "upgrade", "e6480j0f6527")
            historical = create_engine(urls[1])
            engines.append(historical)
            user_id, notice_id = uuid4(), uuid4()
            with historical.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO users (id,phone,hashed_password,status,phone_verified,"
                        "mfa_enabled,is_active,is_staff) "
                        "VALUES (:id,'+2348999888000','unused','active',false,false,true,false)"
                    ),
                    {"id": user_id},
                )
                conn.execute(
                    text(
                        "INSERT INTO notifications "
                        "(id,recipient_id,actor_id,category,kind,event_key,"
                        "in_app,application_status,email_to,email_state,email_attempts) "
                        "VALUES (:id,:user,:user,'community','reply',"
                        "'historical-preserved',true,'','','skipped',0)"
                    ),
                    {"id": notice_id, "user": user_id},
                )
            migrate(historical_env, "upgrade", "head")
            migrate(historical_env, "check")
            with historical.connect() as conn:
                assert conn.execute(text("SELECT event_key FROM notifications")).scalar_one() == (
                    "historical-preserved"
                )
                assert conn.execute(text("SELECT count(*) FROM users")).scalar_one() == 1
            migrate(fresh_env, "upgrade", "head")
            migrate(fresh_env, "check")
            for name in tuple(os.environ):
                if name.startswith("NURSE_NG_"):
                    del os.environ[name]
            os.environ.update(fresh_env)
            fresh = create_engine(urls[0])
            engines.append(fresh)
            summary = {
                "verified_at": datetime.now(UTC).isoformat(),
                "database": "isolated loopback PostgreSQL",
                "fresh_migration_and_metadata": "passed",
                "historical_migration_and_metadata": (
                    "passed; existing member and notification preserved"
                ),
                **learning_checks(fresh),
                "media_transport": "mocked; no live provider calls",
            }
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2))
    finally:
        for engine in engines:
            engine.dispose()
        if created:
            with admin.begin() as conn:
                for schema in reversed(created):
                    conn.execute(DropSchema(schema, cascade=True, if_exists=True))
        admin.dispose()


if __name__ == "__main__":
    main()
