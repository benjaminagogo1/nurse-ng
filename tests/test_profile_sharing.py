"""Activation, sharing controls, and the public share link."""

import pytest
from sqlalchemy import select

from app.models.profile import FieldVisibility, NurseProfile, ProfileStatus
from app.services.profiles import ProfileError, save_sharing_settings
from tests.helpers import csrf_from, register_and_sign_in
from tests.test_profile_pages import save_profile


def profile_id(db_session) -> str:
    profile = db_session.scalar(select(NurseProfile))
    assert profile is not None
    return str(profile.public_id)


def activate(client):
    token = csrf_from(client.get("/profile"))
    return client.post(
        "/profile/activate",
        data={"csrf_token": token},
        follow_redirects=False,
    )


def deactivate(client):
    token = csrf_from(client.get("/profile"))
    return client.post(
        "/profile/deactivate",
        data={"csrf_token": token},
        follow_redirects=False,
    )


def save_sharing(client, **choices: str):
    token = csrf_from(client.get("/profile/sharing"))
    data = {"csrf_token": token}
    data.update({f"visibility_{name}": value for name, value in choices.items()})
    return client.post("/profile/sharing", data=data, follow_redirects=False)


def test_draft_profile_link_is_not_found(client, db_session):
    register_and_sign_in(client)
    save_profile(client)

    response = client.get(f"/p/{profile_id(db_session)}")

    assert response.status_code == 404


