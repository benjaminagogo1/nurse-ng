"""Server confirmation and session boundaries for browser-local community drafts."""

import json
import re
import uuid

import pytest

from tests.helpers import csrf_from
from tests.test_discussions import as_member
from tests.test_discussions import community as community


def scope(response):
    return re.search(r'data-draft-scope="([^"]*)"', response.text).group(1)


def confirmation(response):
    match = re.search(r'id="published-draft">(.*?)</script>', response.text)
    return json.loads(match.group(1)) if match else None


def test_draft_scope_follows_sign_in_and_never_exposes_account_details(client, community):
    users, _, _ = community
    assert scope(client.get("/feed")) == ""
    as_member(client, users[0])
    form = client.get("/posts/new")
    first = scope(form)
    assert re.fullmatch(r"[a-f0-9]{64}", first)
    assert str(users[0].id) not in first and users[0].phone not in first
    assert scope(client.get("/feed")) == first
    assert form.headers["cache-control"] == "no-store"
    assert 'data-community-draft="post"' in form.text
    assert 'name="draft_version"' in form.text
    token = csrf_from(form)
    signed_out = client.post("/auth/logout", data={"csrf_token": token})
    assert scope(signed_out) == ""
    as_member(client, users[0])
    assert scope(client.get("/posts/new")) != first  # A new session for the same member.
    as_member(client, users[1])
    assert scope(client.get("/posts/new")) != first


@pytest.mark.parametrize("kind", ["post", "reply"])
def test_only_successful_publication_acknowledges_the_exact_draft(client, community, kind):
    users, topic, post = community
    as_member(client, users[1])
    page = client.get("/posts/new" if kind == "post" else f"/posts/{post.id}")
    version = str(uuid.uuid4())
    path = "/posts" if kind == "post" else f"/posts/{post.id}/replies"
    data = {
        "csrf_token": csrf_from(page), "body": "Draft content stays out of session metadata",
        "topic_id": str(topic.id), "draft_version": version, "draft_key": "another-composer",
    }
    failed = client.post(path, data={**data, "body": "x" * 10001})
    assert failed.status_code == 400
    assert confirmation(failed) is None
    assert 'data-draft-error="true"' in failed.text
    published = client.post(path, data=data, follow_redirects=False)
    assert published.status_code == 303
    landed = client.get(published.headers["location"])
    assert confirmation(landed) == {
        "key": "post" if kind == "post" else f"reply:{post.id}", "version": version,
    }
    assert confirmation(client.get("/feed")) is None


def test_invalid_draft_version_does_not_prevent_publication_or_emit_clear_instruction(
    client, community,
):
    users, topic, _ = community
    as_member(client, users[1])
    page = client.get("/posts/new")
    response = client.post("/posts", data={
        "csrf_token": csrf_from(page), "body": "A normal post without draft support",
        "topic_id": str(topic.id), "draft_version": '</script><script>alert(1)</script>',
    })
    assert response.status_code == 200
    assert confirmation(response) is None
    assert 'alert(1)' not in response.text


def test_csrf_failure_does_not_acknowledge_or_publish_a_draft(client, community):
    users, topic, _ = community
    as_member(client, users[1])
    response = client.post("/posts", data={
        "body": "Must not publish", "topic_id": str(topic.id), "draft_version": str(uuid.uuid4()),
    })
    assert response.status_code == 400
    assert confirmation(client.get("/feed")) is None
    assert "Must not publish" not in client.get("/feed").text
