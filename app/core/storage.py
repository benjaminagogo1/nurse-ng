"""Private evidence: bounded parsing, quarantine, and fail-closed malware scanning.

Opaque filenames live outside app/static. A file that cannot be validated or
scanned is not released. Verification/evidence services own access audit and
retention; see docs/EMPLOYER_AND_EVIDENCE_OPERATIONS.md.
"""

import hashlib
import os
import re
import shlex
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from app.core.config import settings

ALLOWED_CONTENT_TYPES = frozenset({"image/jpeg", "image/png", "application/pdf"})
CONTENT_TYPE_SUFFIX = {"image/jpeg": ".jpg", "image/png": ".png", "application/pdf": ".pdf"}
_STORAGE_NAME_RE = re.compile(r"^[0-9a-f]{32}$")


class EvidenceStorageError(ValueError):
    """An uploaded file cannot be accepted."""


class EvidenceScanUnavailable(EvidenceStorageError):
    """Retryable scanner outage; the file must remain unavailable."""


def _root() -> Path:
    root = Path(settings.evidence_dir).resolve()
    public = (Path(__file__).resolve().parents[1] / "static").resolve()
    media = Path(settings.community_media_dir).resolve()
    if root == public or public in root.parents or root == media or media in root.parents:
        raise EvidenceStorageError("Private evidence storage is not configured correctly.")
    return root


def sniff_content_type(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def validate_evidence(path: Path) -> str:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "app.core.evidence_validation", str(path.resolve())],
            capture_output=True, timeout=12, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise EvidenceStorageError(
            "The document could not be validated. Try another file."
        ) from None
    content_type = result.stdout.decode("ascii", errors="replace").strip()
    if result.returncode or content_type not in ALLOWED_CONTENT_TYPES:
        raise EvidenceStorageError(
            "Choose a complete JPEG, PNG, or PDF document. PDFs must have 1–25 pages, "
            "without passwords, scripts, or embedded files."
        )
    return content_type


def scan_evidence(path: Path) -> None:
    try:
        command = shlex.split(settings.evidence_scan_command)
        if not command:
            raise OSError("Scanner not configured")
        result = subprocess.run(
            [*command, "--no-summary", str(path.resolve())],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=settings.evidence_scan_timeout_seconds, check=False,
        )
    except (ValueError, OSError, subprocess.TimeoutExpired):
        raise EvidenceScanUnavailable(
            "Document scanning is temporarily unavailable. Please try again later."
        ) from None
    if result.returncode == 1:
        raise EvidenceStorageError("The document was rejected by the malware scanner.")
    if result.returncode != 0:
        raise EvidenceScanUnavailable(
            "Document scanning is temporarily unavailable. Please try again later."
        )


def save_evidence(data: bytes) -> tuple[str, str, int, str]:
    if not data:
        raise EvidenceStorageError("Choose a file to upload.")
    if len(data) > settings.evidence_max_bytes:
        maximum = max(1, settings.evidence_max_bytes // (1024 * 1024))
        raise EvidenceStorageError(f"Each file must be at most {maximum} MB.")
    if sniff_content_type(data) is None:
        raise EvidenceStorageError("Upload a JPEG, PNG, or PDF file.")
    root = _root()
    temporary = None
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        root.chmod(0o700)
        descriptor, name = tempfile.mkstemp(prefix=".quarantine-", dir=root)
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
        content_type = validate_evidence(temporary)
        scan_evidence(temporary)
        storage_name = uuid.uuid4().hex
        temporary.replace(root / storage_name)
    except OSError:
        raise EvidenceStorageError("The file could not be stored.") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return storage_name, content_type, len(data), hashlib.sha256(data).hexdigest()


def evidence_path(storage_name: str) -> Path:
    if not _STORAGE_NAME_RE.fullmatch(storage_name):
        raise EvidenceStorageError("Unknown evidence file.")
    root = _root()
    path = root / storage_name
    if path.is_symlink() or path.resolve().parent != root:
        raise EvidenceStorageError("Unknown evidence file.")
    return path


def delete_evidence(storage_name: str) -> None:
    try:
        evidence_path(storage_name).unlink(missing_ok=True)
    except EvidenceStorageError:
        return
