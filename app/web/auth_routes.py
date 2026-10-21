"""Registration, sign-in, sign-out, and the authenticated account page."""

from math import ceil

from fastapi import APIRouter, Depends, Form, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.ratelimit import FixedWindowLimiter
from app.db.session import get_db
from app.models.user import User
from app.services.auth import (
    AuthError,
    LoginLockedError,
    authenticate_user,
    register_user,
)
from app.web.deps import get_current_user, require_user, verify_csrf
from app.web.templating import render

router = APIRouter(prefix="/auth", tags=["auth"])

# Per-IP counters are process-local (DECISIONS L37). Successful sign-ins do not
# consume the sign-in allowance; only failures do, so a busy shared connection
# is not blocked by people who know their passwords.
_login_ip_limiter = FixedWindowLimiter(
    settings.login_ip_limit, settings.login_ip_window_seconds
)
_register_ip_limiter = FixedWindowLimiter(
    settings.register_ip_limit, settings.register_ip_window_seconds
)


def _client_ip(request: Request) -> str:
    """Return the peer address the ASGI server reports.

    Behind a reverse proxy this is the proxy's address, not the user's. Trusted
    ``X-Forwarded-For`` handling is deliberately deferred (DECISIONS L41).
    """
    return request.client.host if request.client else "unknown"


def _minutes(seconds: int) -> int:
    """Round a retry delay up to whole minutes for the user-facing message."""
    return max(1, ceil(seconds / 60))


def _render_rate_limited(
    request: Request,
    template: str,
    context: dict[str, str],
    *,
    message: str,
    retry_after: int,
) -> Response:
    return render(
        request,
        template,
        {**context, "error": message},
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        headers={"Retry-After": str(retry_after)},
    )


def _start_session(request: Request, user: User) -> None:
    """Replace the session after authentication to prevent fixation."""
    request.session.clear()
    request.session["user_id"] = str(user.id)


@router.get("/register")
def register_form(
    request: Request,
    user: User | None = Depends(get_current_user),
) -> Response:
    if user is not None:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    return render(request, "auth/register.html", {"title": "Create your account"})


@router.post("/register")
def register(
    request: Request,
    phone: str = Form(""),
    password: str = Form(""),
    confirm_password: str = Form(""),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
) -> Response:
    ip = _client_ip(request)
    if _register_ip_limiter.is_limited(ip):
        retry_after = _register_ip_limiter.retry_after(ip)
        return _render_rate_limited(
            request,
            "auth/register.html",
            {"title": "Create your account", "phone": phone},
            message=(
                "Too many accounts were created from this connection. "
                f"Try again in {_minutes(retry_after)} minute(s)."
            ),
            retry_after=retry_after,
        )
    _register_ip_limiter.record(ip)

    if password != confirm_password:
        return render(
            request,
            "auth/register.html",
            {
                "title": "Create your account",
                "phone": phone,
                "error": "The two passwords do not match.",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        user = register_user(db, phone=phone, password=password)
    except AuthError as exc:
        return render(
            request,
            "auth/register.html",
            {"title": "Create your account", "phone": phone, "error": str(exc)},
            status_code=status.HTTP_409_CONFLICT
            if "already exists" in str(exc)
            else status.HTTP_400_BAD_REQUEST,
        )

    _start_session(request, user)
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/login")
def login_form(
    request: Request,
    user: User | None = Depends(get_current_user),
) -> Response:
    if user is not None:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    return render(request, "auth/login.html", {"title": "Sign in"})


@router.post("/login")
def login(
    request: Request,
    phone: str = Form(""),
    password: str = Form(""),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
) -> Response:
    ip = _client_ip(request)
    if _login_ip_limiter.is_limited(ip):
        retry_after = _login_ip_limiter.retry_after(ip)
        return _render_rate_limited(
            request,
            "auth/login.html",
            {"title": "Sign in", "phone": phone},
            message=(
                "Too many sign-in attempts from this connection. "
                f"Try again in {_minutes(retry_after)} minute(s)."
            ),
            retry_after=retry_after,
        )

    try:
        user = authenticate_user(db, phone=phone, password=password)
    except LoginLockedError as exc:
        return _render_rate_limited(
            request,
            "auth/login.html",
            {"title": "Sign in", "phone": phone},
            message=(
                "Too many unsuccessful attempts. "
                f"Try again in {_minutes(exc.retry_after_seconds)} minute(s)."
            ),
            retry_after=exc.retry_after_seconds,
        )

    if user is None:
        _login_ip_limiter.record(ip)
        return render(
            request,
            "auth/login.html",
            {
                "title": "Sign in",
                "phone": phone,
                "error": "The phone number or password is incorrect.",
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    _start_session(request, user)
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/logout")
def logout(
    request: Request,
    _: None = Depends(verify_csrf),
) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/dashboard")
def dashboard(
    request: Request,
    user: User = Depends(require_user),
) -> Response:
    return render(request, "auth/dashboard.html", {"title": "Your account", "user": user})
