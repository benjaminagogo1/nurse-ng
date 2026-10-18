from sqlalchemy import select

from app.models.profile import NurseProfile, ProfileStatus
from tests.helpers import csrf_from, register_and_sign_in

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

    assert 'value="student" selected' in page.text


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
