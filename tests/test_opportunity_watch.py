# ruff: noqa: F811, E501
"""Nigerian-first opportunity discovery, bookmarks, matching and deadline delivery."""

import base64
import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.models.notifications import Notification
from app.models.opportunities import SavedOpportunity
from app.models.vacancies import VacancyRecord
from app.services import notifications
from app.services import opportunity_watch as watch
from app.services.announcement_extraction import (
    announcement_links,
    explicit_date,
    extract_announcements,
)
from app.services.jobs import JobError, apply_for_job, create_job, list_open_jobs
from app.services.recruitment_discovery import execute_discovery
from app.services.recruitment_fetch import FetchedPage
from app.services.vacancies import configure_collector, ingest_page
from app.services.vacancy_extraction import normalize
from tests.helpers import csrf_from
from tests.test_discussions import as_member
from tests.test_vacancy_ingestion import source, staff  # noqa: F401
from tests.test_workspace_flows import accounts, job  # noqa: F401


def make_job(db, employer, **changes):
    return create_job(
        db,
        employer,
        **(
            dict(
                title="Public health internship",
                organization="Example Hospital",
                location="Lagos, Nigeria",
                country_code="NG",
                job_type="internship",
                work_mode="on_site",
                description="A supervised public-health internship",
                salary_min="",
                salary_max="",
            )
            | changes
        ),
    )


def preferences(db, user, **values):
    watch.save_preferences(
        db,
        user,
        **(dict(keyword="", location="", job_type="", country_code="NG", enabled=True) | values),
    )


def test_save_idempotency_ownership_feedback_and_reminder_controls(
    client, db_session, accounts, job
):
    first, other = accounts["nurse"], accounts["peer"]
    as_member(client, first)
    token = csrf_from(client.get(f"/jobs/{job.id}"))
    assert client.post(f"/jobs/{job.id}/save", data={}).status_code == 400
    data = {"csrf_token": token, "remind": "true"}
    result = client.post(f"/jobs/{job.id}/save", data=data)
    assert "Opportunity saved" in result.text
    client.post(f"/jobs/{job.id}/save", data=data)
    assert db_session.scalar(select(func.count()).select_from(SavedOpportunity)) == 1
    assert "Registered Nurse" in client.get("/jobs/saved").text
    as_member(client, other)
    page = client.get("/jobs/saved")
    assert "Registered Nurse" not in page.text
    assert (
        client.post(f"/jobs/{job.id}/reminder", data={"csrf_token": csrf_from(page)}).status_code
        == 404
    )
    as_member(client, first)
    page = client.get("/jobs/saved")
    client.post(f"/jobs/{job.id}/reminder", data={"csrf_token": csrf_from(page)})
    assert not db_session.get(SavedOpportunity, (first.id, job.id)).remind
    client.post(f"/jobs/{job.id}/unsave", data={"csrf_token": csrf_from(client.get("/jobs/saved"))})
    assert db_session.get(SavedOpportunity, (first.id, job.id)) is None


def test_saved_history_has_pagination_and_expired_titles(db_session, client, accounts):
    user = accounts["nurse"]
    for i in range(27):
        item = make_job(db_session, accounts["employer"], title=f"Health internship {i:02}")
        watch.save_job(db_session, user, item)
    as_member(client, user)
    first = client.get("/jobs/saved")
    second = client.get("/jobs/saved?page=2")
    assert "Older saved opportunities" in first.text
    assert first.text.count('class="saved-opportunity"') == 25
    assert second.text.count('class="saved-opportunity"') == 2


def test_match_preferences_default_to_nigeria_and_respect_types_and_location(db_session, accounts):
    user = accounts["nurse"]
    matching = make_job(db_session, accounts["employer"])
    make_job(db_session, accounts["employer"], country_code="GB", location="London")
    make_job(db_session, accounts["employer"], location="Abuja", job_type="fellowship")
    assert all(item.country_code == "NG" for item in watch.matching_jobs(db_session, user))
    preferences(db_session, user, keyword="public health", location="Lagos", job_type="internship")
    assert [item.id for item in watch.matching_jobs(db_session, user)] == [matching.id]
    preferences(db_session, user, keyword="%")
    assert watch.matching_jobs(db_session, user) == []


