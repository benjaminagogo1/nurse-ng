"""Employer requests and staff decisions, with CSRF and separate authority checks."""

from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.employers import EmployerMembership, EmployerReviewEvent
from app.models.user import AccountType, User
from app.services.employers import EmployerError, memberships, request_membership, review_membership
from app.web.deps import require_staff, require_user, verify_csrf
from app.web.templating import render

router = APIRouter(tags=["employer approval"])


def _context(db, user, error=None, values=None):
    return {"user": user, "memberships": memberships(db, user), "error": error,
            "values": values or {"name": "", "website": "", "authority_details": ""}}


@router.get("/employers/organizations")
def organizations(request: Request, user: User = Depends(require_user),
                  db: Session = Depends(get_db)):
    if user.account_type != AccountType.EMPLOYER:
        raise HTTPException(status_code=403)
    return render(request, "employer/organizations.html", _context(db, user))


@router.post("/employers/organizations")
def request_organization(request: Request, name: str = Form(""), website: str = Form(""),
                         authority_details: str = Form(""), user: User = Depends(require_user),
                         _: None = Depends(verify_csrf), db: Session = Depends(get_db)):
    values = {"name": name, "website": website, "authority_details": authority_details}
    try:
        request_membership(db, user, **values)
    except EmployerError as exc:
        db.rollback()
        return render(request, "employer/organizations.html",
                      _context(db, user, str(exc), values), status_code=400)
    return RedirectResponse("/employers/organizations", status_code=303)


@router.get("/staff/employers")
def employer_queue(request: Request, user: User = Depends(require_staff),
                   db: Session = Depends(get_db)):
    return render(request, "employer/review.html", {
        "user": user, "memberships": list(db.scalars(select(EmployerMembership).order_by(
            EmployerMembership.created_at.desc()))),
        "events": list(db.scalars(select(EmployerReviewEvent).order_by(
            EmployerReviewEvent.created_at.desc()).limit(50))),
    })


@router.post("/staff/employers/{membership_id}")
def decide_employer(membership_id: UUID, request: Request, action: str = Form(""),
                    note: str = Form(""), identity_checked: str = Form(""),
                    authority_checked: str = Form(""), include_legacy: str = Form(""),
                    user: User = Depends(require_staff),
                    _: None = Depends(verify_csrf), db: Session = Depends(get_db)):
    member = db.get(EmployerMembership, membership_id)
    if member is None:
        raise HTTPException(status_code=404)
    try:
        review_membership(db, user, member, action=action, note=note,
                          identity_checked=identity_checked == "on",
                          authority_checked=authority_checked == "on",
                          include_legacy=include_legacy == "on")
    except EmployerError as exc:
        return render(request, "employer/review.html", {
            "user": user, "memberships": [member], "events": [], "error": str(exc),
        }, status_code=400)
    return RedirectResponse("/staff/employers", status_code=303)
