"""Private, consistent SQLite backups with bounded retention and isolated restoration."""

import fcntl
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.engine import make_url

from app.core.config import settings

NAME = re.compile(r"backup-\d{8}T\d{12}Z")
OPAQUE = re.compile(r"[0-9a-f]{32}")


class BackupError(ValueError):
    pass


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def private_directory(path):
    path = Path(path).absolute()
    if any(part.is_symlink() for part in [path, *path.parents]):
        raise BackupError("Backup paths cannot contain symbolic links.")
    path = path.resolve()
    public = [
        Path("app/static").resolve(),
        Path(settings.community_media_dir).resolve(),
        Path(settings.avatar_dir).resolve(),
        Path(settings.evidence_dir).resolve(),
    ]
    if any(path == root or root in path.parents for root in public):
        raise BackupError("Choose a private backup directory outside all upload/static stores.")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.stat().st_mode & 0o077:
        raise BackupError("Backup directories must be private (permissions 0700).")
    return path


@contextmanager
def backup_lock(root):
    root = private_directory(root)
    descriptor = os.open(root / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield root


def connect_readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)


def database_summary(db):
    if db.execute("PRAGMA integrity_check").fetchone() != ("ok",):
        raise BackupError("Database integrity check failed.")
    if db.execute("PRAGMA foreign_key_check").fetchone():
        raise BackupError("Database foreign-key check failed.")
    tables = [
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    counts = {
        name: db.execute('SELECT COUNT(*) FROM "' + name.replace('"', '""') + '"').fetchone()[0]
        for name in tables
    }
    revisions = [row[0] for row in db.execute("SELECT version_num FROM alembic_version")]
    return {"table_counts": counts, "revisions": revisions}


def referenced_files(db, at):
    result = []
    expiry = at + timedelta(days=settings.backup_retention_days)
    for (name,) in db.execute(
        "SELECT photo_storage_name FROM users WHERE photo_storage_name != ''"
    ):
        result.append(("avatars", name, None, None))
    for name, size in db.execute("SELECT storage_name, size_bytes FROM community_media"):
        result.append(("community", name, size, None))
    for name, size, digest, created, decided, status in db.execute(
        "SELECT e.storage_name, e.size_bytes, e.sha256, c.created_at, c.decided_at, e.scan_status "
        "FROM evidence_documents e JOIN verification_cases c ON e.case_id=c.id "
        "WHERE e.purged_at IS NULL"
    ):
        origin = datetime.fromisoformat(decided or created).replace(tzinfo=UTC)
        deadline = origin + timedelta(
            days=settings.evidence_retention_days
            if decided
            else settings.evidence_pending_retention_days
        )
        if deadline <= at:
            raise BackupError("Run maintain-evidence before backing up expired documents.")
        expiry = min(expiry, deadline)
        # Maintenance explicitly records historical file loss. Preserve its audit
        # row and unavailable state; never claim these bytes were backed up.
        if status != "missing":
            result.append(("evidence", name, size, digest))
    if any(not OPAQUE.fullmatch(name) for _, name, _, _ in result):
        raise BackupError("An upload reference has an invalid storage name.")
    return result, expiry


def missing_evidence(db):
    return db.execute("SELECT COUNT(*) FROM evidence_documents "
                      "WHERE scan_status='missing' AND purged_at IS NULL").fetchone()[0]


def copy_private(source, destination, *, size=None, digest=None):
    """Copy immutable upload objects, rejecting symlinks, truncation and changed evidence."""
    if any(part.is_symlink() for part in [source, *source.parents]):
        raise BackupError("A backup input is a symbolic link.")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    sha = hashlib.sha256()
    with source.open("rb") as incoming, destination.open("xb") as outgoing:
        destination.chmod(0o600)
        before = os.fstat(incoming.fileno())
        for chunk in iter(lambda: incoming.read(1024 * 1024), b""):
            outgoing.write(chunk)
            sha.update(chunk)
        after = os.fstat(incoming.fileno())
        outgoing.flush()
        os.fsync(outgoing.fileno())
    actual = destination.stat().st_size
    if (
        (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
        or actual != before.st_size
        or size is not None
        and actual != size
        or digest is not None
        and sha.hexdigest() != digest
    ):
        raise BackupError("An upload changed or failed its size/digest check; retry the backup.")
    return {"size": actual, "sha256": sha.hexdigest()}


def read_manifest(backup):
    path = Path(backup) / "manifest.json"
    if path.is_symlink() or Path(backup).is_symlink():
        raise BackupError("Backup manifests cannot be symbolic links.")
    try:
        manifest = json.loads(path.read_text())
        if manifest["format"] != 1:
            raise ValueError()
        datetime.fromisoformat(manifest["expires_at"])
        if "database.sqlite3" not in manifest["files"]:
            raise ValueError()
        for key in manifest["files"]:
            parts = key.split("/")
            if key != "database.sqlite3" and not (
                len(parts) == 2
                and parts[0] in {"avatars", "community", "evidence"}
                and OPAQUE.fullmatch(parts[1])
            ):
                raise ValueError()
    except (KeyError, ValueError, TypeError) as exc:
        raise BackupError("Invalid backup manifest.") from exc
    return manifest


def prune_backups(root, *, at=None):
    at = at or datetime.now(UTC)
    removed = 0
    for backup in root.iterdir():
        if not NAME.fullmatch(backup.name) or backup.is_symlink() or not backup.is_dir():
            continue
        manifest = read_manifest(backup)
        if datetime.fromisoformat(manifest["expires_at"]) <= at:
            shutil.rmtree(backup)
            removed += 1
    return removed


def create_backup(*, root=None, at=None):
    at = at or datetime.now(UTC)
    url = make_url(settings.database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise BackupError("This command supports file-backed SQLite; use pg_dump for PostgreSQL.")
    source = Path(url.database).resolve()
    if not source.is_file():
        raise BackupError("The configured database does not exist.")
    with backup_lock(root or settings.backup_dir) as root:
        pruned = prune_backups(root, at=at)
        name = "backup-" + at.strftime("%Y%m%dT%H%M%S%fZ")
        destination = root / name
        stores = {
            "avatars": Path(settings.avatar_dir),
            "community": Path(settings.community_media_dir),
            "evidence": Path(settings.evidence_dir),
        }
        with tempfile.TemporaryDirectory(prefix=".creating-", dir=root) as temporary:
            stage = Path(temporary)
            database = stage / "database.sqlite3"
            database.touch(mode=0o600)
            # Hold a writer reservation while snapshotting and copying referenced
            # immutable objects. New uploads cannot commit; deleted rows are absent.
            # A separate reader lets SQLite's backup API complete under that lock.
            with closing(sqlite3.connect(source, timeout=30)) as lock:
                lock.execute("BEGIN IMMEDIATE")
                with (
                    closing(connect_readonly(source)) as live,
                    closing(sqlite3.connect(database)) as copied,
                ):
                    live.backup(copied)
                    summary = database_summary(copied)
                    references, expires = referenced_files(copied, at)
                    missing = missing_evidence(copied)
                files = {}
                for kind, filename, size, digest in references:
                    key = kind + "/" + filename
                    files[key] = copy_private(
                        stores[kind] / filename, stage / key, size=size, digest=digest
                    )
                lock.rollback()
            with database.open("rb") as stored:
                files["database.sqlite3"] = {
                    "size": database.stat().st_size,
                    "sha256": hashlib.file_digest(stored, "sha256").hexdigest(),
                }
            manifest = {
                "format": 1,
                "created_at": at.isoformat(),
                "expires_at": expires.isoformat(),
                "files": files,
                "unavailable_evidence": missing,
                **summary,
            }
            path = stage / "manifest.json"
            with path.open("x") as output:
                path.chmod(0o600)
                json.dump(manifest, output, indent=2)
                output.flush()
                os.fsync(output.fileno())
            for directory in stage.iterdir():
                if directory.is_dir():
                    sync_directory(directory)
            sync_directory(stage)
            stage.rename(destination)
        sync_directory(root)
    return {
        "backup": str(destination),
        "files": len(files),
        "expires_at": expires.isoformat(),
        "pruned": pruned,
        "unavailable_evidence": missing,
        **summary,
    }


def restore_backup(backup, destination, *, at=None):
    """Never overwrite an existing directory or alter configured live paths."""
    at = at or datetime.now(UTC)
    backup, destination = Path(backup).absolute(), Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise BackupError("Restore destination must not exist; choose a new private directory.")
    with backup_lock(backup.parent):
        manifest = read_manifest(backup)
        if datetime.fromisoformat(manifest["expires_at"]) <= at:
            raise BackupError("This backup has expired under its evidence/backup retention policy.")
        private_directory(destination.parent)
        with tempfile.TemporaryDirectory(prefix=".restoring-", dir=destination.parent) as temporary:
            stage = Path(temporary)
            for key, expected in manifest["files"].items():
                copy_private(
                    backup / key, stage / key, size=expected["size"], digest=expected["sha256"]
                )
            with closing(connect_readonly(stage / "database.sqlite3")) as db:
                summary = database_summary(db)
                references, _ = referenced_files(db, at)
                missing = missing_evidence(db)
            if summary != {key: manifest[key] for key in summary}:
                raise BackupError("Restored database counts or migration revision differ.")
            required = {kind + "/" + name for kind, name, _, _ in references} | {"database.sqlite3"}
            if required != set(manifest["files"]):
                raise BackupError("Backup does not include exactly the referenced uploads.")
            for kind, name, size, digest in references:
                entry = manifest["files"][kind + "/" + name]
                if (
                    size is not None
                    and size != entry["size"]
                    or digest is not None
                    and digest != entry["sha256"]
                ):
                    raise BackupError("Restored upload metadata does not match its database row.")
            for kind in ("avatars", "community", "evidence"):
                (stage / kind).mkdir(exist_ok=True, mode=0o700)
            stage.rename(destination)
    return {
        "restored": str(destination),
        "files": len(manifest["files"]),
        "integrity": "ok",
        "foreign_keys": "ok",
        "unavailable_evidence": missing,
        **summary,
    }
