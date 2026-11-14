"""Authenticated likes on public posts and ready Reels."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.services.engagement import set_like
from app.services.reels import public_reel
from app.web.deps import require_user, verify_csrf

router = APIRouter(tags=["likes"])


@router.post("/posts/{post_id}/like")
@router.post("/reels/{post_id}/like")
def like_post(post_id: UUID, request: Request, liked: Literal["yes", "no"] = Form(...),
              user: User = Depends(require_user), _: None = Depends(verify_csrf),
              db: Session = Depends(get_db)):
    reel = request.url.path.startswith("/reels/")
    if reel and not public_reel(db, post_id):
        raise HTTPException(404, detail="This reel is no longer available.")
    try:
        result = set_like(db, user, post_id, liked=liked == "yes")
    except LookupError as exc:
        raise HTTPException(404, detail=str(exc)) from None
    except PermissionError as exc:
        raise HTTPException(403, detail=str(exc)) from None
    if request.headers.get("x-post-like") == "1":
        return JSONResponse(result, headers={"Cache-Control": "no-store"})
    return RedirectResponse(f"/{'reels' if reel else 'posts'}/{post_id}", status_code=303)
