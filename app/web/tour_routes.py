"""Authenticated, CSRF-protected guided-tour state. No public user lookup."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.services import tours
from app.web.deps import require_user, verify_csrf

router = APIRouter(prefix="/tour", tags=["tour"])
NO_STORE = {"Cache-Control": "no-store"}


@router.get("")
def tour_state(user: User = Depends(require_user), db: Session = Depends(get_db)):
    return JSONResponse(tours.snapshot(db, user), headers=NO_STORE)


@router.post("")
def change_tour(
    request: Request,
    action: Annotated[
        Literal["start", "next", "previous", "skip", "finish", "unavailable"], Form()
    ],
    revision: Annotated[int, Form(ge=0)],
    run_id: Annotated[UUID | None, Form()] = None,
    direction: Annotated[Literal["next", "previous"], Form()] = "next",
    user: User = Depends(require_user),
    _: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    try:
        result = tours.transition(
            db, user, action=action, revision=revision, run_id=run_id, direction=direction,
        )
    except tours.TourConflict as exc:
        db.refresh(user)
        return JSONResponse(
            {**tours.snapshot(db, user), "message": str(exc)},
            status_code=409, headers=NO_STORE,
        )
    except SQLAlchemyError:
        db.rollback()
        return JSONResponse(
            {"message": "Your progress could not be saved. Check your connection and try again."},
            status_code=503, headers=NO_STORE,
        )
    request.session.pop("tour_invitation", None)
    return JSONResponse(result, headers=NO_STORE)
