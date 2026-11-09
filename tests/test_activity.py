"""Meaningful usage counts, privacy, authentication, concurrency and migration safety."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import Base
from app.db.session import enable_sqlite_foreign_keys
from app.models.activity import UserDailyActivity as Activity
from app.models.user import User
from app.services import activity as service
from tests.helpers import csrf_from, register_and_sign_in

AT = datetime(2026, 11, 9, 23, 2, tzinfo=UTC)


def account(db, number=1, **values):
    user = User(
        phone=f"+23480000{number:05}",
        hashed_password="unused",
        full_name=f"Member {number}",
        **values,
    )
    db.add(user)
    db.commit()
    return user


def visit(db, user, at=AT, *, version=None):
    changed = service.record_activity(
        db, user.id, user.auth_version if version is None else version, at=at
    )
    db.commit()
    return changed


def signed_in(client, db, *, staff=False):
    register_and_sign_in(client)
    user = db.scalar(select(User))
    user.full_name, user.is_staff = "Account Owner", staff
    db.commit()
    return user


def test_repeated_visits_are_one_account_day_and_times_never_move_backwards(db_session):
    user = account(db_session)
    unchanged_updated_at = user.updated_at
    assert visit(db_session, user)
    assert not visit(db_session, user, AT + timedelta(seconds=59))
    assert visit(db_session, user, AT + timedelta(seconds=60))
    assert visit(db_session, user, AT - timedelta(seconds=30))
    rows = db_session.scalars(select(Activity)).all()
    assert len(rows) == 1
    assert service.utc(rows[0].first_seen_at) == AT - timedelta(seconds=30)
    assert service.utc(rows[0].last_seen_at) == AT + timedelta(seconds=60)
    assert user.updated_at == unchanged_updated_at


def test_day_rollover_is_nigerian_midnight_even_inside_write_interval(db_session):
    user = account(db_session)
    before = datetime(2026, 11, 9, 22, 59, 59, tzinfo=UTC)
    assert visit(db_session, user, before)
    assert visit(db_session, user, before + timedelta(seconds=1))
    dates = db_session.scalars(
        select(Activity.activity_date).order_by(Activity.activity_date)
    ).all()
    assert dates == [date(2026, 11, 9), date(2026, 11, 10)]
    report = service.activity_report(db_session, at=before + timedelta(seconds=2))
    assert report["today"] == report["week"] == report["month"] == report["recent"] == 1


def test_recent_activity_can_cross_midnight_without_a_visit_today(db_session):
    user = account(db_session)
    visit(db_session, user, AT - timedelta(minutes=4))
    report = service.activity_report(db_session, at=AT)
    assert report["today"] == 0 and report["recent"] == report["week"] == 1
    assert service.member_activity(db_session, activity="today", at=AT)["total"] == 0
    assert service.member_activity(db_session, activity="recent", at=AT)["total"] == 1


def test_unique_period_counts_role_and_staff_scope_and_account_state(db_session):
    first, returning, never = [account(db_session, n) for n in (1, 2, 3)]
    staff = account(db_session, 4, is_staff=True)
    employer = account(db_session, 5, account_type="employer")
    suspended = account(db_session, 6)
    for user in (first, staff, employer, suspended):
        visit(db_session, user)
    visit(db_session, first, AT - timedelta(days=2))
    visit(db_session, first, AT - timedelta(days=31))
    visit(db_session, returning, AT - timedelta(days=6))
    suspended.status = "suspended"
    db_session.commit()
    report = service.activity_report(db_session, at=AT)
    assert {
        key: report[key] for key in ("total", "enabled", "today", "week", "month", "recent")
    } == {
        "total": 4,
        "enabled": 3,
        "today": 2,
        "week": 3,
        "month": 3,
        "recent": 1,
    }
    assert len(report["history"]) == 14 and report["history"][0]["count"] == 2
    assert report["participation"] == 50
    assert service.activity_report(db_session, include_staff=True, at=AT)["today"] == 3
    assert service.activity_report(db_session, account_type="employer", at=AT)["total"] == 1
    assert service.activity_report(db_session, account_type="all", at=AT)["today"] == 3
    never_card = service.member_activity(db_session, activity="never", at=AT)["cards"][0]
    assert never_card["user"].id == never.id and never_card["last_seen"] is None
    assert never_card["days_active"] == 0


def test_history_does_not_invent_visits_from_account_creation_or_before_tracking(db_session):
    user = account(db_session)
    user.created_at = AT - timedelta(days=100)
    db_session.commit()
    report = service.activity_report(db_session, at=AT)
    assert report["history"] == [] and report["today"] == 0 and not report["first_record"]
    visit(db_session, user, AT - timedelta(days=2))
    history = service.activity_report(db_session, days=30, at=AT)["history"]
    assert len(history) == 3
    assert [day["count"] for day in history] == [0, 0, 1]


@pytest.mark.parametrize("state", ["suspended", "deactivated", "inactive", "revoked", "deleted"])
def test_ineligible_identity_cannot_record_activity(db_session, state):
    user = account(db_session)
    identifier, version = user.id, user.auth_version
    if state == "deleted":
        db_session.delete(user)
    elif state == "inactive":
        user.is_active = False
    elif state == "revoked":
        user.auth_version += 1
    else:
        user.status = state
    db_session.commit()
    assert not service.record_activity(db_session, identifier, version, at=AT)
    db_session.commit()
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 0


def test_search_ids_literal_wildcards_filters_and_pagination(db_session):
    users = [account(db_session, number) for number in range(1, 29)]
    users[0].full_name = "Literal 100% Nurse"
    db_session.commit()
    visit(db_session, users[0])
    first = service.member_activity(db_session, at=AT)
    second = service.member_activity(db_session, page=2, at=AT)
    assert first["total"] == second["total"] == 28
    assert len(first["cards"]) == 25 and len(second["cards"]) == 3
    assert not {c["user"].id for c in first["cards"]} & {c["user"].id for c in second["cards"]}
    assert service.member_activity(db_session, query="%", at=AT)["total"] == 1
    assert service.member_activity(db_session, query="_", at=AT)["total"] == 0
    assert service.member_activity(db_session, query=str(users[2].id), at=AT)["total"] == 1
    assert service.member_activity(db_session, activity="today", at=AT)["total"] == 1
    assert service.member_activity(db_session, page=100, at=AT)["page"] == 2


def test_settings_exposes_only_the_owners_id_and_staff_dashboard_is_private(client, db_session):
    for path in ("/staff/users", "/staff/users/data"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303 and response.headers["location"] == "/auth/login"
    owner = signed_in(client, db_session)
    other = account(db_session, 22)
    settings_page = client.get("/settings")
    assert str(owner.id) in settings_page.text and str(other.id) not in settings_page.text
    assert '/staff/users"' not in settings_page.text
    for path in ("/staff/users", "/staff/users/data"):
        assert client.get(path).status_code == 403
    owner.is_staff = True
    db_session.commit()
    dashboard = client.get("/staff/users")
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.headers["cache-control"] == "no-store"
    assert str(other.id) in dashboard.text and str(owner.id) not in dashboard.text
    assert 'data-metric="total">1<' in dashboard.text
    all_staff = client.get("/staff/users?include_staff=1")
    assert str(owner.id) in all_staff.text
    fragment = client.get("/staff/users/data")
    assert fragment.status_code == 200 and str(other.id) in fragment.text
    assert fragment.headers["cache-control"] == "no-store"
    owner.is_staff = False
    db_session.commit()
    assert client.get("/staff/users/data").status_code == 403


def test_navigations_record_activity_but_polling_prefetch_assets_and_errors_do_not(
    client, db_session, monkeypatch
):
    monkeypatch.setattr(service, "now", lambda: AT)
    user = signed_in(client, db_session, staff=True)
    client.get("/settings")
    monkeypatch.setattr(service, "now", lambda: AT + timedelta(minutes=10))
    for path in (
        "/notifications/summary",
        "/staff/users/data",
        "/static/js/activity.js",
        "/missing",
    ):
        client.get(path)
    client.get("/settings", headers={"Sec-Fetch-Mode": "cors"})
    worker_navigation = {
        "X-Nurse-Navigation": "document",
        "Sec-Fetch-Mode": "same-origin",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Site": "same-origin",
    }
    client.get("/settings", headers={**worker_navigation, "X-Nurse-Navigation": ""})
    client.get("/settings", headers={**worker_navigation, "Sec-Purpose": "prefetch"})
    client.get("/settings", headers={"Sec-Purpose": "prefetch"})
    client.post("/activity/pulse", data={"csrf_token": "bad"})
    row = db_session.get(Activity, (user.id, service.local_day(AT)))
    assert service.utc(row.last_seen_at) == AT
    assert client.get("/settings").status_code == 200
    db_session.expire(row)
    assert service.utc(row.last_seen_at) == AT + timedelta(minutes=10)
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 1
    monkeypatch.setattr(service, "now", lambda: AT + timedelta(minutes=20))
    assert client.get("/settings", headers=worker_navigation).status_code == 200
    db_session.expire(row)
    assert service.utc(row.last_seen_at) == AT + timedelta(minutes=20)
    assert db_session.scalar(select(func.count()).select_from(Activity)) == 1


def test_pulse_uses_authenticated_id_server_time_and_csrf_and_stops_after_logout(
    client, db_session, monkeypatch
):
    user = signed_in(client, db_session)
    other = account(db_session, 2)
    monkeypatch.setattr(service, "now", lambda: AT)
    token = csrf_from(client.get("/settings"))
    monkeypatch.setattr(service, "now", lambda: AT + timedelta(minutes=2))
    assert client.post("/activity/pulse").status_code == 400
    response = client.post(
        "/activity/pulse",
        data={
            "csrf_token": token,
            "user_id": str(other.id),
            "at": "2099-01-01",
        },
    )
    assert response.status_code == 204 and response.headers["cache-control"] == "no-store"
    rows = db_session.scalars(select(Activity)).all()
    assert len(rows) == 1 and rows[0].user_id == user.id
    assert service.utc(rows[0].last_seen_at) == AT + timedelta(minutes=2)
    client.post("/auth/logout", data={"csrf_token": token}, follow_redirects=False)
    assert (
        client.post(
            "/activity/pulse", data={"csrf_token": token}, follow_redirects=False
        ).status_code
        == 303
    )


@pytest.mark.parametrize(
    "query", ["days=3", "account_type=bad", "activity=bad", "page=0", "q=" + "x" * 121]
)
def test_invalid_dashboard_filters_are_rejected(client, db_session, query):
    signed_in(client, db_session, staff=True)
    assert client.get("/staff/users?" + query).status_code in {400, 422}
    assert client.get("/staff/users/data?" + query).status_code in {400, 422}


def test_activity_failure_does_not_break_page_or_log_sensitive_details(
    client, db_session, monkeypatch, caplog
):
    signed_in(client, db_session)
    # Earlier migration tests let Alembic reconfigure/disable existing loggers.
    monkeypatch.setattr(service.logger, "disabled", False)

    def unavailable(*args, **kwargs):
        raise OperationalError("sensitive-sql", {"secret": "do-not-log"}, Exception("private"))

    monkeypatch.setattr(service, "record_activity", unavailable)
    response = client.get("/settings")
    assert response.status_code == 200
    assert "Account activity could not be recorded (OperationalError)." in caplog.text
    assert "do-not-log" not in caplog.text and "sensitive-sql" not in caplog.text
    assert (
        client.post(
            "/activity/pulse",
            data={
                "csrf_token": csrf_from(response),
            },
        ).status_code
        == 503
    )


def test_concurrent_devices_are_deduplicated_and_route_changes_are_not_committed(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'concurrent.db'}")
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as db:
            user = account(db)
            identifier = user.id

        def concurrent_visit(_):
            with Session(engine) as db:
                changed = service.record_activity(db, identifier, 0, at=AT)
                db.commit()
                return changed

        with ThreadPoolExecutor(max_workers=6) as pool:
            assert sum(pool.map(concurrent_visit, range(24))) == 1
        with Session(engine, autoflush=False) as db:
            assert db.scalar(select(func.count()).select_from(Activity)) == 1
            user = db.get(User, identifier)
            user.full_name = "Uncommitted route change"
            assert service.record_visit(db, user)
            db.rollback()
        with Session(engine) as db:
            assert db.get(User, identifier).full_name == "Member 1"
            db.delete(db.get(User, identifier))
            db.commit()
            assert db.scalar(select(func.count()).select_from(Activity)) == 0
    finally:
        engine.dispose()


def test_upgrade_preserves_existing_users_and_downgrade_protects_activity(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'activity-migration.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    config = Config("alembic.ini")
    command.upgrade(config, "c426ed871b03")
    engine = create_engine(url)
    enable_sqlite_foreign_keys(engine)
    try:
        with Session(engine, expire_on_commit=False) as db:
            user = account(db)
            identifier = user.id
        with engine.connect() as connection:
            original = connection.execute(text("SELECT * FROM users")).all()
        command.upgrade(config, "head")
        command.check(config)
        with engine.connect() as connection:
            assert connection.execute(text("SELECT * FROM users")).all() == original
            assert (
                connection.execute(text("SELECT count(*) FROM user_daily_activity")).scalar() == 0
            )
            assert not connection.execute(text("PRAGMA foreign_key_check")).all()
        command.downgrade(config, "c426ed871b03")
        assert "user_daily_activity" not in inspect(engine).get_table_names()
        command.upgrade(config, "head")
        with Session(engine) as db:
            user = db.get(User, identifier)
            visit(db, user)
        with pytest.raises(RuntimeError, match="Activity history exists"):
            command.downgrade(config, "c426ed871b03")
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(Activity)) == 1
    finally:
        engine.dispose()
