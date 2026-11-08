"""Durable, leased video processing. Run with ``python -m app.cli reels-worker``."""

import logging
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.core.community_storage import (
    CommunityStorageError,
    _mp4_file_duration_seconds,
    community_media_path,
    delete_community_media,
)
from app.core.config import settings
from app.models.community import CommunityMedia, CommunityPost, ContentStatus, MediaKind
from app.models.reels import Reel
from app.models.user import User
from app.services.accounts import cleanup_account_files, queue_file_deletion

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 3


class ProcessingError(ValueError):
    pass


def ffmpeg_binary() -> str:
    if settings.reels_ffmpeg:
        return settings.reels_ffmpeg
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def _ffmpeg(arguments: list[str]) -> None:
    try:
        result = subprocess.run(
            [ffmpeg_binary(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
             "-max_alloc", "134217728", "-filter_threads", "1", *arguments],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, timeout=settings.reels_process_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise ProcessingError("Processing took too long. Try a shorter or smaller video.") from None
    except (OSError, RuntimeError):
        raise ProcessingError("Video processing is unavailable. Please try again later.") from None
    if result.returncode:
        # Decoder output can contain local paths and user-controlled metadata.
        # Store a useful, safe message instead of exposing raw stderr.
        raise ProcessingError("This video could not be decoded. Export it as MP4 and upload again.")


def transcode(source: Path, directory: Path, cover_seconds: int) -> list[tuple[str, Path, str]]:
    """Decode the upload into H.264/AAC MP4, a smaller MP4, and a JPEG cover.

    The input is explicitly treated as a local MP4, with external data references
    disabled. No network protocols or playlists are accepted by the decoder.
    """
    main, low, poster = (directory / name for name in ("main.mp4", "low.mp4", "cover.jpg"))
    max_seconds = settings.community_video_max_seconds
    input_args = ["-protocol_whitelist", "file", "-format_whitelist", "mov",
                  "-enable_drefs", "0", "-use_absolute_path", "0", "-threads", "2",
                  "-f", "mov", "-i", str(source)]
    _ffmpeg([
        *input_args, "-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "-1",
        "-map_chapters", "-1", "-t", str(max_seconds + 1),
        "-vf", "scale=w='min(720,iw)':h='min(1280,ih)':"
        "force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1,fps=30",
        "-c:v", "libx264", "-threads", "2", "-preset", "veryfast", "-crf", "25",
        "-maxrate", "1600k", "-bufsize", "3200k", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "96k", "-ac", "2", "-ar", "44100",
        "-movflags", "+faststart", "-fs", str(settings.community_video_max_bytes), str(main),
    ])
    try:
        duration = _mp4_file_duration_seconds(main, main.stat().st_size)
    except (CommunityStorageError, OSError):
        raise ProcessingError(
            "The processed video is incomplete. Please upload another MP4."
        ) from None
    # Validate the decoded timeline too; the uploaded MP4 header is not authoritative.
    if duration > max_seconds + 0.1:
        raise ProcessingError(f"Your video must be at most {max_seconds} seconds long.")
    _ffmpeg([
        "-threads", "2", "-i", str(main), "-map", "0:v:0", "-map", "0:a:0?",
        "-map_metadata", "-1", "-vf", "scale=w='min(360,iw)':h='min(640,ih)':"
        "force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1,fps=24",
        "-c:v", "libx264", "-threads", "2", "-preset", "veryfast", "-crf", "29",
        "-maxrate", "450k", "-bufsize", "900k", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "48k", "-ac", "1", "-movflags", "+faststart", str(low),
    ])
    _ffmpeg([
        "-threads", "2", "-ss", str(min(cover_seconds, max(0, duration - 0.1))),
        "-i", str(main), "-frames:v", "1", "-q:v", "3", str(poster),
    ])
    outputs = [(MediaKind.VIDEO, main, "video/mp4"),
               (MediaKind.REEL_LOW, low, "video/mp4"),
               (MediaKind.REEL_POSTER, poster, "image/jpeg")]
    if any(not path.is_file() or path.stat().st_size == 0 for _, path, _ in outputs):
        raise ProcessingError("A playback file could not be created. Please try again.")
    return outputs


def claim_next(db: Session) -> tuple[uuid.UUID, str] | None:
    now = datetime.now(UTC)
    available = or_(Reel.state == "queued", (Reel.state == "processing") &
                    (Reel.lease_until < now))
    # A killed worker does not leave an upload stuck forever, or retry endlessly.
    db.execute(update(Reel).where(available, Reel.attempts >= MAX_ATTEMPTS).values(
        state="failed", lease_token=None, lease_until=None,
        error="Processing could not finish after three attempts. Please upload a new video.",
    ))
    db.commit()
    ids = list(db.scalars(select(Reel.post_id).join(CommunityPost).where(
        available, Reel.attempts < MAX_ATTEMPTS,
        CommunityPost.status == ContentStatus.PROCESSING,
    ).order_by(Reel.created_at, Reel.post_id).limit(10)))
    for post_id in ids:
        token = uuid.uuid4().hex
        changed = db.execute(update(Reel).where(
            Reel.post_id == post_id, available, Reel.attempts < MAX_ATTEMPTS,
        ).values(
            state="processing", attempts=Reel.attempts + 1, lease_token=token,
            lease_until=now + timedelta(seconds=settings.reels_process_timeout_seconds * 3 + 90),
            error="",
        ))
        db.commit()
        if changed.rowcount == 1:
            return post_id, token
    return None


def run_next(db: Session) -> tuple[str, str] | None:
    claimed = claim_next(db)
    if claimed is None:
        return None
    post_id, token = claimed
    reel = db.get(Reel, post_id)
    source = db.scalar(select(CommunityMedia).where(
        CommunityMedia.post_id == post_id, CommunityMedia.kind == MediaKind.REEL_SOURCE,
    ))
    if reel is None or source is None:
        _fail(db, post_id, token, "The uploaded video is no longer available.")
        return str(post_id), "failed"
    source_name, source_size, source_id = source.storage_name, source.size_bytes, source.id
    cover_seconds, author_id = reel.cover_seconds, reel.post.author_id
    # No database transaction or row lock is held during expensive decoding.
    db.commit()
    stored_names: list[str] = []
    try:
        source_path = community_media_path(source_name)
        with tempfile.TemporaryDirectory(prefix="nurse-reel-") as temporary:
            outputs = transcode(source_path, Path(temporary), cover_seconds)
            duration = _mp4_file_duration_seconds(outputs[0][1], outputs[0][1].stat().st_size)
            total = sum(path.stat().st_size for _, path, _ in outputs)
            # Match account deletion's lock order. If the creator disappeared,
            # no derived file can be attached after their deletion transaction.
            account = db.scalar(select(User).where(
                User.id == author_id, User.is_active.is_(True),
            ).with_for_update().execution_options(populate_existing=True))
            if account is None:
                db.rollback()
                return str(post_id), "cancelled"
            changed = db.execute(update(Reel).where(
                Reel.post_id == post_id, Reel.lease_token == token, Reel.state == "processing",
                Reel.post_id.in_(select(CommunityPost.id).where(
                    CommunityPost.status == ContentStatus.PROCESSING,
                )),
            ).values(state="ready", lease_token=None, lease_until=None, error=""))
            if changed.rowcount != 1:
                db.rollback()
                return str(post_id), "cancelled"
            retained = max(0, account.community_storage_bytes - source_size) + total
            if retained > settings.community_storage_quota_bytes:
                raise ProcessingError(
                    "Your media storage is full. Remove an older upload and retry."
                )
            import shutil

            for position, (kind, path, content_type) in enumerate(outputs):
                name = uuid.uuid4().hex
                stored_names.append(name)
                shutil.copyfile(path, community_media_path(name))
                db.add(CommunityMedia(
                    post_id=post_id, kind=kind, storage_name=name, content_type=content_type,
                    size_bytes=path.stat().st_size, duration_seconds=round(duration)
                    if content_type == "video/mp4" else None, position=position,
                ))
            account.community_storage_bytes = retained
            source_record = db.get(CommunityMedia, source_id)
            db.delete(source_record)
            queue_file_deletion(db, "community", source_name)
            db.execute(update(CommunityPost).where(CommunityPost.id == post_id).values(
                status=ContentStatus.PUBLISHED, published_at=datetime.now(UTC),
            ))
            db.commit()
            stored_names.clear()
        cleanup_account_files(db)
        logger.info("reel=%s state=ready attempts=%s", post_id, reel.attempts)
        return str(post_id), "ready"
    except Exception as exc:
        db.rollback()
        for name in stored_names:
            delete_community_media(name)
        error = str(exc) if isinstance(exc, ProcessingError) else (
            "Processing could not finish. Please try again later."
        )
        _fail(db, post_id, token, error)
        logger.warning("reel=%s state=failed error_type=%s", post_id, type(exc).__name__)
        return str(post_id), "failed"


def _fail(db: Session, post_id: uuid.UUID, token: str, error: str) -> None:
    db.execute(update(Reel).where(Reel.post_id == post_id, Reel.lease_token == token).values(
        state="failed", error=error, lease_token=None, lease_until=None,
    ))
    db.commit()
