"""Integrated offline workspace and a neutral, credential-free navigation shell."""

import hashlib
from datetime import UTC, datetime
from hmac import compare_digest
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.db.session import get_db
from app.models.jobs import Job
from app.models.opportunities import SavedOpportunity
from app.models.profile import NurseProfile
from app.services import notifications, offline, offline_uploads
from app.services.jobs import job_card, list_open_jobs
from app.services.learning import MATERIALS
from app.services.member_interests import INTEREST_OPTIONS
from app.services.profiles import (
    PROFESSIONAL_STATUS_LABELS,
    SHAREABLE_FIELDS,
    discoverable_condition,
    public_profile_fields,
)
from app.web.deps import get_current_user
from app.web.jobs_routes import _job
from app.web.templating import csrf_token, render, templates

router = APIRouter(tags=["offline"])
STATIC = Path(__file__).resolve().parent.parent / "static"


def workspace_context():
    return {
        "values": dict.fromkeys((name for name, _ in SHAREABLE_FIELDS), ""),
        "status_options": list(PROFESSIONAL_STATUS_LABELS.items()),
        "interest_options": INTEREST_OPTIONS,
    }


@router.get("/offline")
def workspace(request: Request, user=Depends(get_current_user)):
    return render(
        request,
        "offline/index.html",
        {
            "user": user,
            "title": "Offline & sync",
            **workspace_context(),
        },
    )


@router.get("/offline-shell", include_in_schema=False)
def shell(request: Request):
    # The cached shell must never mint or embed a CSRF token.
    return templates.TemplateResponse(
        request=request,
        name="offline/index.html",
        context={
            "user": None,
            "title": "Offline & sync",
            "page": "offline",
            "csrf_token": "",
            "draft_scope": "",
            "draft_session_known": False,
            "offline_shell": True,
            **workspace_context(),
        },
        headers={"Cache-Control": "public, max-age=0, must-revalidate"},
    )


@router.get("/service-worker.js", include_in_schema=False)
def service_worker():
    return FileResponse(
        STATIC / "js/service-worker.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
    )


@router.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return JSONResponse(
        {
            "name": "Nurse.ng",
            "short_name": "Nurse.ng",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "background_color": "#f5f8f8",
            "theme_color": "#073c40",
            "icons": [
                {
                    "src": "/static/img/favicon.svg",
                    "sizes": "any",
                    "type": "image/svg+xml",
                    "purpose": "any",
                }
            ],
        },
        media_type="application/manifest+json",
    )


@router.get("/offline/ping", include_in_schema=False)
def ping():
    return JSONResponse({"online": True}, headers={"Cache-Control": "no-store"})


def _json(data, status=200):
    return JSONResponse(
        jsonable_encoder(data), status_code=status, headers={"Cache-Control": "no-store"}
    )


def member(user=Depends(get_current_user)):
    if user is None:
        raise HTTPException(401, "Sign in again before synchronizing.")
    return user


def scope(request, user):
    return hashlib.sha256(f"{user.id}:{csrf_token(request)}".encode()).hexdigest()


def verified_session(
    request: Request,
    user=Depends(member),
    token: str = Header("", alias="X-CSRF-Token"),
    owner: str = Header("", alias="X-Offline-Scope"),
):
    expected = request.session.get("csrf_token")
    if not expected or not compare_digest(expected, token):
        raise HTTPException(403, "Refresh your session before synchronizing.")
    if not compare_digest(scope(request, user), owner):
        raise HTTPException(401, "These changes belong to a different sign-in session.")
    return user


@router.get("/offline/session")
def session(request: Request, user=Depends(member)):
    return _json({"scope": scope(request, user), "csrf": csrf_token(request)})


def _record(kind, key, title, path, data):
    return {
        "kind": kind,
        "key": key,
        "title": title,
        "path": path,
        "data": data,
        "retrieved_at": datetime.now(UTC).isoformat(),
    }


def _job_record(db, user, job):
    return _record(
        "job",
        f"job:{job.id}",
        job.title,
        f"/jobs/{job.id}",
        {
            **job_card(job),
            "bookmark": offline.bookmark_snapshot(db, user, job.id),
        },
    )


