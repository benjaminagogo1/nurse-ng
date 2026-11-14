"""Search existing members and explicitly manage their administrator access."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.models.staff import StaffRoleEvent
from app.models.user import User
from app.services.auth import AuthError
from app.services.staff import change_admin
from app.web.deps import require_staff, verify_csrf
from app.web.feedback import message, redirect_feedback
from app.web.templating import render

router = APIRouter(prefix="/staff/admins", tags=["administrators"])


def _context(db, user, query="", error=None, target=None):
    matches = []
    if query:
        conditions = [column.icontains(query, autoescape=True)
                      for column in (User.full_name, User.email, User.phone)]
        try:
            conditions.append(User.id == UUID(query))
        except ValueError:
            pass
        matches = list(db.scalars(select(User).where(or_(*conditions))
                                  .order_by(User.full_name, User.id).limit(20)))
    elif target:
        matches = [target]
    return {
        "title": "Administrators", "page": "staff-admins", "user": user,
        "query": query, "matches": matches, "error": error,
        "administrators": list(db.scalars(select(User).where(User.is_staff.is_(True))
                                         .order_by(User.full_name, User.id))),
        "events": list(db.scalars(select(StaffRoleEvent).options(
            selectinload(StaffRoleEvent.actor), selectinload(StaffRoleEvent.target)
        ).order_by(StaffRoleEvent.created_at.desc(), StaffRoleEvent.id.desc()).limit(20))),
    }


@router.get("")
def administrators(request: Request, q: str = Query("", max_length=120),
                   user: User = Depends(require_staff), db: Session = Depends(get_db)):
    return render(request, "staff/admins.html", _context(db, user, q.strip()),
                  headers={"Cache-Control": "no-store"})


@router.post("/{user_id}")
def update_administrator(user_id: UUID, request: Request,
                         action: Literal["grant", "revoke"] = Form(...),
                         current_password: str = Form(""), expected_version: int = Form(...),
                         user: User = Depends(require_staff), _: None = Depends(verify_csrf),
                         db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404)
    try:
        change_admin(db, user, target, enabled=action == "grant",
                     current_password=current_password, expected_version=expected_version)
    except AuthError as exc:
        context = _context(db, user, error=str(exc), target=target)
        return render(request, "staff/admins.html", context,
                      status_code=400, headers={"Cache-Control": "no-store"})
    return redirect_feedback(request, "/staff/admins", message(
        "Administrator added" if action == "grant" else "Administrator access removed",
        "The account must sign in again to use its updated permissions.",
    ))
