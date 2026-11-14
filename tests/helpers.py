"""Shared helpers for the web tests."""

import re
from datetime import UTC, datetime
from html.parser import HTMLParser

CSRF_RE = re.compile(r'name="csrf_token"\s+value="([^"]+)"')


def approve_test_employer(db, user, name):
    """Seed reviewed fixture data; approval behavior has separate boundary tests."""
    from sqlalchemy import select

    from app.models.employers import EmployerMembership, EmployerOrganization

    org = db.scalar(select(EmployerOrganization).where(
        EmployerOrganization.name_key == name.casefold()
    ))
    if org is None:
        org = EmployerOrganization(name=name, name_key=name.casefold(),
                                   website="https://example.org", status="approved")
        db.add(org)
        db.flush()
    user.email = user.email or f"employer-{user.id.hex}@example.org"
    user.email_verified_at = datetime.now(UTC)
    member = db.scalar(select(EmployerMembership).where(
        EmployerMembership.organization_id == org.id, EmployerMembership.user_id == user.id
    ))
    if member is None:
        db.add(EmployerMembership(organization_id=org.id, user_id=user.id,
                                 authority_details="Reviewed test fixture", status="approved"))
    db.commit()
    return org


def document_bytes(kind):
    from io import BytesIO

    from PIL import Image
    from pypdf import PdfWriter

    stream = BytesIO()
    if kind == "PDF":
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=400)
        writer.write(stream)
    else:
        Image.new("RGB", (32, 32), "white").save(stream, kind)
    return stream.getvalue()


def has_element(response, tag, **expected):
    """Check rendered attributes without depending on template indentation."""
    found = []

    class Elements(HTMLParser):
        def handle_starttag(self, name, pairs):
            attributes = dict(pairs)
            if name == tag and all(
                (key in attributes if value is True else key not in attributes)
                if isinstance(value, bool) else attributes.get(key) == value
                for key, value in expected.items()
            ):
                found.append(attributes)

    Elements().feed(response.text)
    return bool(found)


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
