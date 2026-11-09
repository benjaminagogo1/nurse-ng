"""Discovery must not infer hidden fields, publish profiles, or change alert consent."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.profile import FieldVisibility, NurseProfile
from app.models.user import User
from app.services.community import follow_profile, request_connection
from app.services.jobs import create_job
from app.services.member_discovery import (
    suggested_opportunities,
    suggested_people,
)
from app.services.member_interests import INTEREST_OPTIONS
from app.services.opportunity_watch import preferences, save_preferences
from app.services.profiles import (
    count_discoverable_profiles,
    get_visibility_map,
    list_discoverable_profiles,
    save_sharing_settings,
)
from tests.helpers import csrf_from, register_and_sign_in


def person(db, number, *, public=True, name=None, fields=(), **values):
    user = User(phone=f"+23480000{number:05}", hashed_password="test-only")
    db.add(user)
    db.flush()
    profile = NurseProfile(
        user_id=user.id,
        display_name=name or f"Member {number:03}",
        status="active" if public else "draft",
        discoverable=public,
        **values,
    )
    db.add(profile)
    db.flush()
    for field in ("display_name", *fields):
        db.add(FieldVisibility(profile_id=profile.id, field=field, visibility="public"))
    db.commit()
    return profile


@pytest.mark.parametrize(
    ("filters", "field", "value"),
    [
        ({"query": "SecretSkill"}, "skills", "SecretSkill"),
        ({"query": "private headline"}, "headline", "private headline"),
        ({"location": "Enugu"}, "location", "Enugu"),
        ({"query": "Enugu"}, "location", "Enugu"),
        ({"interest": "Digital health"}, "interests", "Digital health"),
        ({"query": "Digital health"}, "interests", "Digital health"),
        ({"professional_status": "specialist"}, "professional_status", "specialist"),
    ],
)
def test_hidden_fields_cannot_change_results_or_counts(db_session, filters, field, value):
    profile = person(db_session, 1, **{field: value})
    assert list_discoverable_profiles(db_session, **filters) == []
    assert count_discoverable_profiles(db_session, **filters) == 0
    save_sharing_settings(db_session, profile, {"display_name": "public", field: "public"})
    assert list_discoverable_profiles(db_session, **filters) == [profile]
    assert count_discoverable_profiles(db_session, **filters) == 1
    save_sharing_settings(db_session, profile, {"display_name": "public", field: "private"})
    assert list_discoverable_profiles(db_session, **filters) == []


@pytest.mark.parametrize("state", ["draft", "hidden", "suspended", "inactive", "private_name"])
def test_nonpublic_or_unavailable_members_are_excluded(db_session, state):
    profile = person(db_session, 1)
    if state == "draft":
        profile.status = "draft"
    elif state == "hidden":
        profile.discoverable = False
    elif state == "suspended":
        profile.user.status = "suspended"
    elif state == "inactive":
        profile.user.is_active = False
    else:
        row = db_session.scalar(select(FieldVisibility))
        row.visibility = "private"
    viewer = person(db_session, 2, public=False)
    db_session.commit()
    assert list_discoverable_profiles(db_session) == []
    assert suggested_people(db_session, viewer.user) == []


def test_combined_filters_literal_search_and_stable_pagination(client, db_session):
    for number in range(1, 15):
        person(
            db_session,
            number,
            location="Lagos",
            interests="Public health",
            professional_status="registered",
            fields=("location", "interests", "professional_status"),
        )
    filters = {
        "query": "member",
        "location": "lagos",
        "interest": "Public health",
        "professional_status": "registered",
    }
    first = list_discoverable_profiles(db_session, limit=12, **filters)
    second = list_discoverable_profiles(db_session, limit=12, offset=12, **filters)
    assert len(first) == 12 and len(second) == 2
    assert not {p.id for p in first} & {p.id for p in second}
    assert count_discoverable_profiles(db_session, **filters) == 14
    assert list_discoverable_profiles(db_session, query="%") == []
    assert list_discoverable_profiles(db_session, query="_") == []
    page = client.get("/nurses?location=Lagos&interest=Public+health&page=2")
    assert page.status_code == 200
    assert "Page 2 of 2" in page.text and 'rel="prev"' in page.text
    assert "location=Lagos" in page.text and "interest=Public+health" in page.text
    assert page.text.count('class="profile-card person-card"') == 2
    assert client.get("/nurses?q=" + "a" * 121).status_code == 422
    assert client.get("/nurses?page=0").status_code == 422
    assert "Page 2 of 2" in client.get("/nurses?page=900").text


def test_people_ranking_uses_only_public_fields_and_excludes_existing_relationships(db_session):
    viewer = person(db_session, 1, public=False, interests="Digital health", location="Abuja")
    hidden = person(
        db_session, 2, name="A private match", interests="Digital health", location="Abuja"
    )
    unrelated = person(db_session, 3, name="B unrelated")
    public = person(
        db_session, 4, name="Z public match", interests="Digital health", fields=("interests",)
    )
    cards = suggested_people(db_session, viewer.user)
    assert [c["profile"] for c in cards] == [public, hidden, unrelated]
    assert cards[0]["reason"] == "Shared interest: Digital health"
    assert cards[1]["reason"] == "Explore this public profile"
    hidden.interests = "Maternal health"
    hidden.location = "Lagos"
    db_session.commit()
    assert [c["profile"] for c in suggested_people(db_session, viewer.user)] == [
        public,
        hidden,
        unrelated,
    ]
    follow_profile(db_session, viewer.user, public)
    request_connection(db_session, viewer.user, hidden)
    assert [c["profile"] for c in suggested_people(db_session, viewer.user)] == [unrelated]


def test_directory_and_suggestions_honour_photo_visibility(client, db_session):
    register_and_sign_in(client)
    profile = person(db_session, 2, name="Public Member")
    profile.user.photo_storage_name = "a" * 32
    profile.user.photo_public = False
    db_session.commit()
    path = "/account/photos/" + profile.user.photo_storage_name
    for route in ["/nurses", "/welcome/discover", "/auth/dashboard"]:
        assert path not in client.get(route).text
    assert client.get(path).status_code == 404
    profile.user.photo_public = True
    db_session.commit()
    assert path in client.get("/nurses").text
    profile.user.photo_public = False
    db_session.commit()
    assert path not in client.get("/welcome/discover").text


def welcome_save(client, **values):
    return client.post(
        "/welcome",
        data={"csrf_token": csrf_from(client.get("/welcome")), **values},
        follow_redirects=False,
    )


def test_onboarding_saves_private_profile_and_shows_feedback(client, db_session):
    register_and_sign_in(client)
    user = db_session.scalar(select(User))
    assert "Personalise my experience" in client.get("/auth/dashboard").text
    assert (
        welcome_save(
            client, interests=["Digital health", "Internships"], location=" Lagos "
        ).status_code
        == 303
    )
    profile = db_session.scalar(select(NurseProfile))
    assert profile.interests == "Digital health, Internships"
    assert profile.location == "Lagos"
    assert not profile.discoverable and profile.status == "draft"
    assert set(get_visibility_map(db_session, profile).values()) == {"private"}
    assert not user.photo_public and user.onboarding_completed_at
    assert preferences(db_session, user) is None
    page = client.get("/welcome/discover")
    assert 'id="feedback-title">Your interests are saved' in page.text
    assert "Your profile is private." in page.text
    assert "Personalise my experience" not in client.get("/auth/dashboard").text
    assert 'value="Digital health" checked' in client.get("/welcome").text
    assert 'value="Digital health" checked' in client.get("/profile/edit").text
    assert client.get(f"/p/{profile.public_id}").status_code == 404


def test_skip_is_resumable_and_does_not_create_a_profile(client, db_session):
    register_and_sign_in(client)
    response = client.post("/welcome/skip", data={"csrf_token": csrf_from(client.get("/welcome"))})
    assert response.status_code == 200
    assert db_session.scalar(select(NurseProfile)) is None
    assert db_session.scalar(select(User)).onboarding_completed_at
    assert welcome_save(client, interests=["Research"]).status_code == 303
    assert db_session.scalar(select(NurseProfile)).interests == "Research"


@pytest.mark.parametrize(
    "values",
    [
        {"interests": ["Unknown interest"]},
        {"interests": list(INTEREST_OPTIONS[:7])},
        {"location": "x" * 121},
    ],
)
def test_invalid_onboarding_is_atomic(client, db_session, values):
    register_and_sign_in(client)
    response = welcome_save(client, **values)
    assert response.status_code == 400
    assert 'role="alert"' in response.text
    assert db_session.scalar(select(NurseProfile)) is None
    assert db_session.scalar(select(User)).onboarding_completed_at is None


def test_onboarding_requires_authentication_and_csrf(client, db_session):
    assert client.get("/welcome", follow_redirects=False).headers["location"] == "/auth/login"
    assert client.get("/welcome/discover", follow_redirects=False).status_code == 303
    register_and_sign_in(client)
    for path in ["/welcome", "/welcome/skip"]:
        assert client.post(path, data={"interests": "Public health"}).status_code == 400
    assert db_session.scalar(select(User)).onboarding_completed_at is None


def test_onboarding_preserves_existing_sharing_photo_and_alert_choices(client, db_session):
    register_and_sign_in(client)
    user = db_session.scalar(select(User))
    profile = NurseProfile(
        user_id=user.id,
        display_name="Existing Member",
        headline="Keep this",
        status="active",
        discoverable=True,
        interests="Research",
    )
    db_session.add(profile)
    db_session.commit()
    save_sharing_settings(db_session, profile, {"display_name": "public", "interests": "public"})
    user.photo_public = True
    db_session.commit()
    save_preferences(
        db_session,
        user,
        keyword="fellowship",
        location="Enugu",
        job_type="",
        country_code="NG",
        enabled=True,
    )
    before = preferences(db_session, user).active_since
    page = client.get("/welcome")
    assert "Interests are <strong>public</strong>" in page.text
    assert welcome_save(client, interests=["Public health"], location="Lagos").status_code == 303
    assert profile.discoverable and user.photo_public and profile.headline == "Keep this"
    assert get_visibility_map(db_session, profile)["interests"] == "public"
    choice = preferences(db_session, user)
    assert choice.enabled and choice.location == "Enugu" and choice.keyword == "fellowship"
    assert choice.active_since == before
    public = client.get(f"/p/{profile.public_id}")
    assert "Professional interests" in public.text and "Public health" in public.text


def test_opportunity_suggestions_use_interests_ng_priority_and_current_jobs(db_session):
    viewer = person(db_session, 1, public=False, interests="Digital health")
    employer = person(db_session, 2).user
    employer.account_type = "employer"
    db_session.commit()

    def job(title, code="NG"):
        return create_job(
            db_session,
            employer,
            title=title,
            organization="Test Health",
            location="",
            job_type="fellowship",
            work_mode="on_site",
            salary_min="",
            salary_max="",
            country_code=code,
            description="A supervised placement.",
        )

    local = job("Digital health fellowship")
    abroad = job("Digital health informatics", "GB")
    unrelated = job("Maternal health nurse")
    expired = job("Digital health expired")
    expired.closes_at = datetime.now(UTC) - timedelta(days=1)
    closed = job("Digital health closed")
    closed.status = "closed"
    db_session.commit()
    jobs, personalised = suggested_opportunities(db_session, viewer.user)
    assert personalised and [str(j["id"]) for j in jobs] == [str(local.id), str(abroad.id)]
    viewer.interests = "Critical care"
    db_session.commit()
    jobs, personalised = suggested_opportunities(db_session, viewer.user, limit=10)
    assert not personalised
    assert str(unrelated.id) in {str(j["id"]) for j in jobs}
    assert str(expired.id) not in {str(j["id"]) for j in jobs}
    assert str(closed.id) not in {str(j["id"]) for j in jobs}
    assert str(jobs[-1]["id"]) == str(abroad.id)
