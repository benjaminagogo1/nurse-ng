"""Production startup, host boundaries, and session-signing regressions (A01)."""

import base64
import json
import os
import secrets
import subprocess
import sys
from http.cookies import SimpleCookie
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
from pydantic import ValidationError

import app.main as main_module
from app.core.config import Settings
from app.db.session import get_db
from app.models.user import User
from app.services.auth import register_user
from tests.helpers import csrf_from

REPO_ROOT = Path(__file__).resolve().parents[1]
OLD_KEYS = ("insecure-dev-key-change-me", "change-me-in-development")


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    # Settings checks must not accidentally inherit the test or operator config.
    for name in tuple(os.environ):
        if name.startswith("NURSE_NG_"):
            monkeypatch.delenv(name)


def production_settings(**overrides):
    values = {
        "secret_key": secrets.token_urlsafe(32),
        "allowed_hosts": "nurse.example,www.nurse.example",
        "public_base_url": "https://nurse.example",
        "database_url": "sqlite:////var/lib/nurse-ng/nurse_ng.db",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.mark.parametrize(("overrides", "message"), [
    ({"secret_key": ""}, "NURSE_NG_SECRET_KEY"),
    ({"secret_key": OLD_KEYS[0]}, "NURSE_NG_SECRET_KEY"),
    ({"secret_key": OLD_KEYS[1]}, "NURSE_NG_SECRET_KEY"),
    ({"secret_key": "short"}, "NURSE_NG_SECRET_KEY"),
    ({"allowed_hosts": ""}, "NURSE_NG_ALLOWED_HOSTS"),
    ({"allowed_hosts": "   "}, "NURSE_NG_ALLOWED_HOSTS"),
    ({"debug": True}, "NURSE_NG_DEBUG"),
    ({"session_https_only": False}, "NURSE_NG_SESSION_HTTPS_ONLY"),
    ({"environment": "prodution"}, "environment"),
])
def test_production_rejects_unsafe_configuration(overrides, message):
    with pytest.raises(ValidationError, match=message):
        production_settings(**overrides)


def test_configuration_errors_and_repr_do_not_expose_the_signing_key():
    key = secrets.token_urlsafe(32)
    with pytest.raises(ValidationError) as error:
        production_settings(secret_key=key, debug=True)
    assert key not in str(error.value)
    assert key not in repr(production_settings(secret_key=key))


@pytest.mark.parametrize("hosts", [
    "*", "*.example.com", "nurse.example,*", "https://nurse.example",
    "nurse.example:8000", "nurse.example/path", "user@nurse.example",
    "nurse.example,", "nurse..example",
])
def test_host_configuration_cannot_disable_or_misconfigure_the_boundary(hosts):
    with pytest.raises(ValidationError, match="NURSE_NG_ALLOWED_HOSTS"):
        production_settings(allowed_hosts=hosts)


def test_development_without_a_key_uses_independent_random_keys():
    first = Settings(_env_file=None, environment="development", session_https_only=False)
    second = Settings(_env_file=None, environment="development", session_https_only=False)
    assert len(first.secret_key) >= 32
    assert first.secret_key != second.secret_key
    assert first.secret_key not in OLD_KEYS
    assert first.trusted_hosts == ["localhost", "127.0.0.1", "[::1]"]


@pytest.mark.parametrize("key", OLD_KEYS)
def test_development_also_rejects_shared_placeholder_keys(key):
    with pytest.raises(ValidationError, match="NURSE_NG_SECRET_KEY"):
        Settings(_env_file=None, environment="development", secret_key=key)


def test_samesite_none_requires_secure_cookies_even_in_development():
    with pytest.raises(ValidationError, match="SameSite=None"):
        Settings(
            _env_file=None, environment="development",
            session_same_site="none", session_https_only=False,
        )


@pytest.fixture
def production_client(monkeypatch, db_session):
    config = production_settings()
    monkeypatch.setattr(main_module, "settings", config)
    app = main_module.create_app()

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app, base_url="https://nurse.example") as client:
            yield client, config
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("path", ["/healthz", "/auth/register", "/review", "/static/css/app.css"])
def test_unlisted_host_is_rejected_before_routes_and_sessions(production_client, path):
    client, _ = production_client
    response = client.get(path, headers={
        "Host": "attacker.example",
        "X-Forwarded-Host": "nurse.example",
    }, follow_redirects=False)
    assert response.status_code == 400
    assert "set-cookie" not in response.headers
    assert "location" not in response.headers


@pytest.mark.parametrize("host", ["nurse.example", "www.nurse.example", "nurse.example:443"])
def test_configured_hosts_work(production_client, host):
    client, _ = production_client
    assert client.get("/healthz", headers={"Host": host}).status_code == 200


