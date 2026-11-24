"""Bounded resumable staging on the application's existing private local media volume.

Byte ranges, session scope, ownership and expiry protect resumable staging.
Publication delegates to the regular Reel pipeline; receiving all chunks is
not successful public publication. Receipts recover lost responses.
"""

import fcntl
import hashlib
import hmac
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select

from app.core.config import settings
from app.models.offline_upload import OfflineUpload
from app.services.community import CommunityUpload
from app.services.offline import SyncError
from app.services.offline_content import fields, limit
from app.services.reels import create_reel

CHUNK = 1024 * 1024
MAX_ACTIVE = 2
MAX_STAGING = 2 * 1024 * 1024 * 1024


def root():
    return Path(settings.community_media_dir) / ".offline"


def directory(user_id, upload_id):
    return root() / user_id.hex / upload_id.hex


@contextmanager
def lock_file(path):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with os.fdopen(os.open(path, os.O_CREAT | os.O_RDWR, 0o600), "a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def upload_lock(user_id, upload_id):
    return lock_file(directory(user_id, upload_id) / ".lock")


def _expired(row):
    timestamp = row.expires_at
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp <= datetime.now(UTC)


def _owned(db, user, upload_id, scope):
    row = db.get(OfflineUpload, (user.id, upload_id), populate_existing=True)
    if row is None or not hmac.compare_digest(row.session_scope, scope):
        raise SyncError("This upload is not available in this sign-in session.", status=404)
    if not row.result and _expired(row):
        raise SyncError("This unfinished upload expired. Save a new Reel draft.", status=410)
    return row


def status(row):
    return {
        "received": row.received,
        "size": row.size,
        "chunk": CHUNK,
        "complete": bool(row.result),
    }


def begin(db, user, upload_id, size, scope):
    if type(size) is not int or not 0 < size <= min(
        settings.community_video_max_bytes, 100 * CHUNK
    ):
        raise SyncError("Choose a video within the offline upload size limit.", status=413)
    with lock_file(root() / ".allocation.lock"):
        row = db.get(OfflineUpload, (user.id, upload_id), populate_existing=True)
        if row:
            row = _owned(db, user, upload_id, scope)
            if row.size != size:
                raise SyncError("This upload reference belongs to a different file.", status=409)
            return status(row)
        active = select(OfflineUpload).where(OfflineUpload.publication_hash.is_(None))
        count = db.scalar(
            select(func.count()).select_from(
                active.where(OfflineUpload.user_id == user.id).subquery()
            )
        )
        total = db.scalar(
            select(func.coalesce(func.sum(OfflineUpload.size), 0)).where(
                OfflineUpload.publication_hash.is_(None)
            )
        )
        if count >= MAX_ACTIVE:
            raise SyncError(
                "Finish or discard an existing upload before starting another.", status=409
            )
        if total + size > MAX_STAGING:
            raise SyncError("Upload storage is temporarily full. Please try later.", status=503)
        row = OfflineUpload(
            user_id=user.id,
            upload_id=upload_id,
            session_scope=scope,
            size=size,
            received=0,
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        db.add(row)
        db.commit()
        return status(row)


def append(db, user, upload_id, scope, offset, body):
    with upload_lock(user.id, upload_id):
        row = _owned(db, user, upload_id, scope)
        if row.result:
            return status(row)
        if offset < 0 or offset % CHUNK or offset > row.received:
            raise SyncError(
                "The upload position changed. Resume from the server position.", status=409
            )
        if len(body) != min(CHUNK, row.size - offset) or not body:
            raise SyncError("This upload chunk is incomplete. Retry it.", status=400)
        path = directory(user.id, upload_id) / str(offset)
        if path.exists():
            if not hmac.compare_digest(
                hashlib.sha256(path.read_bytes()).digest(), hashlib.sha256(body).digest()
            ):
                raise SyncError("This chunk reference contains different data.", status=409)
        else:
            if offset != row.received:
                raise SyncError("An earlier upload chunk is missing. Save a new draft.", status=409)
            temporary = path.with_suffix(".tmp")
            with os.fdopen(
                os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600), "wb"
            ) as file:
                file.write(body)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, path)
        row.received = max(row.received, offset + len(body))
        db.commit()
        return status(row)


