"""The member conversation journey: ask, reply, find, and return."""

import base64
import json
import re
from datetime import UTC, datetime, timedelta

import pytest
from itsdangerous import TimestampSigner
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.models.community import (
    CommunityPost,
    CommunityReply,
    CommunityTopic,
    Connection,
    DiscussionFollow,
    DiscussionReplyRead,
    Follow,
)
from app.models.profile import NurseProfile
from app.models.user import User
from app.services.community import (
    add_reply,
    discussion_reply_page,
    discussion_summaries,
    follow_discussion,
    get_published_post,
    mark_discussion_read,
)
from app.web.community_routes import _reply_limiter
from tests.helpers import csrf_from, has_element


@pytest.fixture
def community(db_session):
    users = [
        User(
            phone=f"+234800000000{index}",
            hashed_password="unused",
            community_name=f"Member {index}",
            community_name_key=f"member {index}",
            email=f"private{index}@example.com",
        )
        for index in range(1, 4)
    ]
    topic = CommunityTopic(
        name="General nursing", slug="general-nursing", description="Talk together"
    )
    db_session.add_all([*users, topic])
    db_session.flush()
    post = CommunityPost(
        author_id=users[0].id,
        topic_id=topic.id,
        body="Which hospitals in Makurdi are currently accepting interns?",
    )
    db_session.add(post)
    db_session.commit()
    return users, topic, post


def as_member(client, user):
    client.cookies.clear()
    payload = base64.b64encode(json.dumps({"user_id": str(user.id)}).encode())
    cookie = TimestampSigner(settings.secret_key).sign(payload).decode()
    client.cookies.set(settings.session_cookie_name, cookie, domain="localhost.local", path="/")


def listed_ids(response):
    assert response.status_code == 200
    return re.findall(r'href="/posts/([0-9a-f-]{36})"', response.text)


def follow(client, post):
    token = csrf_from(client.get(f"/posts/{post.id}"))
    return client.post(
        f"/posts/{post.id}/follow", data={"csrf_token": token}, follow_redirects=False
    )


