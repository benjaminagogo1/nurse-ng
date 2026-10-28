"""Private evidence storage on the local filesystem.

Files are written under ``settings.evidence_dir`` with opaque names and are
never placed in the static tree. The only read path is the authenticated
reviewer route. Content is validated by magic bytes, not by the client's
declared type or filename (DECISIONS L48).

This is a development and pilot store. Before production it must move to
private object storage with encryption, malware scanning, and a retention job.
"""

import hashlib
import re
import uuid
from pathlib import Path

from app.core.config import settings

ALLOWED_CONTENT_TYPES = frozenset({"image/jpeg", "image/png", "application/pdf"})
CONTENT_TYPE_SUFFIX = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "application/pdf": ".pdf",
}
_STORAGE_NAME_RE = re.compile(r"^[0-9a-f]{32}$")


class EvidenceStorageError(ValueError):
    """An uploaded file cannot be accepted."""


def _root() -> Path:
    return Path(settings.evidence_dir)


def _max_megabytes() -> int:
    return max(1, settings.evidence_max_bytes // (1024 * 1024))


def sniff_content_type(data: bytes) -> str | None:
    """Return the content type implied by the leading bytes, or None."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def save_evidence(data: bytes) -> tuple[str, str, int, str]:
    """Validate and store ``data``.

    Returns ``(storage_name, content_type, size_bytes, sha256)``. Raises
    ``EvidenceStorageError`` for empty, oversized, or unsupported content.
    """
    if not data:
        raise EvidenceStorageError("Choose a file to upload.")
    if len(data) > settings.evidence_max_bytes:
        raise EvidenceStorageError(f"Each file must be at most {_max_megabytes()} MB.")

    content_type = sniff_content_type(data)
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise EvidenceStorageError("Upload a JPEG, PNG, or PDF file.")

    storage_name = uuid.uuid4().hex
    root = _root()
    # The directory and files are private to the service account. ``mkdir``
    # does not tighten an existing directory, so deployment must check it.
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError:
        raise EvidenceStorageError("The file could not be stored.") from None
    temporary = root / f".{storage_name}.tmp"
    try:
        temporary.write_bytes(data)
        temporary.chmod(0o600)
        temporary.replace(root / storage_name)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise EvidenceStorageError("The file could not be stored.") from None

    digest = hashlib.sha256(data).hexdigest()
    return storage_name, content_type, len(data), digest


def evidence_path(storage_name: str) -> Path:
    """Resolve a stored evidence file, rejecting anything but an opaque name."""
    if not _STORAGE_NAME_RE.fullmatch(storage_name):
        raise EvidenceStorageError("Unknown evidence file.")
    root = _root().resolve()
    path = (root / storage_name).resolve()
    if path.parent != root:
        raise EvidenceStorageError("Unknown evidence file.")
    return path


def delete_evidence(storage_name: str) -> None:
    """Remove a stored file. Used only to clean up a failed multi-file submit."""
    try:
        evidence_path(storage_name).unlink(missing_ok=True)
    except EvidenceStorageError:
        return
