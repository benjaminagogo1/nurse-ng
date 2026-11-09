"""Conflict-aware changes and receipts committed in the existing database."""

import hashlib
import hmac
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.jobs import Job
from app.models.offline import OfflineOperation
from app.models.opportunities import SavedOpportunity
from app.models.profile import NurseProfile
from app.models.user import User
from app.services.jobs import open_job_condition
from app.services.profiles import (
    SHAREABLE_FIELD_NAMES,
    get_profile_for_user,
    validate_profile_input,
)


class SyncError(ValueError):
    def __init__(self, message, *, status=400, current=None, retry_after=0):
        super().__init__(message)
        self.status = status
        self.current = current
        self.retry_after = retry_after


def profile_snapshot(db, user):
    profile = get_profile_for_user(db, user.id)
    values = (
        {field: getattr(profile, field) for field in SHAREABLE_FIELD_NAMES}
        if profile
        else {field: "" for field in SHAREABLE_FIELD_NAMES}
    )
    if not profile:
        values.update(
            display_name=user.full_name, professional_status="student", years_experience=None
        )
    return {"exists": profile is not None, "values": values}


def bookmark_snapshot(db, user, job_id):
    item = db.get(SavedOpportunity, (user.id, job_id))
    return {"saved": item is not None, "remind": bool(item and item.remind)}


def _profile(db, user, payload):
    if set(payload) != {"base", "values"} or not isinstance(payload["base"], dict):
        raise SyncError("Reload the profile before saving offline changes.")
    original, desired = payload["base"].get("values"), payload["values"]
    if not isinstance(original, dict) or not isinstance(desired, dict):
        raise SyncError("Invalid profile fields.")
    if set(original) != SHAREABLE_FIELD_NAMES or set(desired) != SHAREABLE_FIELD_NAMES:
        raise SyncError("Only professional profile fields can be synchronized.")

    # Match HTML form numbers/empty fields to the equivalent stored representation.
    def text(value):
        return "" if value is None else str(value)

    if any(
        not isinstance(value, (str, int, type(None)))
        for value in [*original.values(), *desired.values()]
    ):
        raise SyncError("Invalid profile values.")
    current = profile_snapshot(db, user)
    if current["exists"] != payload["base"].get("exists"):
        raise SyncError(
            "Your profile was created on another device. Review it before saving.",
            status=409,
            current=current,
        )
    changed = {field for field in desired if text(desired[field]) != text(original[field])}
    conflicts = {
        field
        for field in changed
        if text(current["values"][field])
        not in {
            text(original[field]),
            text(desired[field]),
        }
    }
    if conflicts:
        raise SyncError(
            "These fields changed elsewhere: " + ", ".join(sorted(conflicts)),
            status=409,
            current=current,
        )
    merged = {**current["values"], **{field: desired[field] for field in changed}}
    values = validate_profile_input(**{field: text(value) for field, value in merged.items()})
    profile = get_profile_for_user(db, user.id)
    if profile is None:
        profile = NurseProfile(user_id=user.id, status="draft", discoverable=False, **values)
        db.add(profile)
        db.flush()
    elif changed:
        result = db.execute(
            update(NurseProfile)
            .where(
                NurseProfile.id == profile.id,
                *(getattr(NurseProfile, field) == current["values"][field] for field in changed),
            )
            .values(**{field: values[field] for field in changed}, updated_at=datetime.now(UTC)),
            execution_options={"synchronize_session": False},
        )
        if result.rowcount != 1:
            db.expire_all()
            raise SyncError(
                "Your profile changed during synchronization. Review the current values.",
                status=409,
                current=profile_snapshot(db, user),
            )
    return {"path": "/profile", "message": "Profile changes synchronized."}


