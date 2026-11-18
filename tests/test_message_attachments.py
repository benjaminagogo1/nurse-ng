# ruff: noqa: F811
"""Private files must stay private through staging, retries and account lifecycle."""

import hashlib
import io
import os
import sqlite3
import subprocess
import threading
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import imageio_ffmpeg
import pytest
from alembic import command
from alembic.config import Config
from PIL import Image
from pypdf import PdfWriter
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core import message_storage
from app.core.config import settings
from app.core.message_storage import AttachmentError, attachment_path, store_attachment
from app.core.message_validation import DOCUMENTS
from app.core.storage import EvidenceScanUnavailable, EvidenceStorageError
from app.models.messages import DirectMessage, MessageAttachment, MessageUploadUsage
from app.models.user import User
from app.services import accounts, worker_runtime
from app.services import message_attachments as files
from app.services.backups import create_backup, restore_backup
from app.services.messages import message_data, send_message
from tests.helpers import csrf_from
from tests.test_backups import backup_source  # noqa: F401
from tests.test_discussions import as_member, community  # noqa: F401
from tests.test_notifications import connected  # noqa: F401


@pytest.fixture(autouse=True)
def private_files(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "message_media_dir", str(tmp_path / "private-files"))
    # Validation subprocesses run for real; scanner behavior has dedicated tests.
    scans = []
    monkeypatch.setattr(message_storage, "scan_evidence", lambda path: scans.append(path))
    return scans


def picture(format="PNG"):
    stream = io.BytesIO()
    Image.new("RGB", (64, 48), "#247c7d").save(stream, format=format)
    return stream.getvalue()


def pdf(pages=1, script=False):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=500, height=700)
    if script:
        writer.add_js("app.alert('unsafe')")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def office(extension, *, extra=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        if extension in {".docx", ".xlsx", ".pptx"}:
            name, tag = {
                ".docx": ("word/document.xml", "document"),
                ".xlsx": ("xl/workbook.xml", "workbook"),
                ".pptx": ("ppt/presentation.xml", "presentation"),
            }[extension]
            archive.writestr(name, f"<{tag}/>")
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("_rels/.rels", "<Relationships/>")
        else:
            archive.writestr("mimetype", DOCUMENTS[extension])
            archive.writestr("content.xml", "<document/>")
            archive.writestr("META-INF/manifest.xml", "<manifest/>")
        if extra:
            for name, data in extra.items():
                archive.writestr(name, data)
    return output.getvalue()


def upload(db, first, second, data=None, name="nursing.png", key=None):
    return files.upload_attachment(
        db, first, second, io.BytesIO(data or picture()), name, key or str(uuid.uuid4())
    )


@pytest.mark.parametrize(
    "format,extension", [("PNG", ".png"), ("JPEG", ".jpg"), ("WEBP", ".webp"), ("GIF", ".gif")]
)
def test_images_are_validated_scanned_and_private(format, extension, private_files):
    data = picture(format)
    saved = store_attachment(io.BytesIO(data), "colleague" + extension)
    path = attachment_path(saved.storage_name)
    assert saved.kind == "image" and saved.filename == "colleague" + extension
    assert saved.sha256 == hashlib.sha256(data).hexdigest()
    assert path.read_bytes() == data and private_files
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("extension", list(DOCUMENTS))
def test_supported_documents(extension):
    data = (
        pdf(30)
        if extension == ".pdf"
        else "Research,notes\nNursing,learning".encode()
        if extension in {".txt", ".csv"}
        else b"{\\rtf1 Nursing notes}"
        if extension == ".rtf"
        else office(extension)
    )
    result = store_attachment(io.BytesIO(data), "study" + extension)
    assert result.kind == "document" and result.content_type == DOCUMENTS[extension]


@pytest.mark.parametrize(
    "extension,codec",
    [
        (".wav", "pcm_s16le"),
        (".mp3", "libmp3lame"),
        (".m4a", "aac"),
        (".aac", "aac"),
        (".ogg", "libvorbis"),
        (".opus", "libopus"),
        (".flac", "flac"),
        (".mp4", "libx264"),
        (".m4v", "libx264"),
        (".mov", "libx264"),
        (".webm", "libvpx-vp9"),
    ],
)
def test_actual_audio_and_video_decodes_before_release(tmp_path, extension, codec):
    video = extension in {".mp4", ".m4v", ".mov", ".webm"}
    path = tmp_path / ("teaching" + extension)
    args = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-v",
        "error",
        "-nostdin",
        "-f",
        "lavfi",
        "-i",
        "color=c=teal:s=96x64:r=10" if video else "sine=frequency=440:sample_rate=24000",
        "-t",
        "0.3",
        "-threads",
        "1",
        "-c:v" if video else "-c:a",
        codec,
    ]
    if extension == ".m4v":
        args += ["-f", "mp4"]
    subprocess.run([*args, str(path)], check=True, capture_output=True, timeout=15)
    with path.open("rb") as stream:
        result = store_attachment(stream, path.name)
    assert result.kind == ("video" if video else "audio")


