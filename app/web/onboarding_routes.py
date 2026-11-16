"""Optional, resumable welcome flow using the existing profile privacy controls."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.services.community_growth import community_summaries, suggested_communities
from app.services.member_discovery import (
    finish_onboarding,
    suggested_opportunities,
    suggested_people,
)
from app.services.member_interests import INTEREST_OPTIONS, interest_values
from app.services.profiles import ProfileError, get_profile_for_user, get_visibility_map
from app.web.deps import require_user, verify_csrf
from app.web.feedback import message, redirect_feedback
from app.web.templating import render

router = APIRouter(prefix="/welcome", tags=["onboarding"])


def welcome_context(db, user):
    profile = get_profile_for_user(db, user.id)
    return {
        "title": "Make Nurse.ng yours",
        "page": "welcome",
        "user": user,
        "profile": profile,
        "interest_options": INTEREST_OPTIONS,
        "selected_interests": interest_values(profile.interests) if profile else [],
        "location": profile.location if profile else "",
        "visibility": get_visibility_map(db, profile) if profile else {},
    }


@router.get("")
def welcome(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    return render(request, "onboarding/welcome.html", welcome_context(db, user))


@router.post("")
def save_welcome(
    request: Request,
    interests: list[str] = Form([]),
    location: str = Form(""),
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    try:
        finish_onboarding(db, user, interests=", ".join(interests), location=location)
    except ProfileError as exc:
        return render(
            request,
            "onboarding/welcome.html",
            {
                **welcome_context(db, user),
                "selected_interests": interests,
                "location": location,
                "error": str(exc),
            },
            status_code=400,
        )
    return redirect_feedback(
        request,
        "/welcome/discover",
        message(
            "Your interests are saved",
            "Explore people and opportunities below. You can change your choices anytime.",
        ),
    )


@router.post("/skip")
def skip_welcome(
    request: Request,
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    user.onboarding_completed_at = datetime.now(UTC)
    db.commit()
    return redirect_feedback(
        request,
        "/welcome/discover",
        message(
            "You're ready to explore",
            "You can add interests later from your dashboard.",
        ),
    )


@router.get("/discover")
def discover(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    jobs, personalised_jobs = suggested_opportunities(db, user, limit=6)
    topics = suggested_communities(db, user)
    return render(
        request,
        "onboarding/discover.html",
        {
            "title": "Your next connections",
            "user": user,
            "page": "welcome",
            "cards": suggested_people(db, user, limit=6),
            "jobs": jobs,
            "personalised_jobs": personalised_jobs,
            "profile": get_profile_for_user(db, user.id),
            "topics": topics,
            "community_summaries": community_summaries(db, topics, user),
        },
    )
