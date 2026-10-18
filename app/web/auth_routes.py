"""Registration, sign-in, sign-out, and the authenticated account page."""

from fastapi import APIRouter, Depends, Form, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.services.auth import AuthError, authenticate_user, register_user
from app.web.deps import get_current_user, require_user, verify_csrf
from app.web.templating import render

router = APIRouter(prefix="/auth", tags=["auth"])


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
    user = authenticate_user(db, phone=phone, password=password)
    if user is None:
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