def test_local_development_hosts_remain_usable(monkeypatch):
    monkeypatch.setattr(main_module, "settings", Settings(
        _env_file=None, environment="development", session_https_only=False,
    ))
    with TestClient(main_module.create_app(), base_url="http://localhost") as client:
        for host in ("localhost:8000", "127.0.0.1:8000", "[::1]:8000"):
            assert client.get("/healthz", headers={"Host": host}).status_code == 200
        assert client.get("/healthz", headers={"Host": "attacker.example"}).status_code == 400


@pytest.mark.parametrize("old_key", OLD_KEYS)
def test_forged_staff_cookie_using_a_previous_development_key_is_rejected(
    production_client, db_session, old_key,
):
    client, config = production_client
    staff = User(phone="+2348000000001", hashed_password="unused", is_staff=True)
    db_session.add(staff)
    db_session.commit()
    payload = base64.b64encode(json.dumps({"user_id": str(staff.id)}).encode())

    # Control: the staff ID exists and a correctly signed session can reach the queue.
    client.cookies.set(config.session_cookie_name, TimestampSigner(config.secret_key).sign(
        payload,
    ).decode())
    assert client.get("/review", follow_redirects=False).status_code == 200

    client.cookies.clear()
    client.cookies.set(config.session_cookie_name, TimestampSigner(old_key).sign(payload).decode())
    response = client.get("/review", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login"


def test_production_login_and_logout_keep_cookie_protections(production_client, db_session):
    client, config = production_client
    user = register_user(db_session, phone="+2348000000002", password="test-password")
    user.is_staff = True
    db_session.commit()
    token = csrf_from(client.get("/auth/login"))
    response = client.post("/auth/login", data={
        "csrf_token": token, "phone": user.phone, "password": "test-password",
    }, follow_redirects=False)
    assert response.status_code == 303
    cookie = SimpleCookie(response.headers["set-cookie"])[config.session_cookie_name]
    assert cookie["secure"] and cookie["httponly"]
    assert cookie["samesite"] == "lax"
    assert client.get("/review", follow_redirects=False).status_code == 200
    assert client.get("http://nurse.example/review", follow_redirects=False).status_code == 303

    token = csrf_from(client.get("/review"))
    response = client.post("/auth/logout", data={"csrf_token": token}, follow_redirects=False)
    cookie = SimpleCookie(response.headers["set-cookie"])[config.session_cookie_name]
    assert cookie["secure"] and cookie["httponly"]
    assert client.get("/review", follow_redirects=False).status_code == 303


@pytest.mark.parametrize("configured", [False, True])
def test_fresh_process_startup_defaults_to_production(tmp_path, configured):
    env = {name: value for name, value in os.environ.items() if not name.startswith("NURSE_NG_")}
    env["PYTHONPATH"] = str(REPO_ROOT)
    if configured:
        env.update({
            "NURSE_NG_SECRET_KEY": secrets.token_urlsafe(32),
            "NURSE_NG_ALLOWED_HOSTS": "nurse.example",
            "NURSE_NG_PUBLIC_BASE_URL": "https://nurse.example",
            "NURSE_NG_DATABASE_URL": f"sqlite:///{tmp_path / 'database.db'}",
        })
    result = subprocess.run(
        [sys.executable, "-c", "from app.main import app; print('application initialized')"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30,
    )
    if configured:
        assert result.returncode == 0, result.stderr
        assert "application initialized" in result.stdout
    else:
        assert result.returncode != 0
        assert "NURSE_NG_SECRET_KEY" in result.stderr
        assert "application initialized" not in result.stdout


def test_operator_configuration_check_does_not_expose_secrets_or_connect_to_database(tmp_path):
    key = secrets.token_urlsafe(32)
    env = {name: value for name, value in os.environ.items() if not name.startswith("NURSE_NG_")}
    env.update({
        "PYTHONPATH": str(REPO_ROOT),
        "NURSE_NG_SECRET_KEY": key,
        "NURSE_NG_ALLOWED_HOSTS": "nurse.example",
        "NURSE_NG_PUBLIC_BASE_URL": "https://nurse.example",
        # This directory does not exist, so opening the DB would fail.
        "NURSE_NG_DATABASE_URL": f"sqlite:///{tmp_path / 'absent' / 'database.db'}",
    })
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "check-config"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "environment=production" in result.stdout
    assert "Secure cookies: True; debug: False" in result.stdout
    assert key not in result.stdout + result.stderr
    assert env["NURSE_NG_DATABASE_URL"] not in result.stdout + result.stderr
    assert not (tmp_path / "absent").exists()
