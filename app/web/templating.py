"""Template rendering and CSRF tokens."""

import secrets
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def csrf_token(request: Request) -> str:
    """Return the session's CSRF token, creating it on first use."""
    token = request.session.get("csrf_token")
    if not isinstance(token, str) or not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def render(
    request: Request,
    name: str,
    context: dict[str, Any] | None = None,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> HTMLResponse:
    """Render a template with the CSRF token always available.

    ``headers`` carries response metadata such as ``Retry-After`` when a
    rate-limited form is re-rendered.
    """
    path = request.url.path
    section = path.strip("/").split("/")[0] or "home"
    if path == "/auth/dashboard":
        section = "dashboard"
    elif path.startswith("/profile/verification"):
        section = "verification"
    elif section in {"posts", "feed"}:
        section = "feed"
    elif section == "community":
        section = "settings"
    template_context: dict[str, Any] = {
        "csrf_token": csrf_token(request),
        "page": section,
        "is_auth_page": name in {"auth/login.html", "auth/register.html"},
    }
    if context:
        template_context.update(context)
    return templates.TemplateResponse(
        request=request,
        name=name,
        context=template_context,
        status_code=status_code,
        headers=headers,
    )