def test_matching_alerts_only_new_jobs_deduplicate_and_use_shared_channels(db_session, accounts):
    user = accounts["nurse"]
    make_job(db_session, accounts["employer"], title="Older nursing internship")
    preferences(db_session, user, keyword="internship")
    job = make_job(db_session, accounts["employer"])
    make_job(db_session, accounts["employer"], country_code="GB")
    result = watch.generate_alerts(db_session)
    assert result["matches"] == 1
    notice = db_session.scalar(select(Notification).where(Notification.kind == "opportunity_match"))
    assert notice.actor_id is None and notice.job_id == job.id and notice.email_state == "skipped"
    assert notifications.unread_count(db_session, user) == 1
    assert (
        watch.generate_alerts(db_session, now=datetime.now(UTC) + timedelta(minutes=6))["matches"]
        == 0
    )
    job.status = "closed"
    db_session.commit()
    assert notifications.unread_count(db_session, user) == 0


def test_disabled_notifications_do_not_replay_old_matches_or_starve_new_ones(db_session, accounts):
    user = accounts["nurse"]
    preferences(db_session, user)
    choices = notifications.preferences(db_session, user)
    choices["opportunities"] = {"in_app": False, "email": False}
    notifications.save_preferences(db_session, user, choices)
    make_job(db_session, accounts["employer"])
    watch.generate_alerts(db_session)
    choices["opportunities"]["in_app"] = True
    notifications.save_preferences(db_session, user, choices)
    watch.generate_alerts(db_session, now=datetime.now(UTC) + timedelta(minutes=6))
    assert notifications.unread_count(db_session, user) == 0
    make_job(db_session, accounts["employer"], title="Another internship")
    watch.generate_alerts(db_session, now=datetime.now(UTC) + timedelta(minutes=12))
    assert notifications.unread_count(db_session, user) == 1


def test_deadline_reminder_once_and_updated_deadline_creates_new_event(db_session, accounts):
    user = accounts["nurse"]
    job = make_job(db_session, accounts["employer"])
    job.closes_at = datetime.now(UTC) + timedelta(hours=20)
    db_session.commit()
    watch.save_job(db_session, user, job, remind=True)
    assert watch.generate_alerts(db_session)["reminders"] == 1
    assert watch.generate_alerts(db_session)["reminders"] == 0
    assert notifications.unread_count(db_session, user) == 1
    job.closes_at += timedelta(hours=2)
    db_session.commit()
    assert notifications.unread_count(db_session, user) == 0
    assert watch.generate_alerts(db_session)["reminders"] == 1
    assert notifications.unread_count(db_session, user) == 1
    watch.remove_saved(db_session, user, job.id)
    assert notifications.unread_count(db_session, user) == 0


@pytest.mark.parametrize("condition", ["expired", "far", "disabled", "inactive", "unconfirmed"])
def test_reminder_eligibility_is_rechecked(db_session, accounts, condition):
    user = accounts["nurse"]
    item = make_job(db_session, accounts["employer"])
    watch.save_job(db_session, user, item, remind=condition != "disabled")
    item.closes_at = datetime.now(UTC) + timedelta(hours=20)
    if condition == "expired":
        item.closes_at -= timedelta(days=2)
    elif condition == "far":
        item.closes_at += timedelta(days=4)
    elif condition == "inactive":
        user.is_active = False
    elif condition == "unconfirmed":
        item.status = "unconfirmed"
    db_session.commit()
    assert watch.generate_alerts(db_session)["reminders"] == 0


def test_employer_deadlines_are_enforced_in_listing_and_application(db_session, accounts):
    with pytest.raises(JobError):
        make_job(db_session, accounts["employer"], closing_date="01/02/2028")
    with pytest.raises(JobError):
        make_job(db_session, accounts["employer"], closing_date="2020-01-01")
    item = make_job(db_session, accounts["employer"], closing_date="2030-01-01")
    assert item.closes_at.hour == 23  # Midnight after closing day in Africa/Lagos.
    item.closes_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    assert item.id not in {row.id for row in list_open_jobs(db_session)}
    with pytest.raises(JobError, match="no longer"):
        apply_for_job(db_session, accounts["nurse"], item, cover_note="")


def announcement(title="National Digital Health Fellowship", deadline=None):
    deadline = deadline or (datetime.now(UTC) + timedelta(days=20)).strftime("%d %B %Y")
    return f'''<html><head><meta property="article:published_time" content="{(datetime.now(UTC) - timedelta(days=2)).date()}"></head>
    <body><nav>Unrelated navigation</nav><article><h1>{title}</h1><p>Applications are open. Apply now.</p>
    <p>Organisation: Example Hospital</p><p>Location: Lagos, Nigeria</p>
    <p>Application deadline: {deadline}</p><p>Training and supervised public health work.</p>
    <script>Never publish this script</script></article></body></html>'''.encode()


def result(body, url):
    return {
        "body_base64": base64.b64encode(body).decode(),
        "content_hash": hashlib.sha256(body).hexdigest(),
        "observed_url": url,
    }


