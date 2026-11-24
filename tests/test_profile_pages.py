"""Regression coverage for profile pages; see tests/README.md for isolation and runner setup."""

import pytest
from sqlalchemy import select

from app.models.profile import NurseProfile, ProfileStatus
from tests.helpers import csrf_from, has_element, register_and_sign_in

PROFILE = {
    "display_name": "Ada Obi",
    "professional_status": "graduate",
    "headline": "New graduate seeking a first role",
    "location": "Lagos",
    "bio": "Registered in 2026.",
}


def save_profile(
    client,
    token: str | None = None,
    **overrides: str,
):
    if token is None:
        token = csrf_from(client.get("/profile/edit"))
    data = {"csrf_token": token, **PROFILE}
    data.update(overrides)
    return client.post("/profile/edit", data=data, follow_redirects=False)


def test_profile_requires_sign_in(client):
    response = client.get("/profile", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login"


def test_profile_redirects_to_edit_when_missing(client):
    register_and_sign_in(client)

    response = client.get("/profile", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/profile/edit"


def test_create_profile(client, db_session):
    register_and_sign_in(client)

    response = save_profile(client)

    assert response.status_code == 303
    assert response.headers["location"] == "/profile"

    page = client.get("/profile")
    assert "Ada Obi" in page.text
    assert "Graduate awaiting licensure" in page.text
    assert "Lagos" in page.text

    profile = db_session.scalar(select(NurseProfile))
    assert profile is not None
    assert profile.display_name == "Ada Obi"
    assert profile.status == ProfileStatus.DRAFT
    assert profile.discoverable is False


@pytest.mark.parametrize("enhanced", [False, True])
def test_profile_setup_returns_to_verification_without_affecting_ordinary_edits(
    client, db_session, enhanced,
):
    register_and_sign_in(client)
    page = client.get("/profile/edit?return_to=verification")
    assert has_element(page, 'input', name='return_to', value='verification')
    assert "Save and continue to verification" in page.text
    # Opening setup must not change the destination of an ordinary edit in another tab.
    assert 'name="return_to"' not in client.get("/profile/edit").text
    response = client.post(
        "/profile/edit",
        data={**PROFILE, "csrf_token": csrf_from(page), "return_to": "verification"},
        headers={"X-Account-Feedback": "1"} if enhanced else {},
        follow_redirects=False,
    )
    if enhanced:
        assert response.json() == {"redirect": "/profile/verification"}
    else:
        assert response.status_code == 303
        assert response.headers["location"] == "/profile/verification"
    verification = client.get("/profile/verification")
    assert "You can now submit your documents for review." in verification.text
    assert 'name="registration_number"' in verification.text
    assert 'type="file"' in verification.text
    assert "Create your profile to start document review" not in verification.text
    assert db_session.scalar(select(NurseProfile)).discoverable is False
    assert save_profile(client).headers["location"] == "/profile"


def test_profile_validation_keeps_verification_continuation_and_entered_values(client):
    register_and_sign_in(client)
    response = save_profile(client, display_name="", return_to="verification")
    assert response.status_code == 400
    assert has_element(response, 'input', name='return_to', value='verification')
    assert 'value="Lagos"' in response.text
    assert "Save and continue to verification" in response.text
    response = save_profile(client, token=csrf_from(response), return_to="verification")
    assert response.headers["location"] == "/profile/verification"


@pytest.mark.parametrize("destination", ["https://example.org", "//example.org", "/review"])
def test_profile_continuation_accepts_only_the_named_verification_destination(client, destination):
    register_and_sign_in(client)
    page = client.get("/profile/edit", params={"return_to": destination})
    assert 'name="return_to"' not in page.text
    response = save_profile(client, return_to=destination)
    assert response.status_code == 303
    assert response.headers["location"] == "/profile"


def test_edit_updates_the_existing_profile(client, db_session):
    register_and_sign_in(client)
    save_profile(client)

    token = csrf_from(client.get("/profile/edit"))
    response = save_profile(
        client,
        token=token,
        display_name="Ada N. Obi",
        location="Abuja",
    )

    assert response.status_code == 303

    profile = db_session.scalar(select(NurseProfile))
    assert profile is not None
    assert profile.display_name == "Ada N. Obi"
    assert profile.location == "Abuja"

    profiles = db_session.scalars(select(NurseProfile)).all()
    assert len(profiles) == 1


def test_edit_form_is_prefilled(client):
    register_and_sign_in(client)
    save_profile(client)

    page = client.get("/profile/edit")

    assert 'value="Ada Obi"' in page.text
    assert "New graduate seeking a first role" in page.text


def test_new_edit_form_defaults_to_student(client):
    register_and_sign_in(client)

    page = client.get("/profile/edit")

    assert has_element(page, "option", value="student", selected=True)


def test_display_name_is_required(client, db_session):
    register_and_sign_in(client)

    response = save_profile(client, display_name="   ")

    assert response.status_code == 400
    assert "Display name is required." in response.text
    assert db_session.scalar(select(NurseProfile)) is None


def test_professional_status_must_be_known(client):
    register_and_sign_in(client)

    response = save_profile(client, professional_status="chief-nurse")

    assert response.status_code == 400
    assert "valid professional status" in response.text


def test_display_name_length_is_enforced(client):
    register_and_sign_in(client)

    response = save_profile(client, display_name="x" * 121)

    assert response.status_code == 400
    assert "at most 120" in response.text


def test_profile_save_requires_a_csrf_token(client):
    register_and_sign_in(client)

    response = client.post("/profile/edit", data=PROFILE, follow_redirects=False)

    assert response.status_code == 400


def test_one_users_profile_is_not_visible_to_another(client):
    register_and_sign_in(client)
    save_profile(client)

    token = csrf_from(client.get("/"))
    client.post(
        "/auth/logout",
        data={"csrf_token": token},
        follow_redirects=False,
    )

    register_and_sign_in(client, phone="0802 345 6789")

    response = client.get("/profile", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/profile/edit"

    page = client.get("/profile/edit")
    assert "Ada Obi" not in page.text