@router.get("/offline/data")
def data(
    request: Request,
    path: str = Query(..., max_length=300),
    page: int = Query(1, ge=1, le=10000),
    user=Depends(member),
    db: Session = Depends(get_db),
):
    # Explicit selection and serializers; never cache whole pages or ORM dictionaries.
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise HTTPException(400, "Choose a Nurse.ng page.")
    rows = []
    if path in {"/profile", "/profile/edit"}:
        rows = [
            _record(
                "profile",
                "profile:self",
                "Your professional profile",
                "/profile/edit",
                offline.profile_snapshot(db, user),
            )
        ]
    elif path.startswith("/p/"):
        try:
            profile = db.scalar(
                select(NurseProfile).where(
                    NurseProfile.public_id == UUID(path.split("/")[-1]),
                    discoverable_condition(),
                )
            )
        except ValueError:
            profile = None
        if profile is None:
            raise HTTPException(404, "This profile is no longer public.")
        fields = public_profile_fields(db, profile)
        rows = [
            _record(
                "public-profile",
                f"profile:{profile.public_id}",
                fields.get("display_name", "Nurse.ng member"),
                path,
                fields,
            )
        ]
    elif path in {"/jobs", "/jobs/saved"}:
        if path == "/jobs":
            jobs = list_open_jobs(db, limit=25, offset=(page - 1) * 25)
        else:
            jobs = list(
                db.scalars(
                    select(Job)
                    .join(SavedOpportunity)
                    .where(
                        SavedOpportunity.user_id == user.id,
                    )
                    .order_by(Job.id)
                    .offset((page - 1) * 25)
                    .limit(25)
                )
            )
        for job in jobs:
            try:
                rows.append(_job_record(db, user, _job(db, job.id, user)))
            except HTTPException:
                rows.append(
                    _record(
                        "unavailable",
                        f"job:{job.id}",
                        "Unavailable opportunity",
                        f"/jobs/{job.id}",
                        {},
                    )
                )
    elif path.startswith("/jobs/"):
        try:
            job = _job(db, UUID(path.split("/")[-1]), user)
        except ValueError:
            raise HTTPException(404) from None
        rows = [_job_record(db, user, job)]
    elif path == "/notifications":
        notices, _ = notifications.inbox_page(db, user)
        for notice in notices:
            item = notifications.card(db, notice)
            rows.append(
                _record(
                    "notification",
                    f"notice:{notice.id}",
                    item["heading"],
                    item["path"],
                    {"description": item["description"], "read": notice.read_at is not None},
                )
            )
    elif path == "/learning" or path.startswith("/learning/materials/"):
        for name, item in MATERIALS.items():
            if path == "/learning" or path.endswith("/" + name):
                rows.append(
                    _record(
                        "learning",
                        f"learning:{name}",
                        item["title"],
                        f"/learning/materials/{name}",
                        item,
                    )
                )
    else:
        raise HTTPException(404, "This page needs a connection.")
    return _json({"records": rows, "scope": scope(request, user)})


@router.get("/learning/materials/{name}")
def material(name: str, request: Request, user=Depends(get_current_user)):
    if name not in MATERIALS:
        raise HTTPException(404)
    return render(request, "offline/material.html", {"user": user, "material": MATERIALS[name]})


class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: UUID
    kind: str
    payload: dict


@router.post("/offline/operations")
async def apply_operation(
    request: Request,
    user=Depends(verified_session),
    db: Session = Depends(get_db),
):
    body = await bounded_body(request, 128 * 1024)
    try:
        operation = Operation.model_validate_json(body)
    except ValidationError:
        raise HTTPException(400, "Invalid offline operation.") from None
    try:
        result = await run_in_threadpool(
            offline.synchronize,
            db,
            user,
            operation.operation_id,
            operation.kind,
            operation.payload,
            session_scope=scope(request, user),
        )
    except offline.SyncError as exc:
        response = _json(
            {
                "status": "conflict" if exc.status == 409 else "failed",
                "message": str(exc),
                "current": exc.current,
            },
            exc.status,
        )
        if exc.retry_after:
            response.headers["Retry-After"] = str(exc.retry_after)
        return response
    except (ValueError, TypeError, KeyError):
        db.rollback()
        return _json(
            {"status": "failed", "message": "Check these values before trying again."}, 400
        )
    return _json({"status": "confirmed", "result": result})


async def bounded_body(request, maximum):
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > maximum:
            raise HTTPException(413, "This upload or change exceeds its size limit.")
        body.extend(chunk)
    return bytes(body)


class UploadStart(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    size: int


def upload_response(action):
    try:
        return _json(action())
    except offline.SyncError as exc:
        return _json({"message": str(exc)}, exc.status)
    except OSError:
        return _json({"message": "Upload storage is unavailable. Try again later."}, 503)


@router.post("/offline/uploads/{upload_id}")
def begin_upload(
    upload_id: UUID,
    body: UploadStart,
    request: Request,
    user=Depends(verified_session),
    db: Session = Depends(get_db),
):
    return upload_response(
        lambda: offline_uploads.begin(
            db,
            user,
            upload_id,
            body.size,
            scope(request, user),
        )
    )


@router.put("/offline/uploads/{upload_id}")
async def append_upload(
    upload_id: UUID,
    request: Request,
    offset: int = Query(..., ge=0),
    user=Depends(verified_session),
    db: Session = Depends(get_db),
):
    body = await bounded_body(request, offline_uploads.CHUNK)
    return await run_in_threadpool(
        upload_response,
        lambda: offline_uploads.append(
            db,
            user,
            upload_id,
            scope(request, user),
            offset,
            body,
        ),
    )


@router.delete("/offline/uploads/{upload_id}")
def discard_upload(
    upload_id: UUID, request: Request, user=Depends(verified_session), db: Session = Depends(get_db)
):
    return upload_response(
        lambda: offline_uploads.discard(
            db,
            user,
            upload_id,
            scope(request, user),
        )
    )
