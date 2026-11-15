# ruff: noqa: E402, E501
"""Exercise the actual bundled document at the site origin, without a service worker.

Chrome's request interception stands in for the native document loader only.
Storage, Web Crypto, drafts, HTTP session/CSRF checks and sync use real code.
This does not substitute for running WKWebView/Android WebView on a device.
"""

import base64
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
artifacts = Path(tempfile.mkdtemp(prefix="nurse-native-offline-"))


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


web_port, chrome_port = port(), port()
base = f"http://127.0.0.1:{web_port}"
os.environ.update({
    "NURSE_NG_ENVIRONMENT": "development", "NURSE_NG_DEBUG": "0",
    "NURSE_NG_SECRET_KEY": secrets.token_urlsafe(32), "NURSE_NG_SESSION_HTTPS_ONLY": "0",
    "NURSE_NG_ALLOWED_HOSTS": "127.0.0.1,localhost", "NURSE_NG_PUBLIC_BASE_URL": base,
    "NURSE_NG_DATABASE_URL": f"sqlite:///{artifacts / 'browser.db'}",
    "NURSE_NG_ACCOUNT_MAIL_BACKEND": "disabled", "NURSE_NG_REQUIRED_WORKERS": "",
})
from sqlalchemy import func, select
from websockets.sync.client import connect

import app.models  # noqa: F401
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.community import CommunityPost
from app.models.offline import OfflineOperation
from app.models.profile import NurseProfile
from app.models.user import User
from app.services.auth import register_user
from app.services.community import create_topic, set_community_name
from app.services.jobs import create_job
from app.services.profiles import save_profile
from tests.helpers import approve_test_employer

Base.metadata.create_all(engine)
with SessionLocal() as db:
    member = register_user(db, phone="+2348000000051", password="offline-test-password", full_name="Offline Member")
    member_id = member.id
    save_profile(db, member, display_name="Offline Member", professional_status="student", headline="Original headline", location="Lagos", bio="Saved member biography")
    set_community_name(db, member, "Offline Member")
    second = register_user(db, phone="+2348000000052", password="offline-test-password", full_name="Second Member")
    second_id = second.id
    employer = register_user(db, phone="+2348000000053", password="offline-test-password", full_name="Test Employer", account_type="employer")
    employer.is_staff = True
    db.commit()
    topic = create_topic(db, employer, name="Offline testing", description="")
    topic_id = str(topic.id)
    approve_test_employer(db, employer, "Test Hospital")
    create_job(db, employer, title="Saved mobile opportunity", organization="Test Hospital", location="Lagos", job_type="full_time", work_mode="on_site", salary_min="", salary_max="", description="Read these job details without internet.")

bundle_path = artifacts / "offline.html"
subprocess.run([sys.executable, str(ROOT / "mobile/scripts/bundle-offline.py"), str(bundle_path)], check=True, cwd=ROOT)
bundle_body = base64.b64encode(bundle_path.read_bytes()).decode()
processes, logs, errors = [], [], []
ws, sequence = None, 0


def wait(fn, label):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        try:
            value = fn()
            if value:
                return value
        except (OSError, ValueError):
            pass
        time.sleep(.1)
    raise AssertionError("Timed out: " + label)


def send(method, params):
    global sequence
    sequence += 1
    ws.send(json.dumps({"id": sequence, "method": method, "params": params}))
    return sequence


def cdp(method, params=None):
    call = send(method, params or {})
    while True:
        message = json.loads(ws.recv(timeout=45))
        if message.get("method") == "Runtime.exceptionThrown":
            errors.append(message["params"])
        if message.get("method") == "Fetch.requestPaused":
            send("Fetch.fulfillRequest", {
                "requestId": message["params"]["requestId"], "responseCode": 200,
                "responseHeaders": [{"name": "Content-Type", "value": "text/html; charset=utf-8"}],
                "body": bundle_body,
            })
        if message.get("id") == call:
            assert "error" not in message, message
            return message.get("result", {})


