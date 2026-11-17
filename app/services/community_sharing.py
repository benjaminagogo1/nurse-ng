"""Reusable public invitations and tightly scoped sign-in destinations."""

import re
from urllib.parse import urlencode, urlsplit
from uuid import UUID

from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.public_urls import public_site_ready, public_url
from app.services.community import get_published_post, get_topic_by_slug


def community_destination(db: Session, value: str) -> str:
    """Accept current public community/discussion pages, never arbitrary redirects."""
    if not isinstance(value, str) or len(value) > 240 or any(ord(c) < 32 for c in value):
        return ""
    if "\\" in value or "%" in value or value.startswith("//"):
        return ""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    if parsed.scheme or parsed.netloc or parsed.query:
        return ""
    if parsed.fragment not in {"", "reply-form"}:
        return ""
    topic = re.fullmatch(r"/topics/([a-z0-9][a-z0-9-]{0,79})", parsed.path)
    if topic and not parsed.fragment and get_topic_by_slug(db, topic[1]):
        return parsed.path
    post = re.fullmatch(r"/posts/([0-9a-f-]{36})", parsed.path)
    if post:
        try:
            identifier = UUID(post[1])
        except ValueError:
            return ""
        if get_published_post(db, identifier):
            return parsed.path + ("#reply-form" if parsed.fragment else "")
    return ""


def auth_context(db: Session, destination: str) -> dict:
    target = community_destination(db, destination)
    suffix = "?" + urlencode({"next": target}) if target else ""
    return {
        "next": target,
        "login_url": "/auth/login" + suffix,
        "register_url": "/auth/register" + suffix,
    }


def share_preview(path: str, title: str, description: str) -> dict:
    if not public_site_ready():
        return {}
    return {
        "share_preview": {
            "url": public_url(path),
            "title": title[:160] + " — Nurse.ng",
            "description": " ".join(description.split())[:240],
            "image": public_url("/static/img/app-icon-512.png"),
        }
    }


def _signer():
    return URLSafeSerializer(settings.secret_key, salt="nurse-ng-public-community-invitation-v1")


def invitation_url(path: str) -> str:
    if not public_site_ready():
        return ""
    token = _signer().dumps({"path": path})
    return public_url("/join/" + token)


def invitation_destination(db: Session, token: str) -> str:
    if len(token) > 1024:
        return ""
    try:
        value = _signer().loads(token)
    except BadSignature:
        return ""
    return community_destination(db, value.get("path", "")) if isinstance(value, dict) else ""
