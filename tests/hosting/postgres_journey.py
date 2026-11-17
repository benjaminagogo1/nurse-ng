"""Isolated PostgreSQL migration and hosted-community journey; never sends mail."""

import os
import re
import secrets
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
database = os.environ.get("NURSE_NG_TEST_POSTGRES_URL", "")
if not database or not database.split("?", 1)[0].endswith("/nurse_ng_hosting_test"):
    raise RuntimeError("Use an isolated PostgreSQL database named nurse_ng_hosting_test.")
storage = tempfile.TemporaryDirectory(prefix="nurse-hosting-postgres-")
origin = "https://members.nurse.example"
for name in tuple(os.environ):
    if name.startswith("NURSE_NG_"):
        del os.environ[name]
os.environ.update(
    {
        "NURSE_NG_ENVIRONMENT": "production",
        "NURSE_NG_DATABASE_URL": database,
        "NURSE_NG_SECRET_KEY": secrets.token_urlsafe(32),
        "NURSE_NG_PUBLIC_BASE_URL": origin,
        "NURSE_NG_ALLOWED_HOSTS": "members.nurse.example",
        "NURSE_NG_ACCOUNT_MAIL_BACKEND": "disabled",
        "NURSE_NG_REQUIRED_WORKERS": "",
        "NURSE_NG_SESSION_HTTPS_ONLY": "true",
        "NURSE_NG_AVATAR_DIR": storage.name + "/avatars",
        "NURSE_NG_COMMUNITY_MEDIA_DIR": storage.name + "/community",
        "NURSE_NG_EVIDENCE_DIR": storage.name + "/evidence",
    }
)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models.community import CommunityMembership, CommunityPost, CommunityTopic  # noqa: E402
from app.services.community_sharing import invitation_url  # noqa: E402


def csrf(page):
    return re.search(r'name="csrf_token"\s+value="([^"]+)"', page.text)[1]


command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
command.check(Config(str(ROOT / "alembic.ini")))
with TestClient(app, base_url=origin) as client:
    page = client.get("/auth/register")
    result = client.post(
        "/auth/register",
        data={
            "csrf_token": csrf(page),
            "phone": "+2348999222001",
            "password": "hosted-test-password",
            "confirm_password": "hosted-test-password",
            "full_name": "Isolated hosting test member",
        },
        follow_redirects=False,
    )
    assert result.status_code == 303, result.status_code
    page = client.get("/communities/new?example=critical-care")
    assert page.status_code == 200
    result = client.post(
        "/communities",
        data={
            "csrf_token": csrf(page),
            "community_name": "Hosting test host",
            "name": "Hosted peer learning",
            "description": "A PostgreSQL-backed community.",
            "rules": "Respect colleagues and protect privacy.",
            "interest": "Research",
        },
        follow_redirects=False,
    )
    assert result.status_code == 303, result.status_code
    topic_path = result.headers["location"]
    with SessionLocal() as db:
        topic = db.scalar(
            select(CommunityTopic).where(CommunityTopic.name == "Hosted peer learning")
        )
        topic_id = str(topic.id)
        assert db.scalar(select(func.count()).select_from(CommunityMembership)) == 1
    invite = invitation_url(topic_path)
    assert invite.startswith(origin + "/join/")
    assert client.get(invite, follow_redirects=False).headers["location"] == topic_path
    page = client.get("/posts/new?topic=" + topic_id)
    result = client.post(
        "/posts",
        data={
            "csrf_token": csrf(page),
            "topic_id": topic_id,
            "post_kind": "question",
            "body": "How can we learn together on the hosted site?",
        },
        follow_redirects=False,
    )
    assert result.status_code == 303, result.status_code
    post_path = result.headers["location"]
    assert client.get(post_path).status_code == 200
    assert client.get("/readyz").status_code == 200
    page = client.get(topic_path)
    assert origin + "/join/" in page.text and "http://127.0.0.1" not in page.text
    result = client.post("/auth/logout", data={"csrf_token": csrf(page)}, follow_redirects=False)
    assert result.status_code == 303
    invite = invitation_url(post_path)
    target = client.get(urlsplit(invite).path, follow_redirects=False).headers["location"]
    page = client.get("/auth/register", params={"next": target})
    result = client.post(
        "/auth/register",
        data={
            "csrf_token": csrf(page),
            "phone": "+2348999222002",
            "next": target,
            "password": "hosted-test-password",
            "confirm_password": "hosted-test-password",
        },
        follow_redirects=False,
    )
    assert result.status_code == 303 and result.headers["location"] == post_path
    assert "; secure" in result.headers["set-cookie"].lower()
    page = client.get(post_path)
    result = client.post(
        post_path + "/replies",
        data={
            "csrf_token": csrf(page),
            "community_name": "Hosting test colleague",
            "body": "Share questions and useful resources with colleagues.",
        },
        follow_redirects=False,
    )
    assert result.status_code == 303, result.status_code
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(CommunityPost)) == 1
    assert client.get(post_path).status_code == 200
print(
    "PostgreSQL hosting journey passed: migration, signup, community, membership, question, "
    "public invitation, signup continuation, reply and Secure cookies."
)
storage.cleanup()
