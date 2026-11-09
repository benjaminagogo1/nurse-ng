"""Browser-bound social sign-in, explicit linking, and first-time account completion."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.social_auth import SocialAuthAttempt, SocialEnrollment, SocialIdentity
from app.models.user import User
from app.services import social_auth as social
from app.services.accounts import verify_current_password
from app.services.auth import AuthError, LoginLockedError, authenticate_user, register_user
from app.web.auth_routes import (
    _client_ip,
    _login_ip_limiter,
    _register_ip_limiter,
    _start_session,
)
from app.web.deps import get_current_user, require_user, verify_csrf
from app.web.feedback import message, redirect_feedback
from app.web.templating import render

router = APIRouter(tags=["social sign-in"])


def _failure(request, body, destination="/auth/login"):
    return redirect_feedback(
        request, destination, message("Sign-in needs attention", body, tone="error")
    )


def _browser(request):
    return social.digest(request.session.get("oauth_browser", ""))


@router.post("/auth/social/{provider}/start")
def start(
    provider: str,
    request: Request,
    user: User | None = Depends(get_current_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    try:
        social.credentials(provider)
    except social.SocialAuthError as exc:
        return _failure(request, str(exc), "/settings/social" if user else "/auth/login")
    if _login_ip_limiter.is_limited(_client_ip(request)):
        raise HTTPException(429, "Too many sign-in attempts. Please try again in a few minutes.")
    _login_ip_limiter.record(_client_ip(request))
    now = datetime.now(UTC)
    request.session.setdefault("oauth_browser", social.new_secret())
    db.execute(
        delete(SocialAuthAttempt).where(SocialAuthAttempt.expires_at <= now),
        execution_options={"synchronize_session": False},
    )
    db.execute(
        delete(SocialEnrollment).where(SocialEnrollment.expires_at <= now),
        execution_options={"synchronize_session": False},
    )
    state, nonce, verifier = (social.new_secret() for _ in range(3))
    db.add(
        SocialAuthAttempt(
            token_hash=social.digest(state),
            browser_hash=_browser(request),
            provider=provider,
            nonce=nonce,
            verifier=verifier,
            expires_at=now + timedelta(minutes=10),
            user_id=user.id if user else None,
            auth_version=user.auth_version if user else None,
        )
    )
    db.commit()
    return RedirectResponse(
        social.authorization_url(provider, state, nonce, verifier),
        303,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@router.get("/auth/social/{provider}/callback")
def callback(
    provider: str,
    request: Request,
    state: str = "",
    code: str = "",
    error: str = "",
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if provider not in social.PROVIDERS or not state or len(state) > 256:
        return _failure(request, "This sign-in link is invalid. Start sign-in again.")
    attempt = db.execute(
        delete(SocialAuthAttempt)
        .where(
            SocialAuthAttempt.token_hash == social.digest(state),
            SocialAuthAttempt.browser_hash == _browser(request),
            SocialAuthAttempt.provider == provider,
            SocialAuthAttempt.expires_at > datetime.now(UTC),
        )
        # Return values, not an ORM instance whose deleted row expires on commit.
        .returning(
            SocialAuthAttempt.user_id,
            SocialAuthAttempt.auth_version,
            SocialAuthAttempt.nonce,
            SocialAuthAttempt.verifier,
        )
    ).one_or_none()
    db.commit()  # A callback can be used once, including denied and failed attempts.
    if attempt is None:
        return _failure(
            request, "This sign-in has expired or belongs to another browser. Start again."
        )
    destination = "/settings/social" if attempt.user_id else "/auth/login"
    if error or not code or len(code) > 8192:
        return _failure(
            request, "Sign-in was cancelled or could not finish. You can try again.", destination
        )
    if (
        attempt.user_id
        and (not user or user.id != attempt.user_id or user.auth_version != attempt.auth_version)
    ) or (not attempt.user_id and user):
        return _failure(request, "Your account session changed. Start sign-in again.", destination)
    try:
        claims = social.verified_claims(provider, code, attempt.nonce, attempt.verifier)
        if attempt.user_id:
            social.link(db, user, provider, claims["subject"])
            db.commit()
            return redirect_feedback(
                request,
                "/settings/social",
                message(
                    "Sign-in connected",
                    f"You can now sign in with {social.PROVIDERS[provider]['label']}.",
                ),
            )
        identity = db.get(SocialIdentity, (provider, claims["subject"]))
        if identity:
            member = db.get(User, identity.user_id)
            if not social.eligible(member):
                raise social.SocialAuthError("This account cannot sign in.")
            _start_session(request, member, db)
            return redirect_feedback(
                request, "/", message("Signed in", "Welcome back to Nurse.ng.")
            )
        ticket = social.new_secret()
        db.add(
            SocialEnrollment(
                token_hash=social.digest(ticket),
                browser_hash=_browser(request),
                provider=provider,
                **claims,
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
            )
        )
        db.commit()
        request.session["social_enrollment"] = ticket
        return RedirectResponse(
            "/auth/social/complete",
            303,
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )
    except social.SocialAuthError as exc:
        db.rollback()
        return _failure(request, str(exc), destination)


def _enrollment(request, db):
    item = db.scalar(
        select(SocialEnrollment).where(
            SocialEnrollment.token_hash
            == social.digest(request.session.get("social_enrollment", "")),
            SocialEnrollment.browser_hash == _browser(request),
            SocialEnrollment.expires_at > datetime.now(UTC),
        )
    )
    if item is None:
        raise HTTPException(400, "This sign-in has expired. Start again with Google or LinkedIn.")
    return item


@router.get("/auth/social/complete")
def complete_form(request: Request, db: Session = Depends(get_db)):
    item = _enrollment(request, db)
    return render(
        request,
        "auth/social_complete.html",
        {
            "provider_name": social.PROVIDERS[item.provider]["label"],
            "email": item.email,
            "values": {"full_name": item.full_name, "mode": "existing"},
        },
    )


@router.post("/auth/social/complete")
def complete(
    request: Request,
    mode: str = Form("existing"),
    phone: str = Form(""),
    password: str = Form(""),
    full_name: str = Form(""),
    role: str = Form("nurse"),
    user: User | None = Depends(get_current_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    item = _enrollment(request, db)
    if user:
        raise HTTPException(400, "You are already signed in. Connect a provider from Settings.")
    limiter = _register_ip_limiter if mode == "new" else _login_ip_limiter
    if limiter.is_limited(_client_ip(request)):
        raise HTTPException(429, "Too many attempts. Please try again later.")
    limiter.record(_client_ip(request))
    try:
        if mode == "existing":
            member = authenticate_user(db, phone=phone, password=password)
            if member is None:
                raise AuthError("The phone number or password is incorrect.")
        elif mode == "new":
            member = register_user(
                db,
                phone=phone,
                password=password,
                full_name=full_name,
                email=item.email,
                account_type=role,
                commit=False,
            )
            member.email_verified_at = datetime.now(UTC)
        else:
            raise AuthError("Choose an existing or new account.")
        social.link(db, member, item.provider, item.subject)
        consumed = db.execute(
            delete(SocialEnrollment).where(
                SocialEnrollment.token_hash == item.token_hash,
                SocialEnrollment.expires_at > datetime.now(UTC),
            ),
            execution_options={"synchronize_session": False},
        )
        if consumed.rowcount != 1:
            raise AuthError("This sign-in was already completed. Please sign in again.")
        db.commit()
    except (AuthError, LoginLockedError, social.SocialAuthError) as exc:
        db.rollback()
        return render(
            request,
            "auth/social_complete.html",
            {
                "provider_name": social.PROVIDERS[item.provider]["label"],
                "email": item.email,
                "values": {"phone": phone, "full_name": full_name, "role": role, "mode": mode},
                "error": str(exc),
            },
            400,
        )
    _start_session(request, member, db)
    return redirect_feedback(
        request,
        "/welcome" if mode == "new" else "/",
        message(
            "Sign-in connected",
            "You can use this provider or your phone and password next time.",
        ),
    )


@router.get("/settings/social")
def settings_page(
    request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    linked = list(
        db.scalars(select(SocialIdentity.provider).where(SocialIdentity.user_id == user.id))
    )
    return render(request, "auth/social_settings.html", {"user": user, "linked": linked})


@router.post("/settings/social/{provider}/disconnect")
def disconnect(
    provider: str,
    request: Request,
    password: str = Form(""),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    if provider not in social.PROVIDERS:
        raise HTTPException(404)
    try:
        verify_current_password(db, user, password)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    db.execute(
        delete(SocialIdentity).where(
            SocialIdentity.user_id == user.id,
            SocialIdentity.provider == provider,
        )
    )
    db.commit()
    return redirect_feedback(
        request,
        "/settings/social",
        message(
            "Sign-in disconnected",
            "You can still sign in with your phone number and password.",
        ),
    )
