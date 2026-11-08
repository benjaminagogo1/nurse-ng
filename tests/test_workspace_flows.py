"""Account, recruitment, and messaging journeys through the refreshed pages."""

import pytest
from sqlalchemy import select

from app.models.community import Connection, ConnectionStatus
from app.models.jobs import Job, JobApplication
from app.models.messages import DirectMessage
from app.models.profile import NurseProfile
from app.models.user import User
from app.services.auth import register_user
from app.services.community import connection_pair_key
from app.services.jobs import create_job
from app.services.messages import unread_count
from tests.helpers import csrf_from
from tests.test_community import sign_in


@pytest.fixture
def accounts(db_session):
    def create(number, name, role="nurse"):
        return register_user(
            db_session, phone=f"+234800000000{number}", password="s3cret-pass",
            full_name=name, email=f"member{number}@example.com", account_type=role,
        )

    return {
        "nurse": create(1, "Ada Nurse"),
        "peer": create(2, "Bola Nurse"),
        "employer": create(3, "City Hospital", "employer"),
        "other_employer": create(4, "Other Hospital", "employer"),
    }


@pytest.fixture
def job(db_session, accounts):
    return create_job(
        db_session, accounts["employer"], title="Registered Nurse",
        organization="City Hospital", location="Lagos", job_type="full_time",
        work_mode="on_site", salary_min="250,000", salary_max="400,000",
        description="Join our nursing team.",
    )


def test_registration_captures_details_and_preserves_account_boundaries(client, db_session):
    page = client.get("/auth/register?role=employer")
    response = client.post("/auth/register", data={
        "csrf_token": csrf_from(page), "phone": "08012345678", "password": "s3cret-pass",
        "full_name": "  Care Hospital  ", "email": "recruitment@EXAMPLE.COM",
        "role": "employer", "is_staff": "true",
    }, follow_redirects=False)
    assert response.status_code == 303
    user = db_session.scalar(select(User))
    assert (user.full_name, user.email, user.account_type, user.is_staff) == (
        "Care Hospital", "recruitment@example.com", "employer", False,
    )
    assert "Post a job" in client.get("/").text
    assert client.get("/jobs/new").status_code == 200


def test_account_settings_validate_conflicts_and_keep_role(client, db_session, accounts):
    nurse = accounts["nurse"]
    sign_in(client, nurse.phone)
    token = csrf_from(client.get("/settings"))
    response = client.post("/settings", data={
        "csrf_token": token, "full_name": "Updated Name", "email": accounts["peer"].email,
        "current_password": "s3cret-pass",
    })
    assert response.status_code == 400
    assert "already exists" in response.text
    db_session.refresh(nurse)
    assert nurse.full_name == "Ada Nurse"
    response = client.post("/settings", data={
        "csrf_token": token, "full_name": "Updated Name", "email": "ada@EXAMPLE.ORG",
        "current_password": "s3cret-pass",
        "role": "employer",
    }, follow_redirects=False)
    assert response.status_code == 303
    db_session.refresh(nurse)
    assert (nurse.full_name, nurse.email, nurse.account_type) == (
        "Updated Name", "ada@example.org", "nurse",
    )


def test_jobs_can_be_posted_by_employers_and_filtered(client, db_session, accounts):
    sign_in(client, accounts["nurse"].phone)
    assert client.get("/jobs/new").status_code == 403
    token = csrf_from(client.get("/jobs"))
    assert client.post("/jobs", data={"csrf_token": token}).status_code == 403
    sign_in(client, accounts["employer"].phone)
    token = csrf_from(client.get("/jobs/new"))
    data = {
        "csrf_token": token, "title": "Clinical Tutor", "organization": "City Hospital",
        "location": "Abuja", "job_type": "contract", "work_mode": "on_site",
        "salary_min": "450000", "salary_max": "250000", "description": "Teach nursing.",
    }
    assert client.post("/jobs", data=data).status_code == 400
    assert db_session.scalar(select(Job)) is None
    data["salary_max"] = "550000"
    assert client.post("/jobs", data=data, follow_redirects=False).status_code == 303
    client.cookies.clear()
    assert "Clinical Tutor" in client.get("/jobs?q=Abuja&type=contract").text
    assert "Clinical Tutor" not in client.get("/jobs?q=Abuja&type=full_time").text
    assert "Clinical Tutor" not in client.get("/jobs?q=%25").text


