"""Exercise real PostgreSQL attachment races on a disposable database only."""

import io
import os
import runpy
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

if not os.environ.get("NURSE_NG_TEST_POSTGRES_URL", "").endswith("/nurse_ng_hosting_test"):
    raise RuntimeError("Use an isolated PostgreSQL database named nurse_ng_hosting_test.")

runpy.run_path(str(Path(__file__).with_name("participation_journey.py")))

from sqlalchemy import func, select  # noqa: E402

from app.core import message_storage  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.community import Connection  # noqa: E402
from app.models.messages import DirectMessage, MessageAttachment, MessageUploadUsage  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import message_attachments as files  # noqa: E402
from app.services.community import connection_pair_key  # noqa: E402
from app.services.messages import send_message  # noqa: E402

with tempfile.TemporaryDirectory(prefix="nurse-message-postgres-") as directory:
    settings.message_media_dir = directory
    with SessionLocal() as db:
        members = [User(phone=f"+234899955500{i}", hashed_password="unused") for i in range(2)]
        db.add_all(members)
        db.flush()
        ids = [member.id for member in members]
        db.add(
            Connection(
                requester_user_id=ids[0],
                recipient_user_id=ids[1],
                pair_key=connection_pair_key(*ids),
                status="accepted",
            )
        )
        db.commit()

    barrier = threading.Barrier(2)
    message_storage.scan_evidence = lambda path: barrier.wait(timeout=30)
    reference = str(uuid4())

    def upload(reference, first=0):
        with SessionLocal() as db:
            try:
                asset = files.upload_attachment(
                    db,
                    db.get(User, ids[first]),
                    db.get(User, ids[1 - first]),
                    io.BytesIO(b"Study notes"),
                    "notes.txt",
                    reference,
                )
                return str(asset.id)
            except files.AttachmentError as exc:
                db.rollback()
                return str(exc)

    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(upload, [reference, reference]))
    assert outcomes[0] == outcomes[1]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(MessageAttachment)) == 1
        assert db.get(MessageUploadUsage, ids[0]).size_bytes == len(b"Study notes")
        asset_id = db.scalar(select(MessageAttachment.id))

    def send(_):
        with SessionLocal() as db:
            message = send_message(
                db,
                db.get(User, ids[0]),
                db.get(User, ids[1]),
                "",
                reference,
                attachment_ids=[asset_id],
            )
            return str(message.id)

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(send, range(2)))
    assert results[0] == results[1]
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(DirectMessage)
                .where(DirectMessage.sender_id == ids[0])
            )
            == 1
        )

    settings.message_upload_window_bytes = 2 * len(b"Study notes")
    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(upload, [str(uuid4()), str(uuid4())]))
    assert sum("allowance" in result for result in outcomes) == 1, outcomes
    with SessionLocal() as db:
        assert db.get(MessageUploadUsage, ids[0]).size_bytes == 2 * len(b"Study notes")
        assert db.scalar(select(func.count()).select_from(MessageAttachment)) == 2

    # Both participants may upload concurrently without opposite-owner deadlocks.
    settings.message_upload_window_bytes = 1000
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(
            workers.map(lambda pair: upload(*pair), [(str(uuid4()), 0), (str(uuid4()), 1)])
        )
    assert all(len(result) == 36 for result in results), results
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(MessageAttachment)) == 4
        assert len(list(Path(directory).iterdir())) == 4
        assert files.accessible_attachment(db, db.get(User, ids[1]), asset_id)
        participant = db.get(User, ids[1])
        participant.is_active = False
        db.commit()
        assert files.accessible_attachment(db, participant, asset_id) is None

print("PostgreSQL private files: migration, upload/send races, quotas and access checks passed.")
