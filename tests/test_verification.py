"""Document review: private evidence, staff decisions, and the public label."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.profile import NurseProfile
from app.models.user import User
from app.models.verification import (
    CaseStatus,
    EvidenceAccess,
    EvidenceDocument,
    VerificationCase,
)
from app.services.auth import register_user
from app.services.profiles import save_profile as save_profile_service
from app.services.verification import EvidenceUpload, VerificationError, decide_case, submit_case
from tests.helpers import csrf_from, register_and_sign_in
from tests.test_profile_pages import save_profile
from tests.test_profile_sharing import activate, save_sharing

NURSE_PHONE = "+2348011111111"
STAFF_PHONE = "+2348022222222"
OTHER_PHONE = "+2348033333333"
PASSWORD = "s3cret-pass"

JPEG = b"\xff\xd8\xff\xe0" + b"jpeg-body" * 4
PNG = b"\x89PNG\r\n\x1a\n" + b"png-body" * 4
PDF = b"%PDF-1.4\n" + b"pdf-body" * 4


@pytest.fixture(autouse=True)
def evidence_dir(tmp_path, monkeypatch):
    directory = tmp_path / "evidence"
    monkeypatch.setattr(settings, "evidence_dir", str(directory))
    return directory


def stored_files(directory):
    return sorted(directory.glob("*")) if directory.exists() else []


def nurse(db_session) -> User:
    user = db_session.scalar(select(User).where(User.phone == NURSE_PHONE))
    assert user is not None
    return user


def profile(db_session) -> NurseProfile:
    item = db_session.scalar(select(NurseProfile))
    assert item is not None
    return item


def make_staff(db_session, phone: str) -> User:
    user = db_session.scalar(select(User).where(User.phone == phone))
    assert user is not None
    user.is_staff = True
    db_session.commit()
    return user


def create_case(db_session) -> VerificationCase:
    return submit_case(
        db_session,
        user=nurse(db_session),
        profile=profile(db_session),
        registration_number="NMCN/12345",
        licence=EvidenceUpload(data=JPEG, filename="licence.jpg"),
        government_id=EvidenceUpload(data=PNG, filename="id.png"),
    )


def submit_form(
    client,
    *,
    licence=JPEG,
    government_id=PNG,
    consent="on",
    registration_number="NMCN/12345",
):
    token = csrf_from(client.get("/profile/verification"))
    data = {"csrf_token": token, "registration_number": registration_number}
    if consent is not None:
        data["consent"] = consent
    files = {}
    if licence is not None:
        files["licence"] = ("licence.jpg", licence, "image/jpeg")
    if government_id is not None:
        files["government_id"] = ("id.png", government_id, "image/png")
    return client.post(
        "/profile/verification",
        data=data,
        files=files or None,
        follow_redirects=False,
    )


def sign_in(client, phone: str, password: str = PASSWORD):
    client.cookies.clear()
    token = csrf_from(client.get("/auth/login"))
    response = client.post(
        "/auth/login",
        data={"csrf_token": token, "phone": phone, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text


def sign_in_as_staff(client, db_session):
    client.cookies.clear()
    register_and_sign_in(client, phone=STAFF_PHONE, password=PASSWORD)
    return make_staff(db_session, STAFF_PHONE)


def decide(client, case: VerificationCase, decision: str, note: str = ""):
    token = csrf_from(client.get(f"/review/{case.id}"))
    return client.post(
        f"/review/{case.id}/decide",
        data={"csrf_token": token, "decision": decision, "note": note},
        follow_redirects=False,
    )


def test_verification_page_requires_sign_in(client):
    response = client.get("/profile/verification", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login"


def test_missing_profile_keeps_verification_as_its_own_page(client, db_session):
    register_and_sign_in(client)
    page = client.get("/profile/verification", follow_redirects=False)

    assert page.status_code == 200
    assert '<h1>Verification</h1>' in page.text
    assert 'href="/profile/verification" aria-current="page"' in " ".join(page.text.split())
    assert "Create your profile to start document review" in page.text
    assert 'href="/profile/edit?return_to=verification"' in page.text
    assert 'type="file"' not in page.text
    assert 'name="display_name"' not in page.text
    assert db_session.scalar(select(NurseProfile)) is None
    assert db_session.scalar(select(VerificationCase)) is None

    profile_page = client.get("/profile")
    assert "<h1>Create your profile</h1>" in profile_page.text
    assert 'name="display_name"' in profile_page.text


@pytest.mark.parametrize("enhanced", [False, True])
def test_submission_without_profile_explains_prerequisite_without_storing_evidence(
    client, db_session, evidence_dir, enhanced,
):
    register_and_sign_in(client)
    token = csrf_from(client.get("/profile/verification"))
    response = client.post(
        "/profile/verification",
        data={"csrf_token": token, "consent": "on", "registration_number": "NMCN/12345"},
        files={"licence": ("licence.jpg", JPEG, "image/jpeg")},
        headers={"X-Account-Feedback": "1"} if enhanced else {},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "Create and save your profile" in response.text
    if enhanced:
        assert response.json()["feedback"]["tone"] == "error"
    else:
        assert '<h1>Verification</h1>' in response.text
    assert db_session.scalar(select(VerificationCase)) is None
    assert db_session.scalar(select(EvidenceDocument)) is None
    assert stored_files(evidence_dir) == []


def test_submission_stores_private_evidence_and_a_pending_case(
    client, db_session, evidence_dir
):
    register_and_sign_in(client, phone=NURSE_PHONE, password=PASSWORD)
    save_profile(client)

    response = submit_form(client)

    assert response.status_code == 303
    case = db_session.scalar(select(VerificationCase))
    assert case is not None
    assert case.status == CaseStatus.PENDING
    assert case.registration_number == "NMCN/12345"

    documents = db_session.scalars(select(EvidenceDocument)).all()
    assert {document.kind for document in documents} == {"licence", "government_id"}
    for document in documents:
        path = evidence_dir / document.storage_name
        assert path.is_file()
        assert document.storage_name.isalnum()
        assert len(document.sha256) == 64
        assert document.content_type in {"image/jpeg", "image/png"}

    assert len(stored_files(evidence_dir)) == 2
    assert db_session.scalars(select(EvidenceAccess)).all() == []


def test_submission_accepts_a_pdf(client, db_session):
    register_and_sign_in(client, phone=NURSE_PHONE, password=PASSWORD)
    save_profile(client)

    response = submit_form(client, licence=PDF, government_id=JPEG)

    assert response.status_code == 303
    content_types = {
        document.content_type for document in db_session.scalars(select(EvidenceDocument))
    }
    assert content_types == {"application/pdf", "image/jpeg"}


def test_submission_rejects_an_unsupported_file_type(client, db_session, evidence_dir):
    register_and_sign_in(client, phone=NURSE_PHONE, password=PASSWORD)
    save_profile(client)

    response = submit_form(client, licence=b"GIF89a" + b"nope")

    assert response.status_code == 400
    assert "JPEG, PNG, or PDF" in response.text
    assert db_session.scalars(select(VerificationCase)).all() == []
    assert stored_files(evidence_dir) == []


def test_submission_rejects_an_oversized_file(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "evidence_max_bytes", 10)
    register_and_sign_in(client, phone=NURSE_PHONE, password=PASSWORD)
    save_profile(client)

    response = submit_form(client)

    assert response.status_code == 400
    assert "at most" in response.text
    assert db_session.scalars(select(VerificationCase)).all() == []


def test_submission_requires_consent(client, db_session):
    register_and_sign_in(client, phone=NURSE_PHONE, password=PASSWORD)
    save_profile(client)

    response = submit_form(client, consent=None)

    assert response.status_code == 400
    assert "Consent is required" in response.text
    assert db_session.scalars(select(VerificationCase)).all() == []


def test_submission_requires_csrf(client, db_session):
    register_and_sign_in(client, phone=NURSE_PHONE, password=PASSWORD)
    save_profile(client)

    response = client.post(
        "/profile/verification",
        data={"registration_number": "NMCN/12345", "consent": "on"},
        files={"licence": ("licence.jpg", JPEG, "image/jpeg")},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert db_session.scalars(select(VerificationCase)).all() == []


def test_a_second_pending_case_is_refused(client, db_session):
    register_and_sign_in(client, phone=NURSE_PHONE, password=PASSWORD)
    save_profile(client)
    assert submit_form(client).status_code == 303

    response = submit_form(client)

    assert response.status_code == 400
    assert "already have a review in progress" in response.text
    assert len(db_session.scalars(select(VerificationCase)).all()) == 1


def test_review_queue_is_staff_only(client, db_session):
    register_and_sign_in(client, phone=NURSE_PHONE, password=PASSWORD)
    save_profile(client)
    create_case(db_session)

    forbidden = client.get("/review")

    assert forbidden.status_code == 403

    make_staff(db_session, NURSE_PHONE)
    allowed = client.get("/review")

    assert allowed.status_code == 200
    assert "Document review queue" in allowed.text
    assert "Ada Obi" in allowed.text


def test_approval_sets_the_document_reviewed_label(client, db_session):
    register_and_sign_in(client, phone=NURSE_PHONE, password=PASSWORD)
    save_profile(client)
    save_sharing(client, display_name="public")
    activate(client)
    case = create_case(db_session)
    public_id = profile(db_session).public_id

    sign_in_as_staff(client, db_session)
    response = decide(client, case, "approve", note="Names match.")

    assert response.status_code == 303
    db_session.expire_all()
    refreshed = db_session.get(VerificationCase, case.id)
    assert refreshed is not None
    assert refreshed.status == CaseStatus.APPROVED
    assert refreshed.decision_note == "Names match."
    assert profile(db_session).document_reviewed_at is not None

    client.cookies.clear()
    page = client.get(f"/p/{public_id}")
    assert page.status_code == 200
    text = " ".join(page.text.split())
    assert "Document reviewed" in text
    assert "not source confirmation" in text
    assert "does not check the registration against NMCN" in text


def test_a_reviewer_cannot_decide_their_own_case(client, db_session):
    register_and_sign_in(client, phone=NURSE_PHONE, password=PASSWORD)
    save_profile(client)
    case = create_case(db_session)
    make_staff(db_session, NURSE_PHONE)

    response = decide(client, case, "approve")

    assert response.status_code == 400
    assert "cannot decide their own case" in response.text
    db_session.refresh(case)
    assert case.status == CaseStatus.PENDING
    assert profile(db_session).document_reviewed_at is None


def test_rejection_needs_a_note_and_does_not_set_the_label(client, db_session):
    register_and_sign_in(client, phone=NURSE_PHONE, password=PASSWORD)
    save_profile(client)
    case = create_case(db_session)

    sign_in_as_staff(client, db_session)
    blank = decide(client, case, "reject")
    assert blank.status_code == 400
    assert "rejection needs a reason" in blank.text

    response = decide(client, case, "reject", note="Names do not match.")
    assert response.status_code == 303

    db_session.expire_all()
    refreshed = db_session.get(VerificationCase, case.id)
    assert refreshed is not None
    assert refreshed.status == CaseStatus.REJECTED
    assert refreshed.decision_note == "Names do not match."
    assert profile(db_session).document_reviewed_at is None

    sign_in(client, NURSE_PHONE)
    page = client.get("/profile/verification")
    assert "Not approved" in page.text
    assert "Names do not match." in page.text


def test_opening_evidence_is_logged(client, db_session):
    register_and_sign_in(client, phone=NURSE_PHONE, password=PASSWORD)
    save_profile(client)
    case = create_case(db_session)
    document = next(item for item in case.evidence if item.kind == "licence")

    not_staff = client.get(f"/review/{case.id}/evidence/{document.id}")
    assert not_staff.status_code == 403

    staff = sign_in_as_staff(client, db_session)
    response = client.get(f"/review/{case.id}/evidence/{document.id}")

    assert response.status_code == 200
    assert response.content == JPEG
    rows = db_session.scalars(select(EvidenceAccess)).all()
    assert len(rows) == 1
    assert rows[0].accessed_by_user_id == staff.id


def test_a_nurse_sees_only_their_own_review_history(client, db_session):
    register_and_sign_in(client, phone=NURSE_PHONE, password=PASSWORD)
    save_profile(client)
    create_case(db_session)

    client.cookies.clear()
    register_and_sign_in(client, phone=OTHER_PHONE, password=PASSWORD)
    save_profile(client)
    page = client.get("/profile/verification")

    assert page.status_code == 200
    assert "NMCN/12345" not in page.text
    assert "Submit for review" in page.text


def test_the_service_refuses_a_case_for_another_users_profile(db_session):
    owner = register_user(db_session, phone=NURSE_PHONE, password=PASSWORD)
    intruder = register_user(db_session, phone=OTHER_PHONE, password=PASSWORD)
    owner_profile = save_profile_service(
        db_session,
        owner,
        display_name="Ada Obi",
        headline="",
        location="",
        bio="",
        professional_status="graduate",
    )

    with pytest.raises(VerificationError, match="does not belong"):
        submit_case(
            db_session,
            user=intruder,
            profile=owner_profile,
            registration_number="NMCN/12345",
            licence=EvidenceUpload(data=JPEG, filename="licence.jpg"),
            government_id=EvidenceUpload(data=PNG, filename="id.png"),
        )


@pytest.mark.parametrize("first_approves", [True, False])
def test_stale_reviewer_cannot_overwrite_decision_or_public_label(
    client, db_session, first_approves,
):
    register_and_sign_in(client, phone=NURSE_PHONE, password=PASSWORD)
    save_profile(client)
    case = create_case(db_session)
    first = register_user(db_session, phone=STAFF_PHONE, password=PASSWORD)
    second = register_user(db_session, phone=OTHER_PHONE, password=PASSWORD)
    first.is_staff = second.is_staff = True
    db_session.commit()
    case_id, first_id, second_id, profile_id = case.id, first.id, second.id, case.profile_id
    with Session(db_session.get_bind()) as one, Session(db_session.get_bind()) as two:
        loaded_one = one.get(VerificationCase, case_id)
        loaded_two = two.get(VerificationCase, case_id)
        assert loaded_one.status == loaded_two.status == CaseStatus.PENDING
        decide_case(one, case=loaded_one, reviewer=one.get(User, first_id),
                    approve=first_approves, note="First completed review")
        with pytest.raises(VerificationError, match="already been decided"):
            decide_case(two, case=loaded_two, reviewer=two.get(User, second_id),
                        approve=not first_approves, note="Stale conflicting review")
        # The error page can now display the winning decision, not the stale object.
        assert loaded_two.decision_note == "First completed review"
    db_session.expire_all()
    completed = db_session.get(VerificationCase, case_id)
    assert completed.status == (CaseStatus.APPROVED if first_approves else CaseStatus.REJECTED)
    assert completed.decided_by_user_id == first_id
    assert completed.decision_note == "First completed review"
    reviewed_profile = db_session.get(NurseProfile, profile_id)
    assert (reviewed_profile.document_reviewed_at is not None) == first_approves
