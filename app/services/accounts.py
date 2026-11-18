"""Account photos, verified email recovery and deletion with durable file cleanup."""

import hashlib
import re
import secrets
import uuid
import warnings
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from app.core.community_storage import community_media_path
from app.core.config import settings
from app.core.security import hash_password
from app.core.storage import evidence_path
from app.core.validators import normalize_phone
from app.models.account import AccountToken, FileDeletion
from app.models.community import CommunityMedia, CommunityPost
from app.models.profile import NurseProfile
from app.models.user import User
from app.models.verification import EvidenceDocument, VerificationCase
from app.services.account_mail import MailUnavailable, mail_available, send_account_mail
from app.services.auth import AuthError, LoginLockedError, authenticate_user, validate_password

TOKEN_ERROR = "This link is invalid or has expired. Please request a new one."


def now():
    return datetime.now(UTC)


def verify_current_password(db: Session, user: User, password: str) -> None:
    version = user.auth_version
    db.refresh(user)
    if user.auth_version != version:
        raise AuthError("Your session has changed. Sign in again before continuing.")
    if not password or len(password) > 128:
        raise AuthError("Enter your current password.")
    try:
        authenticated = authenticate_user(db, phone=user.phone, password=password)
    except LoginLockedError:
        raise AuthError("Too many unsuccessful attempts. Please try again later.") from None
    if authenticated is None or authenticated.id != user.id:
        raise AuthError("Your current password is incorrect.")


