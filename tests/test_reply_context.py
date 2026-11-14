"""Specific-response context remains public, current, and within one conversation."""

import uuid

import pytest
from sqlalchemy import delete, func, select

from app.models.community import CommunityPost, CommunityReply
from app.services.community import (
    CommunityError,
    add_reply,
    follow_discussion,
)
from tests.helpers import csrf_from, has_element
from tests.test_discussions import as_member, new_reply_count, paged_replies
from tests.test_discussions import community as community


def test_context_lookup_exposes_only_a_current_public_excerpt(client, db_session, community):
    users, _, post = community
    original = add_reply(
        db_session, users[0], post, '<script>alert("x")</script> ' + "details " * 80
    )
    result = client.get(f"/posts/{post.id}/reply-context/{original.id}")
    assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
    assert result.json() == {
        "id": str(original.id),
        "author": users[0].community_name,
        "excerpt": " ".join(original.body.split())[:180] + "…",
        "url": f"/posts/{post.id}/replies/{original.id}",
    }
    assert users[0].email not in result.text and users[0].phone not in result.text
    child = add_reply(
        db_session, users[1], post, "Which department should I contact?", in_reply_to_id=original.id
    )
    page = client.get(f"/posts/{post.id}")
    assert f'href="/posts/{post.id}/replies/{original.id}"' in page.text
    assert "In reply to Member 1" in page.text
    assert '<script>alert("x")</script>' not in page.text
    assert "&lt;script&gt;" in page.text
    assert child.body in page.text


def test_replying_across_pages_keeps_the_target_and_does_not_mark_it_read(
    client,
    db_session,
    community,
):
    users, _, post = community
    member = users[1]
    follow_discussion(db_session, member, post)
    replies = paged_replies(db_session, users, post, count=40)
    target = replies[0]
    as_member(client, member)
    form = client.get(f"/posts/{post.id}?page=2&reply_to={target.id}")
    assert has_element(form, "input", name="in_reply_to_id", value=str(target.id))
    assert 'data-reply-target-explicit="true"' in form.text
    assert f"?page=1&amp;reply_to={target.id}#replies" in form.text
    assert "Replying to Member 1" in form.text and target.body in form.text
    assert new_reply_count(db_session, post, member) == 20
    failed = client.post(
        f"/posts/{post.id}/replies",
        data={
            "csrf_token": csrf_from(form),
            "body": "x" * 2001,
            "page": "2",
            "in_reply_to_id": str(target.id),
        },
    )
    assert failed.status_code == 400
    assert has_element(failed, "input", name="in_reply_to_id", value=str(target.id))
    assert "x" * 2001 in failed.text and "Page 2 of 2" in failed.text
    result = client.post(
        f"/posts/{post.id}/replies",
        data={
            "csrf_token": csrf_from(form),
            "body": "Which department should I contact?",
            "page": "2",
            "in_reply_to_id": str(target.id),
        },
        follow_redirects=False,
    )
    assert result.status_code == 303 and "?page=3#reply-" in result.headers["location"]
    page = client.get(result.headers["location"])
    child = db_session.scalar(
        select(CommunityReply).where(
            CommunityReply.body == "Which department should I contact?",
        )
    )
    assert child.in_reply_to_id == target.id and target.body in page.text
    assert "In reply to Member 1" in page.text
    assert new_reply_count(db_session, post, member) == 20


