"""Self-service account management. Actor identity always comes from the session."""

import logging

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.ratelimit import FixedWindowLimiter
from app.db.session import SessionLocal, get_db
from app.models.account import AccountToken
from app.models.user import User
from app.services import accounts
from app.services.account_mail import MailUnavailable, mail_available, send_account_mail
from app.services.auth import AuthError
from app.web.deps import get_current_user, require_user, verify_csrf
from app.web.feedback import message, pending_feedback, redirect_feedback, render_error
from app.web.templating import render

router = APIRouter(tags=["account"])
_email_limit = FixedWindowLimiter(limit=5, window_seconds=900)
_credential_limit = FixedWindowLimiter(limit=20, window_seconds=900)
_photo_limit = FixedWindowLimiter(limit=20, window_seconds=3600)
PRIVATE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
logger = logging.getLogger(__name__)


def throttle(request: Request, limiter: FixedWindowLimiter, *, key: str = ""):
    key = key or (request.client.host if request.client else "unknown")
    if limiter.is_limited(key):
        retry = limiter.retry_after(key)
        raise HTTPException(
            429, "Too many attempts. Please try again later.", headers={"Retry-After": str(retry)}
        )
    limiter.record(key)


def settings_response(request, user, *, error="", title="Action not completed", code=400,
                      fields=None):
    return render_error(
        request,
        "pages/settings.html",
        {
            "title": "Account settings",
            "user": user,
            "mail_available": mail_available(),
            "values": {"full_name": user.full_name, "email": user.email or ""},
        },
        message(title, error, tone="error", fields=fields), status_code=code,
    )


def deliver_mail(recipient: str, purpose: str, token: str):
    # Delivery follows the HTTP response, so provider latency doesn't identify
    # registered accounts. A failed delivery invalidates that specific token.
    try:
        send_account_mail(recipient, purpose, token)
    except MailUnavailable:
        logger.warning("Account email delivery failed; check the email service configuration.")
        import hashlib

        with SessionLocal() as db:
            db.execute(
                delete(AccountToken).where(
                    AccountToken.token_hash == hashlib.sha256(token.encode()).hexdigest(),
                )
            )
            db.commit()


