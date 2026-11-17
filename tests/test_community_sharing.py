"""Public invitations and destination continuity across real authentication routes."""

from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.models.community import ContentStatus
from app.models.social_auth import SocialAuthAttempt, SocialEnrollment, SocialIdentity
from app.services import community_sharing as sharing
from app.services.auth import register_user
from app.services.community import create_post, set_community_name
from tests.helpers import csrf_from, has_element, register_payload
from tests.test_community import create_topic
from tests.test_social_auth import providers  # noqa: F401 - shared isolated provider fixture


@pytest.fixture(autouse=True)
def hosted_public_address(monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://nurse.example")


@pytest.fixture
def conversation(db_session):
    owner = register_user(db_session, phone="+2348999000101", password="s3cret-pass")
    set_community_name(db_session, owner, "Community host")
    topic = create_topic(db_session)
    post = create_post(
        db_session,
        owner,
        topic_id=topic.id,
        body="A useful public question",
        post_kind="question",
        title="Learning together",
    )
    return owner, topic, post


@pytest.mark.parametrize("kind", ["topic", "post", "reply"])
def test_public_invitation_redirects_and_contains_no_member_identity(
    client, db_session, conversation, kind
):
    owner, topic, post = conversation
    path = {
        "topic": f"/topics/{topic.slug}",
        "post": f"/posts/{post.id}",
        "reply": f"/posts/{post.id}#reply-form",
    }[kind]
    url = sharing.invitation_url(path)
    token = urlsplit(url).path.removeprefix("/join/")
    assert sharing._signer().loads(token) == {"path": path}
    assert owner.phone not in url and str(owner.id) not in url
    result = client.get(urlsplit(url).path, follow_redirects=False)
    assert result.status_code == 303 and result.headers["location"] == path
    assert result.headers["cache-control"] == "no-store"
    assert sharing.invitation_destination(db_session, token + "tampered") == ""
    assert client.get("/join/invalid", follow_redirects=False).status_code == 404


@pytest.mark.parametrize(
    "value",
    [
        "https://example.org",
        "//example.org",
        "/\\example.org",
        "/topics/general?next=/",
        "/topics/general#reply-form",
        "/topics/%67eneral",
        "/auth/login",
        "/",
        "",
        "/topics/general\n",
        "/posts/not-a-uuid",
        f"/posts/{uuid4()}",
        None,
        {"path": "/"},
    ],
)
def test_auth_destination_rejects_external_malformed_and_missing_targets(db_session, value):
    assert sharing.community_destination(db_session, value) == ""


def test_removed_targets_and_unexpected_signed_payloads_fail_closed(
    client, db_session, conversation
):
    _, topic, post = conversation
    post_token = sharing._signer().dumps({"path": f"/posts/{post.id}"})
    post.status = ContentStatus.REMOVED
    db_session.commit()
    assert sharing.invitation_destination(db_session, post_token) == ""
    post.status = ContentStatus.PUBLISHED
    topic.is_active = False
    db_session.commit()
    for value in [
        {"path": f"/posts/{post.id}"},
        {"path": f"/topics/{topic.slug}"},
        [],
        {"path": []},
        {"path": "//example.org"},
    ]:
        token = sharing._signer().dumps(value)
        assert client.get(f"/join/{token}", follow_redirects=False).status_code == 404


@pytest.mark.parametrize("flow", ["login", "register"])
def test_password_auth_preserves_destination_on_errors_and_success(
    client, db_session, conversation, flow
):
    owner, _, post = conversation
    path = f"/posts/{post.id}#reply-form"
    page = client.get(f"/auth/{flow}", params={"next": path})
    assert has_element(page, "input", name="next", value=path)
    other = "register" if flow == "login" else "login"
    assert has_element(page, "a", href=sharing.auth_context(db_session, path)[f"{other}_url"])
    data = {"csrf_token": csrf_from(page), "next": path}
    if flow == "login":
        data.update(phone=owner.phone, password="incorrect")
    else:
        data.update(register_payload(phone="+2348999000102"), confirm_password="incorrect")
    failure = client.post(f"/auth/{flow}", data=data, follow_redirects=False)
    assert failure.status_code in (400, 401)
    assert has_element(failure, "input", name="next", value=path)
    data.update(password="s3cret-pass", confirm_password="s3cret-pass")
    result = client.post(f"/auth/{flow}", data=data, follow_redirects=False)
    assert result.status_code == 303 and result.headers["location"] == path
    page = client.get(f"/posts/{post.id}")
    assert has_element(page, "form", action=f"/posts/{post.id}/replies")
    assert (
        client.get("/auth/login", params={"next": path}, follow_redirects=False).headers["location"]
        == path
    )


def test_removed_target_between_login_page_and_submit_uses_safe_default(
    client, db_session, conversation
):
    owner, _, post = conversation
    page = client.get("/auth/login", params={"next": f"/posts/{post.id}"})
    post.status = ContentStatus.REMOVED
    db_session.commit()
    result = client.post(
        "/auth/login",
        data={
            "csrf_token": csrf_from(page),
            "phone": owner.phone,
            "password": "s3cret-pass",
            "next": f"/posts/{post.id}",
        },
        follow_redirects=False,
    )
    assert result.headers["location"] == "/"


@pytest.mark.parametrize("provider", ["google", "linkedin"])
@pytest.mark.parametrize("flow", ["linked", "new", "existing", "denied"])
@pytest.mark.usefixtures("providers")
def test_social_auth_continuation_with_fresh_request_sessions(
    client, engine, db_session, conversation, provider, flow
):
    owner, _, post = conversation
    path = f"/posts/{post.id}#reply-form"
    if flow == "linked":
        db_session.add(
            SocialIdentity(provider=provider, subject="stable-subject", user_id=owner.id)
        )
        db_session.commit()

    def request_db():
        with Session(engine, autoflush=False) as db:
            yield db

    app.dependency_overrides[get_db] = request_db
    page = client.get("/auth/login", params={"next": path})
    start = client.post(
        f"/auth/social/{provider}/start",
        data={"csrf_token": csrf_from(page), "next": path},
        follow_redirects=False,
    )
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    assert db_session.scalar(select(SocialAuthAttempt)).return_to == path
    result = client.get(
        f"/auth/social/{provider}/callback",
        params={
            "state": state,
            **({"error": "access_denied"} if flow == "denied" else {"code": "isolated-code"}),
        },
        follow_redirects=False,
    )
    if flow == "denied":
        assert result.headers["location"] == sharing.auth_context(db_session, path)["login_url"]
        assert has_element(client.get(result.headers["location"]), "input", name="next", value=path)
    elif flow == "linked":
        assert result.headers["location"] == path
    else:
        assert result.headers["location"] == "/auth/social/complete"
        enrollment = db_session.scalar(select(SocialEnrollment))
        assert enrollment.return_to == path
        page = client.get("/auth/social/complete")
        result = client.post(
            "/auth/social/complete",
            data={
                "csrf_token": csrf_from(page),
                "mode": flow,
                "phone": "+2348999000103" if flow == "new" else owner.phone,
                "password": "s3cret-pass",
                "full_name": "A new colleague",
            },
            follow_redirects=False,
        )
        assert result.status_code == 303 and result.headers["location"] == path
    assert db_session.scalar(select(SocialAuthAttempt)) is None


def test_share_metadata_uses_public_content_without_account_details(
    client, db_session, conversation
):
    owner, topic, post = conversation
    owner.email = "private@example.org"
    owner.full_name = "Private account name"
    db_session.commit()
    for path, title in [(f"/topics/{topic.slug}", topic.name), (f"/posts/{post.id}", post.title)]:
        page = client.get(path)
        assert has_element(page, "meta", property="og:title", content=title + " — Nurse.ng")
        assert owner.phone not in page.text and owner.email not in page.text
        assert owner.full_name not in page.text
