"""Shared helpers for the web tests."""

import re

CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def csrf_from(response) -> str:
    match = CSRF_RE.search(response.text)
    assert match is not None, "page did not render a CSRF token"
    return match.group(1)


def register_payload(
    phone: str = "0801 234 5678", password: str = "s3cret-pass"
) -> dict[str, str]:
    return {
        "phone": phone,
        "password": password,
        "confirm_password": password,
    }


def register_and_sign_in(
    client,
    phone: str = "0801 234 5678",
    password: str = "s3cret-pass",
) -> None:
    token = csrf_from(client.get("/auth/register"))
    response = client.post(
        "/auth/register",
        data={"csrf_token": token, **register_payload(phone, password)},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