@router.post("/settings/photo")
def upload_photo(
    request: Request,
    photo: UploadFile = File(...),
    public: bool = Form(False),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    throttle(request, _photo_limit, key=str(user.id))
    try:
        accounts.set_photo(
            db, user, data=photo.file.read(settings.avatar_max_bytes + 1), public=public
        )
    except AuthError as exc:
        return settings_response(request, user, title="Photo wasn’t uploaded", error=str(exc),
                                 fields={"photo": str(exc)})
    finally:
        photo.file.close()
    return redirect_feedback(request, "/settings", message(
        "Profile photo updated", "Your new photo is saved. " + (
            "Other people can see it." if public else "Only you can see it."
        )
    ))


@router.post("/settings/photo/remove")
def remove_photo(
    request: Request,
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    try:
        accounts.set_photo(db, user, data=None)
    except AuthError as exc:
        return settings_response(request, user, title="Photo wasn’t removed", error=str(exc))
    return redirect_feedback(request, "/settings", message(
        "Profile photo removed", "Your initials will appear in place of your photo."
    ))


@router.post("/settings/photo/visibility")
def photo_visibility(
    request: Request,
    public: bool = Form(False),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    changed = db.execute(
        update(User)
        .where(
            User.id == user.id,
            User.auth_version == user.auth_version,
            User.photo_storage_name != "",
            User.is_active.is_(True),
        )
        .values(photo_public=public)
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        db.rollback()
        return settings_response(request, user, title="Visibility wasn’t changed", code=409,
                                 error="Your photo changed. Reload the page before trying again.")
    db.commit()
    db.refresh(user)
    return redirect_feedback(request, "/settings", message(
        "Photo visibility saved", "Other people can now see your photo." if public
        else "Your photo is private. Only you can see it."
    ))


@router.get("/account/photos/{name}")
def account_photo(
    name: str, user: User | None = Depends(get_current_user), db: Session = Depends(get_db)
):
    owner = db.scalar(
        select(User).where(
            User.photo_storage_name == name,
            User.is_active.is_(True),
            User.status == "active",
        )
    )
    if not owner or (not owner.photo_public and (user is None or user.id != owner.id)):
        raise HTTPException(404)
    try:
        path = accounts.avatar_path(name)
    except AuthError:
        raise HTTPException(404) from None
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={
            **PRIVATE_HEADERS,
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/auth/forgot-password")
def forgot_form(request: Request, user: User | None = Depends(get_current_user)):
    saved = pending_feedback(request)
    return render(
        request,
        "auth/recovery.html",
        {
            "mode": "sent" if saved and saved.get("code") == "reset_requested" else "forgot",
            "user": user,
            "mail_available": mail_available(),
        },
        headers=PRIVATE_HEADERS,
    )


@router.post("/auth/forgot-password")
def forgot_password(
    request: Request,
    background: BackgroundTasks,
    phone: str = Form(""),
    user: User | None = Depends(get_current_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    throttle(request, _email_limit)
    if not mail_available():
        return render_error(
            request,
            "auth/recovery.html",
            {
                "mode": "forgot",
                "user": user,
                "mail_available": False,
            },
            message("Email is temporarily unavailable", "Please try again later.", tone="error"),
            status_code=503,
        )
    accounts.request_account_email(
        db,
        purpose="reset",
        phone=phone,
        dispatch=lambda recipient, purpose, token: background.add_task(
            deliver_mail,
            recipient,
            purpose,
            token,
        ),
    )
    return redirect_feedback(request, "/auth/forgot-password", message(
        "Check your email", "If the account has a verified email address, we’ll send a "
        "password-reset link. Check your spam folder too. The link expires in 30 minutes.",
        tone="info",
    ), code="reset_requested")


@router.post("/settings/verify-email")
def request_verification(
    request: Request,
    background: BackgroundTasks,
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    throttle(request, _email_limit)
    if user.email_verified_at:
        return redirect_feedback(request, "/settings", message(
            "Email already verified", "You can use your email address for password recovery."
        ))
    if not user.email:
        return settings_response(request, user, error="Add an email address first.", code=400)
    try:
        sent = accounts.request_account_email(
            db,
            purpose="verify",
            user=user,
            dispatch=lambda recipient, purpose, token: background.add_task(
                deliver_mail,
                recipient,
                purpose,
                token,
            ),
        )
    except MailUnavailable as exc:
        return settings_response(request, user, error=str(exc), code=503)
    return redirect_feedback(request, "/settings", message(
        "Check your email" if sent else "Please wait before trying again",
        "Your verification email has been requested. Check your inbox and spam folder for the link."
        if sent else "Please wait a minute before requesting another verification email.",
        tone="info",
    ))


@router.get("/auth/reset-password")
def reset_form(request: Request, user: User | None = Depends(get_current_user)):
    return render(
        request, "auth/recovery.html", {"mode": "reset", "user": user}, headers=PRIVATE_HEADERS
    )


@router.post("/auth/reset-password")
def reset_password(
    request: Request,
    token: str = Form(""),
    password: str = Form(""),
    confirm_password: str = Form(""),
    user: User | None = Depends(get_current_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    throttle(request, _credential_limit)
    try:
        if password != confirm_password:
            raise AuthError("The passwords do not match.")
        accounts.consume_account_token(db, token, "reset", password=password)
    except AuthError as exc:
        return render_error(
            request,
            "auth/recovery.html",
            {
                "mode": "reset",
                "user": user,
                "token": token[:100],
                "error": str(exc),
            },
            message("Password wasn’t changed", str(exc), tone="error", fields=(
                {"confirm_password": str(exc)} if password != confirm_password else {}
            )),
        )
    request.session.clear()
    return redirect_feedback(request, "/auth/login", message(
        "Password updated", "Your password has been reset. Sign in with your new password. "
        "Your previous sign-in sessions have ended."
    ))


@router.get("/auth/verify-email")
def verification_form(request: Request, user: User | None = Depends(get_current_user)):
    return render(
        request, "auth/recovery.html", {"mode": "verify", "user": user}, headers=PRIVATE_HEADERS
    )


@router.post("/auth/verify-email")
def verify_email(
    request: Request,
    token: str = Form(""),
    user: User | None = Depends(get_current_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    throttle(request, _credential_limit)
    try:
        accounts.consume_account_token(db, token, "verify")
    except AuthError as exc:
        return render_error(
            request,
            "auth/recovery.html",
            {
                "mode": "verify",
                "user": user,
                "token": token[:100],
                "error": str(exc),
            },
            message("Email wasn’t verified", str(exc), tone="error"),
        )
    return redirect_feedback(request, "/settings" if user else "/auth/login", message(
        "Email verified", "Your email address is confirmed. You can now use it to recover "
        "your Nurse.ng account."
    ))


@router.get("/settings/delete-account")
def delete_form(request: Request, user: User = Depends(require_user)):
    return render(request, "pages/delete_account.html", {"user": user})


@router.post("/settings/delete-account")
def delete_account(
    request: Request,
    password: str = Form(""),
    confirmation: str = Form(""),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    throttle(request, _credential_limit)
    try:
        if confirmation != "DELETE":
            raise AuthError("Type DELETE to confirm account deletion.")
        accounts.delete_account(db, user, password=password)
    except AuthError as exc:
        return render_error(
            request,
            "pages/delete_account.html",
            {
                "user": user,
                "error": str(exc),
            },
            message("Account wasn’t deleted", str(exc), tone="error"),
        )
    request.session.clear()
    return redirect_feedback(request, "/auth/login", message(
        "Account deleted", "Your account and associated content have been removed from the live "
        "app. You have been signed out."
    ))
