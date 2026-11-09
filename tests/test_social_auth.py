"""OIDC trust boundaries, explicit linking, replay protection and account completion."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.models.social_auth import SocialAuthAttempt, SocialEnrollment, SocialIdentity
from app.models.user import User
from app.services import social_auth as service
from app.services.auth import register_user
from tests.helpers import csrf_from
from tests.test_community import sign_in


@pytest.fixture
def providers(monkeypatch):
    for provider in service.PROVIDERS:
        monkeypatch.setattr(settings, provider + "_client_id", "test-client")
        monkeypatch.setattr(settings, provider + "_client_secret", "private-test-secret")
    monkeypatch.setattr(
        service,
        "verified_claims",
        lambda *args: {
            "subject": "stable-subject",
            "email": "provider@example.org",
            "full_name": "Test Member",
        },
    )


def start(client, provider="google"):
    token = csrf_from(client.get("/auth/login"))
    result = client.post(
        f"/auth/social/{provider}/start", data={"csrf_token": token}, follow_redirects=False
    )
    assert result.status_code == 303
    parts = parse_qs(urlsplit(result.headers["location"]).query)
    assert parts["scope"] == ["openid profile email"]
    assert parts["code_challenge_method"] == ["S256"]
    assert "client_secret" not in parts
    return parts["state"][0]


def finish_callback(client, state, provider="google"):
    return client.get(
        f"/auth/social/{provider}/callback",
        params={"state": state, "code": "code"},
        follow_redirects=False,
    )


@pytest.mark.parametrize("provider", ["google", "linkedin"])
@pytest.mark.parametrize("flow", ["enroll", "sign_in", "link", "denied"])
def test_callback_with_production_session_lifecycle(
    client, engine, db_session, providers, provider, flow
):
    # Production uses a fresh session per request and expires objects on commit.
    def request_db():
        with Session(engine, autoflush=False) as db:
            yield db

    app.dependency_overrides[get_db] = request_db
    if flow in {"sign_in", "link"}:
        member = register_user(db_session, phone="+2348000000136", password="s3cret-pass")
        if flow == "sign_in":
            db_session.add(
                SocialIdentity(provider=provider, subject="stable-subject", user_id=member.id)
            )
            db_session.commit()
        else:
            sign_in(client, member.phone)
    state = start(client, provider)
    if flow == "denied":
        result = client.get(
            f"/auth/social/{provider}/callback",
            params={"state": state, "error": "access_denied"},
            follow_redirects=False,
        )
    else:
        result = finish_callback(client, state, provider)
    assert result.status_code == 303
    assert result.headers["location"] == {
        "enroll": "/auth/social/complete",
        "sign_in": "/",
        "link": "/settings/social",
        "denied": "/auth/login",
    }[flow]
    assert db_session.scalar(select(func.count()).select_from(SocialAuthAttempt)) == 0
    if flow == "enroll":
        page = client.get(result.headers["location"])
        result = client.post(
            "/auth/social/complete",
            data={"csrf_token": csrf_from(page), "mode": "new", "phone": "+2348000000137",
                  "password": "s3cret-pass", "full_name": "New member"},
            follow_redirects=False,
        )
        assert result.headers["location"] == "/welcome"
        assert db_session.scalar(select(func.count()).select_from(SocialEnrollment)) == 0
    if flow != "denied":
        assert db_session.get(SocialIdentity, (provider, "stable-subject")) is not None
        assert "Connected sign-ins" in client.get("/settings").text
    else:
        assert "cancelled" in client.get("/auth/login").text
    # Consuming the callback still prevents a second use after the session closes.
    assert finish_callback(client, state, provider).headers["location"] == "/auth/login"


@pytest.mark.parametrize("provider", ["google", "linkedin"])
def test_new_account_and_subsequent_provider_login(client, db_session, providers, provider):
    state = start(client, provider)
    assert finish_callback(client, state, provider).headers["location"] == "/auth/social/complete"
    page = client.get("/auth/social/complete")
    result = client.post(
        "/auth/social/complete",
        data={
            "csrf_token": csrf_from(page),
            "mode": "new",
            "phone": "+2348000000131",
            "password": "s3cret-pass",
            "full_name": "New Social Member",
            "role": "nurse",
            "is_staff": "true",
        },
        follow_redirects=False,
    )
    assert result.status_code == 303
    assert result.headers["location"] == "/welcome"
    user = db_session.scalar(select(User))
    assert user.email == "provider@example.org" and user.email_verified_at
    assert not user.is_staff and not user.phone_verified
    assert user.check_password("s3cret-pass")
    assert db_session.get(SocialIdentity, (provider, "stable-subject")).user_id == user.id
    assert db_session.scalar(select(func.count()).select_from(SocialEnrollment)) == 0
    client.cookies.clear()
    state = start(client, provider)
    assert finish_callback(client, state, provider).headers["location"] == "/"
    assert "Connected sign-ins" in client.get("/settings").text
    user.is_active = False
    db_session.commit()
    client.cookies.clear()
    state = start(client, provider)
    assert finish_callback(client, state, provider).headers["location"] == "/auth/login"


def test_email_match_never_silently_links_existing_account(client, db_session, providers):
    user = register_user(
        db_session, phone="+2348000000132", password="s3cret-pass", email="provider@example.org"
    )
    user.email_verified_at = datetime.now(UTC)
    db_session.commit()
    state = start(client)
    assert finish_callback(client, state).headers["location"] == "/auth/social/complete"
    assert db_session.scalar(select(SocialIdentity)) is None
    page = client.get("/auth/social/complete")
    token = csrf_from(page)
    data = {"csrf_token": token, "mode": "existing", "phone": user.phone, "password": "incorrect"}
    response = client.post("/auth/social/complete", data=data, headers={"X-Account-Feedback": "1"})
    assert response.status_code == 400
    assert db_session.scalar(select(SocialIdentity)) is None
    assert db_session.scalar(select(SocialEnrollment)) is not None
    response = client.post(
        "/auth/social/complete", data={**data, "password": "s3cret-pass"}, follow_redirects=False
    )
    assert response.headers["location"] == "/"
    assert db_session.get(SocialIdentity, ("google", "stable-subject")).user_id == user.id


def test_state_is_bound_to_browser_provider_expiry_and_used_once(client, db_session, providers):
    state = start(client)
    cookies = dict(client.cookies)
    client.cookies.clear()
    assert finish_callback(client, state).headers["location"] == "/auth/login"
    assert db_session.scalar(select(SocialAuthAttempt)) is not None
    client.cookies.clear()
    client.cookies.update(cookies)
    assert finish_callback(client, state, "linkedin").headers["location"] == "/auth/login"
    assert finish_callback(client, state).headers["location"] == "/auth/social/complete"
    client.cookies.clear()
    client.cookies.update(cookies)
    assert finish_callback(client, state).headers["location"] == "/auth/login"
    assert db_session.scalar(select(func.count()).select_from(SocialEnrollment)) == 1
    state = start(client)
    attempt = db_session.scalar(select(SocialAuthAttempt))
    attempt.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    assert finish_callback(client, state).headers["location"] == "/auth/login"


def test_linked_identity_cannot_be_stolen_and_new_user_is_rolled_back(
    client, db_session, providers
):
    user = register_user(db_session, phone="+2348000000133", password="s3cret-pass")
    state = start(client)
    finish_callback(client, state)
    page = client.get("/auth/social/complete")
    db_session.add(SocialIdentity(provider="google", subject="stable-subject", user_id=user.id))
    db_session.commit()
    response = client.post(
        "/auth/social/complete",
        data={
            "csrf_token": csrf_from(page),
            "mode": "new",
            "phone": "+2348000000134",
            "password": "s3cret-pass",
            "full_name": "Other member",
        },
    )
    assert response.status_code == 400
    assert db_session.scalar(select(func.count()).select_from(User)) == 1
    assert db_session.get(SocialIdentity, ("google", "stable-subject")).user_id == user.id


def test_settings_link_disconnect_and_denied_callback(client, db_session, providers):
    user = register_user(db_session, phone="+2348000000135", password="s3cret-pass")
    sign_in(client, user.phone)
    token = csrf_from(client.get("/settings/social"))
    response = client.post(
        "/auth/social/google/start", data={"csrf_token": token}, follow_redirects=False
    )
    state = parse_qs(urlsplit(response.headers["location"]).query)["state"][0]
    assert finish_callback(client, state).headers["location"] == "/settings/social"
    assert db_session.get(SocialIdentity, ("google", "stable-subject"))
    response = client.post(
        "/settings/social/google/disconnect",
        data={
            "csrf_token": token,
            "password": "wrong",
        },
    )
    assert response.status_code == 400
    assert db_session.get(SocialIdentity, ("google", "stable-subject"))
    response = client.post(
        "/settings/social/google/disconnect",
        data={
            "csrf_token": token,
            "password": "s3cret-pass",
        },
    )
    assert response.status_code == 200
    assert db_session.get(SocialIdentity, ("google", "stable-subject")) is None
    client.cookies.clear()
    state = start(client)
    result = client.get(
        "/auth/social/google/callback", params={"state": state, "error": "access_denied"}
    )
    assert "cancelled" in result.text
    assert db_session.scalar(select(SocialAuthAttempt)) is None


def test_unconfigured_provider_and_csrf_have_useful_feedback(client, monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "")
    page = client.get("/auth/register")
    assert 'action="/auth/social/google/start"' in page.text
    assert "Soon" not in page.text
    assert client.post("/auth/social/google/start").status_code == 400
    response = client.post("/auth/social/google/start", data={"csrf_token": csrf_from(page)})
    assert "not connected yet" in response.text
    assert 'action="/auth/login"' in response.text


@pytest.mark.parametrize(
    "mutation",
    [None, "signature", "nonce", "issuer", "audience", "expired", "unverified", "azp", "algorithm"],
)
def test_signed_id_token_validation(monkeypatch, mutation):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(settings, "google_client_id", "test-client")
    monkeypatch.setattr(settings, "google_client_secret", "test-secret")
    monkeypatch.setattr(
        service.jwt,
        "PyJWKClient",
        lambda *a, **kw: SimpleNamespace(
            get_signing_key_from_jwt=lambda token: SimpleNamespace(key=key.public_key()),
        ),
    )
    now = datetime.now(UTC)
    claims = {
        "sub": "subject",
        "email": "person@example.org",
        "email_verified": True,
        "nonce": "expected",
        "iss": "https://accounts.google.com",
        "aud": "test-client",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    overrides = {
        "nonce": {"nonce": "wrong"},
        "issuer": {"iss": "https://evil.example"},
        "audience": {"aud": "another-client"},
        "expired": {"exp": now - timedelta(minutes=5)},
        "unverified": {"email_verified": False},
        "azp": {"azp": "other-client"},
    }
    claims.update(overrides.get(mutation, {}))
    signer = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        if mutation == "signature"
        else key
    )
    token = jwt.encode(
        claims,
        "shared-secret-with-at-least-32-characters" if mutation == "algorithm" else signer,
        algorithm="HS256" if mutation == "algorithm" else "RS256",
    )
    monkeypatch.setattr(service, "exchange_token", lambda *args: {"id_token": token})
    if mutation:
        with pytest.raises(service.SocialAuthError):
            service.verified_claims("google", "code", "expected", "verifier")
    else:
        assert (
            service.verified_claims("google", "code", "expected", "verifier")["subject"]
            == "subject"
        )
