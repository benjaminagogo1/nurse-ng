"""Real hosting boundaries: canonical links, proxy navigation and safe startup."""

import json
import os
import secrets
import subprocess
import sys
from http.cookies import SimpleCookie
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine

import app.main as main_module
from app.core.config import Settings, settings
from app.core.public_urls import normalize_origin, public_site_ready, public_url
from app.db.session import get_db
from app.models.user import User
from app.services import account_mail, community_sharing, notification_worker, social_auth
from app.services.community import create_post, set_community_name
from app.web.urls import page_url
from deploy.start import command_for
from tests.helpers import csrf_from, has_element, register_payload
from tests.test_community import create_topic

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "https://members.nurse.example"


def production(**overrides):
    return Settings(
        _env_file=None,
        **{
            "environment": "production",
            "debug": False,
            "session_https_only": True,
            "secret_key": secrets.token_urlsafe(32),
            "allowed_hosts": "members.nurse.example,internal-service",
            "public_base_url": ORIGIN,
            "database_url": "postgresql://test:private-password@database/nurse",
            "required_workers": "recruitment,reels,notifications",
            **overrides,
        },
    )


@pytest.mark.parametrize(
    "origin",
    [
        "",
        "http://members.nurse.example",
        "https://localhost",
        "https://localhost.",
        "https://site.localhost",
        "https://site.local",
        "https://site.localdomain",
        "https://site.internal",
        "https://site.lan",
        "https://site.home.arpa",
        "https://127.0.0.1",
        "https://127.1",
        "https://2130706433",
        "https://0x7f000001",
        "https://10.0.0.1",
        "https://192.168.1.2",
        "https://172.16.0.1",
        "https://169.254.0.1",
        "https://0.0.0.0",
        "https://[::1]",
        "https://[fc00::1]",
        "https://[::ffff:127.0.0.1]",
        "https://224.0.0.1",
        "https://[ff02::1]",
        "https://user:secret@members.nurse.example",
        "https://members.nurse.example/path",
        "https://members.nurse.example?next=/",
        "https://members.nurse.example#fragment",
        "https://members.nurse.example:0",
        "https://members.nurse.example:99999",
        " https://members.nurse.example",
        "https://members.nurse.example\\evil",
    ],
)
def test_production_cannot_generate_local_or_invalid_public_links(monkeypatch, origin):
    for name in tuple(os.environ):
        if name.startswith("NURSE_NG_"):
            monkeypatch.delenv(name)
    with pytest.raises(ValidationError, match="NURSE_NG_PUBLIC_BASE_URL"):
        production(public_base_url=origin)


def test_production_origin_must_match_allowed_host(monkeypatch):
    monkeypatch.delenv("NURSE_NG_ALLOWED_HOSTS", raising=False)
    with pytest.raises(ValidationError, match="public site hostname"):
        production(allowed_hosts="different.example")


def test_production_requires_explicit_persistent_database(monkeypatch):
    for name in tuple(os.environ):
        if name.startswith("NURSE_NG_"):
            monkeypatch.delenv(name)
    with pytest.raises(ValidationError, match="NURSE_NG_DATABASE_URL"):
        Settings(
            _env_file=None,
            environment="production",
            secret_key=secrets.token_urlsafe(32),
            allowed_hosts="members.nurse.example",
            public_base_url=ORIGIN,
        )
    for url in ("sqlite://", "sqlite:///:memory:"):
        with pytest.raises(ValidationError, match="persistent SQLite"):
            production(database_url=url)


@pytest.mark.parametrize(
    "path", ["//attacker.example", "https://attacker.example", "/../x", "/\\x", "/x\n"]
)
def test_public_application_links_cannot_change_the_origin(path):
    with pytest.raises(ValueError):
        public_url(path)


def test_origin_is_normalized_without_an_external_request():
    assert normalize_origin("HTTPS://Members.Nurse.Example:443/", public=True) == ORIGIN
    assert normalize_origin("https://[2606:4700:4700::1111]/", public=True).startswith("https://[")


