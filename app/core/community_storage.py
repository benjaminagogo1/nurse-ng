"""Controlled local storage for public community images and videos.

This store is intentionally separate from private document-review evidence.
Files have opaque names and are exposed only through a route that confirms the
owning post is still published. Production should serve processed media from a
dedicated object-storage origin rather than the application process.
"""

import math
import re
import uuid
from pathlib import Path

from app.core.config import settings
from app.models.community import MediaKind

IMAGE_CONTENT_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
VIDEO_CONTENT_TYPES = frozenset({"video/mp4"})
_STORAGE_NAME_RE = re.compile(r"^[0-9a-f]{32}$")


class CommunityStorageError(ValueError):
    """A community upload cannot be accepted safely."""


def _root() -> Path:
    return Path(settings.community_media_dir)


def _max_megabytes(value: int) -> int:
    return max(1, value // (1024 * 1024))


def _image_content_type(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _boxes(data: bytes, start: int, end: int):
    """Yield valid ISO Base Media File Format boxes within one container."""
    position = start
    while position + 8 <= end:
        size = int.from_bytes(data[position : position + 4], "big")
        box_type = data[position + 4 : position + 8]
        header_size = 8
        if size == 1:
            if position + 16 > end:
                raise CommunityStorageError("The MP4 video is incomplete.")
            size = int.from_bytes(data[position + 8 : position + 16], "big")
            header_size = 16
        elif size == 0:
            size = end - position
        if size < header_size or position + size > end:
            raise CommunityStorageError("The MP4 video is incomplete.")
        yield box_type, position + header_size, position + size
        position += size


def mp4_duration_seconds(data: bytes) -> float:
    """Read duration from an MP4 movie header without trusting form metadata."""
    top_level = list(_boxes(data, 0, len(data)))
    if not any(box_type == b"ftyp" for box_type, _, _ in top_level):
        raise CommunityStorageError("Upload an MP4 video.")

    for box_type, payload_start, box_end in top_level:
        if box_type != b"moov":
            continue
        for child_type, child_start, child_end in _boxes(
            data, payload_start, box_end
        ):
            if child_type != b"mvhd":
                continue
            payload = data[child_start:child_end]
            if len(payload) < 20:
                break
            version = payload[0]
            if version == 0:
                timescale_offset, duration_offset, duration_size = 12, 16, 4
            elif version == 1:
                timescale_offset, duration_offset, duration_size = 20, 24, 8
            else:
                break
            required = duration_offset + duration_size
            if len(payload) < required:
                break
            timescale = int.from_bytes(
                payload[timescale_offset : timescale_offset + 4], "big"
            )
            duration = int.from_bytes(
                payload[duration_offset:required], "big"
            )
            if timescale > 0 and duration > 0:
                return duration / timescale
            break
    raise CommunityStorageError("The MP4 duration could not be read.")


def inspect_media(data: bytes, kind: str) -> tuple[str, int | None]:
    """Validate bytes and return their content type and duration, if video."""
    if not data:
        raise CommunityStorageError("Choose a file to upload.")

    if kind == MediaKind.IMAGE.value:
        if len(data) > settings.community_image_max_bytes:
            maximum = _max_megabytes(settings.community_image_max_bytes)
            raise CommunityStorageError(f"Each image must be at most {maximum} MB.")
        content_type = _image_content_type(data)
        if content_type not in IMAGE_CONTENT_TYPES:
            raise CommunityStorageError("Upload a JPEG, PNG, or WebP image.")
        return content_type, None

    if kind == MediaKind.VIDEO.value:
        if len(data) > settings.community_video_max_bytes:
            maximum = _max_megabytes(settings.community_video_max_bytes)
            raise CommunityStorageError(f"The video must be at most {maximum} MB.")
        duration = mp4_duration_seconds(data)
        if duration > settings.community_video_max_seconds:
            minutes = max(1, settings.community_video_max_seconds // 60)
            raise CommunityStorageError(
                f"The uploaded video must be at most {minutes} minutes long."
            )
        return "video/mp4", math.ceil(duration)

    raise CommunityStorageError("Unknown community media type.")


def save_community_media(
    data: bytes,
    kind: str,
) -> tuple[str, str, int, int | None]:
    """Validate/store bytes and return name, type, size, and duration."""
    content_type, duration = inspect_media(data, kind)
    storage_name = uuid.uuid4().hex
    root = _root()
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError:
        raise CommunityStorageError("The media file could not be stored.") from None

    temporary = root / f".{storage_name}.tmp"
    try:
        temporary.write_bytes(data)
        temporary.chmod(0o600)
        temporary.replace(root / storage_name)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise CommunityStorageError("The media file could not be stored.") from None
    return storage_name, content_type, len(data), duration


def community_media_path(storage_name: str) -> Path:
    """Resolve an opaque media name without allowing path traversal."""
    if not _STORAGE_NAME_RE.fullmatch(storage_name):
        raise CommunityStorageError("Unknown media file.")
    root = _root().resolve()
    path = (root / storage_name).resolve()
    if path.parent != root:
        raise CommunityStorageError("Unknown media file.")
    return path


def delete_community_media(storage_name: str) -> None:
    """Clean up a file after a rejected multi-file post or failed commit."""
    try:
        community_media_path(storage_name).unlink(missing_ok=True)
    except CommunityStorageError:
        return
