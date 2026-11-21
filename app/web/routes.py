from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.web.auth_routes import dashboard
from app.web.deps import get_current_user
from app.web.templating import render

router = APIRouter()


@router.get("/healthz")
@router.head("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    """GET/HEAD liveness probe for health monitors. Deliberately touches no data."""
    return {"status": "ok"}


@router.get("/readyz")
def readyz(db: Session = Depends(get_db)):
    """Report service readiness without exposing queue contents or configuration."""
    from app.services.worker_health import readiness

    try:
        ready = readiness(db)
    except SQLAlchemyError:
        ready = False
    return JSONResponse({"status": "ready" if ready else "unavailable"},
                        status_code=200 if ready else 503,
                        headers={"Cache-Control": "no-store"})


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