@pytest.mark.parametrize("kind", ["malformed", "missing", "removed", "other_discussion"])
def test_unavailable_targets_reject_publication_without_losing_text(
    client,
    db_session,
    community,
    kind,
):
    users, topic, post = community
    target = add_reply(db_session, users[0], post, "Do not expose this unavailable target")
    target_id = str(target.id)
    if kind == "malformed":
        target_id = "not-a-reply-id"
    elif kind == "missing":
        target_id = str(uuid.uuid4())
    elif kind == "removed":
        target.status = "removed"
    else:
        other = CommunityPost(author_id=users[0].id, topic_id=topic.id, body="Other post")
        db_session.add(other)
        db_session.flush()
        target.post_id = other.id
    db_session.commit()
    as_member(client, users[1])
    token = csrf_from(client.get("/feed"))
    before = db_session.scalar(select(func.count()).select_from(CommunityReply))
    response = client.post(
        f"/posts/{post.id}/replies",
        data={
            "csrf_token": token,
            "body": "Keep my question",
            "in_reply_to_id": target_id,
        },
    )
    assert response.status_code == 400 and "Keep my question" in response.text
    assert has_element(response, "input", name="in_reply_to_id", value=str(target_id))
    assert db_session.scalar(select(func.count()).select_from(CommunityReply)) == before
    assert client.get(f"/posts/{post.id}/reply-context/{target_id}").status_code == 404
    if kind != "malformed":
        with pytest.raises(CommunityError):
            add_reply(
                db_session,
                users[1],
                post,
                "Direct service call",
                in_reply_to_id=uuid.UUID(target_id),
            )


def test_removed_source_disappears_from_existing_references_and_draft_context(
    client,
    db_session,
    community,
):
    users, _, post = community
    source = add_reply(db_session, users[0], post, "Sensitive source excerpt")
    child = add_reply(
        db_session, users[1], post, "This answer remains visible", in_reply_to_id=source.id
    )
    source.status = "removed"
    db_session.commit()
    as_member(client, users[1])
    page = client.get(f"/posts/{post.id}?reply_to={source.id}")
    assert source.body not in page.text and child.body in page.text
    assert "The original response is no longer available." in page.text
    assert "The selected response is no longer available." in page.text
    assert client.get(f"/posts/{post.id}/reply-context/{source.id}").status_code == 404
    db_session.execute(delete(CommunityReply).where(CommunityReply.id == source.id))
    db_session.commit()
    db_session.refresh(child)
    assert child.in_reply_to_id is None and child.body == "This answer remains visible"


def test_reply_selection_has_a_native_link_and_can_be_cleared_without_javascript(
    client,
    db_session,
    community,
):
    users, _, post = community
    source = add_reply(db_session, users[0], post, "The hospital is accepting interns")
    as_member(client, users[1])
    page = client.get(f"/posts/{post.id}")
    assert f"?page=1&amp;reply_to={source.id}#reply-form" in page.text
    selected = client.get(f"/posts/{post.id}?page=1&reply_to={source.id}")
    assert "Replying to Member 1" in selected.text
    assert "?page=1&amp;reply_to=#reply-form" in selected.text
    cleared = client.get(f"/posts/{post.id}?page=1&reply_to=")
    assert has_element(cleared, "input", name="in_reply_to_id", value="")
    response = client.post(
        f"/posts/{post.id}/replies",
        data={
            "csrf_token": csrf_from(cleared),
            "body": "A general response",
        },
    )
    assert response.status_code == 200
    assert (
        db_session.scalar(
            select(CommunityReply).where(
                CommunityReply.body == "A general response",
            )
        ).in_reply_to_id
        is None
    )


def test_reply_context_does_not_bypass_authentication_or_csrf(client, db_session, community):
    users, _, post = community
    source = add_reply(db_session, users[0], post, "Original")
    assert (
        client.post(
            f"/posts/{post.id}/replies",
            data={
                "body": "Unauthorized",
                "in_reply_to_id": str(source.id),
            },
            follow_redirects=False,
        ).status_code
        == 303
    )
    as_member(client, users[1])
    assert (
        client.post(
            f"/posts/{post.id}/replies",
            data={
                "body": "Missing CSRF",
                "in_reply_to_id": str(source.id),
            },
        ).status_code
        == 400
    )
    post.status = "removed"
    db_session.commit()
    assert client.get(f"/posts/{post.id}/reply-context/{source.id}").status_code == 404