def js(expression):
    result = cdp("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
    assert "exceptionDetails" not in result, result
    return result.get("result", {}).get("value")


def navigate(path):
    cdp("Page.navigate", {"url": base + path})
    wait(lambda: js(f"location.pathname === {json.dumps(path)} && document.readyState === 'complete'"), path)
    js("NurseOffline.ready")


def attach():
    global ws
    tabs = wait(lambda: json.load(urllib.request.urlopen(f"http://127.0.0.1:{chrome_port}/json/list", timeout=1)), "Chrome")
    ws = connect(next(tab["webSocketDebuggerUrl"] for tab in tabs if tab["type"] == "page"), legacy=True, max_size=32 * 1024 * 1024)
    for domain in ["Page", "Runtime", "Network"]:
        cdp(domain + ".enable")
    cdp("Network.setBypassServiceWorker", {"bypass": True})
    cdp("Emulation.setFocusEmulationEnabled", {"enabled": True})
    cdp("Fetch.enable", {"patterns": [{"urlPattern": base + "/offline-shell", "resourceType": "Document"}]})


def network(offline):
    cdp("Network.emulateNetworkConditions", {"offline": offline, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1})
    cdp("Network.overrideNetworkState", {"offline": offline, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1})


def restart_offline():
    global ws
    args = processes[1].args
    cdp("Browser.close")
    ws.close()
    ws = None
    processes[1].wait(timeout=15)
    processes[1] = subprocess.Popen(args, cwd=ROOT, env=os.environ.copy(), stdout=logs[1], stderr=logs[1])
    attach()
    network(True)
    navigate("/offline-shell")
    network(True)


def login(phone):
    navigate("/auth/login")
    js(f'document.querySelector("#phone").value={json.dumps(phone)}; document.querySelector("#password").value="offline-test-password"; document.querySelector("form[action=\\"/auth/login\\"]").requestSubmit()')
    wait(lambda: js("location.pathname === '/' && document.readyState === 'complete'"), "login")
    assert js("NurseOffline.ready")


def screenshot(name):
    (artifacts / name).write_bytes(base64.b64decode(cdp("Page.captureScreenshot", {"format": "png"})["data"]))


def interrupted(signum, frame):
    raise SystemExit(128 + signum)


signal.signal(signal.SIGTERM, interrupted)


try:
    for name, command in [
        ("server", [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(web_port), "--log-level", "warning"]),
        ("chrome", ["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--no-first-run", "--no-default-browser-check", f"--user-data-dir={artifacts / 'chrome'}", f"--remote-debugging-port={chrome_port}", "about:blank"]),
    ]:
        log = (artifacts / (name + ".log")).open("w")
        logs.append(log)
        processes.append(subprocess.Popen(command, cwd=ROOT, env=os.environ.copy(), stdout=log, stderr=log))
    server_args = processes[0].args
    wait(lambda: urllib.request.urlopen(base + "/healthz", timeout=1).status == 200, "server")
    attach()
    # A fresh installation has no account or cached member data to unlock.
    navigate("/offline-shell")
    assert js("window.NurseNativeOffline && !NurseOffline.store.available")
    print("Passed: fresh bundled workspace without an account", flush=True)
    login("+2348000000051")
    navigate("/profile/edit")
    wait(lambda: js("NurseOffline.store.get('record','profile:self').then(Boolean)"), "saved profile")
    navigate("/jobs")
    wait(lambda: js("NurseOffline.store.list('record').then(r=>r.some(x=>x.value.kind==='job'))"), "saved job")
    navigate("/posts/new")
    wait(lambda: js("!!document.querySelector('form[action=\"/posts\"] .offline-actions')"), "draft controls")
    js(f'document.querySelector("[name=topic_id]").value={json.dumps(topic_id)}; document.querySelector("[name=body]").value="Draft saved before closing"')
    js("[...document.querySelectorAll('form[action=\"/posts\"] button')].find(b=>b.textContent==='Save draft locally').click()")
    wait(lambda: js("NurseOffline.store.get('draft','post:/posts').then(d=>d?.payload.body==='Draft saved before closing')"), "saved draft")
    print("Passed: online preparation of profile, job and draft", flush=True)
    # Remove the browser fallback entirely; native recovery must not depend on it.
    js("Promise.all([navigator.serviceWorker.getRegistrations().then(rs=>Promise.all(rs.map(r=>r.unregister()))), caches.keys().then(ns=>Promise.all(ns.map(n=>caches.delete(n))))])")
    processes[0].terminate()
    processes[0].wait(timeout=10)
    restart_offline()
    assert js("NurseOffline.ready")
    assert js("!navigator.serviceWorker.controller && caches.keys().then(x=>x.length===0)")
    state = js("({online:navigator.onLine,bundled:window.NurseNativeOffline})")
    assert state == {"online": False, "bundled": True}, state
    assert js("NurseOffline.store.get('draft','post:/posts').then(d=>d.payload.body==='Draft saved before closing')")
    print("Passed: full offline restart without service worker or cache", flush=True)
    wait(lambda: js("!!document.querySelector('[data-record-key=\"profile:self\"] button')"), "offline library")
    for width in [320, 390, 1280]:
        cdp("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": width < 900})
        assert js("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
        screenshot(f"offline-workspace-{width}.png")
    js("document.querySelector('[data-record-key=\"profile:self\"] button').click()")
    js("document.querySelector('[data-offline-profile-form] [name=headline]').value='Edited without internet'; document.querySelector('[data-offline-profile-form]').requestSubmit()")
    wait(lambda: js("NurseOffline.store.list('operation').then(r=>r.length===1)"), "queued profile")
    js("document.querySelector('[data-draft-kind=post] button').click()")
    js("document.querySelector('[data-offline-compose=post] [name=body]').value='Post edited in native offline workspace'; document.querySelector('[data-offline-compose=post]').requestSubmit()")
    wait(lambda: js("NurseOffline.store.list('operation').then(r=>r.length===2)"), "queued post")
    ids = js("NurseOffline.store.list('operation').then(r=>r.map(x=>x.id).sort())")
    restart_offline()
    assert js("NurseOffline.store.list('operation').then(r=>r.map(x=>x.id).sort())") == ids
    assert js("NurseOffline.store.list('operation').then(r=>r.every(x=>x.value.status==='pending'))")
    print("Passed: offline edits and queued sends survive another restart", flush=True)
    with SessionLocal() as db:
        assert db.scalar(select(NurseProfile.headline).where(NurseProfile.user_id == member_id)) == "Original headline"
        assert db.scalar(select(func.count()).select_from(CommunityPost)) == 0
    # Reconnect inside the bundled document and lose one committed response.
    js("""(() => {
      const real = NurseOffline.fetch; let drop = true;
      NurseOffline.fetch = async (...args) => {
        const response = await real(...args);
        if (drop && args[0] === '/offline/operations' && response.ok) {
          drop = false; throw new TypeError('Simulated lost acknowledgement');
        }
        return response;
      };
    })()""")
    processes[0] = subprocess.Popen(server_args, cwd=ROOT, env=os.environ.copy(), stdout=logs[0], stderr=logs[0])
    wait(lambda: urllib.request.urlopen(base + "/healthz", timeout=1).status == 200, "server reconnect")
    network(False)
    wait(lambda: js("NurseOffline.store.list('operation').then(r=>r.length===2 && r.every(x=>x.value.status==='confirmed'))"), "automatic sync after reconnect")
    js("NurseOffline.sync(true)")
    with SessionLocal() as db:
        assert db.scalar(select(NurseProfile.headline).where(NurseProfile.user_id == member_id)) == "Edited without internet"
        assert db.scalar(select(func.count()).select_from(CommunityPost)) == 1
        assert db.scalar(select(func.count()).select_from(OfflineOperation)) == 2
    navigate("/")
    js("document.querySelector('form[action=\"/auth/logout\"]').requestSubmit()")
    wait(lambda: js("document.readyState==='complete' && !document.querySelector('.account-menu') && !NurseOffline.store.available"), "logout clears workspace")
    login("+2348000000052")
    navigate("/offline-shell")
    assert js("NurseOffline.store.get('draft','post:/posts').then(x=>x===null)")
    assert js("NurseOffline.store.list('operation').then(x=>x.length===0)")
    assert js("NurseOffline.store.get('record','profile:self').then(x=>x===null)")
    # Revocation must be learned even with no queued operations or saved records.
    js("NurseOffline.store.put('draft','private-unsent',{body:'Second account private draft'})")
    with SessionLocal() as db:
        db.get(User, second_id).auth_version += 1
        db.commit()
    navigate("/offline-shell")
    wait(lambda: js("!NurseOffline.store.available"), "revoked draft-only session cleared")
    assert not errors, errors
    assert not (artifacts / "server.log").read_text().strip()
    report = {"passed": True, "loader": "Chrome document interception at the site origin; native loader not executed", "service_worker": "bypassed and caches cleared", "checks": ["first use", "saved jobs/profile/draft", "two full offline browser restarts", "offline profile edit and post queue", "automatic sync", "lost acknowledgement with no duplicate", "logout and account isolation", "draft-only session revocation"], "widths": [320, 390, 1280], "artifacts": str(artifacts)}
    (artifacts / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)
finally:
    if ws:
        ws.close()
    for process in reversed(processes):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    for log in logs:
        log.close()
