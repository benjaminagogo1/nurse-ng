"""Community participation, useful replies, activities and public membership privacy."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.models.community import (
    CommunityAnswer,
    CommunityMembership,
    CommunityPost,
    CommunityTopic,
    ContentStatus,
    HelpfulReply,
)
from app.models.profile import NurseProfile
from app.models.user import User, UserStatus
from app.services import community_growth as growth
from app.services.community import CommunityError, add_reply, create_post, list_published_posts
from app.services.offline_content import post as offline_post
from app.web.deps import get_current_user
from tests.helpers import csrf_from, has_element
from tests.test_community import create_topic


@pytest.fixture
def members(db_session):
    result = [
        User(
            phone=f"+23480990000{i:02}",
            hashed_password="unused",
            community_name=f"Peer {i}",
            community_name_key=f"peer {i}",
            full_name=f"PRIVATE ACCOUNT NAME {i}",
        )
        for i in range(3)
    ]
    db_session.add_all(result)
    db_session.commit()
    return result


def values(**changes):
    return {
        "name": "Critical care colleagues",
        "description": "For all career stages.",
        "welcome_text": "Everyone is welcome.",
        "rules": "Respect privacy and colleagues.",
        "interest": "Critical care",
        **changes,
    }


def question(db, user, topic, **changes):
    return create_post(
        db,
        user,
        topic_id=topic.id,
        body="How do you prepare for a shift?",
        post_kind="question",
        **changes,
    )


@pytest.mark.parametrize("key", growth.COMMUNITY_EXAMPLES)
def test_examples_prefill_editable_form_without_creating_communities(
    client, db_session, members, key
):
    from app.main import app

    owner = members[0]
    app.dependency_overrides[get_current_user] = lambda: owner
    directory = client.get("/communities")
    link = f"/communities/new?example={key}#community-details"
    assert has_element(directory, "a", href=link)
    form = client.get(link)
    assert form.status_code == 200
    assert form.context["values"] == growth.COMMUNITY_EXAMPLES[key]
    for field in ("name", "description", "welcome_text", "rules", "interest"):
        tag = "input" if field == "name" else "select" if field == "interest" else "textarea"
        assert has_element(form, tag, name=field, readonly=False, disabled=False)
    assert db_session.scalar(select(func.count()).select_from(CommunityTopic)) == 0
    assert db_session.scalar(select(func.count()).select_from(CommunityMembership)) == 0
    assert not owner.community_name_locked


def test_member_can_customize_example_or_create_own_community(client, db_session, members):
    from app.main import app

    owner = members[0]
    assert not owner.is_staff
    app.dependency_overrides[get_current_user] = lambda: owner
    for source in ("/communities/new?example=local-network", "/communities/new"):
        form = client.get(source)
        own_values = values(
            name="Nurses returning to practice" if "example" in source else "Nurses in Jos",
            description="A peer network shaped around our own professional needs.",
            interest="",
            welcome_text="Bring your ideas and questions.",
            rules="Be kind and protect personal information.",
        )
        response = client.post(
            "/communities",
            data={"csrf_token": csrf_from(form), **own_values},
            follow_redirects=False,
        )
        assert response.status_code == 303
        topic = db_session.scalar(
            select(CommunityTopic).where(CommunityTopic.name == own_values["name"])
        )
        assert topic.created_by_user_id == owner.id
        assert all(getattr(topic, field) == value for field, value in own_values.items())
        assert growth.community_summaries(db_session, [topic], owner)[topic.id]["joined"]
        composer = client.get(f"/posts/new?topic={topic.id}")
        assert has_element(composer, "option", value=str(topic.id), selected=True)
        published = client.post(
            "/posts",
            data={
                "csrf_token": csrf_from(composer),
                "topic_id": str(topic.id),
                "body": f"Welcome to {topic.name}.",
            },
            follow_redirects=False,
        )
        assert published.status_code == 303
        assert topic.name in client.get(published.headers["location"]).text
    assert db_session.scalar(select(func.count()).select_from(CommunityTopic)) == 2


def test_unknown_example_keeps_form_blank_and_creation_is_discoverable(client, members):
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: members[0]
    form = client.get("/communities/new?example=custom-idea")
    assert form.status_code == 200 and form.context["values"] == {}
    for path in ("/feed", "/posts/new", "/welcome/discover"):
        assert has_element(client.get(path), "a", href="/communities/new")


@pytest.mark.parametrize("additional_community", [False, True])
def test_generic_composer_requires_member_to_choose_community(
    client, db_session, members, additional_community
):
    from app.main import app

    general = create_topic(db_session)
    if additional_community:
        create_topic(db_session, "Nurses in Jos")
    app.dependency_overrides[get_current_user] = lambda: members[0]
    form = client.get("/posts/new")
    assert form.context["values"]["topic_id"] == ""
    assert not has_element(form, "option", selected=True, value=str(general.id))
    linked = client.get(f"/posts/new?topic={general.id}")
    assert has_element(linked, "option", selected=True, value=str(general.id))
    invalid = client.get(f"/posts/new?topic={uuid4()}")
    assert invalid.context["values"]["topic_id"] == ""


def test_member_can_host_edit_and_join_without_publishing_profile(db_session, members):
    owner, peer, staff = members
    topic = growth.create_community(db_session, owner, **values())
    original_slug = topic.slug
    assert owner.community_name_locked
    assert db_session.scalar(select(NurseProfile)) is None
    assert growth.community_summaries(db_session, [topic], owner)[topic.id] == {
        "members": 1,
        "joined": True,
    }
    with pytest.raises(CommunityError, match="host or staff"):
        growth.update_community(db_session, peer, topic, **values(name="Another name"))
    growth.update_community(db_session, owner, topic, **values(name="Nursing colleagues"))
    assert topic.slug == original_slug
    staff.is_staff = True
    growth.update_community(db_session, staff, topic, **values(welcome_text="Welcome back."))
    assert topic.welcome_text == "Welcome back."
    assert growth.can_manage_community(None, topic) is False


@pytest.mark.parametrize(
    "change", [{"rules": ""}, {"description": ""}, {"interest": "unknown"}, {"name": "Official"}]
)
def test_community_validation_leaves_no_partial_community(db_session, members, change):
    from app.models.community import CommunityTopic

    with pytest.raises(CommunityError):
        growth.create_community(db_session, members[0], **values(**change))
    assert db_session.scalar(select(func.count()).select_from(CommunityTopic)) == 0
    assert db_session.scalar(select(func.count()).select_from(CommunityMembership)) == 0


def test_membership_is_idempotent_private_and_excludes_inactive_accounts(
    client, db_session, members
):
    owner, peer, _ = members
    topic = growth.create_community(db_session, owner, **values())
    post = question(db_session, owner, topic)
    for _ in range(2):
        growth.membership(db_session, peer, topic, joined=True)
    assert growth.communities(db_session, user=peer, mine=True) == [topic]
    assert list_published_posts(db_session, community_member_id=peer.id) == [post]
    page = client.get(f"/topics/{topic.slug}")
    assert "2 members" in page.text
    assert peer.full_name not in page.text and peer.phone not in page.text
    assert not growth.communities(db_session, mine=True)
    peer.is_active = False
    db_session.commit()
    assert growth.community_summaries(db_session, [topic], None)[topic.id]["members"] == 1
    with pytest.raises(CommunityError, match="active account"):
        growth.membership(db_session, peer, topic, joined=True)
    peer.is_active = True
    for _ in range(2):
        growth.membership(db_session, peer, topic, joined=False)
    assert list_published_posts(db_session, community_member_id=peer.id) == []
    # Leaving does not block reading or replying to a public conversation.
    assert client.get(f"/posts/{post.id}").status_code == 200
    assert add_reply(db_session, peer, post, "Useful context").status == "published"
    topic.is_active = False
    db_session.commit()
    assert growth.communities(db_session) == []
    assert client.get(f"/topics/{topic.slug}").status_code == 404
    assert client.get(f"/posts/{post.id}").status_code == 404
    with pytest.raises(CommunityError, match="no longer available"):
        growth.membership(db_session, owner, topic, joined=True)


def test_unanswered_questions_ignore_author_followups_and_removed_answers(db_session, members):
    owner, peer, _ = members
    topic = create_topic(db_session)
    post = question(db_session, owner, topic)
    conversation = create_post(db_session, owner, topic_id=topic.id, body="An experience")
    assert list_published_posts(db_session, unanswered=True) == [post]
    add_reply(db_session, owner, post, "More details from the question's author")
    assert list_published_posts(db_session, unanswered=True) == [post]
    reply = add_reply(db_session, peer, post, "A colleague's response")
    assert list_published_posts(db_session, unanswered=True) == []
    growth.select_answer(db_session, owner, reply.id, selected=True)
    assert growth.answer_summaries(db_session, [post])[post.id]["answer_id"] == reply.id
    reply.status = ContentStatus.REMOVED
    db_session.commit()
    assert list_published_posts(db_session, unanswered=True) == [post]
    assert not growth.answer_summaries(db_session, [post])[post.id]["answered"]
    assert conversation.post_kind == "discussion"


def test_helpful_recognition_is_one_per_member_and_cannot_be_self_given(db_session, members):
    owner, peer, voter = members
    topic = create_topic(db_session)
    post = question(db_session, owner, topic)
    reply = add_reply(db_session, peer, post, "Prepare and communicate")
    with pytest.raises(CommunityError, match="another member"):
        growth.recognize_reply(db_session, peer, reply.id, marked=True)
    for _ in range(2):
        growth.recognize_reply(db_session, owner, reply.id, marked=True)
    growth.recognize_reply(db_session, voter, reply.id, marked=True)
    assert growth.helpful_summaries(db_session, [reply], owner)[reply.id] == {
        "count": 2,
        "marked": True,
    }
    voter.status = UserStatus.SUSPENDED
    db_session.commit()
    assert growth.helpful_summaries(db_session, [reply], None)[reply.id]["count"] == 1
    for _ in range(2):
        growth.recognize_reply(db_session, owner, reply.id, marked=False)
    assert db_session.scalar(select(func.count()).select_from(HelpfulReply)) == 1
    reply.status = ContentStatus.REMOVED
    db_session.commit()
    with pytest.raises(CommunityError, match="no longer available"):
        growth.recognize_reply(db_session, owner, reply.id, marked=True)


def test_answer_belongs_to_its_question_and_only_author_can_select(db_session, members):
    owner, peer, _ = members
    topic = create_topic(db_session)
    first = question(db_session, owner, topic)
    second = question(db_session, peer, topic)
    reply = add_reply(db_session, peer, first, "Answer one")
    other = add_reply(db_session, owner, second, "Answer two")
    with pytest.raises(CommunityError, match="question's author"):
        growth.select_answer(db_session, peer, reply.id, selected=True)
    with pytest.raises(CommunityError, match="question's author"):
        growth.select_answer(db_session, owner, other.id, selected=True)
    growth.select_answer(db_session, owner, reply.id, selected=True)
    replacement = add_reply(db_session, peer, first, "A more useful answer")
    growth.select_answer(db_session, owner, replacement.id, selected=True)
    # A stale removal action cannot remove a newly selected answer.
    growth.select_answer(db_session, owner, reply.id, selected=False)
    assert db_session.get(CommunityAnswer, first.id).reply_id == replacement.id
    growth.select_answer(db_session, owner, replacement.id, selected=False)
    assert db_session.get(CommunityAnswer, first.id) is None
    first.status = ContentStatus.REMOVED
    db_session.commit()
    with pytest.raises(CommunityError, match="no longer available"):
        growth.select_answer(db_session, owner, reply.id, selected=True)


@pytest.mark.parametrize("activity_format", growth.ACTIVITY_FORMATS)
def test_learning_formats_timezone_and_search(db_session, members, activity_format):
    topic = create_topic(db_session)
    post = create_post(
        db_session,
        members[0],
        topic_id=topic.id,
        body="Discuss your approach.",
        post_kind="activity",
        title="Professional development practice",
        activity_format=activity_format,
        activity_starts_at="2026-11-30T16:30",
    )
    assert post.activity_starts_at.replace(tzinfo=UTC) == datetime(2026, 11, 30, 15, 30, tzinfo=UTC)
    assert growth.activity_time(post.activity_starts_at) == "30 Nov 2026 04:30 PM"
    assert list_published_posts(db_session, post_kind="activity", query="development") == [post]
    assert list_published_posts(db_session, post_kind="question") == []


@pytest.mark.parametrize(
    "changes",
    [
        {"title": ""},
        {"activity_format": "invalid"},
        {"activity_starts_at": "not a date"},
        {"body": ""},
        {"post_kind": "unknown"},
    ],
)
def test_invalid_learning_activity_is_not_published(db_session, members, changes):
    topic = create_topic(db_session)
    details = {
        "body": "Instructions",
        "post_kind": "activity",
        "title": "Practice together",
        "activity_format": "practice",
        **changes,
    }
    with pytest.raises(CommunityError):
        create_post(db_session, members[0], topic_id=topic.id, **details)
    assert db_session.scalar(select(func.count()).select_from(CommunityPost)) == 0


def test_offline_metadata_and_legacy_payloads_use_normal_validation(db_session, members):
    topic = create_topic(db_session)
    payload = {
        "topic_id": str(topic.id),
        "body": "Discuss together",
        "community_name": "",
        "external_video_url": "",
    }
    legacy = offline_post(db_session, members[0], payload)
    assert db_session.get(CommunityPost, UUID(legacy["id"])).post_kind == "discussion"
    result = offline_post(
        db_session,
        members[0],
        {
            **payload,
            "post_kind": "activity",
            "title": "Digital health Q&A",
            "activity_format": "q-and-a",
            "activity_starts_at": "2026-11-30T15:00",
        },
    )
    assert result["path"].startswith("/posts/")
    with pytest.raises(CommunityError, match="Title"):
        offline_post(db_session, members[0], {**payload, "post_kind": "activity"})


def test_routes_enforce_csrf_and_render_growth_controls(client, db_session, members):
    from app.main import app

    owner, peer, _ = members
    app.dependency_overrides[get_current_user] = lambda: owner
    token = csrf_from(client.get("/communities/new"))
    assert client.post("/communities", data=values(), follow_redirects=False).status_code == 400
    result = client.post(
        "/communities", data={"csrf_token": token, **values()}, follow_redirects=False
    )
    assert result.status_code == 303
    topic = growth.communities(db_session)[0]
    post = question(db_session, owner, topic)
    reply = add_reply(db_session, peer, post, "Here is what helps")
    page = client.get(f"/posts/{post.id}")
    assert has_element(page, "form", action=f"/replies/{reply.id}/helpful")
    assert has_element(page, "form", action=f"/replies/{reply.id}/answer")
    for endpoint in [
        f"/communities/{topic.slug}/membership",
        f"/replies/{reply.id}/helpful",
        f"/replies/{reply.id}/answer",
    ]:
        assert client.post(endpoint, follow_redirects=False).status_code == 400
    for endpoint, action in [
        (f"/replies/{reply.id}/helpful", "mark"),
        (f"/replies/{reply.id}/answer", "select"),
    ]:
        result = client.post(
            endpoint, data={"csrf_token": csrf_from(page), "action": action}, follow_redirects=False
        )
        assert result.status_code == 303
        assert f"#reply-{reply.id}" in result.headers["location"]
    assert "Selected answer" in client.get(f"/posts/{post.id}").text
    assert client.get("/activities").status_code == 200
    assert client.get("/feed/communities").status_code == 200
    assert client.get("/feed/unanswered").status_code == 200
    assert client.get(f"/replies/{uuid4()}/answer").status_code == 405


def test_suggestions_use_own_interests_without_exposing_profile(client, db_session, members):
    from app.main import app

    owner, peer, _ = members
    general = growth.create_community(
        db_session, peer, **values(name="A general space", interest="")
    )
    match = growth.create_community(db_session, peer, **values())
    profile = NurseProfile(user_id=owner.id, interests="Critical care", discoverable=False)
    db_session.add(profile)
    db_session.commit()
    assert growth.suggested_communities(db_session, owner)[0] == match
    growth.membership(db_session, owner, match, joined=True)
    assert growth.suggested_communities(db_session, owner) == [general]
    app.dependency_overrides[get_current_user] = lambda: owner
    assert "Communities to explore" in client.get("/welcome/discover").text
