"""Private staging, bounded upload usage, authorized file access and cleanup.

Files stage privately, validate/scan, then attach to an authorized message.
Ownership, per-file/window quotas and release state are checked server-side.
Maintenance handles unfinished uploads and disk remnants; an opaque filename
by itself never authorizes download. See docs/PRIVATE_MESSAGE_FILES.md.
"""

import re
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update

from app.core.config import settings
from app.core.message_storage import (
    AttachmentError,
    attachment_path,
    fingerprint,
    message_root,
    store_attachment,
)
from app.models.community import Connection
from app.models.messages import DirectMessage, MessageAttachment, MessageUploadUsage
from app.models.user import User, UserStatus
from app.services.community import connection_pair_key
from app.services.messages import can_message


def utc(value):
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def lock_participants(db, user, recipient, *, auth_version=None):
    """Lock active accounts in stable order, check auth_version and recheck the mutual
    connection.
    """
    expected_version = user.auth_version if auth_version is None else auth_version
    for identifier in sorted([user.id, recipient.id], key=str):
        statement = update(User).where(
            User.id == identifier, User.is_active.is_(True), User.status == UserStatus.ACTIVE
        )
        if identifier == user.id:
            statement = statement.where(User.auth_version == expected_version)
        # A harmless owner update also obtains SQLite's writer reservation; on
        # PostgreSQL, acquiring both owners in order avoids opposite-send deadlocks.
        changed = db.execute(
            statement.values(updated_at=User.updated_at).execution_options(
                synchronize_session=False
            )
        )
        if changed.rowcount != 1:
            raise AttachmentError("This conversation is no longer available.")
    db.expire_all()
    connection = db.scalar(
        select(Connection)
        .where(Connection.pair_key == connection_pair_key(user.id, recipient.id))
        .with_for_update()
    )
    if not connection or not can_message(db, user, recipient):
        raise AttachmentError("This conversation is no longer available.")


def upload_key(value):
    """Normalize a client-generated UUID upload identity or reject a malformed retry
    reference.
    """
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise AttachmentError("Reopen this conversation before attaching a file.") from None


def existing_upload(db, user, recipient, key, name, size, digest):
    """Resolve an owner retry key only if recipient, filename, size and digest still match."""
    item = db.scalar(
        select(MessageAttachment).where(
            MessageAttachment.sender_id == user.id, MessageAttachment.upload_key == key
        )
    )
    if item and (
        item.recipient_id != recipient.id
        or item.filename != name
        or item.size_bytes != size
        or item.sha256 != digest
    ):
        raise AttachmentError("This file reference was already used. Choose the file again.")
    return item


def upload_attachment(db, user, recipient, source, filename, key, *, auth_version=None):
    """Validate/store a private connection file, reserve quota and persist owner-bound retry
    state.
    """
    expected_version = user.auth_version if auth_version is None else auth_version
    if not can_message(db, user, recipient):
        raise AttachmentError("This conversation is no longer available.")
    key = upload_key(key)
    name, size, digest = fingerprint(source, filename)
    old = existing_upload(db, user, recipient, key, name, size, digest)
    if old:
        lock_participants(db, user, recipient, auth_version=expected_version)
        old = existing_upload(db, user, recipient, key, name, size, digest)
        if not old or not attachment_path(old.storage_name).is_file():
            raise AttachmentError("This file is no longer available. Choose it again.")
        db.commit()
        return old
    saved = store_attachment(source, filename)
    retained = False
    try:
        lock_participants(db, user, recipient, auth_version=expected_version)
        old = existing_upload(db, user, recipient, key, name, size, digest)
        if old:
            db.rollback()
            return old
        pending = (
            db.scalar(
                select(func.count())
                .select_from(MessageAttachment)
                .where(
                    MessageAttachment.sender_id == user.id, MessageAttachment.message_id.is_(None)
                )
            )
            or 0
        )
        if pending >= 20:
            raise AttachmentError(
                "Send or remove some of your unfinished files before attaching more."
            )
        used = (
            db.scalar(
                select(func.sum(MessageAttachment.size_bytes)).where(
                    MessageAttachment.sender_id == user.id
                )
            )
            or 0
        )
        if used + size > settings.message_storage_quota_bytes:
            raise AttachmentError("Your file storage is full. Please try a smaller file.")
        now = datetime.now(UTC)
        usage = db.get(MessageUploadUsage, user.id)
        if usage is None:
            usage = MessageUploadUsage(user_id=user.id, window_started_at=now, size_bytes=0)
            db.add(usage)
        elif utc(usage.window_started_at) <= now - timedelta(days=1):
            usage.window_started_at, usage.size_bytes = now, 0
        if usage.size_bytes + size > settings.message_upload_window_bytes:
            raise AttachmentError(
                "You have reached your file upload allowance for today. Please try again later."
            )
        usage.size_bytes += size
        item = MessageAttachment(
            sender_id=user.id,
            recipient_id=recipient.id,
            upload_key=key,
            storage_name=saved.storage_name,
            filename=saved.filename,
            content_type=saved.content_type,
            kind=saved.kind,
            size_bytes=saved.size_bytes,
            sha256=saved.sha256,
            scanned_at=now,
        )
        db.add(item)
        db.commit()
        retained = True
        return item
    except Exception:
        db.rollback()
        raise
    finally:
        if not retained:
            try:
                attachment_path(saved.storage_name).unlink(missing_ok=True)
            except OSError:
                from app.services.accounts import queue_file_deletion

                queue_file_deletion(db, "message", saved.storage_name)
                db.commit()