def publish(db, user, payload):
    fields(
        payload,
        "topic_id body category audience cover_seconds consent upload_key "
        "file_id file_size captions",
    )
    if payload["consent"] is not True:
        raise SyncError("Confirm public publication before queuing this Reel.")
    upload_id = UUID(payload["file_id"])
    row = _owned(db, user, upload_id, db.info.get("offline_scope", ""))
    fingerprint = hmac.new(
        settings.secret_key.encode(), json.dumps(payload, sort_keys=True).encode(), hashlib.sha256
    ).hexdigest()
    if row.result:
        if not hmac.compare_digest(row.publication_hash, fingerprint):
            raise SyncError("This video was already submitted with different details.", status=409)
        return row.result
    if row.size != payload["file_size"] or row.received != row.size:
        raise SyncError("The video upload is incomplete. Resume it before publishing.", status=409)
    limit(user, "post")
    with tempfile.TemporaryFile() as assembled:
        for offset in range(0, row.size, CHUNK):
            path = directory(user.id, upload_id) / str(offset)
            if not path.exists() or path.stat().st_size != min(CHUNK, row.size - offset):
                raise SyncError("An upload chunk is missing. Save a new Reel draft.", status=409)
            assembled.write(path.read_bytes())
        assembled.seek(0)
        reel = create_reel(
            db,
            user,
            topic_id=UUID(payload["topic_id"]),
            body=payload["body"],
            video=CommunityUpload(assembled, "offline.mp4"),
            category=payload["category"],
            audience=payload["audience"],
            upload_key=payload["upload_key"],
            cover_seconds=payload["cover_seconds"],
            captions=payload["captions"].encode(),
        )
    result = {
        "path": f"/reels/{reel.post_id}/status",
        "id": str(reel.post_id),
        "message": "Video received. Publication awaits processing and checks.",
    }
    row.publication_hash, row.result = fingerprint, result
    db.flush()
    return result


def remove_chunks(user_id, upload_id):
    path = directory(user_id, upload_id)
    if path.exists():
        for file in path.iterdir():
            if file.name != ".lock" and file.is_file():
                file.unlink(missing_ok=True)


def discard(db, user, upload_id, scope):
    with upload_lock(user.id, upload_id):
        row = db.get(OfflineUpload, (user.id, upload_id), populate_existing=True)
        if row and not hmac.compare_digest(row.session_scope, scope):
            raise SyncError("This upload belongs to a different sign-in session.", status=404)
        if row and row.result:
            return {"complete": True}  # Publication requires its existing removal workflow.
        if row:
            db.delete(row)
            db.commit()
        remove_chunks(user.id, upload_id)
        return {"discarded": True}


def cleanup(db):
    """Called by the existing media cleanup command; completed receipts remain durable."""
    removed = 0
    if not root().exists():
        return removed
    for account in root().iterdir():
        if not account.is_dir():
            continue
        for path in account.iterdir():
            if not path.is_dir():
                continue
            try:
                user_id, upload_id = UUID(account.name), UUID(path.name)
            except ValueError:
                continue
            with upload_lock(user_id, upload_id):
                row = db.get(OfflineUpload, (user_id, upload_id), populate_existing=True)
                if row is None or row.result or _expired(row):
                    remove_chunks(user_id, upload_id)
                    if row and not row.result:
                        db.delete(row)
                        db.commit()
                    removed += 1
    # Reservations can exist before the first chunk created its directory.
    for row in db.scalars(
        select(OfflineUpload).where(
            OfflineUpload.publication_hash.is_(None),
            OfflineUpload.expires_at <= datetime.now(UTC),
        )
    ).all():
        with upload_lock(row.user_id, row.upload_id):
            remove_chunks(row.user_id, row.upload_id)
            db.delete(row)
            db.commit()
    return removed
