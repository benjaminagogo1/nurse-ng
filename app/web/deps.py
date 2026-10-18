"""Request dependencies: current user and CSRF validation."""

import uuid
from hmac import compare_digest

from fastapi import Depends, Form, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User, UserStatus


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User | None:
    """Return the signed-in user, or None for an anonymous request."""
    raw_id = request.session.get("user_id")
    if not isinstance(raw_id, str):
        return None

    try:
        user_id = uuid.UUID(raw_id)
    except ValueError:
        return None

    user = db.get(User, user_id)
    if user is None or not user.is_active or user.status != UserStatus.ACTIVE:
        return None
    return user


def require_user(user: User | None = Depends(get_current_user)) -> User:
    """Redirect anonymous requests to the sign-in page."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/auth/login"},
        )
    return user


def verify_csrf(request: Request, csrf_token: str = Form("")) -> None:
    """Reject state-changing requests without the session's CSRF token."""
    expected = request.session.get("csrf_token")
    if not isinstance(expected, str) or not compare_digest(expected, csrf_token):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or missing CSRF token.",
        )
