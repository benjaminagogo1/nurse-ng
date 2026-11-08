"""Learning, resources, and account settings."""

from fastapi import APIRouter, Depends, Form, Request, Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.services.account_mail import mail_available
from app.services.auth import AuthError, save_account_details
from app.web.deps import get_current_user, require_user, verify_csrf
from app.web.feedback import message, redirect_feedback, render_error
from app.web.templating import render

router = APIRouter()

LEARNING_RESOURCES = [
    {
        "title": "Learn with OpenWHO",
        "description": (
            "Explore the World Health Organization's learning resources for health workers."
        ),
        "category": "Clinical learning", "icon": "globe",
        "url": "https://openwho.org/", "label": "Explore OpenWHO",
    },
    {
        "title": "Grow your nursing perspective",
        "description": (
            "Discover nursing publications, policy resources, and professional development "
            "from the International Council of Nurses."
        ),
        "category": "Professional development", "icon": "book",
        "url": "https://www.icn.ch/", "label": "Visit the ICN",
    },
    {
        "title": "Stay connected to your profession",
        "description": (
            "Find official registration information and professional updates from the "
            "Nursing and Midwifery Council of Nigeria."
        ),
        "category": "Professional practice", "icon": "shield",
        "url": "https://www.nmcn.gov.ng/", "label": "Visit NMCN",
    },
    {
        "title": "Learn from your community",
        "description": (
            "Ask questions, exchange experiences, and build your confidence with fellow nurses."
        ),
        "category": "Peer learning", "icon": "users",
        "url": "/topics", "label": "Find a conversation",
    },
]


@router.get("/learning")
def learning(request: Request, user: User | None = Depends(get_current_user)) -> Response:
    return render(request, "pages/learning.html", {
        "title": "Learning", "user": user, "resources": LEARNING_RESOURCES,
    })


@router.get("/resources")
def resources(request: Request, user: User | None = Depends(get_current_user)) -> Response:
    return render(request, "pages/resources.html", {"title": "Resources", "user": user})


@router.get("/settings")
def settings_page(request: Request, user: User = Depends(require_user)) -> Response:
    return render(request, "pages/settings.html", {
        "title": "Account settings", "user": user,
        "values": {"full_name": user.full_name, "email": user.email or ""},
        "mail_available": mail_available(),
    })


@router.post("/settings")
def save_settings(
    request: Request, full_name: str = Form(""), email: str = Form(""),
    current_password: str = Form(""),
    user: User = Depends(require_user), _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
) -> Response:
    try:
        save_account_details(db, user, full_name=full_name, email=email,
                             current_password=current_password)
    except AuthError as exc:
        return render_error(request, "pages/settings.html", {
            "title": "Account settings", "user": user, "error": str(exc),
            "values": {"full_name": full_name, "email": email},
            "mail_available": mail_available(),
        }, message("Your details weren’t saved", str(exc), tone="error"))
    return redirect_feedback(request, "/settings", message(
        "Account details saved", "Your contact details are up to date."
    ))