@pytest.mark.parametrize(
    "name,data",
    [
        ("spoof.png", b"<html>not a picture</html>"),
        ("wrong.jpg", picture()),
        ("broken.mp4", b"\x00\x00\x00\x20ftypisom incomplete"),
        ("script.pdf", pdf(script=True)),
        ("locked.docx", b"not a ZIP"),
        ("macro.docx", office(".docx", extra={"word/vbaProject.bin": b"code"})),
        (
            "external.docx",
            office(
                ".docx",
                extra={
                    "word/_rels/document.xml.rels": "<Relationships><Relationship "
                    'TargetMode="External" Type="image" '
                    'Target="https://example.org/remote"/></Relationships>'
                },
            ),
        ),
        ("traversal.odt", office(".odt", extra={"../program": b"code"})),
        ("active.rtf", b"{\\rtf1\\object\\objdata executable}"),
        ("binary.txt", b"hello\x00secret"),
        ("old.doc", b"legacy"),
        ("run.exe", b"MZ"),
    ],
)
def test_unsafe_or_spoofed_files_never_leave_quarantine(name, data):
    with pytest.raises(AttachmentError):
        store_attachment(io.BytesIO(data), name)
    root = Path(settings.message_media_dir)
    assert not root.exists() or not list(root.iterdir())


@pytest.mark.parametrize(
    "error",
    [EvidenceStorageError("Malware rejected"), EvidenceScanUnavailable("Scanner unavailable")],
)
def test_malware_and_scanner_outage_fail_closed(monkeypatch, error):
    def reject(_):
        raise error

    monkeypatch.setattr(message_storage, "scan_evidence", reject)
    with pytest.raises(type(error)):
        store_attachment(io.BytesIO(picture()), "study.png")
    assert not list(Path(settings.message_media_dir).iterdir())


def test_name_cleanup_size_and_storage_guards(tmp_path, monkeypatch):
    assert message_storage.clean_filename("../../lecture\u202e.png") == "lecture.png"
    assert len(message_storage.clean_filename("a" * 300 + ".docx")) == 180
    monkeypatch.setattr(settings, "message_attachment_max_bytes", 10)
    with pytest.raises(AttachmentError, match="at most"):
        store_attachment(io.BytesIO(picture()), "large.png")
    with pytest.raises(AttachmentError, match="empty"):
        store_attachment(io.BytesIO(), "empty.txt")
    with pytest.raises(AttachmentError):
        attachment_path("../secret")
    monkeypatch.setattr(settings, "message_media_dir", settings.community_media_dir)
    with pytest.raises(AttachmentError, match="Private file"):
        message_storage.message_root()
    root = tmp_path / "linked"
    root.symlink_to(tmp_path / "target")
    monkeypatch.setattr(settings, "message_media_dir", str(root))
    with pytest.raises(AttachmentError, match="unavailable"):
        message_storage.message_root()


