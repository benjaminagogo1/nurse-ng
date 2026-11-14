"""Server-confirmed results and correctable errors across ordinary and enhanced forms."""

from sqlalchemy import select

from app.models.community import CommunityPost
from app.models.jobs import Job
from app.services.auth import register_user
from app.services.community import create_topic
from tests.helpers import approve_test_employer, csrf_from
from tests.test_community import sign_in

HEADERS = {"X-Account-Feedback": "1", "Accept": "application/json"}


def test_job_feedback_preserves_failure_and_confirms_success_once(client, db_session):
    user = register_user(
        db_session, phone="+2348000000111", password="s3cret-pass", account_type="employer"
    )
    approve_test_employer(db_session, user, "Test clinic")
    sign_in(client, user.phone)
    token = csrf_from(client.get("/jobs/new"))
    bad = client.post("/jobs", headers=HEADERS, data={"csrf_token": token})
    assert bad.status_code == 400
    assert bad.json()["feedback"]["tone"] == "error"
    assert db_session.scalar(select(Job)) is None
    result = client.post(
        "/jobs",
        headers=HEADERS,
        data={
            "csrf_token": token,
            "title": "Nurse",
            "organization": "Test clinic",
        },
    )
    assert result.json() == {"redirect": "/jobs"}
    assert db_session.scalar(select(Job)).title == "Nurse"
    assert "Job published" not in client.get("/settings").text
    page = client.get("/jobs")
    assert page.text.count("data-feedback-panel") == 1
    assert "Job published" in page.text
    assert "Job published" not in client.get("/jobs").text


def test_reply_confirmation_matches_destination_with_query_and_fragment(client, db_session):
    user = register_user(db_session, phone="+2348000000112", password="s3cret-pass")
    user.is_staff = True
    db_session.commit()
    topic = create_topic(db_session, user, name="Quality", description="")
    sign_in(client, user.phone)
    token = csrf_from(client.get("/posts/new"))
    result = client.post(
        "/posts",
        headers=HEADERS,
        data={
            "csrf_token": token,
            "body": "A conversation",
            "topic_id": str(topic.id),
            "community_name": "Quality Member",
        },
    )
    post = db_session.scalar(select(CommunityPost))
    assert result.json()["redirect"] == f"/posts/{post.id}"
    client.get(result.json()["redirect"])
    result = client.post(
        f"/posts/{post.id}/replies",
        headers=HEADERS,
        data={"csrf_token": token, "body": "A useful response"},
    )
    assert "#reply-" in result.json()["redirect"]
    page = client.get(result.json()["redirect"])
    assert "Reply published" in page.text
    assert page.text.count("data-feedback-panel") == 1


def test_csrf_validation_and_missing_destination_have_useful_errors(client):
    response = client.post("/auth/register", headers=HEADERS, data={"phone": "private input"})
    assert response.status_code == 400
    assert response.json()["feedback"]["tone"] == "error"
    assert "private input" not in response.text
    missing = client.get("/missing-destination", headers={"Accept": "text/html"})
    assert missing.status_code == 404
    assert "Go to home" in missing.text
    assert 'role="alert"' in missing.text


def test_enhanced_registration_and_login_use_server_results(client):
    token = csrf_from(client.get("/auth/register"))
    data = {
        "csrf_token": token,
        "phone": "+2348000000113",
        "password": "quality-password",
        "full_name": "Quality Member",
    }
    result = client.post("/auth/register", headers=HEADERS, data=data)
    assert result.json() == {"redirect": "/welcome"}
    page = client.get("/welcome")
    assert "Account created" in page.text
    token = csrf_from(page)
    result = client.post("/auth/logout", headers=HEADERS, data={"csrf_token": token})
    assert result.json() == {"redirect": "/"}
    assert "Signed out" in client.get("/").text
    token = csrf_from(client.get("/auth/login"))
    result = client.post(
        "/auth/login", headers=HEADERS, data={**data, "csrf_token": token, "password": "incorrect"}
    )
    assert result.status_code == 401
    assert "incorrect" in result.json()["feedback"]["body"]