def test_plain_announcement_extracts_explicit_facts_and_rejects_ambiguous_date():
    raw = extract_announcements(announcement(), "https://example.org/fellowship")[0]
    data = normalize(raw)
    assert data["country"] == "NG" and data["job_type"] == "fellowship"
    assert data["employer"] == "Example Hospital"
    assert (
        "Never publish" not in data["description"]
        and "Unrelated navigation" not in data["description"]
    )
    assert explicit_date("2nd November 2028") == "2028-11-02"
    assert explicit_date("02/11/2028") == ""
    assert (
        extract_announcements(
            b"<h1>National Health Fellowship</h1><p>Meet our alumni</p>", "https://example.org"
        )
        == []
    )


def test_announcements_follow_scoped_links_and_publish_only_valid_records(
    db_session, source, staff
):
    configure_collector(
        db_session,
        staff,
        source,
        revision=source.revision,
        enabled=True,
        url_prefix="https://hospital.example.ng",
        timezone="Africa/Lagos",
        note="Use existing permission",
        reference="https://hospital.example.ng/terms",
        adapter="announcements",
    )
    body = b'<h1>Careers</h1><a href="/one">Nursing internship</a><a href="https://evil.example/two">Health fellowship</a><a href="http://127.0.0.1/job">Nursing job</a>'
    assert announcement_links(body, source.original_url, source.vacancy_url_prefix) == [
        "https://hospital.example.ng/one"
    ]
    source.health_status = "healthy"
    source.last_success_at = datetime.now(UTC)
    counts = ingest_page(
        db_session,
        source,
        result(announcement(), "https://hospital.example.ng/one"),
        datetime.now(UTC),
    )
    db_session.commit()
    assert counts["published"] == 1
    assert list_open_jobs(db_session)[0].job_type == "fellowship"
    changed = ingest_page(
        db_session,
        source,
        result(announcement(deadline="02/11/2028"), "https://hospital.example.ng/one"),
        datetime.now(UTC),
    )
    db_session.commit()
    assert changed["pending"] == 1 and list_open_jobs(db_session) == []
    assert "closing_date" in str(db_session.scalar(select(VacancyRecord)).issues)


def test_collector_reads_detail_pages_with_scope_and_keeps_unvisited_records(
    db_session, source, staff
):
    configure_collector(
        db_session,
        staff,
        source,
        revision=source.revision,
        enabled=True,
        url_prefix="https://hospital.example.ng",
        timezone="Africa/Lagos",
        note="Use existing permission",
        reference="https://hospital.example.ng/terms",
        adapter="announcements",
    )
    body = b"<h1>Careers</h1>" + b"".join(
        f'<a href="/{i}">Health internship {i}</a>'.encode() for i in range(6)
    )

    class Fetcher:
        def get(self, url, **limits):
            assert limits["allowed_url_prefix"] == source.vacancy_url_prefix
            content = (
                body
                if url == source.original_url
                else announcement(title=f"Health internship {url[-1]}")
            )
            return FetchedPage(url, 200, "text/html", content)

    payload = dict(
        url=source.original_url,
        reuse_url_prefix=source.vacancy_url_prefix,
        collect_vacancies=True,
        collection_adapter="announcements",
    )
    source.health_status = "healthy"
    first = execute_discovery("inspect", payload, fetcher=Fetcher())
    assert len(first["detail_pages"]) == 4
    assert ingest_page(db_session, source, first, datetime.now(UTC))["published"] == 4
    db_session.commit()
    second = execute_discovery("inspect", payload | {"page_offset": 4}, fetcher=Fetcher())
    ingest_page(db_session, source, second, datetime.now(UTC))
    db_session.commit()
    assert len(list_open_jobs(db_session)) == 6


def test_system_notices_render_and_revoked_source_disappears(client, db_session, accounts):
    user = accounts["nurse"]
    preferences(db_session, user)
    item = make_job(db_session, accounts["employer"])
    watch.generate_alerts(db_session)
    as_member(client, user)
    page = client.get("/notifications?category=opportunities")
    assert "matches your interests" in page.text and item.title in page.text
    assert client.get("/jobs/preferences").status_code == 200
    assert client.get("/jobs/matches").status_code == 200
    item.status = "closed"
    db_session.commit()
    assert item.title not in client.get("/notifications?category=opportunities").text