def _bookmark(db, user, payload):
    if set(payload) != {"job_id", "base", "saved", "remind"}:
        raise SyncError("Invalid bookmark change.")
    if type(payload["saved"]) is not bool or type(payload["remind"]) is not bool:
        raise SyncError("Invalid bookmark choices.")
    job_id = UUID(str(payload["job_id"]))
    current = bookmark_snapshot(db, user, job_id)
    desired = {
        "saved": payload["saved"],
        "remind": payload["remind"] if payload["saved"] else False,
    }
    if current == desired:
        return {"path": "/jobs/saved", "message": "Bookmark already synchronized."}
    if current != payload["base"]:
        raise SyncError(
            "This bookmark changed on another device. Review your choice.",
            status=409,
            current=current,
        )
    if desired["saved"]:
        if not db.scalar(select(Job.id).where(Job.id == job_id, open_job_condition())):
            raise SyncError("This opportunity is no longer available to save.", status=404)
        if current["saved"]:
            changed = db.execute(
                update(SavedOpportunity)
                .where(
                    SavedOpportunity.user_id == user.id,
                    SavedOpportunity.job_id == job_id,
                    SavedOpportunity.remind == current["remind"],
                )
                .values(remind=desired["remind"], updated_at=datetime.now(UTC))
            )
            if changed.rowcount != 1:
                raise SyncError("The bookmark changed during synchronization.", status=409)
        else:
            db.add(SavedOpportunity(user_id=user.id, job_id=job_id, remind=desired["remind"]))
            db.flush()
    else:
        changed = db.execute(
            delete(SavedOpportunity).where(
                SavedOpportunity.user_id == user.id,
                SavedOpportunity.job_id == job_id,
                SavedOpportunity.remind == current["remind"],
            )
        )
        if changed.rowcount != 1:
            raise SyncError("The bookmark changed during synchronization.", status=409)
    return {"path": "/jobs/saved", "message": "Bookmark synchronized."}


HANDLERS = {"profile": _profile, "bookmark": _bookmark}


def synchronize(db, user, operation_id, kind, payload, *, session_scope=""):
    if kind == "reel":
        from app.services.offline_uploads import remove_chunks, upload_lock

        upload_id = UUID(str(payload["file_id"]))
        with upload_lock(user.id, upload_id):
            result = _synchronize(db, user, operation_id, kind, payload, session_scope)
            try:
                remove_chunks(user.id, upload_id)
            except OSError:
                pass  # The existing media cleanup command retries completed staging cleanup.
            return result
    return _synchronize(db, user, operation_id, kind, payload, session_scope)


def _synchronize(db, user, operation_id, kind, payload, session_scope):
    from app.services.offline_content import HANDLERS as CONTENT_HANDLERS
    from app.services.offline_uploads import publish

    handlers = {**HANDLERS, **CONTENT_HANDLERS, "reel": publish}
    if kind not in handlers:
        raise SyncError("This action requires an online form.")
    fingerprint = hmac.new(
        settings.secret_key.encode(),
        json.dumps(
            {"kind": kind, "payload": payload},
            sort_keys=True,
            separators=(",", ":"),
        ).encode(),
        hashlib.sha256,
    ).hexdigest()
    user_id, auth_version = user.id, user.auth_version

    def previous_result():
        previous = db.get(OfflineOperation, (user_id, operation_id))
        if previous is None:
            return None
        if not hmac.compare_digest(previous.payload_hash, fingerprint):
            raise SyncError("This operation reference was used for different changes.", status=409)
        return previous.result

    previous = previous_result()
    if previous is not None:
        return previous
    receipt = OfflineOperation(
        user_id=user_id, operation_id=operation_id, kind=kind, payload_hash=fingerprint, result={}
    )
    db.add(receipt)
    try:
        # This write also starts a real SQLite transaction before any savepoint.
        db.flush()
    except IntegrityError:
        db.rollback()
        previous = previous_result()
        if previous is not None:
            return previous
        raise
    try:
        # Existing services may commit. Their commits release only a savepoint;
        # the domain change and receipt remain in the outer transaction together.
        with Session(bind=db.connection(), join_transaction_mode="create_savepoint") as work:
            work.info["offline_scope"] = session_scope
            actor = work.get(User, user_id)
            if (
                not actor
                or not actor.is_active
                or actor.status != "active"
                or actor.auth_version != auth_version
            ):
                raise SyncError("Sign in again before synchronizing.", status=401)
            result = handlers[kind](work, actor, payload)
            work.commit()
        receipt.result = result
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        raise SyncError(
            "This record changed during synchronization. Refresh and review it.", status=409
        ) from None
    except Exception:
        db.rollback()
        raise
