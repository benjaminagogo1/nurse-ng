"""Public role selection cannot confer publication or access to applicant contacts."""

import pytest
from sqlalchemy import select

from app.models.employers import EmployerMembership, EmployerReviewEvent
from app.models.jobs import Job, JobApplication
from app.services.employers import EmployerError, request_membership, review_membership
from app.services.jobs import JobError, apply_for_job, create_job, list_open_jobs
from tests.helpers import csrf_from
from tests.test_community import sign_in
from tests.test_workspace_flows import accounts as accounts
from tests.test_workspace_flows import job as job


def publish(db, employer, organization):
    return create_job(db, employer, title="Approved role", organization=organization,
                      location="Lagos", job_type="full_time", work_mode="on_site",
                      salary_min="", salary_max="", description="Nursing role")


def test_pending_organization_and_member_cannot_publish(client, db_session, accounts):
    employer, reviewer = accounts["other_employer"], accounts["peer"]
    reviewer.is_staff = True
    db_session.commit()
    sign_in(client, employer.phone)
    path = "/employers/organizations"
    data = {"name": "New Hospital", "website": "https://new.example.org",
            "authority_details": "Recruiting lead; confirm through official switchboard."}
    assert client.post(path, data=data).status_code == 400
    data["csrf_token"] = csrf_from(client.get(path))
    assert client.post(path, data=data, follow_redirects=False).status_code == 303
    member = db_session.scalar(select(EmployerMembership).where(
        EmployerMembership.user_id == employer.id, EmployerMembership.status == "pending"
    ))
    with pytest.raises(JobError, match="approved organization"):
        publish(db_session, employer, "New Hospital")
    sign_in(client, reviewer.phone)
    route = f"/staff/employers/{member.id}"
    data = {"csrf_token": csrf_from(client.get("/staff/employers")), "action": "approve",
            "note": "Confirmed organization registration and member with official HR contact."}
    assert client.post(route, data=data).status_code == 400
    assert client.post(route, data={**data, "identity_checked": "on",
                                   "authority_checked": "on"},
                       follow_redirects=False).status_code == 303
    published = publish(db_session, employer, "New Hospital")
    assert published.employer_organization_id == member.organization_id
    assert db_session.scalar(select(EmployerReviewEvent)).reviewer_id == reviewer.id
    assert published in list_open_jobs(db_session)
    with pytest.raises(JobError):
        publish(db_session, employer, "Unrelated Hospital")


def test_approval_requires_staff_verified_contact_and_independent_reviewer(db_session, accounts):
    employer, reviewer = accounts["employer"], accounts["peer"]
    member = request_membership(db_session, employer, name="Additional Hospital",
                                website="https://additional.example.org", authority_details="HR")
    values = dict(action="approve", note="Independent official reference",
                  identity_checked=True, authority_checked=True)
    with pytest.raises(EmployerError, match="Staff"):
        review_membership(db_session, reviewer, member, **values)
    employer.is_staff = True
    db_session.commit()
    with pytest.raises(EmployerError, match="own membership"):
        review_membership(db_session, employer, member, **values)
    reviewer.is_staff = True
    employer.email_verified_at = None
    db_session.commit()
    with pytest.raises(EmployerError, match="verified email"):
        review_membership(db_session, reviewer, member, **values)


@pytest.mark.parametrize("revocation", ["membership", "organization", "email", "account"])
def test_revocation_blocks_publication_applications_and_contact_access(
    client, db_session, accounts, job, revocation,
):
    employer, nurse = accounts["employer"], accounts["nurse"]
    application = apply_for_job(db_session, nurse, job, cover_note="Private application")
    member = db_session.scalar(select(EmployerMembership).where(
        EmployerMembership.user_id == employer.id))
    sign_in(client, employer.phone)
    assert nurse.phone in client.get(f"/applications/{application.id}").text
    if revocation == "membership":
        member.status = "revoked"
    elif revocation == "organization":
        member.organization.status = "suspended"
    elif revocation == "email":
        employer.email_verified_at = None
    else:
        employer.account_type = "partner"
    db_session.commit()
    assert job not in list_open_jobs(db_session)
    assert client.get(f"/jobs/{job.id}").status_code == 404
    assert client.get(f"/applications/{application.id}").status_code == 404
    assert nurse.phone not in client.get("/applications").text
    assert "New application received" not in client.get("/notifications").text
    token = csrf_from(client.get("/applications"))
    assert client.post(f"/applications/{application.id}/status", data={
        "csrf_token": token, "new_status": "shortlisted",
    }).status_code == 404
    with pytest.raises(JobError):
        publish(db_session, employer, job.organization)
    with pytest.raises(JobError, match="not currently authorized"):
        apply_for_job(db_session, accounts["peer"], job, cover_note="Blocked")
    sign_in(client, nurse.phone)
    assert client.get(f"/applications/{application.id}").status_code == 200


def test_legacy_listings_are_not_silently_trusted(client, db_session, accounts):
    employer, nurse = accounts["employer"], accounts["nurse"]
    legacy = Job(employer_user_id=employer.id, organization="City Hospital", title="Legacy job")
    db_session.add(legacy)
    db_session.flush()
    application = JobApplication(job_id=legacy.id, applicant_user_id=nurse.id,
                                 candidate_name=nurse.full_name, candidate_phone=nurse.phone)
    db_session.add(application)
    db_session.commit()
    sign_in(client, employer.phone)
    assert client.get(f"/applications/{application.id}").status_code == 404
    assert legacy not in list_open_jobs(db_session)
    with pytest.raises(JobError, match="not currently authorized"):
        apply_for_job(db_session, nurse, legacy, cover_note="Blocked")
    member = db_session.scalar(select(EmployerMembership).where(
        EmployerMembership.user_id == employer.id))
    reviewer = accounts["peer"]
    reviewer.is_staff = True
    db_session.commit()
    review_membership(db_session, reviewer, member, action="approve", note="Checked current role",
                      identity_checked=True, authority_checked=True)
    assert legacy not in list_open_jobs(db_session)
    review_membership(db_session, reviewer, member, action="approve", note="Checked legacy role",
                      identity_checked=True, authority_checked=True, include_legacy=True)
    assert legacy in list_open_jobs(db_session)
    assert client.get(f"/applications/{application.id}").status_code == 200
