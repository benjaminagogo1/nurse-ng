"""Controlled local storage for public community images and videos.

Uploads are streamed to an opaque temporary file, validated and optionally
scanned, then atomically renamed. Production should replace this local store
with a dedicated media-processing and object-storage pipeline.
"""

import logging
import math
import re
import shlex
import shutil
import subprocess
import uuid
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

from app.core.config import settings
from app.models.community import MediaKind

IMAGE_CONTENT_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
VIDEO_CONTENT_TYPES = frozenset({"video/mp4"})
_STORAGE_NAME_RE = re.compile(r"^[0-9a-f]{32}$")
_TEMPORARY_NAME_RE = re.compile(r"^\.[0-9a-f]{32}\.tmp$")
logger = logging.getLogger(__name__)


class CommunityStorageError(ValueError):
    """A community upload cannot be accepted safely."""


def community_media_root() -> Path:
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
    """Yield valid ISO Base Media File Format boxes from in-memory data."""
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


def _duration_from_movie_header(payload: bytes) -> float | None:
    if len(payload) < 20:
        return None
    version = payload[0]
    if version == 0:
        timescale_offset, duration_offset, duration_size = 12, 16, 4
    elif version == 1:
        timescale_offset, duration_offset, duration_size = 20, 24, 8
    else:
        return None
    required = duration_offset + duration_size
    if len(payload) < required:
        return None
    timescale = int.from_bytes(payload[timescale_offset : timescale_offset + 4], "big")
    duration = int.from_bytes(payload[duration_offset:required], "big")
    if timescale <= 0 or duration <= 0:
        return None
    return duration / timescale


def mp4_duration_seconds(data: bytes) -> float:
    """Read duration from an MP4 movie header without trusting form metadata."""
    top_level = list(_boxes(data, 0, len(data)))
    if not any(box_type == b"ftyp" for box_type, _, _ in top_level):
        raise CommunityStorageError("Upload an MP4 video.")

    for box_type, payload_start, box_end in top_level:
        if box_type != b"moov":
            continue
        for child_type, child_start, child_end in _boxes(data, payload_start, box_end):
            if child_type != b"mvhd":
                continue
            duration = _duration_from_movie_header(data[child_start:child_end])
            if duration is not None:
                return duration
    raise CommunityStorageError("The MP4 duration could not be read.")


def _file_boxes(file: BinaryIO, start: int, end: int):
    """Yield box offsets without loading MP4 payloads into memory."""
    position = start
    while position + 8 <= end:
        file.seek(position)
        header = file.read(8)
        if len(header) != 8:
            raise CommunityStorageError("The MP4 video is incomplete.")
        size = int.from_bytes(header[:4], "big")
        box_type = header[4:8]
        header_size = 8
        if size == 1:
            extended = file.read(8)
            if len(extended) != 8:
                raise CommunityStorageError("The MP4 video is incomplete.")
            size = int.from_bytes(extended, "big")
            header_size = 16
        elif size == 0:
            size = end - position
        if size < header_size or position + size > end:
            raise CommunityStorageError("The MP4 video is incomplete.")
        yield box_type, position + header_size, position + size
        position += size


def _mp4_file_duration_seconds(path: Path, size_bytes: int) -> float:
    with path.open("rb") as file:
        top_level = list(_file_boxes(file, 0, size_bytes))
        if not any(box_type == b"ftyp" for box_type, _, _ in top_level):
            raise CommunityStorageError("Upload an MP4 video.")
        for box_type, payload_start, box_end in top_level:
            if box_type != b"moov":
                continue
            for child_type, child_start, child_end in _file_boxes(
                file, payload_start, box_end
            ):
                if child_type != b"mvhd":
                    continue
                file.seek(child_start)
                payload = file.read(min(child_end - child_start, 40))
                duration = _duration_from_movie_header(payload)
                if duration is not None:
                    return duration
    raise CommunityStorageError("The MP4 duration could not be read.")


def inspect_media(data: bytes, kind: str) -> tuple[str, int | None]:
    """Validate in-memory media. Retained for focused service/unit callers."""
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