@pytest.mark.parametrize(
    "origin", ["http://127.0.0.1:8000", "https://localhost", "http://site.example"]
)
def test_local_setup_never_offers_broken_invitations_or_sends_smtp_links(
    client, db_session, monkeypatch, origin
):
    monkeypatch.setattr(settings, "public_base_url", origin)
    monkeypatch.setattr(settings, "account_mail_backend", "smtp")
    topic = create_topic(db_session)
    assert not public_site_ready()
    assert community_sharing.invitation_url(f"/topics/{topic.slug}") == ""
    page = client.get(f"/topics/{topic.slug}")
    assert not has_element(page, "button", **{"data-copy-share": True})
    assert "Invitations will be available" in page.text
    assert not has_element(page, "meta", property="og:url")
    with pytest.raises(account_mail.MailUnavailable):
        account_mail.send_account_mail("fixture@example.org", "reset", "x" * 43)


def test_postgresql_provider_urls_use_installed_driver_without_connecting(monkeypatch):
    for name in tuple(os.environ):
        if name.startswith("NURSE_NG_"):
            monkeypatch.delenv(name)
    for prefix in ("postgres://", "postgresql://", "postgresql+psycopg://"):
        config = production(database_url=prefix + "test:private-password@database/nurse")
        assert config.database_url.startswith("postgresql+psycopg://")
        assert "private-password" not in repr(config)
        engine = create_engine(config.database_url)
        assert engine.dialect.driver == "psycopg"
        engine.dispose()


@pytest.mark.parametrize("proxies", ["*", "0.0.0.0/0", "::/0", "proxy.invalid", "10.0.0.1,*"])
def test_unbounded_or_invalid_proxy_trust_is_rejected(monkeypatch, proxies):
    monkeypatch.delenv("NURSE_NG_TRUSTED_PROXY_IPS", raising=False)
    with pytest.raises(ValidationError, match="NURSE_NG_TRUSTED_PROXY_IPS"):
        production(trusted_proxy_ips=proxies)


def test_hosted_start_binds_provider_port_and_limits_proxy_trust():
    config = SimpleNamespace(
        environment="production", required_workers="reels", trusted_proxy_ips=""
    )
    command = command_for(config, "web", "54321")
    assert command[command.index("--host") + 1] == "0.0.0.0"
    assert command[command.index("--port") + 1] == "54321"
    assert "--no-proxy-headers" in command
    config.trusted_proxy_ips = "127.0.0.1,10.20.0.0/24"
    command = command_for(config, "web", "8000")
    assert command[command.index("--forwarded-allow-ips") + 1] == config.trusted_proxy_ips
    assert command_for(config, "workers", "unused")[-2:] == ["app.cli", "workers"]
    for port in ("bad", "0", "65536"):
        with pytest.raises(ValueError, match="PORT"):
            command_for(config, "web", port)
    config.environment = "development"
    with pytest.raises(ValueError, match="production"):
        command_for(config, "web", "8000")


@pytest.fixture
def hosted_client(monkeypatch, db_session):
    for name in tuple(os.environ):
        if name.startswith("NURSE_NG_"):
            monkeypatch.delenv(name)
    config = production(
        account_mail_backend="smtp", smtp_host="smtp.example.org", smtp_from="noreply@nurse.example"
    )
    for name, value in config.model_dump().items():
        monkeypatch.setattr(settings, name, value)
    app = main_module.create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app, base_url=ORIGIN) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def test_hosted_invitation_signup_stays_on_public_site(hosted_client, db_session):
    owner = User(phone="+2348999111001", hashed_password="unused", community_name="Host")
    db_session.add(owner)
    db_session.commit()
    set_community_name(db_session, owner, "Hosting test host")
    topic = create_topic(db_session)
    for number in range(21):
        create_post(db_session, owner, topic_id=topic.id, body=f"A hosted conversation {number}")
    page = hosted_client.get(f"/topics/{topic.slug}")
    invitation = community_sharing.invitation_url(f"/topics/{topic.slug}")
    assert invitation.startswith(ORIGIN + "/join/")
    assert has_element(page, "div", **{"data-share-url": invitation})
    assert has_element(page, "meta", property="og:url", content=ORIGIN + f"/topics/{topic.slug}")
    assert has_element(page, "a", href=f"/topics/{topic.slug}?page=2")
    destination = hosted_client.get(invitation, follow_redirects=False).headers["location"]
    assert destination == f"/topics/{topic.slug}"
    registration = hosted_client.get("/auth/register", params={"next": destination})
    result = hosted_client.post(
        "/auth/register",
        data={
            "csrf_token": csrf_from(registration),
            "next": destination,
            **register_payload(phone="+2348999111002"),
        },
        follow_redirects=False,
    )
    assert result.status_code == 303 and result.headers["location"] == destination
    cookie = SimpleCookie(result.headers["set-cookie"])
    assert cookie[settings.session_cookie_name]["secure"]
    assert has_element(
        hosted_client.get(destination), "form", action=f"/communities/{topic.slug}/membership"
    )


