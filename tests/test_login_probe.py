"""Regression coverage for login probe; see tests/README.md for isolation and runner setup."""

from tests.helpers import CSRF_RE, register_and_sign_in


def test_probe(client):
    for phone in ["+2348999999999", "+2348988888888"]:
        register_and_sign_in(client, phone=phone)
        token = CSRF_RE.search(client.get("/auth/login").text).group(1)
        resp = client.post(
            "/auth/login",
            data={"csrf_token": token, "phone": phone, "password": "s3cret-pass"},
            follow_redirects=False,
        )
        print("\n=== PHONE:", phone, "status:", resp.status_code)
        print(resp.text[:850])