def _inspect_stored_media(path: Path, kind: str, size_bytes: int) -> tuple[str, int | None]:
    if size_bytes == 0:
        raise CommunityStorageError("Choose a file to upload.")
    if kind == MediaKind.IMAGE.value:
        with path.open("rb") as file:
            content_type = _image_content_type(file.read(12))
        if content_type not in IMAGE_CONTENT_TYPES:
            raise CommunityStorageError("Upload a JPEG, PNG, or WebP image.")
        return content_type, None
    if kind == MediaKind.VIDEO.value:
        duration = _mp4_file_duration_seconds(path, size_bytes)
        if duration > settings.community_video_max_seconds:
            minutes = max(1, settings.community_video_max_seconds // 60)
            raise CommunityStorageError(
                f"The uploaded video must be at most {minutes} minutes long."
            )
        return "video/mp4", math.ceil(duration)
    raise CommunityStorageError("Unknown community media type.")


def _maximum_bytes(kind: str) -> int:
    if kind == MediaKind.IMAGE.value:
        return settings.community_image_max_bytes
    if kind == MediaKind.VIDEO.value:
        return settings.community_video_max_bytes
    raise CommunityStorageError("Unknown community media type.")


def _scan_media(path: Path) -> None:
    mode = settings.community_malware_scan_mode
    if mode == "disabled":
        return
    command = shlex.split(settings.community_malware_scan_command)
    executable = shutil.which(command[0]) if command else None
    if executable is None:
        if mode == "required":
            raise CommunityStorageError("Media scanning is temporarily unavailable.")
        logger.warning("ClamAV is unavailable; optional community scan skipped")
        return
    try:
        result = subprocess.run(
            [executable, *command[1:], "--no-summary", str(path)],
            capture_output=True,
            check=False,
            timeout=settings.community_malware_scan_timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired):
        if mode == "required":
            raise CommunityStorageError("Media scanning is temporarily unavailable.") from None
        logger.warning("ClamAV failed; optional community scan skipped", exc_info=True)
        return
    if result.returncode == 1:
        raise CommunityStorageError("The upload was rejected by the malware scanner.")
    if result.returncode != 0:
        if mode == "required":
            raise CommunityStorageError("Media scanning is temporarily unavailable.")
        logger.warning(
            "ClamAV returned %s; optional community scan skipped",
            result.returncode,
        )


def save_community_media(
    source: BinaryIO | bytes,
    kind: str,
) -> tuple[str, str, int, int | None]:
    """Stream, validate, scan, and store one upload."""
    maximum = _maximum_bytes(kind)
    if isinstance(source, bytes):
        source = BytesIO(source)
    try:
        source.seek(0)
    except (AttributeError, OSError):
        pass

    storage_name = uuid.uuid4().hex
    root = community_media_root()
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError:
        raise CommunityStorageError("The media file could not be stored.") from None

    temporary = root / f".{storage_name}.tmp"
    size_bytes = 0
    chunk_size = max(1, settings.community_upload_chunk_bytes)
    try:
        with temporary.open("xb") as destination:
            temporary.chmod(0o600)
            while chunk := source.read(chunk_size):
                size_bytes += len(chunk)
                if size_bytes > maximum:
                    maximum_mb = _max_megabytes(maximum)
                    label = "Each image" if kind == MediaKind.IMAGE.value else "The video"
                    raise CommunityStorageError(
                        f"{label} must be at most {maximum_mb} MB."
                    )
                destination.write(chunk)
        content_type, duration = _inspect_stored_media(temporary, kind, size_bytes)
        _scan_media(temporary)
        temporary.replace(root / storage_name)
    except CommunityStorageError:
        temporary.unlink(missing_ok=True)
        raise
    except OSError:
        temporary.unlink(missing_ok=True)
        raise CommunityStorageError("The media file could not be stored.") from None
    return storage_name, content_type, size_bytes, duration


def community_media_path(storage_name: str) -> Path:
    """Resolve an opaque media name without allowing path traversal."""
    if not _STORAGE_NAME_RE.fullmatch(storage_name):
        raise CommunityStorageError("Unknown media file.")
    root = community_media_root().resolve()
    path = (root / storage_name).resolve()
    if path.parent != root:
        raise CommunityStorageError("Unknown media file.")
    return path


def delete_community_media(storage_name: str) -> bool:
    """Delete one opaque media file, returning whether no file remains."""
    try:
        community_media_path(storage_name).unlink(missing_ok=True)
    except (CommunityStorageError, OSError):
        logger.warning("Could not remove community media %s", storage_name, exc_info=True)
        return False
    return True


def cleanup_orphan_community_media(
    referenced_names: set[str],
    *,
    dry_run: bool = False,
) -> list[str]:
    """Remove recognised temporary/orphan files and return their names."""
    root = community_media_root()
    if not root.is_dir():
        return []
    removed: list[str] = []
    for path in root.iterdir():
        if not path.is_file():
            continue
        is_temporary = _TEMPORARY_NAME_RE.fullmatch(path.name) is not None
        is_orphan = (
            _STORAGE_NAME_RE.fullmatch(path.name) is not None
            and path.name not in referenced_names
        )
        if not is_temporary and not is_orphan:
            continue
        removed.append(path.name)
        if not dry_run:
            try:
                path.unlink()
            except OSError:
                logger.warning("Could not remove orphan media %s", path, exc_info=True)
    return removed
