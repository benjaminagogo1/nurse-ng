from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.web.auth_routes import dashboard
from app.web.deps import get_current_user
from app.web.templating import render

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness probe. Deliberately touches no data."""
    return {"status": "ok"}


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots_txt() -> str:
    """Keep the invite-only pilot out of search indexes."""
    return "User-agent: *\nDisallow: /\n"


@router.get("/")
def home(
    request: Request,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    if user is not None:
        return dashboard(request, user, db)
    return render(request, "home.html", {"title": "Nurse.ng", "user": user})