def test_member_can_choose_identity_while_asking_without_publishing_profile(
    client,
    db_session,
    community,
):
    users, topic, _ = community
    member = users[1]
    member.community_name = ""
    member.community_name_key = None
    db_session.add(NurseProfile(user_id=member.id, display_name="Private nurse identity"))
    db_session.commit()
    as_member(client, member)
    form = client.get(f"/posts/new?topic={topic.id}")
    assert 'name="community_name"' in form.text
    assert has_element(form, 'option', value=str(topic.id), selected=True)
    question = "Has the recruitment exercise started in Abuja?"
    response = client.post(
        "/posts",
        data={
            "csrf_token": csrf_from(form),
            "topic_id": str(topic.id),
            "community_name": "Ada Asks",
            "body": question,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    page = client.get(response.headers["location"])
    assert question in page.text and "Ada Asks" in page.text
    assert "Private nurse identity" not in page.text and member.email not in page.text
    profile = db_session.scalar(select(NurseProfile))
    assert not profile.discoverable and profile.status == "draft"
    assert member.community_name_locked


def test_reply_composer_submits_and_keeps_validation_errors_visible(client, db_session, community):
    users, _, post = community
    as_member(client, users[1])
    page = client.get(f"/posts/{post.id}")
    assert f'action="/posts/{post.id}/replies"' in page.text
    assert 'id="reply-body"' in page.text
    bad = client.post(
        f"/posts/{post.id}/replies",
        data={
            "csrf_token": csrf_from(page),
            "body": "x" * 2001,
        },
    )
    assert bad.status_code == 400
    assert 'role="alert"' in bad.text and "x" * 2001 in bad.text
    response = client.post(
        f"/posts/{post.id}/replies",
        data={
            "csrf_token": csrf_from(bad),
            "body": "I contacted the hospital yesterday. <script>bad()</script>",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303 and "#reply-" in response.headers["location"]
    page = client.get(response.headers["location"])
    assert "I contacted the hospital yesterday." in page.text
    assert "&lt;script&gt;bad()&lt;/script&gt;" in page.text
    assert "<script>bad()</script>" not in page.text
    assert "1 reply" in page.text
    client.cookies.clear()
    page = client.get(f"/posts/{post.id}")
    assert 'id="reply-body"' not in page.text and "Have something to add?" in page.text


def test_first_reply_can_set_name_and_preserves_body_on_name_conflict(
    client, db_session, community
):
    users, _, post = community
    users[1].community_name = ""
    users[1].community_name_key = None
    db_session.commit()
    as_member(client, users[1])
    page = client.get(f"/posts/{post.id}")
    body = "I have a question about the application."
    response = client.post(
        f"/posts/{post.id}/replies",
        data={
            "csrf_token": csrf_from(page),
            "body": body,
            "community_name": users[0].community_name,
        },
    )
    assert response.status_code == 400 and "already in use" in response.text
    assert body in response.text
    response = client.post(
        f"/posts/{post.id}/replies",
        data={
            "csrf_token": csrf_from(response),
            "body": body,
            "community_name": "Bola Replies",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert users[1].community_name == "Bola Replies"


def test_throttled_reply_preserves_the_member_message(client, community):
    users, _, post = community
    as_member(client, users[1])
    token = csrf_from(client.get(f"/posts/{post.id}"))
    for _ in range(_reply_limiter.limit):
        _reply_limiter.record(str(users[1].id))
    response = client.post(
        f"/posts/{post.id}/replies",
        data={
            "csrf_token": token,
            "body": "Please keep this reply while I wait.",
        },
    )
    assert response.status_code == 429 and int(response.headers["retry-after"]) > 0
    assert "Please keep this reply while I wait." in response.text
    assert 'id="reply-body"' in response.text


def test_search_matches_published_replies_and_escapes_wildcards(client, db_session, community):
    users, topic, post = community
    add_reply(db_session, users[1], post, "The information came from Riverview Hospital.")
    db_session.add(
        CommunityReply(
            author_id=users[1].id,
            post_id=post.id,
            body="HiddenKeyword",
            status="removed",
        )
    )
    hidden = CommunityPost(
        author_id=users[0].id, topic_id=topic.id, body="RemovedKeyword", status="removed"
    )
    db_session.add(hidden)
    db_session.commit()
    for query in ("MAKURDI", "Riverview", "Makurdi Riverview", "General nursing"):
        assert listed_ids(client.get("/feed", params={"q": query})) == [str(post.id)]
    for query in ("HiddenKeyword", "RemovedKeyword", "%", "_", users[0].email):
        assert listed_ids(client.get("/feed", params={"q": query})) == []
    assert client.get("/feed", params={"q": "x" * 121}).status_code == 422
    assert client.get("/feed?page=0").status_code == 422


def test_pagination_retains_search_and_topic_filters(client, db_session, community):
    users, topic, _ = community
    for index in range(23):
        db_session.add(
            CommunityPost(
                author_id=users[0].id, topic_id=topic.id, body=f"Placements question {index:02}"
            )
        )
    other = CommunityTopic(name="Other", slug="other", description="Other conversations")
    db_session.add(other)
    db_session.flush()
    db_session.add(
        CommunityPost(author_id=users[0].id, topic_id=other.id, body="Placements elsewhere")
    )
    db_session.commit()
    path = f"/topics/{topic.slug}"
    first = client.get(path, params={"q": "Placements"})
    second = client.get(path, params={"q": "Placements", "page": 2})
    assert len(listed_ids(first)) == 20 and len(listed_ids(second)) == 3
    assert set(listed_ids(first)).isdisjoint(listed_ids(second))
    assert "q=Placements&amp;page=2" in first.text
    assert "q=Placements&amp;page=1" in second.text
    assert "Placements elsewhere" not in first.text + second.text


def test_following_is_private_and_independent_of_people_or_connections(
    client, db_session, community
):
    users, _, post = community
    assert client.get("/feed/discussions", follow_redirects=False).status_code == 303
    assert client.post(f"/posts/{post.id}/follow", follow_redirects=False).status_code == 303
    as_member(client, users[1])
    assert client.post(f"/posts/{post.id}/follow").status_code == 400
    assert follow(client, post).status_code == 303
    assert follow(client, post).status_code == 303
    assert len(db_session.scalars(select(DiscussionFollow)).all()) == 1
    assert db_session.scalar(select(Follow)) is None
    assert db_session.scalar(select(Connection)) is None
    assert listed_ids(client.get("/feed/discussions")) == [str(post.id)]
    as_member(client, users[2])
    assert listed_ids(client.get("/feed/discussions")) == []
    token = csrf_from(client.get(f"/posts/{post.id}"))
    assert client.post(f"/posts/{post.id}/unfollow", data={"csrf_token": token}).status_code == 200
    assert len(db_session.scalars(select(DiscussionFollow)).all()) == 1


def test_followed_discussion_shows_new_replies_until_read(client, db_session, community):
    users, _, post = community
    as_member(client, users[1])
    follow(client, post)
    add_reply(db_session, users[0], post, "Here is an update about placement availability.")
    listing = client.get("/feed/discussions")
    assert "1 new reply" in listing.text
    assert listing.headers["cache-control"] == "no-store"
    assert "1 new reply" in client.get("/feed/discussions").text
    page = client.get(f"/posts/{post.id}")
    assert "Here is an update" in page.text
    assert "1 new reply" not in client.get("/feed/discussions").text
    add_reply(db_session, users[1], post, "My own reply is not an unread notification.")
    assert "new reply" not in client.get("/feed/discussions").text
    hidden = add_reply(db_session, users[0], post, "Removed update")
    hidden.status = "removed"
    db_session.commit()
    assert "new reply" not in client.get("/feed/discussions").text
    token = csrf_from(page)
    client.post(f"/posts/{post.id}/unfollow", data={"csrf_token": token})
    assert listed_ids(client.get("/feed/discussions")) == []


def test_removed_conversations_disappear_from_following_and_reject_new_follows(
    client,
    db_session,
    community,
):
    users, _, post = community
    as_member(client, users[1])
    follow(client, post)
    token = csrf_from(client.get(f"/posts/{post.id}"))
    post.status = "removed"
    db_session.commit()
    assert listed_ids(client.get("/feed/discussions")) == []
    assert client.get(f"/posts/{post.id}").status_code == 404
    assert client.post(f"/posts/{post.id}/follow", data={"csrf_token": token}).status_code == 404


def test_only_rendered_replies_are_recorded_read(db_session, community):
    users, _, post = community
    follow_discussion(db_session, users[1], post)
    first = add_reply(db_session, users[0], post, "The reply that is on the page")
    rendered = discussion_reply_page(db_session, post, users[1])
    assert len(rendered.replies) == 1
    second = add_reply(db_session, users[0], post, "A reply arriving after the page was loaded")
    mark_discussion_read(db_session, users[1], post, rendered.replies)
    assert discussion_summaries(db_session, [post], users[1])[post.id]["new_replies"] == 1
    subscription = db_session.scalar(select(DiscussionFollow))
    future = datetime.now(UTC) + timedelta(minutes=1)
    subscription.last_read_at = future
    db_session.commit()
    mark_discussion_read(db_session, users[1], post, rendered.replies)
    db_session.refresh(subscription)
    assert subscription.last_read_at.replace(tzinfo=UTC) == future
    assert first.id != second.id


def test_database_enforces_one_follow_per_member_and_discussion(db_session, community):
    users, _, post = community
    follow_discussion(db_session, users[1], post)
    db_session.add(
        DiscussionFollow(user_id=users[1].id, post_id=post.id, last_read_at=datetime.now(UTC))
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def paged_replies(db, users, post, count=45):
    # Tied timestamps exercise the ID ordering and distinguish reads at page boundaries.
    created = datetime.now(UTC)
    replies = [CommunityReply(
        post_id=post.id, author_id=users[0].id, body=f"Placement update {index:03}",
        created_at=created,
    ) for index in range(count)]
    db.add_all(replies)
    db.commit()
    return sorted(replies, key=lambda reply: reply.id)


def reply_ids(response):
    assert response.status_code == 200
    return re.findall(r'<article class="reply-card" id="reply-([0-9a-f-]{36})"', response.text)


def new_reply_count(db, post, member):
    return discussion_summaries(db, [post], member)[post.id]["new_replies"]


def test_pages_read_out_of_order_leave_skipped_replies_new(client, db_session, community):
    users, _, post = community
    member = users[1]
    follow_discussion(db_session, member, post)
    replies = paged_replies(db_session, users, post)
    as_member(client, member)
    last = client.get(f"/posts/{post.id}?page=3")
    assert reply_ids(last) == [str(reply.id) for reply in replies[40:]]
    assert 'name="page" value="3"' in last.text
    assert "Page 3 of 3" in last.text and "New reply" in last.text
    assert new_reply_count(db_session, post, member) == 40
    first_unread = client.get(f"/posts/{post.id}/unread", follow_redirects=False)
    assert first_unread.headers["location"] == f"/posts/{post.id}?page=1#reply-{replies[0].id}"
    assert first_unread.headers["cache-control"] == "no-store"
    assert new_reply_count(db_session, post, member) == 40  # Redirects do not consume replies.
    first = client.get(first_unread.headers["location"])
    assert reply_ids(first) == [str(reply.id) for reply in replies[:20]]
    assert f'href="#reply-{replies[0].id}"' in first.text
    assert new_reply_count(db_session, post, member) == 20
    again = client.get(f"/posts/{post.id}?page=3")
    assert "New reply" not in again.text
    assert new_reply_count(db_session, post, member) == 20
    middle_link = client.get(f"/posts/{post.id}/unread", follow_redirects=False)
    assert middle_link.headers["location"] == f"/posts/{post.id}?page=2#reply-{replies[20].id}"
    middle = client.get(middle_link.headers["location"])
    assert reply_ids(middle) == [str(reply.id) for reply in replies[20:40]]
    assert new_reply_count(db_session, post, member) == 0
    assert client.get(f"/posts/{post.id}/unread", follow_redirects=False).headers[
        "location"
    ] == f"/posts/{post.id}#replies"


def test_reply_pages_are_bounded_in_database_and_hide_removed_content(
    client, db_session, community,
):
    users, _, post = community
    replies = paged_replies(db_session, users, post, count=65)
    replies[10].status = "removed"
    replies[10].body = "Removed reply must not load"
    db_session.commit()
    db_session.expire_all()
    queries = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", capture)
    try:
        response = client.get(f"/posts/{post.id}?page=2")
    finally:
        event.remove(db_session.bind, "before_cursor_execute", capture)
    visible = [reply for reply in replies if reply.status == "published"]
    assert reply_ids(response) == [str(reply.id) for reply in visible[20:40]]
    assert "Removed reply must not load" not in response.text
    assert "64 replies" in response.text and "Page 2 of 4" in response.text
    # Counts may scan reply IDs, but every query loading reply bodies must be bounded.
    body_queries = [query for query in queries if "community_replies.body" in query]
    assert body_queries and all("LIMIT" in query for query in body_queries)
    loaded = get_published_post(db_session, post.id)
    assert "replies" not in loaded.__dict__


def test_reply_links_resolve_current_page_and_reject_wrong_or_removed_targets(
    client, db_session, community,
):
    users, topic, post = community
    replies = paged_replies(db_session, users, post, count=21)
    target = replies[-1]
    link = f"/posts/{post.id}/replies/{target.id}"
    assert client.get(link, follow_redirects=False).headers["location"] == (
        f"/posts/{post.id}?page=2#reply-{target.id}"
    )
    replies[0].status = "removed"
    db_session.commit()
    assert client.get(link, follow_redirects=False).headers["location"] == (
        f"/posts/{post.id}?page=1#reply-{target.id}"
    )
    other = CommunityPost(author_id=users[0].id, topic_id=topic.id, body="Other conversation")
    db_session.add(other)
    db_session.commit()
    assert client.get(f"/posts/{other.id}/replies/{target.id}").status_code == 404
    assert client.get(f"/posts/{post.id}/replies/{replies[0].id}").status_code == 404
    assert client.get(f"/posts/{post.id}/replies/not-an-id").status_code == 404
    post.status = "removed"
    db_session.commit()
    assert client.get(link).status_code == 404


def test_reply_submission_stays_on_its_page_and_opens_new_reply(
    client, db_session, community,
):
    users, _, post = community
    member = users[1]
    follow_discussion(db_session, member, post)
    replies = paged_replies(db_session, users, post, count=40)
    as_member(client, member)
    token = csrf_from(client.get("/feed/discussions"))
    bad = client.post(f"/posts/{post.id}/replies", data={
        "csrf_token": token, "body": "x" * 2001, "page": "2",
    })
    assert bad.status_code == 400 and "Page 2 of 2" in bad.text
    assert 'name="page" value="2"' in bad.text and "x" * 2001 in bad.text
    assert new_reply_count(db_session, post, member) == 40  # Error render does not mark read.
    response = client.post(f"/posts/{post.id}/replies", data={
        "csrf_token": token, "body": "New response at the end", "page": "2",
    }, follow_redirects=False)
    assert response.status_code == 303 and "?page=3#reply-" in response.headers["location"]
    result = client.get(response.headers["location"])
    assert "New response at the end" in result.text and len(reply_ids(result)) == 1
    assert new_reply_count(db_session, post, member) == 40
    for _ in range(settings.community_reply_limit):
        _reply_limiter.record(str(member.id))
    throttled = client.post(f"/posts/{post.id}/replies", data={
        "csrf_token": token, "body": "Keep this reply", "page": "2",
    })
    assert throttled.status_code == 429 and "Keep this reply" in throttled.text
    assert "Page 2 of 3" in throttled.text and str(replies[20].id) in throttled.text


def test_read_records_are_private_additive_and_deleted_on_unfollow(client, db_session, community):
    users, _, post = community
    first_member, other_member = users[1:]
    follow_discussion(db_session, first_member, post)
    follow_discussion(db_session, other_member, post)
    paged_replies(db_session, users, post, count=25)
    first_page = discussion_reply_page(db_session, post, first_member)
    second_page = discussion_reply_page(db_session, post, first_member, page=2)
    mark_discussion_read(db_session, first_member, post, second_page.replies)
    mark_discussion_read(db_session, first_member, post, first_page.replies)
    mark_discussion_read(db_session, first_member, post, first_page.replies)
    assert new_reply_count(db_session, post, first_member) == 0
    assert new_reply_count(db_session, post, other_member) == 25
    assert db_session.scalar(select(func.count()).select_from(DiscussionReplyRead)) == 25
    as_member(client, first_member)
    token = csrf_from(client.get("/feed/discussions"))
    client.post(f"/posts/{post.id}/unfollow", data={"csrf_token": token})
    assert db_session.scalar(select(func.count()).select_from(DiscussionReplyRead)) == 0
    follow_discussion(db_session, first_member, post)
    assert new_reply_count(db_session, post, first_member) == 0
    assert new_reply_count(db_session, post, other_member) == 25


@pytest.mark.parametrize("page", ["0", "-1", "invalid", "10001"])
def test_invalid_reply_pages_are_rejected(client, community, page):
    _, _, post = community
    assert client.get(f"/posts/{post.id}?page={page}").status_code == 422


def test_empty_and_stale_pages_and_nonfollowers(client, db_session, community):
    users, _, post = community
    assert reply_ids(client.get(f"/posts/{post.id}?page=5")) == []
    replies = paged_replies(db_session, users, post, count=21)
    replies[-1].status = "removed"
    db_session.commit()
    assert len(reply_ids(client.get(f"/posts/{post.id}?page=2"))) == 20
    assert client.get(f"/posts/{post.id}/unread", follow_redirects=False).status_code == 303
    as_member(client, users[1])
    assert "First unread reply" not in client.get(f"/posts/{post.id}").text
    assert db_session.scalar(select(func.count()).select_from(DiscussionReplyRead)) == 0
    assert client.get(f"/posts/{post.id}/unread", follow_redirects=False).headers[
        "location"
    ] == f"/posts/{post.id}#replies"


def test_failed_render_does_not_consume_unread_replies(client, db_session, community, monkeypatch):
    import app.web.community_routes as routes

    users, _, post = community
    follow_discussion(db_session, users[1], post)
    paged_replies(db_session, users, post, count=1)
    as_member(client, users[1])

    def fail_render(*args, **kwargs):
        raise RuntimeError("render failed")

    monkeypatch.setattr(routes, "render", fail_render)
    with pytest.raises(RuntimeError, match="render failed"):
        client.get(f"/posts/{post.id}")
    assert new_reply_count(db_session, post, users[1]) == 1