def test_attachment_only_order_and_send_upload_retries(db_session, connected):
    first, second, _ = connected
    reference = str(uuid.uuid4())
    one = upload(db_session, first, second, key=reference)
    two = upload(db_session, first, second, b"Study notes", "notes.txt")
    assert upload(db_session, first, second, key=reference).id == one.id
    with pytest.raises(AttachmentError, match="already used"):
        upload(db_session, first, second, b"changed", "notes.txt", reference)
    db_session.rollback()
    key = str(uuid.uuid4())
    sent = send_message(db_session, first, second, "", key, attachment_ids=[two.id, one.id])
    assert [item.id for item in sent.attachments] == [two.id, one.id]
    assert [item.position for item in sent.attachments] == [0, 1]
    assert (
        send_message(db_session, first, second, "", key, attachment_ids=[two.id, one.id]).id
        == sent.id
    )
    with pytest.raises(ValueError, match="reference was already used"):
        send_message(db_session, first, second, "", key, attachment_ids=[one.id, two.id])
    db_session.rollback()
    with pytest.raises(ValueError, match="no longer available"):
        send_message(db_session, first, second, "Again", attachment_ids=[one.id])
    db_session.rollback()
    assert db_session.scalar(select(func.count()).select_from(DirectMessage)) == 1
    dto = message_data(sent, first)
    assert dto["attachments"][0]["name"] == "notes.txt"


