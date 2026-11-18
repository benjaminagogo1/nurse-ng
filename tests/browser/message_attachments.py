# ruff: noqa: E402, E501
"""Isolated notification and live-message browser journeys; file email only."""

import base64
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path("/home/recoding/nurse-ng")
sys.path.insert(0, str(ROOT))
artifacts = Path(tempfile.mkdtemp(prefix="nurse-message-files-browser-"))


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


port, chrome_port = free_port(), free_port()
base = f"http://127.0.0.1:{port}"
os.environ.update(
    {
        "NURSE_NG_ENVIRONMENT": "development",
        "NURSE_NG_DEBUG": "0",
        "NURSE_NG_SECRET_KEY": secrets.token_urlsafe(32),
        "NURSE_NG_SESSION_HTTPS_ONLY": "0",
        "NURSE_NG_ALLOWED_HOSTS": "127.0.0.1,localhost",
        "NURSE_NG_DATABASE_URL": f"sqlite:///{artifacts / 'browser.db'}",
        "NURSE_NG_PUBLIC_BASE_URL": base,
        "NURSE_NG_ACCOUNT_MAIL_BACKEND": "disabled",
        "NURSE_NG_MESSAGE_MEDIA_DIR": str(artifacts / "private-files"),
        "NURSE_NG_ACCOUNT_MAIL_DIR": str(artifacts / "mail"),
        "NURSE_NG_SMTP_FROM": "Nurse.ng <no-reply@example.org>",
    }
)
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from websockets.sync.client import connect

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.community import Connection
from app.models.messages import DirectMessage
from app.models.user import User
from app.services.auth import register_user
from app.services.community import connection_pair_key
from app.services.messages import send_message

command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
with SessionLocal() as db:
    first = register_user(
        db,
        phone="+2348000000077",
        password="browser-password",
        email="first@example.org",
        full_name="Ada Browser",
    )
    second = register_user(
        db,
        phone="+2348000000078",
        password="browser-password",
        email="second@example.org",
        full_name="Bola Browser",
    )
    first.community_name = "Ada Browser"
    second.community_name = "Bola Browser"
    first.email_verified_at = datetime.now(UTC)
    first_id, second_id = first.id, second.id
    connection = Connection(
        requester_user_id=first.id,
        recipient_user_id=second.id,
        pair_key=connection_pair_key(first.id, second.id),
        status="accepted",
    )
    db.add(connection)
    db.commit()
    connection_id = connection.id
    db.add_all(
        [
            DirectMessage(
                sender_id=second.id,
                recipient_id=first.id,
                body=f"Earlier message {i:03}",
                read_at=datetime.now(UTC),
                created_at=datetime.now(UTC) - timedelta(days=1, seconds=130 - i),
            )
            for i in range(125)
        ]
    )
    db.commit()
    send_message(db, second, first, "Welcome to your professional network")
processes, logs, errors, paused = [], [], [], []
ws, sequence = None, 0


def wait_for(fn, label, seconds=45):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            result = fn()
            if result:
                return result
        except (OSError, ValueError, AttributeError):
            pass
        time.sleep(0.1)
    raise AssertionError("Timed out: " + label)


def cdp(method, params=None):
    global sequence
    sequence += 1
    ws.send(json.dumps({"id": sequence, "method": method, "params": params or {}}))
    while True:
        response = json.loads(ws.recv(timeout=45))
        if response.get("method") == "Runtime.exceptionThrown":
            errors.append(response["params"])
        if response.get("method") == "Fetch.requestPaused":
            paused.append(response["params"])
        if response.get("id") == sequence:
            assert "error" not in response, response
            return response.get("result", {})


def js(expression, *, user_gesture=False):
    result = cdp(
        "Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True, "userGesture": user_gesture}
    )
    assert "exceptionDetails" not in result, result
    return result.get("result", {}).get("value")


def navigate(path, selector="main"):
    cdp("Page.navigate", {"url": base + path})
    wait_for(
        lambda: js(
            f"location.pathname === {json.dumps(path.split('?')[0])} && "
            f'document.readyState === "complete" && !!document.querySelector({json.dumps(selector)})'
        ),
        path,
    )


