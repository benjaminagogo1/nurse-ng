"""Real event journeys, privacy, permission boundaries and calendar interoperability."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select

from app.models.events import CommunityEvent, EventAttendance
from app.models.user import User
from app.services.auth import register_user
from app.services.events import calendar
from tests.helpers import csrf_from
from tests.test_community import sign_in


@pytest.fixture
def event_accounts(db_session):
    staff = register_user(db_session, phone="+2348000000121", password="s3cret-pass")
    member = register_user(db_session, phone="+2348000000122", password="s3cret-pass")
    staff.is_staff = True
    db_session.commit()
    return staff, member


def event_data():
    future = datetime.now(UTC) + timedelta(days=5)
    return {
        "title": "Community learning",
        "description": "Join our nursing discussion.",
        "location": "Lagos",
        "starts_at": future.isoformat(),
        "ends_at": (future + timedelta(hours=1)).isoformat(),
        "registration_url": "https://example.org/register",
    }


def publish(client, db, staff):
    sign_in(client, staff.phone)
    token = csrf_from(client.get("/events/new"))
    result = client.post(
        "/events", data={"csrf_token": token, **event_data()}, follow_redirects=False
    )
    assert result.status_code == 303
    return db.scalar(select(CommunityEvent)), token


def test_event_publish_rsvp_update_cancel_journey(client, db_session, event_accounts):
    staff, member = event_accounts
    event, token = publish(client, db_session, staff)
    path = f"/events/{event.id}"
    assert "Event published" in client.get(path).text
    assert event.title in client.get("/events").text
    assert event.title in client.get("/").text
    sign_in(client, member.phone)
    token = csrf_from(client.get(path))
    data = {"csrf_token": token, "attending": "true"}
    for _ in range(2):
        assert client.post(path + "/rsvp", data=data).status_code == 200
    assert db_session.scalar(select(func.count()).select_from(EventAttendance)) == 1
    assert "You are planning to attend" in client.get(path).text
    calendar_response = client.get(path + "/calendar.ics")
    assert "BEGIN:VEVENT" in calendar_response.text
    assert "Content-Disposition" in calendar_response.headers
    assert member.phone not in calendar_response.text
    sign_in(client, staff.phone)
    assert member.phone not in client.get(path).text
    token = csrf_from(client.get(path + "/edit"))
    response = client.post(
        path + "/edit",
        data={"csrf_token": token, **event_data(), "title": "Updated learning event"},
    )
    assert "Event updated" in response.text
    assert "Updated learning event" in response.text
    response = client.post(path + "/cancel", data={"csrf_token": token})
    assert "Event cancelled" in response.text
    assert "Updated learning event" not in client.get("/events").text
    assert "STATUS:CANCELLED" in client.get(path + "/calendar.ics").text
    sign_in(client, member.phone)
    token = csrf_from(client.get(path))
    assert (
        client.post(path + "/rsvp", data={"csrf_token": token, "attending": "true"}).status_code
        == 400
    )
    assert (
        client.post(path + "/rsvp", data={"csrf_token": token, "attending": "false"}).status_code
        == 200
    )
    assert db_session.scalar(select(func.count()).select_from(EventAttendance)) == 0


def test_event_permissions_validation_and_attendance_deletion(client, db_session, event_accounts):
    staff, member = event_accounts
    event, _ = publish(client, db_session, staff)
    path = f"/events/{event.id}"
    sign_in(client, member.phone)
    token = csrf_from(client.get(path))
    assert client.get("/events/new").status_code == 403
    assert client.post("/events", data={"csrf_token": token, **event_data()}).status_code == 403
    assert client.post(path + "/cancel", data={"csrf_token": token}).status_code == 403
    assert client.post(path + "/rsvp", data={"attending": "true"}).status_code == 400
    client.post(path + "/rsvp", data={"csrf_token": token, "attending": "true"})
    db_session.execute(delete(User).where(User.id == member.id))
    db_session.commit()
    assert db_session.scalar(select(func.count()).select_from(EventAttendance)) == 0
    sign_in(client, staff.phone)
    token = csrf_from(client.get("/events/new"))
    for extra in (
        {"registration_url": "javascript:alert(1)"},
        {"starts_at": "bad"},
        {"ends_at": "2001-01-01T00:00"},
    ):
        response = client.post(
            "/events",
            data={"csrf_token": token, **event_data(), **extra},
            headers={"X-Account-Feedback": "1"},
        )
        assert response.status_code == 400
        assert response.json()["feedback"]["tone"] == "error"
    assert db_session.scalar(select(func.count()).select_from(CommunityEvent)) == 1


def test_calendar_escapes_and_folds_utf8_without_injecting_properties(db_session, event_accounts):
    now = datetime.now(UTC)
    event = CommunityEvent(
        title="Nursing, learning; " + "é" * 100,
        description="First\nATTENDEE:someone@example.org",
        location="Lagos",
        starts_at=now,
        ends_at=now + timedelta(hours=1),
        creator_id=event_accounts[0].id,
    )
    db_session.add(event)
    db_session.commit()
    data = calendar(event)
    assert "\\nATTENDEE:" in data
    assert "\r\nATTENDEE:" not in data
    assert "Nursing\\, learning\\;" in data
    assert all(len(line.encode()) <= 75 for line in data.split("\r\n"))