def test_application_consent_contact_snapshot_and_employer_isolation(
    client, db_session, accounts, job,
):
    nurse = accounts["nurse"]
    sign_in(client, nurse.phone)
    path = f"/jobs/{job.id}/apply"
    token = csrf_from(client.get(f"/jobs/{job.id}"))
    assert client.post(path, data={"csrf_token": token}).status_code == 400
    assert db_session.scalar(select(JobApplication)) is None
    data = {"csrf_token": token, "consent": "on", "cover_note": "I enjoy patient care."}
    assert client.post(path, data=data, follow_redirects=False).status_code == 303
    assert client.post(path, data=data).status_code == 400
    application = db_session.scalar(select(JobApplication))
    assert (application.candidate_name, application.candidate_phone) == ("Ada Nurse", nurse.phone)
    nurse.full_name = "Later Name"
    db_session.commit()
    assert application.candidate_name == "Ada Nurse"
    sign_in(client, accounts["other_employer"].phone)
    assert "Ada Nurse" not in client.get("/applications").text
    token = csrf_from(client.get("/applications"))
    assert client.post(f"/applications/{application.id}/status", data={
        "csrf_token": token, "new_status": "shortlisted",
    }).status_code == 404
    sign_in(client, accounts["employer"].phone)
    assert "Ada Nurse" in client.get("/applications").text
    token = csrf_from(client.get("/applications"))
    assert client.post(f"/applications/{application.id}/status", data={
        "csrf_token": token, "new_status": "shortlisted",
    }, follow_redirects=False).status_code == 303
    assert application.status == "shortlisted"
    sign_in(client, nurse.phone)
    token = csrf_from(client.get("/applications"))
    assert client.post(f"/applications/{application.id}/status", data={
        "csrf_token": token, "new_status": "withdrawn",
    }, follow_redirects=False).status_code == 303
    sign_in(client, accounts["employer"].phone)
    token = csrf_from(client.get("/applications"))
    assert client.post(f"/applications/{application.id}/status", data={
        "csrf_token": token, "new_status": "reviewing",
    }).status_code == 400
    assert application.status == "withdrawn"


def test_messages_require_accepted_active_connection_and_track_reads(
    client, db_session, accounts,
):
    nurse, peer = accounts["nurse"], accounts["peer"]
    sign_in(client, nurse.phone)
    path = f"/messages/{peer.id}"
    token = csrf_from(client.get("/messages"))
    assert client.get(path).status_code == 404
    assert client.post(path, data={"csrf_token": token, "body": "Hello"}).status_code == 404
    connection = Connection(
        requester_user_id=nurse.id, recipient_user_id=peer.id,
        pair_key=connection_pair_key(nurse.id, peer.id), status=ConnectionStatus.PENDING,
    )
    db_session.add(connection)
    db_session.commit()
    assert client.get(path).status_code == 404
    connection.status = ConnectionStatus.ACCEPTED
    db_session.commit()
    assert client.get(path).status_code == 200
    assert f'/messages/{peer.id}' in client.get("/network").text
    assert client.post(path, data={"body": "Missing token"}).status_code == 400
    assert client.post(path, data={"csrf_token": token, "body": " "}).status_code == 400
    assert client.post(path, data={"csrf_token": token, "body": "x" * 3001}).status_code == 400
    assert client.post(path, data={
        "csrf_token": token, "body": "Hello <script>alert(1)</script>",
    }, follow_redirects=False).status_code == 303
    assert unread_count(db_session, peer) == 1
    sign_in(client, accounts["employer"].phone)
    assert client.get(f"/messages/{nurse.id}").status_code == 404
    sign_in(client, peer.phone)
    response = client.get(f"/messages/{nurse.id}")
    assert "Hello &lt;script&gt;" in response.text
    assert unread_count(db_session, peer) == 0
    message = db_session.scalar(select(DirectMessage))
    assert message.read_at is not None
    nurse.is_active = False
    db_session.commit()
    assert client.get(f"/messages/{nurse.id}").status_code == 404
    nurse.is_active = True
    db_session.delete(connection)
    db_session.commit()
    assert client.get(f"/messages/{nurse.id}").status_code == 404


def test_extended_profile_fields_are_saved_and_shared_only_by_choice(client, db_session, accounts):
    sign_in(client, accounts["nurse"].phone)
    page = client.get("/profile/edit")
    assert 'value="Ada Nurse"' in page.text
    data = {
        "csrf_token": csrf_from(page), "display_name": "Ada Nurse",
        "professional_status": "graduate", "qualification": "BSc Nursing",
        "years_experience": "0", "skills": "Patient care, patient CARE, Teamwork",
    }
    assert client.post("/profile/edit", data=data, follow_redirects=False).status_code == 303
    profile = db_session.scalar(select(NurseProfile))
    assert (profile.qualification, profile.years_experience, profile.skills) == (
        "BSc Nursing", 0, "Patient care, Teamwork",
    )
    token = csrf_from(client.get("/profile/sharing"))
    sharing = {"csrf_token": token, "visibility_display_name": "public"}
    assert client.post("/profile/sharing", data=sharing, follow_redirects=False).status_code == 303
    assert client.post("/profile/activate", data={
        "csrf_token": token,
    }, follow_redirects=False).status_code == 303
    public = client.get(f"/p/{profile.public_id}")
    assert "BSc Nursing" not in public.text
    assert "Patient care" not in public.text
    sharing.update({
        "visibility_qualification": "public", "visibility_years_experience": "public",
        "visibility_skills": "public",
    })
    assert client.post("/profile/sharing", data=sharing, follow_redirects=False).status_code == 303
    public = client.get(f"/p/{profile.public_id}")
    assert "BSc Nursing" in public.text and "Patient care" in public.text
    assert "0 years" in public.text
    data["years_experience"] = "61"
    assert client.post("/profile/edit", data=data).status_code == 400
    db_session.refresh(profile)
    assert profile.years_experience == 0


@pytest.mark.parametrize("path", ["/settings", "/applications", "/messages", "/jobs/new"])
def test_workspace_pages_require_sign_in(client, path):
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login"
