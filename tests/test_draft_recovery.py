"""Server confirmation and session boundaries for browser-local community drafts."""

import json
import re
import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import create_app
from tests.helpers import csrf_from
from tests.test_discussions import as_member
from tests.test_discussions import community as community


def scope(response):
    return re.search(r'data-draft-scope="([^"]*)"', response.text).group(1)


def confirmation(response):
    match = re.search(r'id="published-draft"\s*>(.*?)</script>', response.text, re.S)
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


@pytest.mark.parametrize("path, code", [
    ("/missing-destination", 404), ("/events/new", 403), ("/events?page=invalid", 422),
])
def test_error_page_preserves_pending_publication_confirmation(client, community, path, code):
    users, topic, _ = community
    as_member(client, users[1])
    form = client.get("/posts/new")
    version = str(uuid.uuid4())
    result = client.post("/posts", data={
        "csrf_token": csrf_from(form), "body": "Published before visiting an error page",
        "topic_id": str(topic.id), "draft_version": version,
    }, follow_redirects=False)
    assert result.status_code == 303
    error = client.get(path, headers={"Accept": "text/html"})
    assert error.status_code == code
    assert confirmation(error) is None
    # Error rendering does not establish whether the account session has ended.
    assert "js/community-drafts.js" not in error.text
    landed = client.get(result.headers["location"])
    assert scope(landed) == scope(form)
    assert confirmation(landed) == {"key": "post", "version": version}


def test_database_failure_renders_without_treating_the_member_as_signed_out(client, community):
    users, _, _ = community
    as_member(client, users[1])
    original_scope = scope(client.get("/posts/new"))
    failing_app = create_app()

    def unavailable_db():
        raise RuntimeError("Private database failure details")

    failing_app.dependency_overrides[get_db] = unavailable_db
    with TestClient(
        failing_app, base_url="http://localhost", raise_server_exceptions=False,
    ) as failing_client:
        failing_client.cookies.update(client.cookies)
        error = failing_client.get("/settings", headers={"Accept": "text/html"})
    assert error.status_code == 500
    assert "js/community-drafts.js" not in error.text
    assert "Private database failure" not in error.text
    assert "Check whether the action completed" in error.text
    assert scope(client.get("/posts/new")) == original_scope