def resolve_attachments(db, user, recipient, identifiers):
    """Validate owned, recipient-bound, available files before binding them to a sent
    message.
    """
    if len(identifiers) > settings.message_attachment_max_files or len(set(identifiers)) != len(
        identifiers
    ):
        raise AttachmentError(
            f"Choose up to {settings.message_attachment_max_files} different files."
        )
    rows = []
    now = datetime.now(UTC)
    for identifier in identifiers:
        item = db.scalar(
            select(MessageAttachment).where(MessageAttachment.id == identifier).with_for_update()
        )
        if (
            not item
            or item.sender_id != user.id
            or item.recipient_id != recipient.id
            or item.message_id
            or utc(item.created_at) <= now - timedelta(days=1)
        ):
            raise AttachmentError("An attached file is no longer available. Choose it again.")
        if not attachment_path(item.storage_name).is_file():
            raise AttachmentError("An attached file is unavailable. Choose it again.")
        rows.append(item)
    if sum(item.size_bytes for item in rows) > settings.message_attachment_total_bytes:
        limit_mb = settings.message_attachment_total_bytes // (1024 * 1024)
        raise AttachmentError(f"Keep the files in one message below {limit_mb} MB in total.")
    return rows


def attachment_data(item):
    """Expose safe attachment presentation metadata, not a filesystem path."""
    size = item.size_bytes
    label = (
        f"{size / (1024 * 1024):.1f} MB"
        if size >= 1024 * 1024
        else f"{max(1, (size + 1023) // 1024)} KB"
    )
    return {
        "id": str(item.id),
        "name": item.filename,
        "kind": item.kind,
        "content_type": item.content_type,
        "size": size,
        "size_label": label,
        "url": f"/messages/files/{item.id}",
        "download_url": f"/messages/files/{item.id}?download=1",
    }


def accessible_attachment(db, user, identifier):
    """Check current participant/connection and staging/message ownership before download.
    """
    item = db.get(MessageAttachment, identifier)
    if not item or user.id not in {item.sender_id, item.recipient_id}:
        return None
    if not item.message_id and (
        user.id != item.sender_id or utc(item.created_at) <= datetime.now(UTC) - timedelta(days=1)
    ):
        return None
    other = db.get(User, item.recipient_id if user.id == item.sender_id else item.sender_id)
    if not other or not can_message(db, user, other):
        return None
    if item.message_id:
        message = db.get(DirectMessage, item.message_id)
        if (
            not message
            or message.sender_id != item.sender_id
            or message.recipient_id != item.recipient_id
        ):
            return None
    return item


def discard_attachment(db, user, identifier):
    """Remove only the owner's unfinished attachment; sent files use message lifecycle
    cleanup.
    """
    from app.services.accounts import cleanup_account_files, queue_file_deletion

    item = db.scalar(
        select(MessageAttachment)
        .where(MessageAttachment.id == identifier, MessageAttachment.sender_id == user.id)
        .with_for_update()
    )
    if not item:
        return
    if item.message_id:
        raise AttachmentError("A sent file cannot be removed from this draft.")
    queue_file_deletion(db, "message", item.storage_name)
    db.delete(item)
    db.commit()
    cleanup_account_files(db)


def maintain_message_files(db, *, dry_run=False, now=None):
    """Reconcile expired staging and orphan disk files; dry_run reports without deleting."""
    from app.services.accounts import cleanup_account_files, queue_file_deletion

    now = now or datetime.now(UTC)
    stale = list(
        db.scalars(
            select(MessageAttachment)
            .where(
                MessageAttachment.message_id.is_(None),
                MessageAttachment.created_at < now - timedelta(days=1),
            )
            .limit(100)
            .with_for_update()
        )
    )
    for item in stale:
        if not dry_run:
            queue_file_deletion(db, "message", item.storage_name)
            db.delete(item)
    if not dry_run:
        db.commit()
        cleanup_account_files(db)
    names = set(db.scalars(select(MessageAttachment.storage_name)))
    root = message_root()
    orphaned = 0
    if root.is_dir():
        for path in root.iterdir():
            if (
                not path.is_symlink()
                and path.is_file()
                and path.name not in names
                and (
                    re.fullmatch(r"[0-9a-f]{32}", path.name) or path.name.startswith(".quarantine-")
                )
                and path.stat().st_mtime < (now - timedelta(days=1)).timestamp()
            ):
                orphaned += 1
                if not dry_run:
                    path.unlink(missing_ok=True)
    return {"expired": len(stale), "orphaned": orphaned}
