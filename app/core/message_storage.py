"""Opaque private attachment objects, released only after validation and scanning."""

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.core.message_validation import EXTENSIONS
from app.core.storage import scan_evidence

NAME = re.compile(r"[0-9a-f]{32}")


class AttachmentError(ValueError):
    pass


@dataclass
class StoredAttachment:
    storage_name: str
    filename: str
    content_type: str
    kind: str
    size_bytes: int
    sha256: str


def message_root():
    root = Path(settings.message_media_dir).absolute()
    if any(part.is_symlink() for part in [root, *root.parents]):
        raise AttachmentError("File storage is temporarily unavailable.")
    root = root.resolve()
    others = [
        Path(__file__).resolve().parents[1] / "static",
        Path(settings.community_media_dir),
        Path(settings.evidence_dir),
        Path(settings.avatar_dir),
    ]
    if any(
        root == other.resolve()
        or other.resolve() in root.parents
        or root in other.resolve().parents
        for other in others
    ):
        raise AttachmentError("Private file storage is not configured correctly.")
    return root


def attachment_path(name):
    if not NAME.fullmatch(name):
        raise AttachmentError("This file is unavailable.")
    path = message_root() / name
    if path.is_symlink() or path.resolve().parent != message_root():
        raise AttachmentError("This file is unavailable.")
    return path


def clean_filename(value):
    value = unicodedata.normalize("NFC", value or "").replace("\\", "/").rsplit("/", 1)[-1]
    value = (
        "".join(c for c in value if not unicodedata.category(c).startswith("C")).strip().strip(".")
    )
    extension = Path(value).suffix.lower()
    if extension not in EXTENSIONS:
        raise AttachmentError(
            "Choose an image, audio/video file, PDF, modern Office document, or text file."
        )
    return value if len(value) <= 180 else value[: 180 - len(extension)] + extension


def fingerprint(source, filename):
    filename = clean_filename(filename)
    source.seek(0)
    digest, size = hashlib.sha256(), 0
    while chunk := source.read(1024 * 1024):
        size += len(chunk)
        if size > settings.message_attachment_max_bytes:
            limit_mb = settings.message_attachment_max_bytes // (1024 * 1024)
            raise AttachmentError(f"Each file must be at most {limit_mb} MB.")
        digest.update(chunk)
    if not size:
        raise AttachmentError("Choose a file that is not empty.")
    source.seek(0)
    return filename, size, digest.hexdigest()


def store_attachment(source, filename):
    filename, size, digest = fingerprint(source, filename)
    root = message_root()
    temporary = None
    try:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        root.chmod(0o700)
        descriptor, name = tempfile.mkstemp(prefix=".quarantine-", dir=root)
        temporary = Path(name)
        copied, copied_hash = 0, hashlib.sha256()
        with os.fdopen(descriptor, "wb") as output:
            while chunk := source.read(1024 * 1024):
                copied += len(chunk)
                if copied > size:
                    raise AttachmentError(
                        "This file changed while being prepared. Choose it again."
                    )
                copied_hash.update(chunk)
                output.write(chunk)
        if copied != size or copied_hash.hexdigest() != digest:
            raise AttachmentError("This file changed while being prepared. Choose it again.")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "app.core.message_validation",
                str(temporary),
                Path(filename).suffix.lower(),
            ],
            capture_output=True,
            timeout=15,
            check=False,
        )
        if result.returncode:
            raise AttachmentError(
                "This file could not be read safely. "
                "Choose a complete file without passwords or embedded programs."
            )
        info = json.loads(result.stdout)
        if info.get("kind") not in {"image", "audio", "video", "document"}:
            raise AttachmentError("This file could not be prepared.")
        scan_evidence(temporary)
        storage_name = uuid.uuid4().hex
        temporary.replace(root / storage_name)
        return StoredAttachment(
            storage_name, filename, info["content_type"], info["kind"], size, digest
        )
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        raise AttachmentError(
            "File preparation is temporarily unavailable. Please try again."
        ) from None
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