def test_activation_requires_sign_in(client):
    response = client.post("/profile/activate", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login"


def test_activation_turns_on_a_share_link(client, db_session):
    register_and_sign_in(client)
    save_profile(client)

    response = activate(client)

    assert response.status_code == 303
    assert response.headers["location"] == "/profile"

    profile = db_session.scalar(select(NurseProfile))
    assert profile is not None
    assert profile.status == ProfileStatus.ACTIVE
    assert profile.discoverable is False

    page = client.get("/profile")
    assert "Active · shared by link" in page.text
    assert f"/p/{profile.public_id}" in page.text


def test_activation_requires_a_csrf_token(client, db_session):
    register_and_sign_in(client)
    save_profile(client)

    response = client.post("/profile/activate", follow_redirects=False)

    assert response.status_code == 400
    profile = db_session.scalar(select(NurseProfile))
    assert profile is not None
    assert profile.status == ProfileStatus.DRAFT


def test_activation_requires_a_display_name(client, db_session):
    register_and_sign_in(client)
    save_profile(client)

    profile = db_session.scalar(select(NurseProfile))
    assert profile is not None
    profile.display_name = ""
    db_session.commit()

    response = activate(client)

    assert response.status_code == 400
    assert "Add a display name" in response.text
    assert profile.status == ProfileStatus.DRAFT


def test_activation_never_sets_discoverable(client, db_session):
    register_and_sign_in(client)
    save_profile(client)

    profile = db_session.scalar(select(NurseProfile))
    assert profile is not None
    profile.discoverable = True
    db_session.commit()

    activate(client)

    db_session.refresh(profile)
    assert profile.discoverable is False


def test_public_link_shows_only_public_fields(client, db_session):
    register_and_sign_in(client)
    save_profile(client)
    save_sharing(client, display_name="public", headline="public")
    activate(client)

    response = client.get(f"/p/{profile_id(db_session)}")

    assert response.status_code == 200
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    assert "Ada Obi" in response.text
    assert "New graduate seeking a first role" in response.text
    assert "Lagos" not in response.text
    assert "Registered in 2026." not in response.text
    assert "Graduate awaiting licensure" not in response.text


def test_public_link_falls_back_when_name_is_private(client, db_session):
    register_and_sign_in(client)
    save_profile(client)
    save_sharing(client, headline="public")
    activate(client)

    response = client.get(f"/p/{profile_id(db_session)}")

    assert response.status_code == 200
    assert "Nurse profile" in response.text
    assert "New graduate seeking a first role" in response.text
    assert "Ada Obi" not in response.text


def test_public_link_is_readable_without_signing_in(client, db_session):
    register_and_sign_in(client)
    save_profile(client)
    save_sharing(client, display_name="public")
    activate(client)
    identifier = profile_id(db_session)

    client.cookies.clear()
    response = client.get(f"/p/{identifier}")

    assert response.status_code == 200
    assert "Ada Obi" in response.text


def test_deactivation_turns_the_link_off(client, db_session):
    register_and_sign_in(client)
    save_profile(client)
    activate(client)
    identifier = profile_id(db_session)

    response = deactivate(client)

    assert response.status_code == 303
    assert response.headers["location"] == "/profile"

    profile = db_session.scalar(select(NurseProfile))
    assert profile is not None
    assert profile.status == ProfileStatus.DRAFT
    assert client.get(f"/p/{identifier}").status_code == 404

    page = client.get("/profile")
    assert "Private profile · Draft" in page.text


def test_unknown_and_malformed_links_are_not_found(client):
    assert client.get("/p/not-a-uuid").status_code == 404
    assert (
        client.get("/p/01920000-0000-7000-8000-000000000000").status_code == 404
    )


def test_sharing_requires_sign_in(client):
    response = client.get("/profile/sharing", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login"


def test_sharing_redirects_to_edit_when_missing(client):
    register_and_sign_in(client)

    response = client.get("/profile/sharing", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/profile/edit"


def test_sharing_page_lists_every_shareable_field(client):
    register_and_sign_in(client)
    save_profile(client)

    page = client.get("/profile/sharing")

    assert page.status_code == 200
    for name in ("display_name", "professional_status", "headline", "location", "bio"):
        assert f'name="visibility_{name}"' in page.text
    assert "Employer-only visibility will arrive" in page.text


def test_sharing_saves_and_removes_rows(client, db_session):
    register_and_sign_in(client)
    save_profile(client)

    response = save_sharing(client, display_name="public", bio="public")

    assert response.status_code == 303
    profile = db_session.scalar(select(NurseProfile))
    assert profile is not None
    rows = db_session.scalars(select(FieldVisibility)).all()
    assert {row.field for row in rows} == {"display_name", "bio"}
    assert all(row.visibility == "public" for row in rows)

    save_sharing(client, display_name="public")

    rows = db_session.scalars(select(FieldVisibility)).all()
    assert {row.field for row in rows} == {"display_name"}


def test_sharing_can_make_every_field_private_again(client, db_session):
    register_and_sign_in(client)
    save_profile(client)
    save_sharing(client, display_name="public")

    response = save_sharing(client, display_name="private")

    assert response.status_code == 303
    rows = db_session.scalars(select(FieldVisibility)).all()
    assert rows == []


def test_sharing_rejects_an_unknown_visibility_level(client, db_session):
    register_and_sign_in(client)
    save_profile(client)

    response = save_sharing(client, display_name="employers")

    assert response.status_code == 400
    assert "Choose private or public" in response.text
    assert db_session.scalars(select(FieldVisibility)).all() == []


def test_sharing_rejects_an_unknown_field(client, db_session):
    register_and_sign_in(client)
    save_profile(client)
    profile = db_session.scalar(select(NurseProfile))
    assert profile is not None

    with pytest.raises(ProfileError, match="Unknown profile field"):
        save_sharing_settings(db_session, profile, {"licence_number": "public"})


def test_sharing_requires_a_csrf_token(client, db_session):
    register_and_sign_in(client)
    save_profile(client)

    response = client.post(
        "/profile/sharing",
        data={"visibility_display_name": "public"},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert db_session.scalars(select(FieldVisibility)).all() == []


def test_active_owner_page_warns_when_name_is_private(client, db_session):
    register_and_sign_in(client)
    save_profile(client)
    activate(client)

    page = client.get("/profile")

    assert "shared page will not show your name" in page.text
    assert "(0 public)" in page.text


def test_robots_txt_blocks_crawlers(client):
    response = client.get("/robots.txt")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "User-agent: *\nDisallow: /\n"
