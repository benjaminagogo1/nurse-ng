# ruff: noqa: E402
"""Isolated Chrome + actual CLI worker exercise; no live accounts or external mail."""

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
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
artifacts = Path(tempfile.mkdtemp(prefix="nurse-reels-browser-"))


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


port, chrome_port = free_port(), free_port()
base = f"http://127.0.0.1:{port}"
os.environ.update({
    "NURSE_NG_ENVIRONMENT": "development", "NURSE_NG_DEBUG": "0",
    "NURSE_NG_SECRET_KEY": secrets.token_urlsafe(32), "NURSE_NG_SESSION_HTTPS_ONLY": "0",
    "NURSE_NG_ALLOWED_HOSTS": "127.0.0.1,localhost",
    "NURSE_NG_DATABASE_URL": f"sqlite:///{artifacts / 'browser.db'}",
    "NURSE_NG_PUBLIC_BASE_URL": base, "NURSE_NG_ACCOUNT_MAIL_BACKEND": "disabled",
    "NURSE_NG_COMMUNITY_MEDIA_DIR": str(artifacts / "media"),
    "NURSE_NG_COMMUNITY_MALWARE_SCAN_MODE": "disabled",
})
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from websockets.sync.client import connect

from app.db.session import SessionLocal
from app.models.community import CommunityTopic
from app.models.reels import Reel
from app.services.auth import register_user
from app.services.community import CommunityUpload, set_community_name
from app.services.reel_worker import ffmpeg_binary
from app.services.reels import create_reel

command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
with SessionLocal() as db:
    author = register_user(db, phone="+2348000000081", password="browser-password")
    set_community_name(db, author, "Reels Browser Creator")
    author_id = author.id
video = artifacts / "test-video.mp4"
subprocess.run([
    ffmpeg_binary(), "-v", "error", "-y", "-f", "lavfi", "-i",
    "testsrc2=size=540x960:rate=24", "-f", "lavfi", "-i", "sine=frequency=400",
    "-t", "5", "-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-movflags", "+faststart", str(video),
], check=True, timeout=30, capture_output=True)
processes, logs, errors = [], [], []
sequence, ws = 0, None


def wait_for(fn, label, seconds=40):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            value = fn()
            if value:
                return value
        except (OSError, ValueError):
            pass
        time.sleep(.1)
    raise AssertionError("Timed out: " + label)


def cdp(method, params=None):
    global sequence
    sequence += 1
    ws.send(json.dumps({"id": sequence, "method": method, "params": params or {}}))
    while True:
        result = json.loads(ws.recv(timeout=40))
        if result.get("method") == "Runtime.exceptionThrown":
            errors.append(result["params"])
        if result.get("id") == sequence:
            assert "error" not in result, result
            return result.get("result", {})


def js(expression):
    result = cdp("Runtime.evaluate", {
        "expression": expression, "returnByValue": True, "awaitPromise": True,
    })
    assert "exceptionDetails" not in result, result
    return result.get("result", {}).get("value")


def navigate(path):
    cdp("Page.navigate", {"url": base + path})
    wait_for(lambda: js(f"location.pathname === {json.dumps(path.split('?')[0])} && "
                        "document.readyState === 'complete'"), path)


def viewport(width, height=900):
    cdp("Emulation.setDeviceMetricsOverride", {
        "width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 900,
    })


def screenshot(name):
    js("new Promise(r => requestAnimationFrame(() => setTimeout(r, 150)))")
    assert js("document.documentElement.scrollWidth <= innerWidth + 1"), name + " overflows"
    (artifacts / name).write_bytes(base64.b64decode(cdp(
        "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False},
    )["data"]))


