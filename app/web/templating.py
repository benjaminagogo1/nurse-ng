"""Template rendering and CSRF tokens."""

import secrets
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from sqlalchemy.orm import object_session

from app.services.activity import record_visit
from app.services.community_growth import activity_time
from app.services.notifications import unread_count
from app.services.tours import snapshot as tour_snapshot
from app.web.feedback import enhanced, message, pending_feedback

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@pass_context
def relative_url_for(context, name: str, **parameters) -> str:
    request = context["request"]
    return request.url_for(name, **parameters).path


templates.env.globals["url_for"] = relative_url_for


def display_date(value: date | str | None) -> str:
    """Format a calendar date without shifting an ISO timestamp's stated day."""
    if value is None:
        return ""
    if not isinstance(value, date):
        try:
            value = datetime.fromisoformat(value.strip())
        except ValueError:
            return value
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    return f"{months[value.month - 1]} {value.day}, {value.year}"


templates.env.filters["display_date"] = display_date
templates.env.filters["community_activity_time"] = activity_time


def csrf_token(request: Request) -> str:
    """Return the session's CSRF token, creating it on first use."""
    token = request.session.get("csrf_token")
    if not isinstance(token, str) or not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def confirm_published_draft(request: Request, key: str, version: str) -> None:
    """Acknowledge only a valid opaque version, never store draft content in the session."""
    try:
        version = str(UUID(version))
    except ValueError:
        return
    request.session["published_draft"] = {"key": key, "version": version}


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
    fetch_mode = request.headers.get("sec-fetch-mode", "navigate")
    # The offline worker's abortable fetch loses native navigation metadata.
    # This is a display/activity hint only; authentication and CSRF are unchanged.
    worker_navigation = (
        request.headers.get("x-nurse-navigation") == "document"
        and fetch_mode == "same-origin"
        and request.headers.get("sec-fetch-dest") == "empty"
        and request.headers.get("sec-fetch-site") == "same-origin"
    )
    page_navigation = (
        request.method == "GET"
        and 200 <= status_code < 300
        and (fetch_mode == "navigate" or worker_navigation)
        and "prefetch" not in request.headers.get("sec-purpose", "").lower()
        and "prefetch" not in request.headers.get("purpose", "").lower()
    )
    section = path.strip("/").split("/")[0] or "home"
    if path == "/auth/dashboard":
        section = "dashboard"
    elif path.startswith("/staff/employers"):
        section = "employer-approvals"
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
        "draft_session_known": True,
    }
    if context:
        template_context.update(context)
    error = template_context.get("error") or template_context.get("reply_error")
    if error and not template_context.get("feedback"):
        template_context["feedback"] = message("Please check this action", str(error), tone="error")
    if request.method == "POST" and enhanced(request) and status_code >= 400:
        return JSONResponse(
            {
                "feedback": template_context.get("feedback")
                or message(
                    "We couldn’t complete this action",
                    "Please check your entries and try again.",
                    tone="error",
                )
            },
            status_code=status_code,
            headers={"Cache-Control": "no-store", **(headers or {})},
        )
    saved_feedback = pending_feedback(request)
    if saved_feedback:
        if not template_context.get("feedback"):
            template_context["feedback"] = saved_feedback["notice"]
    user = template_context.get("user")
    if user is not None and object_session(user) is not None:
        template_context.setdefault("notification_count", unread_count(object_session(user), user))
        template_context["tour"] = {
            **tour_snapshot(object_session(user), user),
            "csrf": template_context["csrf_token"],
            "offer": bool(request.session.get("tour_invitation")) and page_navigation,
        }
    template_context["draft_scope"] = (
        sha256(f"{user.id}:{template_context['csrf_token']}".encode()).hexdigest()
        if user is not None
        else ""
    )
    template_context["published_draft"] = request.session.get("published_draft") if user else None
    response = templates.TemplateResponse(
        request=request,
        name=name,
        context=template_context,
        status_code=status_code,
        headers={"Cache-Control": "no-store", **(headers or {})},
    )
    # A rendering failure leaves the acknowledgement available for a later page.
    if template_context["draft_session_known"]:
        request.session.pop("published_draft", None)
    if user is not None and page_navigation:
        request.session.pop("tour_invitation", None)
    if saved_feedback:
        request.session.pop("account_feedback", None)
    # Only completed page navigations count here. JSON polling, fetch fragments,
    # prefetches, assets, failures and anonymous visitors do not create visits.
    if user is not None and object_session(user) is not None and page_navigation:
        record_visit(object_session(user), user)
    return response