def test_staging_and_sent_access_are_participant_only(client, db_session, connected, community):
    first, second, connection = connected
    outsider = community[0][2]
    item = upload(db_session, first, second)
    url = f"/messages/files/{item.id}"
    client.cookies.clear()
    assert client.get(url, follow_redirects=False).status_code in {303, 401}
    for person in [second, outsider]:
        as_member(client, person)
        assert client.get(url).status_code == 404
    as_member(client, first)
    response = client.get(url)
    assert response.status_code == 200 and response.content == picture()
    assert "no-store" in response.headers["cache-control"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cross-origin-resource-policy"] == "same-origin"
    assert "sandbox" in response.headers["content-security-policy"]
    send_message(db_session, first, second, "Lecture", attachment_ids=[item.id])
    as_member(client, second)
    response = client.get(url, headers={"Range": "bytes=0-15"})
    assert response.status_code == 206 and response.content == picture()[:16]
    assert "attachment" in client.get(url + "?download=1").headers["content-disposition"]
    outsider.is_staff = True
    db_session.commit()
    as_member(client, outsider)
    assert client.get(url).status_code == 404
    connection.status = "pending"
    db_session.commit()
    for person in [first, second]:
        as_member(client, person)
        assert client.get(url).status_code == 404


def test_routes_upload_send_download_and_no_script_fallback(client, db_session, connected):
    first, second, _ = connected
    as_member(client, first)
    token = csrf_from(client.get(f"/messages/{second.id}"))
    url = f"/messages/{second.id}/attachments"
    payload = {"csrf_token": token, "upload_key": str(uuid.uuid4())}
    rejected = client.post(
        url, data={"upload_key": payload["upload_key"]}, files={"file": ("notes.txt", b"study")}
    )
    assert rejected.status_code in {400, 403}
    response = client.post(url, data=payload, files={"file": ("notes.txt", b"study")})
    assert response.status_code == 200, response.text
    item = response.json()["attachment"]
    response = client.post(
        f"/messages/{second.id}",
        headers={"X-Messages": "1"},
        data={"csrf_token": token, "client_key": str(uuid.uuid4()), "attachment_ids": item["id"]},
    )
    assert response.status_code == 200 and response.json()["message"]["body"] == ""
    assert response.json()["message"]["attachments"][0]["name"] == "notes.txt"
    as_member(client, second)
    assert client.get(item["url"]).content == b"study"
    assert "attachment" in client.get(item["url"]).headers["content-disposition"]
    as_member(client, first)
    token = csrf_from(client.get(f"/messages/{second.id}"))
    response = client.post(
        f"/messages/{second.id}",
        data={"csrf_token": token, "client_key": str(uuid.uuid4()), "body": "Clinical notes"},
        files=[("files", ("teaching.png", picture())), ("files", ("guide.pdf", pdf()))],
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    page = client.get(response.headers["location"])
    assert "teaching.png" in page.text and "guide.pdf" in page.text
    assert " UTC" not in page.text and "message-file-card" in page.text


def test_request_and_message_limits(client, db_session, connected, monkeypatch):
    first, second, _ = connected
    as_member(client, first)
    token = csrf_from(client.get(f"/messages/{second.id}"))
    monkeypatch.setattr(settings, "message_attachment_max_bytes", 1024)
    url = f"/messages/{second.id}/attachments"
    response = client.post(url, content=b"", headers={"Content-Length": "999999"})
    assert response.status_code == 413
    response = client.post(
        url,
        data={"csrf_token": token, "upload_key": str(uuid.uuid4())},
        files={"file": ("notes.txt", b"x" * 1200)},
    )
    assert response.status_code == 400 and "at most" in response.text
    item = upload(db_session, first, second, b"study", "notes.txt")
    monkeypatch.setattr(settings, "message_attachment_total_bytes", 4)
    with pytest.raises(AttachmentError, match="total"):
        send_message(db_session, first, second, "", attachment_ids=[item.id])
    db_session.rollback()
    with pytest.raises(AttachmentError, match="different files"):
        send_message(db_session, first, second, "", attachment_ids=[item.id, item.id])


def test_quotas_expiry_and_discard(db_session, connected, monkeypatch):
    first, second, _ = connected
    item = upload(db_session, first, second, b"study", "notes.txt")
    assert db_session.get(MessageUploadUsage, first.id).size_bytes == 5
    monkeypatch.setattr(settings, "message_upload_window_bytes", 6)
    with pytest.raises(AttachmentError, match="allowance"):
        upload(db_session, first, second, b"study", "second.txt")
    assert len(list(Path(settings.message_media_dir).iterdir())) == 1
    monkeypatch.setattr(settings, "message_upload_window_bytes", 100)
    monkeypatch.setattr(settings, "message_storage_quota_bytes", 6)
    with pytest.raises(AttachmentError, match="storage is full"):
        upload(db_session, first, second, b"study", "second.txt")
    files.discard_attachment(db_session, second, item.id)
    assert db_session.get(MessageAttachment, item.id)
    files.discard_attachment(db_session, first, item.id)
    assert not attachment_path(item.storage_name).exists()
    item = upload(db_session, first, second, b"study", "notes.txt")
    item.created_at = datetime.now(UTC) - timedelta(days=2)
    db_session.commit()
    assert files.accessible_attachment(db_session, first, item.id) is None
    with pytest.raises(AttachmentError, match="no longer available"):
        send_message(db_session, first, second, "", attachment_ids=[item.id])
    db_session.rollback()
    orphan = Path(settings.message_media_dir) / ("b" * 32)
    orphan.write_bytes(b"expired orphan")
    old_time = (datetime.now(UTC) - timedelta(days=2)).timestamp()
    os.utime(orphan, (old_time, old_time))
    assert files.maintain_message_files(db_session, dry_run=True) == {"expired": 1, "orphaned": 1}
    assert orphan.exists() and attachment_path(item.storage_name).exists()
    assert files.maintain_message_files(db_session) == {"expired": 1, "orphaned": 1}
    assert not orphan.exists() and not attachment_path(item.storage_name).exists()


def test_notification_worker_expires_files_and_throttles_cleanup(
    db_session, connected, monkeypatch
):
    first, second, _ = connected
    item = upload(db_session, first, second, b"unfinished notes", "notes.txt")
    storage = attachment_path(item.storage_name)
    item.created_at = datetime.now(UTC) - timedelta(days=2)
    db_session.commit()
    stop = threading.Event()
    clock, passes, cleanups = [100], [], []
    maintain = files.maintain_message_files

    def cleanup(db):
        cleanups.append(clock[0])
        return maintain(db)

    def step(name, db):
        passes.append(name)
        assert not storage.exists()
        assert db.get(MessageAttachment, item.id) is None
        if len(passes) == 3:
            stop.set()
        clock[0] = 200 if len(passes) == 1 else 405

    monkeypatch.setattr(worker_runtime, "SessionLocal", sessionmaker(bind=db_session.get_bind()))
    monkeypatch.setattr(worker_runtime, "_step", step)
    monkeypatch.setattr(worker_runtime.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(files, "maintain_message_files", cleanup)
    monkeypatch.setattr(stop, "wait", lambda seconds: False)
    assert worker_runtime.run_worker("notifications", stop=stop) == 0
    assert passes == ["notifications"] * 3
    assert cleanups == [100, 405]


@pytest.mark.parametrize("change", ["connection", "suspend", "credentials"])
def test_access_changes_during_scan_never_release_file(db_session, connected, monkeypatch, change):
    first, second, connection = connected

    def revoke(_):
        if change == "connection":
            connection.status = "pending"
        elif change == "suspend":
            second.is_active = False
        else:
            first.auth_version += 1
        db_session.commit()

    monkeypatch.setattr(message_storage, "scan_evidence", revoke)
    with pytest.raises(AttachmentError, match="no longer available"):
        upload(db_session, first, second)
    assert db_session.scalar(select(func.count()).select_from(MessageAttachment)) == 0
    assert not list(Path(settings.message_media_dir).iterdir())


@pytest.mark.parametrize("owner", [0, 1])
def test_deleting_either_account_removes_files(db_session, connected, monkeypatch, owner):
    first, second, _ = connected
    item = upload(db_session, first, second)
    send_message(db_session, first, second, "", attachment_ids=[item.id])
    staged = upload(db_session, first, second, b"draft", "draft.txt")
    names = [item.storage_name, staged.storage_name]
    monkeypatch.setattr(accounts, "verify_current_password", lambda *args: None)
    accounts.delete_account(db_session, [first, second][owner], password="synthetic")
    assert all(not attachment_path(name).exists() for name in names)
    assert db_session.scalar(select(func.count()).select_from(MessageAttachment)) == 0


def test_backup_restores_private_sent_and_staged_files(backup_source, tmp_path):
    from app.models.community import Connection
    from app.services.community import connection_pair_key

    engine = create_engine("sqlite:///" + str(backup_source))
    with Session(engine, expire_on_commit=False) as db:
        first = User(phone="+2348999000001", hashed_password="unused")
        second = User(phone="+2348999000002", hashed_password="unused")
        db.add_all([first, second])
        db.flush()
        db.add(
            Connection(
                requester_user_id=first.id,
                recipient_user_id=second.id,
                pair_key=connection_pair_key(first.id, second.id),
                status="accepted",
            )
        )
        db.commit()
        item = upload(db, first, second)
        send_message(db, first, second, "", attachment_ids=[item.id])
        staged = upload(db, first, second, b"study", "study.txt")
        names = item.storage_name, staged.storage_name
    engine.dispose()
    result = create_backup()
    destination = tmp_path / "restore"
    restore_backup(result["backup"], destination)
    assert (destination / "messages" / names[0]).read_bytes() == picture()
    assert (destination / "messages" / names[1]).read_bytes() == b"study"
    with sqlite3.connect(destination / "database.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM message_attachments").fetchone()[0] == 2


def test_migration_preserves_messages_and_protects_nonempty_downgrade(tmp_path, monkeypatch):
    database = tmp_path / "migration.db"
    monkeypatch.setattr(settings, "database_url", "sqlite:///" + str(database))
    config = Config("alembic.ini")
    command.upgrade(config, "e6480i9e5416")
    with sqlite3.connect(database) as db:
        prior = {
            name: db.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
            for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    command.upgrade(config, "head")
    command.check(config)
    with sqlite3.connect(database) as db:
        assert all(
            db.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0] == count
            for name, count in prior.items()
        )
    engine = create_engine(settings.database_url)
    with Session(engine) as db:
        first, second = (
            User(phone="+2348999000001", hashed_password="unused"),
            User(phone="+2348999000002", hashed_password="unused"),
        )
        db.add_all([first, second])
        db.flush()
        db.add(
            MessageAttachment(
                sender_id=first.id,
                recipient_id=second.id,
                upload_key=str(uuid.uuid4()),
                storage_name="a" * 32,
                filename="notes.txt",
                kind="document",
                content_type="text/plain",
                size_bytes=5,
                sha256="b" * 64,
                scanned_at=datetime.now(UTC),
            )
        )
        db.commit()
    with pytest.raises(RuntimeError, match="attachments"):
        command.downgrade(config, "e6480i9e5416")
    with engine.begin() as connection:
        connection.execute(MessageAttachment.__table__.delete())
    command.downgrade(config, "e6480i9e5416")
    command.upgrade(config, "head")
    command.check(config)
    engine.dispose()