def viewport(width=390):
    cdp(
        "Emulation.setDeviceMetricsOverride",
        {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": width < 900},
    )


def screenshot(name):
    (artifacts / name).write_bytes(
        base64.b64decode(cdp("Page.captureScreenshot", {"format": "png"})["data"])
    )


def incoming(text):
    with SessionLocal() as db:
        return send_message(db, db.get(User, second_id), db.get(User, first_id), text).id


try:
    for name, args in [
        (
            "server",
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
        ),
        (
            "chrome",
            [
                "/usr/bin/google-chrome",
                "--headless=new",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
                "--disable-sync",
                "--no-first-run",
                "--no-default-browser-check",
                "--password-store=basic",
                "--disable-background-networking",
                f"--user-data-dir={artifacts / 'chrome'}",
                f"--remote-debugging-port={chrome_port}",
                "about:blank",
            ],
        ),
    ]:
        log = (artifacts / f"{name}.log").open("w")
        logs.append(log)
        processes.append(
            subprocess.Popen(args, cwd=ROOT, env=os.environ.copy(), stdout=log, stderr=log)
        )
    wait_for(lambda: urllib.request.urlopen(base + "/healthz", timeout=1).status == 200, "server")
    tabs = wait_for(
        lambda: json.load(
            urllib.request.urlopen(f"http://127.0.0.1:{chrome_port}/json/list", timeout=1)
        ),
        "Chrome",
    )
    ws = connect(next(t["webSocketDebuggerUrl"] for t in tabs if t["type"] == "page"), legacy=True)
    for method in ["Page.enable", "Runtime.enable", "Network.enable"]:
        cdp(method)
    viewport()
    navigate("/auth/login", "#phone")
    js(
        'document.querySelector("#phone").value="+2348000000077"; document.querySelector("#password").value="browser-password"; document.querySelector("form[action=\\"/auth/login\\"]").requestSubmit()'
    )
    wait_for(
        lambda: js('location.pathname === "/" && document.readyState === "complete"'), "sign in"
    )

    import hashlib

    import imageio_ffmpeg
    from PIL import Image, ImageDraw
    from pypdf import PdfWriter

    from app.models.messages import MessageAttachment, MessageUploadUsage

    examples = artifacts / "examples"
    examples.mkdir()
    image = Image.new("RGB", (480, 300), "#deeeeb")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((40, 40, 440, 260), radius=24, fill="#187b79")
    draw.text((95, 145), "NURSING STUDY GROUP", fill="white", font_size=22)
    image.save(examples / "study-group.png")
    writer = PdfWriter()
    writer.add_blank_page(width=500, height=700)
    with (examples / "clinical-guide.pdf").open("wb") as output:
        writer.write(output)
    (examples / "nursing-notes.txt").write_text("Synthetic nursing study notes.\n")
    for name, source, codec in [
        ("voice-note.wav", "sine=frequency=440:sample_rate=24000", "pcm_s16le"),
        ("teaching-video.mp4", "color=c=teal:s=320x180:r=10", "libx264"),
    ]:
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-nostdin",
            "-f", "lavfi", "-i", source, "-t", "1", "-threads", "1",
            "-c:v" if name.endswith("mp4") else "-c:a", codec, str(examples / name)],
            check=True, timeout=15, capture_output=True)

    def choose(names):
        document = cdp("DOM.getDocument")
        node = cdp("DOM.querySelector", {"nodeId": document["root"]["nodeId"],
                    "selector": "#message-files"})["nodeId"]
        cdp("DOM.setFileInputFiles", {"nodeId": node,
            "files": [str(examples / name) for name in names]})

    def count_files():
        with SessionLocal() as db:
            return db.scalar(select(func.count()).select_from(MessageAttachment))

    navigate(f"/messages/{second_id}", "#message-body")
    wait_for(lambda: js('!document.querySelector(".message-draft-options").hidden'), "draft controls")
    choose(["nursing-notes.txt"])
    assert js('document.querySelectorAll(".message-selected-files li").length === 1')
    js('document.querySelector(".message-file-remove").click()')
    assert js('document.querySelectorAll(".message-selected-files li").length === 0')
    choose(["study-group.png", "voice-note.wav", "teaching-video.mp4", "clinical-guide.pdf"])
    assert js('document.querySelectorAll(".message-selected-files li").length === 4')
    assert js('document.querySelector(".message-selected-files img").src.startsWith("blob:")')
    choose(["nursing-notes.txt"])
    assert js('document.querySelectorAll(".message-selected-files li").length === 4')
    assert js('document.querySelector(".thread-status").textContent.includes("up to 4")')
    # File drafts cannot silently turn into text-only offline drafts.
    js('document.querySelector(".message-draft-options").open=true')
    js('document.querySelector("[data-message-draft-actions] button").click()')
    assert js('document.body.textContent.includes("Send attached files while connected")')
    js('document.querySelector(".message-draft-options").open=false')
    # Lose a committed file-message response and retain the original payload.
    paused.clear()
    cdp("Fetch.enable", {"patterns": [{"urlPattern": f"*/messages/{second_id}", "requestStage": "Response"}]})
    js('document.querySelector("form.message-compose").requestSubmit()')
    # Each real scan may consume its full allowance; uploads run sequentially.
    upload_allowance = 4 * (settings.evidence_scan_timeout_seconds + 15) + 30
    wait_for(lambda: js("true") and paused, "file message response", seconds=upload_allowance)
    assert count_files() == 4
    cdp("Fetch.failRequest", {"requestId": paused[0]["requestId"], "errorReason": "ConnectionClosed"})
    cdp("Fetch.disable")
    wait_for(lambda: js('!document.querySelector(".message-compose .btn-primary").disabled'), "retry ready")
    assert js('document.querySelectorAll(".message-selected-files li").length === 4 && document.querySelector("#message-files").disabled')
    js('document.querySelector("#message-body").value="A newer caption stays here"; document.querySelector("form.message-compose").requestSubmit()')
    wait_for(lambda: js('document.querySelector(".thread-status").textContent === "Message sent."'), "exact file retry")
    assert js('document.querySelector("#message-body").value === "A newer caption stays here"')
    assert js('document.querySelectorAll(".message-selected-files li").length === 0')
    assert js('document.querySelectorAll(".message-files .message-file-card").length === 4')
    with SessionLocal() as db:
        sent = list(db.scalars(select(DirectMessage).where(DirectMessage.sender_id == first_id)))
        assert len(sent) == 1 and sent[0].body == "" and len(sent[0].attachments) == 4
        assert db.get(MessageUploadUsage, first_id).size_bytes == sum((examples / n).stat().st_size for n in ["study-group.png", "voice-note.wav", "teaching-video.mp4", "clinical-guide.pdf"])

    # A new caption and document can be sent after the original is confirmed.
    choose(["nursing-notes.txt"])
    js('document.querySelector("form.message-compose").requestSubmit()')
    wait_for(lambda: js('document.querySelector("#message-body").value === ""'), "caption and document", seconds=settings.evidence_scan_timeout_seconds + 45)
    # Check received files from a separate member session.
    js("fetch('/auth/logout',{method:'POST',body:new URLSearchParams({csrf_token:document.querySelector('[name=csrf_token]').value})}).then(()=>true)")
    navigate("/auth/login", "#phone")
    js('document.querySelector("#phone").value="+2348000000078"; document.querySelector("#password").value="browser-password"; document.querySelector("form[action=\\"/auth/login\\"]").requestSubmit()')
    wait_for(lambda: js('location.pathname === "/" && document.readyState === "complete"'), "recipient login")
    navigate(f"/messages/{first_id}", "#message-body")
    wait_for(lambda: js('document.querySelectorAll(".message-file-card").length === 5'), "recipient attachments")
    assert js('Array.from(document.querySelectorAll(".message-bubble time")).every(t=>/ (AM|PM)$/.test(t.textContent.trim()) && !t.textContent.includes("UTC"))')
    assert js('document.querySelector(".message-file-image").complete && document.querySelector(".message-file-image").naturalWidth === 480')
    assert js("Promise.all(Array.from(document.querySelectorAll('audio,video')).map(m=>m.play().then(()=>true))).then(r=>r.every(Boolean))", user_gesture=True)
    wait_for(lambda: js("Array.from(document.querySelectorAll('audio,video')).every(m=>m.currentTime > 0 && m.readyState >= 2)"), "audio and video playback")
    js("document.querySelectorAll('audio,video').forEach(m=>m.pause())")
    # Returning through browser history must retain usable media sources.
    history_entry = cdp("Page.getNavigationHistory")["entries"][-1]["id"]
    navigate("/network")
    cdp("Page.navigateToHistoryEntry", {"entryId": history_entry})
    wait_for(lambda: js('!!document.querySelector(".message-file-image")'), "return to file conversation")
    assert js("Array.from(document.querySelectorAll('audio source,video source')).every(s=>s.src.includes('/messages/files/'))")
    assert js("Promise.all(Array.from(document.querySelectorAll('audio,video')).map(m=>m.play().then(()=>true))).then(r=>r.every(Boolean))", user_gesture=True)
    js("document.querySelectorAll('audio,video').forEach(m=>m.pause())")
    downloaded = js("fetch(document.querySelector('.message-file-download').href).then(async r=>({status:r.status,disposition:r.headers.get('content-disposition'),cache:r.headers.get('cache-control'),bytes:btoa(String.fromCharCode(...new Uint8Array(await r.arrayBuffer())))}))")
    assert downloaded["status"] == 200 and "attachment" in downloaded["disposition"] and "no-store" in downloaded["cache"]
    assert hashlib.sha256(base64.b64decode(downloaded["bytes"])).digest() == hashlib.sha256((examples / "study-group.png").read_bytes()).digest()
    axe_source = Path('/tmp/nurse-community-browser-tools/node_modules/axe-core/axe.min.js').read_text()
    audits = []
    for width, theme, large in [(390,"light",False),(1280,"light",False),(320,"dark",True),(390,"dark",False)]:
        viewport(width)
        js(f'document.documentElement.dataset.theme={json.dumps(theme)}; document.documentElement.dataset.textSize={json.dumps("large" if large else "normal")}')
        js('document.fonts.ready.then(()=>true)')
        js('document.querySelector(".thread-messages").scrollTop=document.querySelector(".thread-messages").scrollHeight')
        js(axe_source)
        result = js("axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']},rules:{'video-caption':{enabled:false}}}).then(r=>({violations:r.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>n.target)})),overflow:document.documentElement.scrollWidth>innerWidth+1}))")
        result.update(width=width,theme=theme,large=large)
        audits.append(result)
        assert not result['violations'] and not result['overflow'], result
        screenshot(f"files-{width}-{theme}{'-large' if large else ''}.png")
        assert js('document.querySelector(".message-compose-row").scrollWidth <= document.querySelector(".message-compose-row").clientWidth + 1')
    viewport(390)
    js('document.querySelector("[data-older]").click()')
    wait_for(lambda: js('document.querySelectorAll("[data-message-id]").length > 40'), "file history")
    with SessionLocal() as db:
        connection = db.get(Connection, connection_id)
        connection.status = "pending"
        db.commit()
    js('window.dispatchEvent(new Event("online"))')
    wait_for(lambda: js('document.querySelector("#message-body").disabled && document.querySelectorAll(".message-file-card").length === 0'), "revoked file access")
    assert not errors, errors
    result = {"status":"passed","audits":audits,"javascript_errors":errors,
        "caption_rule_scope":"Video sample is silent; spoken member videos are not evaluated for supplied captions.",
        "checks":["real picker selection and removal","count limits and image preview","offline draft guard",
        "scanned image/audio/video/PDF upload","file-only send","lost response exact retry preserves newer caption",
        "caption and text document","recipient image/audio/video playback","browser-history media recovery","private byte-for-byte download",
        "mobile/desktop/dark/enlarged-text reflow","older history","connection revocation clears media"]}
    (artifacts / 'results.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({"status":"passed","artifacts":str(artifacts),"audits":len(audits)}))

except Exception:
    if ws:
        screenshot("failure.png")
        print("Page:", js("location.pathname"))
        print("Status:", js('document.querySelector(".thread-status")?.textContent'))
    print("Artifacts:", artifacts)
    raise
finally:
    if ws:
        ws.close()
    for process in reversed(processes):
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    for log in logs:
        log.close()