def worker():
    with SessionLocal() as db:
        pending = db.scalar(select(Reel.post_id).where(Reel.state == "queued"))
        assert pending is not None
    result = subprocess.run([
        sys.executable, "-m", "app.cli", "reels-worker", "--once",
    ], cwd=ROOT, env=os.environ.copy(), capture_output=True, text=True, timeout=90)
    with (artifacts / "worker.log").open("a") as log:
        log.write(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    with SessionLocal() as db:
        assert db.get(Reel, pending).state == "ready"


try:
    for name, args in [
        ("server", [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                    "--port", str(port), "--log-level", "warning"]),
        ("chrome", ["/usr/bin/google-chrome", "--headless=new", "--no-sandbox",
                    "--disable-dev-shm-usage", "--disable-gpu", "--disable-extensions",
                    "--disable-sync", "--no-first-run", "--no-default-browser-check",
                    "--password-store=basic", "--disable-background-networking",
                    f"--user-data-dir={artifacts / 'chrome'}",
                    f"--remote-debugging-port={chrome_port}", "about:blank"]),
    ]:
        log = (artifacts / (name + ".log")).open("w")
        logs.append(log)
        processes.append(subprocess.Popen(args, cwd=ROOT, env=os.environ.copy(),
                                          stdout=log, stderr=log))
    wait_for(lambda: urllib.request.urlopen(base + "/healthz", timeout=1).status == 200, "server")
    tabs = wait_for(lambda: json.load(urllib.request.urlopen(
        f"http://127.0.0.1:{chrome_port}/json/list", timeout=1,
    )), "Chrome")
    ws = connect(next(t["webSocketDebuggerUrl"] for t in tabs if t["type"] == "page"), legacy=True)
    cdp("Page.enable")
    cdp("Runtime.enable")
    cdp("Network.enable")
    viewport(1280)
    navigate("/reels")
    screenshot("01-empty-desktop.png")
    navigate("/auth/login")
    js("document.querySelector('[name=phone]').value='+2348000000081';"
       "document.querySelector('[name=password]').value='browser-password';"
       "document.querySelector('form[action=\"/auth/login\"]').requestSubmit()")
    wait_for(lambda: js("location.pathname === '/'"), "login")
    navigate("/reels/new")
    screenshot("02-upload-desktop.png")
    root = cdp("DOM.getDocument")["root"]["nodeId"]
    node = cdp("DOM.querySelector", {"nodeId": root, "selector": "#reel-file"})["nodeId"]
    cdp("DOM.setFileInputFiles", {"nodeId": node, "files": [str(video)]})
    wait_for(lambda: js("document.querySelector('[data-upload-preview]').duration > 0"), "preview")
    js("document.querySelector('#reel-body').value="
       "'A short guide to finding Nigerian internships. Browser test video.';"
       "document.querySelector('#reel-topic').selectedIndex=1;"
       "document.querySelector('[name=consent]').checked=true")
    viewport(390, 844)
    screenshot("03-upload-mobile.png")
    cdp("Network.emulateNetworkConditions", {"offline": True, "latency": 0,
                                            "downloadThroughput": -1, "uploadThroughput": -1})
    js("document.querySelector('[data-reel-upload]').requestSubmit()")
    wait_for(lambda: js("!document.querySelector('[data-feedback-panel]').hidden"), "offline error")
    assert js("document.querySelector('#feedback-body').textContent.includes('offline')")
    screenshot("04-visible-upload-error.png")
    cdp("Network.emulateNetworkConditions", {"offline": False, "latency": 0,
                                            "downloadThroughput": -1, "uploadThroughput": -1})
    cdp("Network.overrideNetworkState", {"offline": False, "latency": 0,
                                        "downloadThroughput": -1, "uploadThroughput": -1})
    js("document.querySelector('[data-reel-upload]').requestSubmit()")
    wait_for(lambda: js("location.pathname.endsWith('/status')"), "uploaded")
    screenshot("05-processing-mobile.png")
    worker()
    wait_for(lambda: js("document.querySelector('[data-status-title]').textContent === "
                        "'Your reel is live'"), "ready")
    assert js("document.querySelector('[data-status-body]').textContent.includes('Community')")
    screenshot("06-ready-mobile.png")
    with SessionLocal() as db:
        reel = db.scalar(select(Reel))
        post_id = str(reel.post_id)
        from app.models.user import User

        with video.open("rb") as stream:
            create_reel(db, db.get(User, author_id), topic_id=db.scalar(select(CommunityTopic.id)),
                        body="A second browser test reel for playback and keyboard navigation.",
                        video=CommunityUpload(stream, "second.mp4"), category="career",
                        audience="nigeria", upload_key=str(uuid.uuid4()),
                        captions=b"WEBVTT\n\n00:00:00.000 --> 00:00:04.800\nTest captions")
    worker()
    navigate("/reels")
    wait_for(lambda: js("!!document.querySelector('[data-active] video')?.currentSrc"),
             "active reel")
    js("if (document.querySelector('[data-active] video').paused) "
       "document.querySelector('[data-active] [data-play]').click()")
    wait_for(lambda: js("document.querySelector('[data-active] video').currentTime > 0 && "
                        "!document.querySelector('[data-active] video').paused"), "video playing")
    wait_for(lambda: js("document.querySelector('[data-active] video').textTracks[0]"
                        "?.cues?.length === 1"), "captions loaded")
    assert js("[...document.querySelectorAll('[data-reel] video')]"
              ".filter(v => !v.paused).length <= 1")
    assert js("[...document.querySelectorAll('[data-reel] video')]"
              ".filter(v => v.hasAttribute('src')).length === 1")
    screenshot("07-viewer-mobile.png")
    liked_post = js("document.querySelector('[data-active] [data-post-like]').dataset.postLike")
    js("document.querySelector('[data-active] [data-post-like]').requestSubmit()")
    wait_for(lambda: js("document.querySelector('[data-active] [data-like-label]')"
                        ".textContent === 'Liked'"), "like reel")
    assert js("document.querySelector('[data-active] [data-like-count]').textContent") == "1"
    screenshot("07-liked-mobile.png")
    navigate("/posts/" + liked_post)
    assert js("document.querySelector('[data-like-count]').textContent") == "1"
    assert js("document.querySelector('[data-post-like] button')"
              ".getAttribute('aria-pressed')") == "true"
    js("document.querySelector('[data-post-like]').requestSubmit()")
    wait_for(lambda: js("document.querySelector('[data-like-label]').textContent === 'Like'"),
             "unlike community video")
    assert js("document.querySelector('[data-like-count]').textContent") == "0"
    navigate("/reels")
    wait_for(lambda: js("!!document.querySelector('[data-active] video')?.currentSrc"),
             "return to reels")
    js("document.querySelector('[data-data-saver]').click()")
    assert js("document.querySelector('[data-active] video').paused")
    assert js("document.querySelector('[data-active] video').src.endsWith("
              "document.querySelector('[data-active] video').dataset.low)")
    js("document.querySelector('[data-active] [data-reel-action=save]').requestSubmit()")
    wait_for(lambda: js("document.querySelector('[data-active] [data-save-label]')"
                        ".textContent === 'Saved'"), "save")
    js("document.querySelector('[data-active] [data-comments]').click()")
    wait_for(lambda: js("!!document.querySelector('#reel-comment-body')"), "comments")
    js("document.querySelector('#reel-comment-body').value='A helpful browser test comment.';"
       "document.querySelector('[data-reel-action=comment]').requestSubmit()")
    wait_for(lambda: js("document.querySelector('.reel-comments-list').textContent.includes("
                        "'A helpful browser test comment.')"), "comment posted")
    screenshot("08-comments-mobile.png")
    assert js("[...document.querySelectorAll('[data-reel] video')].every(v => v.paused)")
    js("document.querySelector('#reel-comments [data-close-dialog]').click()")
    old = js("document.querySelector('[data-active]').dataset.reel")
    js("document.querySelector('[data-next]').click()")
    wait_for(lambda: js("document.querySelector('[data-active]').dataset.reel") != old, "next reel")
    assert js("[...document.querySelectorAll('[data-reel] video')]"
              ".filter(v => v.hasAttribute('src')).length === 1")
    for width in (320, 1280):
        viewport(width, 900)
        navigate("/reels")
        screenshot(f"09-viewer-{width}.png")
    cdp("Emulation.setEmulatedMedia", {"features": [
        {"name": "prefers-color-scheme", "value": "dark"},
        {"name": "prefers-reduced-motion", "value": "reduce"},
    ]})
    navigate("/reels")
    screenshot("10-dark-desktop.png")
    assert js("[...document.querySelectorAll('[data-reel] video')].every(v => v.paused)")
    cdp("Emulation.setEmulatedMedia", {"features": [
        {"name": "prefers-color-scheme", "value": "light"},
        {"name": "prefers-reduced-motion", "value": "reduce"},
    ]})
    navigate("/reels")
    screenshot("11-light-desktop.png")
    viewport(320, 900)
    js("document.documentElement.style.fontSize='24px'")
    screenshot("12-large-text-320.png")
    assert not errors, errors
    print(json.dumps({
        "ok": True, "artifacts": str(artifacts), "post_id": post_id,
        "checks": "upload, offline feedback, actual worker, status polling, playback, "
        "single active source, shared reel/community likes, unlike, data saver, saves, "
        "comments, navigation, 320/390/1280px",
    }))
finally:
    if ws:
        ws.close()
    for process in reversed(processes):
        process.terminate()
    for process in reversed(processes):
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    for log in logs:
        log.close()
    print("Artifacts:", artifacts)
