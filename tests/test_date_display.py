"""Readable deadlines preserve their source day and machine-readable values."""

from datetime import UTC, date, datetime, timedelta

import pytest

from app.services.jobs import create_job
from app.web.templating import display_date
from tests.helpers import approve_test_employer, csrf_from, has_element
from tests.test_discussions import as_member
from tests.test_recruitment import staff as staff


@pytest.mark.parametrize("value, expected", [
    ("2026-11-30T23:59:59+00:00", "Nov 30, 2026"),
    ("2026-11-30T23:59:59Z", "Nov 30, 2026"),
    ("2026-11-30", "Nov 30, 2026"),
    ("2026-01-05T00:00:00+14:00", "Jan 5, 2026"),
    (date(2028, 2, 29), "Feb 29, 2028"),
    (datetime(2026, 11, 30, 23, 59, tzinfo=UTC), "Nov 30, 2026"),
    (None, ""),
    ("", ""),
    ("Not stated", "Not stated"),
    ("2026-02-30", "2026-02-30"),
])
def test_display_date_preserves_calendar_day(value, expected):
    assert display_date(value) == expected


@pytest.mark.parametrize("timestamp", [False, True])
def test_job_feed_and_detail_display_readable_deadline_without_changing_storage(
    client, db_session, staff, timestamp,
):
    staff.account_type = "employer"
    db_session.commit()
    approve_test_employer(db_session, staff, "Example Hospital")
    future = datetime.now(UTC) + timedelta(days=30)
    deadline = future.isoformat() if timestamp else future.date().isoformat()
    job = create_job(
        db_session, staff, title="Registered Nurse", organization="Example Hospital",
        location="Lagos", country_code="NG", job_type="full_time", work_mode="on_site",
        salary_min="", salary_max="", description="Nursing care.", closing_date=deadline,
    )
    expected = f"{future:%b} {future.day}, {future.year}"
    for path in ["/jobs", f"/jobs/{job.id}"]:
        page = client.get(path)
        assert page.status_code == 200
        assert expected in page.text
        assert deadline not in page.text
    db_session.refresh(job)
    assert job.normalized_data["closing_date"] == deadline
    assert job.closes_at is not None


def test_employer_deadline_input_keeps_iso_value_after_validation_error(
    client, db_session, staff,
):
    deadline = "2026-11-30T23:59:59+00:00"
    staff.account_type = "employer"
    db_session.commit()
    approve_test_employer(db_session, staff, "Example Hospital")
    as_member(client, staff)
    token = csrf_from(client.get("/jobs/new"))
    page = client.post("/jobs", data={
        "csrf_token": token, "title": "", "organization": "Example Hospital",
        "country_code": "NG", "closing_date": deadline,
    })
    assert page.status_code == 400
    assert has_element(page, "input", name="closing_date", value=deadline)
    assert "Nov 30, 2026" not in page.text
