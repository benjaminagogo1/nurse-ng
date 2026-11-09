"""Authorization-code sign-in with fixed OIDC providers and signed ID tokens."""

import base64
import hashlib
import json
import secrets
from hmac import compare_digest
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import jwt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.models.social_auth import SocialIdentity
from app.models.user import User

PROVIDERS = {
    "google": {
        "label": "Google",
        "issuer": ["https://accounts.google.com", "accounts.google.com"],
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "jwks": "https://www.googleapis.com/oauth2/v3/certs",
    },
    "linkedin": {
        "label": "LinkedIn",
        "issuer": "https://www.linkedin.com/oauth",
        "authorize": "https://www.linkedin.com/oauth/v2/authorization",
        "token": "https://www.linkedin.com/oauth/v2/accessToken",
        "jwks": "https://www.linkedin.com/oauth/openid/jwks",
    },
}


class SocialAuthError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def callback_url(provider):
    return settings.public_base_url.rstrip("/") + f"/auth/social/{provider}/callback"


def credentials(provider):
    if provider not in PROVIDERS:
        raise SocialAuthError("Choose Google or LinkedIn to continue.")
    client_id = getattr(settings, f"{provider}_client_id")
    secret = getattr(settings, f"{provider}_client_secret")
    parsed = urlsplit(settings.public_base_url)
    if not client_id or not secret or not parsed.hostname:
        raise SocialAuthError(
            f"{PROVIDERS[provider]['label']} sign-in is not connected yet. "
            "You can use your phone number and password to continue.",
        )
    if settings.environment == "production" and (
        parsed.scheme != "https" or settings.session_same_site == "strict"
    ):
        raise SocialAuthError("Social sign-in configuration needs attention. Use phone sign-in.")
    return client_id, secret


def authorization_url(provider, state, nonce, verifier):
    client_id, _ = credentials(provider)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    return (
        PROVIDERS[provider]["authorize"]
        + "?"
        + urlencode(
            {
                "client_id": client_id,
                "redirect_uri": callback_url(provider),
                "response_type": "code",
                "scope": "openid profile email",
                "state": state,
                "nonce": nonce,
                "code_challenge": challenge.decode(),
                "code_challenge_method": "S256",
            }
        )
    )


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def exchange_token(provider, code, verifier):
    client_id, secret = credentials(provider)
    body = urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": callback_url(provider),
            "client_id": client_id,
            "client_secret": secret,
            "code_verifier": verifier,
        }
    ).encode()
    request = Request(
        PROVIDERS[provider]["token"],
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with build_opener(NoRedirect).open(request, timeout=15) as response:
        data = response.read(128 * 1024 + 1)
    if len(data) > 128 * 1024:
        raise SocialAuthError(
            "The sign-in provider returned an invalid response. Please try again."
        )
    return json.loads(data)


def verified_claims(provider, code, nonce, verifier):
    client_id, _ = credentials(provider)
    try:
        tokens = exchange_token(provider, code, verifier)
        token = tokens["id_token"]
        key = jwt.PyJWKClient(PROVIDERS[provider]["jwks"], timeout=10).get_signing_key_from_jwt(
            token
        )
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            audience=client_id,
            issuer=PROVIDERS[provider]["issuer"],
            leeway=30,
            options={"require": ["exp", "iat", "iss", "aud", "sub", "nonce"]},
        )
        if not compare_digest(str(claims["nonce"]), nonce):
            raise ValueError("nonce")
        if claims.get("azp", client_id) != client_id:
            raise ValueError("authorized party")
        if isinstance(claims["aud"], list) and len(claims["aud"]) > 1 and "azp" not in claims:
            raise ValueError("authorized party required")
        subject, email = claims["sub"], claims.get("email", "")
        if not isinstance(subject, str) or not 1 <= len(subject) <= 255:
            raise ValueError("subject")
        if claims.get("email_verified") is not True or not isinstance(email, str):
            raise ValueError("verified email required")
        if len(email) > 254 or "@" not in email or any(c.isspace() for c in email):
            raise ValueError("email")
        return {"subject": subject, "email": email, "full_name": str(claims.get("name", ""))[:120]}
    except Exception as exc:
        # Never display provider responses, tokens, or client credentials.
        raise SocialAuthError(
            "We couldn’t verify this sign-in. Use an account with a verified email address "
            "and try again, or use phone sign-in.",
        ) from exc


def eligible(user):
    return user is not None and user.is_active and user.status == "active"


def linked_user(db, provider, subject):
    identity = db.get(SocialIdentity, (provider, subject))
    return db.get(User, identity.user_id) if identity else None


def link(db, user, provider, subject):
    if not eligible(user):
        raise SocialAuthError("This account cannot sign in. Please use another account.")
    identity = db.get(SocialIdentity, (provider, subject))
    if identity:
        if identity.user_id != user.id:
            raise SocialAuthError("This provider account is already connected to another member.")
        return
    existing = db.scalar(
        select(SocialIdentity).where(
            SocialIdentity.user_id == user.id,
            SocialIdentity.provider == provider,
        )
    )
    if existing:
        raise SocialAuthError("Disconnect your existing provider account in Settings first.")
    db.add(SocialIdentity(provider=provider, subject=subject, user_id=user.id))
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise SocialAuthError(
            "This provider account is already connected. Please sign in again."
        ) from None


def new_secret():
    return secrets.token_urlsafe(32)