def test_backend_http_cannot_leak_into_assets_or_share_links(hosted_client, db_session):
    topic = create_topic(db_session)
    page = hosted_client.get(
        "http://internal-service:8000/topics/" + topic.slug,
        headers={
            "X-Forwarded-Host": "attacker.example",
            "X-Forwarded-Proto": "http",
        },
    )
    assert page.status_code == 200
    assert has_element(page, "script", src="/static/js/display.js")
    assert has_element(page, "meta", property="og:url", content=ORIGIN + f"/topics/{topic.slug}")
    assert "internal-service" not in page.text and "attacker.example" not in page.text
    request = Request(
        {
            "type": "http",
            "scheme": "http",
            "server": ("internal-service", 8000),
            "path": "/communities",
            "query_string": b"q=critical+care&mine=true",
            "headers": [],
        }
    )
    assert page_url(request, page=2) == "/communities?q=critical+care&mine=true&page=2"


def test_emails_and_oidc_use_same_public_domain(hosted_client, monkeypatch):
    messages = []
    monkeypatch.setattr(account_mail, "deliver_mail", messages.append)
    monkeypatch.setattr(notification_worker, "deliver_mail", messages.append)
    account_mail.send_account_mail("fixture@example.org", "reset", "x" * 43)
    account_mail.send_account_mail("fixture@example.org", "verify", "y" * 43)
    notice = SimpleNamespace(email_to="fixture@example.org", email_attempts=1)
    assert notification_worker.deliver_notification(notice, uuid4()) == "sent"
    bodies = "\n".join(message.get_content() for message in messages)
    for path in (
        "/auth/reset-password",
        "/auth/verify-email",
        "/notifications",
        "/notifications/preferences",
    ):
        assert ORIGIN + path in bodies
    assert "localhost" not in bodies and "127.0.0.1" not in bodies
    for provider in social_auth.PROVIDERS:
        monkeypatch.setattr(settings, provider + "_client_id", "fixture-client")
        monkeypatch.setattr(settings, provider + "_client_secret", "fixture-secret")
        url = social_auth.authorization_url(provider, "state", "nonce", "verifier")
        assert parse_qs(urlsplit(url).query)["redirect_uri"] == [
            ORIGIN + f"/auth/social/{provider}/callback"
        ]


@pytest.mark.parametrize("role", ["web", "all"])
def test_hosting_preflight_uses_env_without_opening_database(tmp_path, role):
    env = {name: value for name, value in os.environ.items() if not name.startswith("NURSE_NG_")}
    key = secrets.token_urlsafe(32)
    env.update(
        {
            "NURSE_NG_ENVIRONMENT": "production",
            "NURSE_NG_SECRET_KEY": key,
            "NURSE_NG_PUBLIC_BASE_URL": ORIGIN,
            "NURSE_NG_ALLOWED_HOSTS": "members.nurse.example",
            "NURSE_NG_DATABASE_URL": "postgres://fixture:private-password@unreachable.invalid/nurse",
            "NURSE_NG_REQUIRED_WORKERS": "recruitment,reels,notifications",
            "PORT": "32123",
        }
    )
    result = subprocess.run(
        [sys.executable, str(ROOT / "deploy/start.py"), role, "--check"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    command = output["command"]["web"] if role == "all" else output["command"]
    assert output["public_site"] == ORIGIN and "32123" in command
    if role == "all":
        assert output["command"]["workers"][-2:] == ["app.cli", "workers"]
    assert key not in result.stdout + result.stderr
    assert "private-password" not in result.stdout + result.stderr