def request_account_email(
    db: Session, *, purpose: str, user: User | None = None, phone: str = "", dispatch=None
) -> bool:
    if purpose not in {"verify", "reset"}:
        raise ValueError("Unsupported account email purpose")
    if not mail_available():
        raise MailUnavailable("Email delivery is unavailable. Please try again later.")
    if purpose == "reset":
        user = db.scalar(select(User).where(User.phone == normalize_phone(phone)))
    if (
        user is None
        or not user.is_active
        or user.status != "active"
        or not user.email
        or (purpose == "reset" and user.email_verified_at is None)
    ):
        return False
    timestamp = now()
    # Persisted per-account cooldown prevents cross-worker request races and spam.
    changed = db.execute(
        update(User)
        .where(
            User.id == user.id,
            User.auth_version == user.auth_version,
            User.email == user.email,
            User.is_active.is_(True),
            User.status == "active",
            or_(
                User.account_mail_requested_at.is_(None),
                User.account_mail_requested_at <= timestamp - timedelta(seconds=60),
            ),
        )
        .values(account_mail_requested_at=timestamp)
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        db.rollback()
        return False
    db.execute(
        delete(AccountToken).where(
            AccountToken.user_id == user.id,
            AccountToken.purpose == purpose,
        )
    )
    token = secrets.token_urlsafe(32)
    credential = AccountToken(
        user_id=user.id,
        purpose=purpose,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        email=user.email,
        auth_version=user.auth_version,
        expires_at=timestamp
        + (timedelta(minutes=30) if purpose == "reset" else timedelta(hours=24)),
    )
    db.add(credential)
    recipient = user.email
    db.commit()
    try:
        (dispatch or send_account_mail)(recipient, purpose, token)
    except MailUnavailable:
        db.execute(delete(AccountToken).where(AccountToken.id == credential.id))
        db.commit()
        raise
    return True


def consume_account_token(db: Session, token: str, purpose: str, *, password: str = "") -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise AuthError(TOKEN_ERROR)
    if purpose == "reset":
        validate_password(password)
        new_hash = hash_password(password)
    timestamp = now()
    credential = db.scalar(
        select(AccountToken).where(
            AccountToken.token_hash == hashlib.sha256(token.encode()).hexdigest(),
            AccountToken.purpose == purpose,
            AccountToken.consumed_at.is_(None),
            AccountToken.expires_at > timestamp,
        )
    )
    if credential is None:
        raise AuthError(TOKEN_ERROR)
    taken = db.execute(
        update(AccountToken)
        .where(
            AccountToken.id == credential.id,
            AccountToken.consumed_at.is_(None),
            AccountToken.expires_at > timestamp,
        )
        .values(consumed_at=timestamp)
        .execution_options(synchronize_session=False)
    )
    if taken.rowcount != 1:
        db.rollback()
        raise AuthError(TOKEN_ERROR)
    statement = update(User).where(
        User.id == credential.user_id,
        User.email == credential.email,
        User.auth_version == credential.auth_version,
        User.is_active.is_(True),
        User.status == "active",
    )
    if purpose == "reset":
        statement = statement.where(User.email_verified_at.is_not(None)).values(
            hashed_password=new_hash,
            auth_version=User.auth_version + 1,
            failed_login_attempts=0,
            locked_until=None,
        )
    elif purpose == "verify":
        statement = statement.values(email_verified_at=timestamp)
    else:
        db.rollback()
        raise AuthError(TOKEN_ERROR)
    changed = db.execute(statement.execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        db.rollback()
        raise AuthError(TOKEN_ERROR)
    if purpose == "reset":
        db.execute(delete(AccountToken).where(AccountToken.user_id == credential.user_id))
    db.commit()
    db.expire_all()


def avatar_path(name: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", name):
        raise AuthError("Unknown photo.")
    root = Path(settings.avatar_dir).resolve()
    path = (root / name).resolve()
    if path.parent != root:
        raise AuthError("Unknown photo.")
    return path


def prepare_photo(data: bytes) -> bytes:
    if not data or len(data) > settings.avatar_max_bytes:
        raise AuthError("Choose a JPEG, PNG or WebP photo of at most 5 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if (
                    source.format not in {"JPEG", "PNG", "WEBP"}
                    or getattr(source, "n_frames", 1) != 1
                ):
                    raise AuthError("Choose a still JPEG, PNG or WebP photo.")
                if source.width * source.height > 16_000_000:
                    raise AuthError("Choose a photo smaller than 16 megapixels.")
                source.load()
                oriented = ImageOps.exif_transpose(source)
                resized = ImageOps.fit(oriented.convert("RGBA"), (512, 512))
                clean = Image.new("RGB", (512, 512), "white")
                clean.paste(resized, mask=resized.getchannel("A"))
                output = BytesIO()
                clean.save(output, format="JPEG", quality=85)
                return output.getvalue()
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise AuthError("This photo could not be read. Choose a valid JPEG, PNG or WebP.") from None


def queue_file_deletion(db: Session, kind: str, name: str) -> None:
    if name:
        db.add(FileDeletion(kind=kind, storage_name=name))


def cleanup_account_files(db: Session, *, limit: int = 100) -> dict:
    from app.core.message_storage import attachment_path
    removed = 0
    for item in list(
        db.scalars(select(FileDeletion).order_by(FileDeletion.created_at).limit(limit))
    ):
        try:
            resolver = {
                "photo": avatar_path,
                "community": community_media_path,
                "evidence": evidence_path,
                "message": attachment_path,
            }[item.kind]
            resolver(item.storage_name).unlink(missing_ok=True)
        except (OSError, ValueError, KeyError):
            continue
        db.delete(item)
        removed += 1
    db.commit()
    return {"removed": removed}


def set_photo(db: Session, user: User, *, data: bytes | None, public: bool = False) -> None:
    previous = user.photo_storage_name
    name = uuid.uuid4().hex if data is not None else ""
    if data is not None:
        encoded = prepare_photo(data)
        path = avatar_path(name)
        try:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            import os

            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(encoded)
        except OSError:
            path.unlink(missing_ok=True)
            raise AuthError("Your photo could not be saved. Please try again.") from None
    try:
        changed = db.execute(
            update(User)
            .where(
                User.id == user.id,
                User.auth_version == user.auth_version,
                User.photo_storage_name == previous,
                User.is_active.is_(True),
                User.status == "active",
            )
            .values(photo_storage_name=name, photo_public=bool(name and public))
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            raise AuthError("Your account changed. Reload the page before trying again.")
        queue_file_deletion(db, "photo", previous)
        db.commit()
    except Exception:
        db.rollback()
        if name:
            queue_file_deletion(db, "photo", name)
            db.commit()
            cleanup_account_files(db)
        raise
    db.refresh(user)
    cleanup_account_files(db)


def delete_account(db: Session, user: User, *, password: str) -> None:
    verify_current_password(db, user, password)
    # Lock the owner before enumerating files. Concurrent uploads must either
    # finish first or fail their owner update after this transaction deletes it.
    guarded = db.execute(
        update(User)
        .where(
            User.id == user.id,
            User.auth_version == user.auth_version,
            User.hashed_password == user.hashed_password,
            User.is_active.is_(True),
        )
        .values(is_active=False)
        .execution_options(synchronize_session=False)
    )
    if guarded.rowcount != 1:
        db.rollback()
        raise AuthError("Your account changed. Please sign in again.")
    queue_file_deletion(db, "photo", user.photo_storage_name)
    from app.models.messages import MessageAttachment
    for name in db.scalars(select(MessageAttachment.storage_name).where(
        (MessageAttachment.sender_id == user.id) | (MessageAttachment.recipient_id == user.id)
    )):
        queue_file_deletion(db, "message", name)
    for name in db.scalars(
        select(CommunityMedia.storage_name)
        .join(CommunityPost)
        .where(
            CommunityPost.author_id == user.id,
        )
    ):
        queue_file_deletion(db, "community", name)
    for name in db.scalars(
        select(EvidenceDocument.storage_name)
        .join(VerificationCase)
        .join(NurseProfile)
        .where(NurseProfile.user_id == user.id)
    ):
        queue_file_deletion(db, "evidence", name)
    db.flush()
    # Database FK cascades cover profiles, messages, relationships, applications,
    # owned jobs and conversations. Staff references to other records use SET NULL.
    db.execute(delete(User).where(User.id == user.id).execution_options(synchronize_session=False))
    db.commit()
    db.expunge_all()
    cleanup_account_files(db)
