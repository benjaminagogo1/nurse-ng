"""Login throttling, account lockout, and timing equalisation."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.config import settings
from app.models.user import User
from app.services import auth as auth_service
from app.services.auth import register_user
from tests.helpers import csrf_from, register_payload

PHONE = "+2348012345678"
PASSWORD = "s3cret-pass"


def login(client, phone: str = PHONE, password: str = "wrong-pass"):
    """Submit the sign-in form with a fresh CSRF token."""
    token = csrf_from(client.get("/auth/login"))
    return client.post(
        "/auth/login",
        data={"csrf_token": token, "phone": phone, "password": password},
        follow_redirects=False,
    )


def test_account_locks_after_repeated_failures(client, db_session):
    register_user(db_session, phone=PHONE, password=PASSWORD)

    for _ in range(settings.login_lockout_threshold):
        response = login(client)
        assert response.status_code == 401

    response = login(client, password=PASSWORD)

    assert response.status_code == 429
    assert "Too many unsuccessful attempts" in response.text
    assert int(response.headers["retry-after"]) >= 1

    user = db_session.scalar(select(User).where(User.phone == PHONE))
    assert user.failed_login_attempts >= settings.login_lockout_threshold
    assert user.locked_until is not None


def test_expired_lock_allows_sign_in_and_resets_the_counter(client, db_session):
    user = register_user(db_session, phone=PHONE, password=PASSWORD)
    user.failed_login_attempts = settings.login_lockout_threshold
    user.locked_until = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    # Force a reload so the comparison also covers SQLite's naive datetimes.
    db_session.expire_all()

    response = login(client, password=PASSWORD)

    assert response.status_code == 303
    db_session.expire_all()
    refreshed = db_session.scalar(select(User).where(User.phone == PHONE))
    assert refreshed.failed_login_attempts == 0
    assert refreshed.locked_until is None


def test_successful_sign_in_resets_the_failure_counter(client, db_session):
    register_user(db_session, phone=PHONE, password=PASSWORD)

    for _ in range(settings.login_lockout_threshold - 1):
        assert login(client).status_code == 401

    response = login(client, password=PASSWORD)

    assert response.status_code == 303
    db_session.expire_all()
    user = db_session.scalar(select(User).where(User.phone == PHONE))
    assert user.failed_login_attempts == 0
    assert user.locked_until is None


def test_lockout_is_scoped_to_one_account(client, db_session):
    register_user(db_session, phone=PHONE, password=PASSWORD)
    other_phone = "+2348099999999"
    register_user(db_session, phone=other_phone, password=PASSWORD)

    for _ in range(settings.login_lockout_threshold):
        assert login(client).status_code == 401

    response = login(client, phone=other_phone, password=PASSWORD)

    assert response.status_code == 303


def test_unknown_phone_still_performs_a_dummy_hash(client, monkeypatch):
    calls: list[str] = []
    real_verify = auth_service.verify_password

    def recording_verify(password: str, hashed_password: str) -> bool:
        calls.append(hashed_password)
        return real_verify(password, hashed_password)

    monkeypatch.setattr(auth_service, "verify_password", recording_verify)

    response = login(client, phone="+2348099999999")

    assert response.status_code == 401
    assert calls == [auth_service._DUMMY_PASSWORD_HASH]


def test_login_ip_limit_blocks_further_attempts(client):
    for _ in range(settings.login_ip_limit):
        assert login(client, phone="+2348099999999").status_code == 401

    response = login(client, phone="+2348099999999")

    assert response.status_code == 429
    assert "from this connection" in response.text
    assert int(response.headers["retry-after"]) >= 1


def test_registration_ip_limit_blocks_further_attempts(client):
    # Each successful registration signs the user in, and signing in clears the
    # session (including its CSRF token, L4). Clear the cookie jar to return to
    # an anonymous session for the next attempt; the IP counter is unaffected.
    for index in range(settings.register_ip_limit):
        client.cookies.clear()
        token = csrf_from(client.get("/auth/register"))
        response = client.post(
            "/auth/register",
            data={
                "csrf_token": token,
                **register_payload(phone=f"0801234500{index}"),
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

    client.cookies.clear()
    token = csrf_from(client.get("/auth/register"))
    response = client.post(
        "/auth/register",
        data={"csrf_token": token, **register_payload(phone="08012345099")},
        follow_redirects=False,
    )

    assert response.status_code == 429
    assert "from this connection" in response.text
    assert int(response.headers["retry-after"]) >= 1
