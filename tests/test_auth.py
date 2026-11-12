from sqlalchemy import select

from app.models.user import User
from app.services.auth import register_user
from tests.helpers import csrf_from


def register_payload(
    phone: str = "0801 234 5678", password: str = "s3cret-pass"
) -> dict[str, str]:
    return {
        "phone": phone,
        "password": password,
        "confirm_password": password,
    }


def test_register_page_renders_a_form(client):
    response = client.get("/auth/register")

    assert response.status_code == 200
    assert 'name="phone"' in response.text
    assert 'name="csrf_token"' in response.text


def test_register_creates_a_user_and_signs_in(client, db_session):
    token = csrf_from(client.get("/auth/register"))

    response = client.post(
        "/auth/register",
        data={"csrf_token": token, **register_payload()},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/welcome"

    user = db_session.scalar(select(User).where(User.phone == "+2348012345678"))
    assert user is not None
    assert user.check_password("s3cret-pass")

    home = client.get("/")
    assert "Sign out" in home.text


def test_register_rejects_duplicate_phone(client, db_session):
    register_user(db_session, phone="+2348012345678", password="s3cret-pass")
    token = csrf_from(client.get("/auth/register"))

    response = client.post(
        "/auth/register",
        data={"csrf_token": token, **register_payload()},
        follow_redirects=False,
    )

    assert response.status_code == 409
    assert "already exists" in response.text


def test_register_rejects_invalid_phone(client):
    token = csrf_from(client.get("/auth/register"))

    response = client.post(
        "/auth/register",
        data={"csrf_token": token, **register_payload(phone="not-a-phone")},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "phone number" in response.text


def test_register_rejects_short_password(client):
    token = csrf_from(client.get("/auth/register"))

    response = client.post(
        "/auth/register",
        data={"csrf_token": token, **register_payload(password="short")},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "at least 8" in response.text


def test_register_rejects_mismatched_passwords(client):
    token = csrf_from(client.get("/auth/register"))

    response = client.post(
        "/auth/register",
        data={
            "csrf_token": token,
            "phone": "08012345678",
            "password": "s3cret-pass",
            "confirm_password": "different-pass",
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "do not match" in response.text


def test_post_without_csrf_token_is_rejected(client):
    response = client.post("/auth/login", data={"phone": "08012345678", "password": "x"})

    assert response.status_code == 400


def test_login_with_valid_credentials_signs_in(client, db_session):
    register_user(db_session, phone="+2348012345678", password="s3cret-pass")
    token = csrf_from(client.get("/auth/login"))

    response = client.post(
        "/auth/login",
        data={"csrf_token": token, "phone": "0801 234 5678", "password": "s3cret-pass"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/"

    home = client.get("/")
    assert "Sign out" in home.text


def test_login_with_wrong_password_is_rejected(client, db_session):
    register_user(db_session, phone="+2348012345678", password="s3cret-pass")
    token = csrf_from(client.get("/auth/login"))

    response = client.post(
        "/auth/login",
        data={"csrf_token": token, "phone": "08012345678", "password": "wrong-pass"},
        follow_redirects=False,
    )

    assert response.status_code == 401
    assert "incorrect" in response.text


def test_logout_clears_the_session(client):
    token = csrf_from(client.get("/auth/register"))
    client.post(
        "/auth/register",
        data={"csrf_token": token, **register_payload()},
        follow_redirects=False,
    )

    home = client.get("/")
    assert "Sign out" in home.text
    token = csrf_from(home)

    response = client.post(
        "/auth/logout",
        data={"csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "Sign in" in client.get("/").text


def test_dashboard_requires_sign_in(client):
    response = client.get("/auth/dashboard", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login"


def test_dashboard_shows_the_signed_in_user(client):
    token = csrf_from(client.get("/auth/register"))
    client.post(
        "/auth/register",
        data={"csrf_token": token, **register_payload()},
        follow_redirects=False,
    )

    response = client.get("/auth/dashboard")

    assert response.status_code == 200
    assert "+2348012345678" in response.text