def test_replacement_interests_cancel_queued_match_emails(db_session, accounts):
    user = accounts["nurse"]
    user.email_verified_at = datetime.now(UTC)
    db_session.commit()
    choices = notifications.preferences(db_session, user)
    choices["opportunities"]["email"] = True
    notifications.save_preferences(db_session, user, choices)
    preferences(db_session, user)
    make_job(db_session, accounts["employer"])
    watch.generate_alerts(db_session)
    notice = db_session.scalar(select(Notification).where(Notification.kind == "opportunity_match"))
    assert notice.email_state == "queued"
    preferences(db_session, user, enabled=False)
    db_session.refresh(notice)
    assert notice.email_state == "skipped" and notice.email_to == ""


def test_coverage_requires_staff_and_counts_candidates_separately(
    client, db_session, source, staff, accounts
):
    from app.services.opportunity_coverage import coverage

    source.health_status = "healthy"
    source.organization.location = "Lagos"
    source.last_success_at = datetime.now(UTC)
    db_session.commit()
    report = coverage(db_session)
    assert report["registered"] == 1 and report["collecting"] == 1 and report["current"] == 0
    assert report["regions"]["Lagos"] == 1
    as_member(client, accounts["nurse"])
    assert client.get("/recruitment/coverage").status_code == 403
    as_member(client, staff)
    assert client.get("/recruitment/coverage").status_code == 200
    source.verification_status = "pending"
    db_session.commit()
    assert coverage(db_session)["collecting"] == 0


def test_migration_preserves_existing_notifications_and_blocks_data_loss(tmp_path, monkeypatch):
    import uuid

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    from app.core.config import settings

    url = f"sqlite:///{tmp_path / 'opportunities.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    config = Config("alembic.ini")
    command.upgrade(config, "9de420c3b287")
    engine = create_engine(url)
    user_id, notice_id = uuid.uuid4().hex, uuid.uuid4().hex
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id,phone,hashed_password,status,is_active,is_staff,phone_verified,mfa_enabled) VALUES (:id,'+2348888888888','unused','active',1,0,0,0)"
            ),
            {"id": user_id},
        )
        conn.execute(
            text(
                "INSERT INTO notifications (id,recipient_id,actor_id,category,kind,event_key,in_app,application_status,email_to,email_state,email_attempts) VALUES (:notice,:user,:user,'connections','connection_request','migration',1,'','','skipped',0)"
            ),
            {"notice": notice_id, "user": user_id},
        )
    command.upgrade(config, "head")
    command.check(config)
    with engine.begin() as conn:
        assert (
            conn.execute(
                text("SELECT event_key FROM notifications WHERE id=:id"), {"id": notice_id}
            ).scalar_one()
            == "migration"
        )
        conn.execute(
            text(
                "INSERT INTO opportunity_preferences (user_id,enabled,keyword,location,job_type,country_code,active_since,next_check_at) VALUES (:id,1,'','','','NG',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            ),
            {"id": user_id},
        )
        assert not conn.execute(text("PRAGMA foreign_key_check")).all()
    with pytest.raises(RuntimeError, match="Opportunity data exists"):
        command.downgrade(config, "9de420c3b287")
    engine.dispose()


def test_discovery_records_public_redirect_without_activating_or_retaining_content():
    class Fetcher:
        def get(self, url, **limits):
            assert not limits
            return FetchedPage(
                "https://canonical.example.ng/", 200, "text/html", b"<h1>Hospital</h1>"
            )

    result = execute_discovery(
        "inspect",
        {
            "url": "http://old.example.ng/",
            "source_type": "recruitment_page",
            "automatic_activation": {
                "identity": "candidate",
                "name": "Hospital",
                "country": "NG",
                "website": "http://old.example.ng/",
            },
        },
        fetcher=Fetcher(),
    )
    assert result["ok"] and result["observed_url"] == "https://canonical.example.ng/"
    assert result["activation_review"]["status"] == "needs_review"
    assert "body_base64" not in result


def test_announcement_collection_through_the_background_worker(db_session, source, staff):
    from app.services import recruitment as registry
    from app.services import recruitment_worker as worker

    configure_collector(
        db_session,
        staff,
        source,
        revision=source.revision,
        enabled=True,
        url_prefix="https://hospital.example.ng",
        timezone="Africa/Lagos",
        note="Existing scope",
        reference="https://hospital.example.ng/terms",
        adapter="announcements",
    )
    registry.request_inspection(db_session, staff, source)
    worker.enqueue_due(db_session)

    class Fetcher:
        def get(self, url, **limits):
            return FetchedPage(url, 200, "text/html", announcement())

    def execute(kind, payload):
        assert payload["collection_adapter"] == "announcements"
        return execute_discovery(kind, payload, fetcher=Fetcher())

    task = worker.run_next(db_session, executor=execute)
    assert task.status == "completed", task.message
    assert "1 publishable" in task.message
    assert len(list_open_jobs(db_session)) == 1
