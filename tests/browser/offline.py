# ruff: noqa: E402
"""Exercise real offline navigation, encrypted data and idempotent synchronization."""

import base64
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from email import policy
from email.parser import BytesParser
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
artifacts = Path(tempfile.mkdtemp(prefix="nurse-offline-browser-"))


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
        "NURSE_NG_ACCOUNT_MAIL_BACKEND": "file",
        "NURSE_NG_GOOGLE_CLIENT_ID": "",
        "NURSE_NG_LINKEDIN_CLIENT_ID": "",
        "NURSE_NG_ACCOUNT_MAIL_DIR": str(artifacts / "mail"),
        "NURSE_NG_AVATAR_DIR": str(artifacts / "avatars"),
        "NURSE_NG_COMMUNITY_MEDIA_DIR": str(artifacts / "media"),
        "NURSE_NG_COMMUNITY_MALWARE_SCAN_MODE": "disabled",
        "NURSE_NG_SMTP_FROM": "Nurse.ng <no-reply@example.org>",
    }
)
from alembic import command
from alembic.config import Config
from PIL import Image
from sqlalchemy import func, select
from websockets.sync.client import connect

from app.db.session import SessionLocal
from app.models.messages import DirectMessage
from app.models.offline import OfflineOperation
from app.models.offline_upload import OfflineUpload
from app.models.profile import NurseProfile
from app.models.reels import Reel
from app.services import reel_worker
from app.services.auth import register_user
from app.services.jobs import create_job
from app.services.profiles import save_profile

command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
with SessionLocal() as db:
    user = register_user(
        db,
        phone="+2348000000077",
        password="browser-password",
        email="browser@example.org",
        full_name="Browser Member",
    )
    user_id = user.id
    save_profile(
        db,
        user,
        display_name="Browser Member",
        professional_status="student",
        headline="Original headline",
        location="Lagos",
        bio="Saved professional bio",
    )
picture = artifacts / "photo.jpg"
Image.new("RGB", (640, 480), "#087c72").save(picture)
video_path = artifacts / "offline-clip.mp4"
subprocess.run(
    [
        reel_worker.ffmpeg_binary(),
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=360x640:rate=24",
        "-t",
        "1.5",
        "-c:v",
        "libx264",
        "-threads",
        "1",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(video_path),
    ],
    check=True,
    capture_output=True,
    timeout=30,
)
with video_path.open("ab") as file:
    padding = b"\x00" * (2 * 1024 * 1024)
    file.write((len(padding) + 8).to_bytes(4, "big") + b"free" + padding)
processes = []
logs = []
ws = None
sequence = 0
errors = []
paused = []


def wait_for(fn, label, seconds=45):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            value = fn()
            if value:
                return value
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


def js(expression):
    result = cdp(
        "Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True}
    )
    assert "exceptionDetails" not in result, result
    return result.get("result", {}).get("value")


def navigate(path, selector="main"):
    cdp("Page.navigate", {"url": base + path})
    target_path = path.split("?")[0].split("#")[0]
    wait_for(
        lambda: js(
            f"location.pathname === {json.dumps(target_path)} && "
            f'document.readyState === "complete" && '
            f"!!document.querySelector({json.dumps(selector)})"
        ),
        path,
    )
    js("window.NurseOffline?.ready || Promise.resolve(false)")


def attach(target_id=None, offline=False):
    global ws
    tabs = wait_for(
        lambda: json.load(
            urllib.request.urlopen(f"http://127.0.0.1:{chrome_port}/json/list", timeout=1)
        ),
        "Chrome page",
    )
    ws = connect(
        next(
            tab["webSocketDebuggerUrl"]
            for tab in tabs
            if tab["id"] == target_id or (target_id is None and tab["type"] == "page")
        ),
        legacy=True,
        max_size=16 * 1024 * 1024,
    )
    cdp("Page.enable")
    cdp("Runtime.enable")
    cdp("Network.enable")
    cdp("Emulation.setFocusEmulationEnabled", {"enabled": True})
    viewport()
    network(offline)


def network(offline):
    cdp(
        "Network.emulateNetworkConditions",
        {"offline": offline, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1},
    )


def fresh_tab(offline=False):
    """Close the original tab; no opener or sessionStorage is copied to its replacement."""
    previous_ws = ws
    previous_id = cdp("Target.getTargetInfo")["targetInfo"]["targetId"]
    target_id = cdp("Target.createTarget", {"url": "about:blank"})["targetId"]
    attach(target_id, offline)
    cdp("Target.closeTarget", {"targetId": previous_id})
    previous_ws.close()


def restart_browser(offline=False):
    """Gracefully exit all of Chrome and restart it using only its on-disk profile."""
    global ws
    args = processes[1].args
    cdp("Browser.close")
    ws.close()
    ws = None
    processes[1].wait(timeout=15)
    processes[1] = subprocess.Popen(
        args, cwd=ROOT, env=os.environ.copy(), stdout=logs[1], stderr=logs[1]
    )
    attach(offline=offline)


def seed_legacy(body):
    """Build the previous release's encrypted rows and tab-only raw key."""
    return js(
        """(async body => {
      const scope = NurseOffline.store.scope || document.body.dataset.draftScope;
      const tab = crypto.randomUUID(), secret = crypto.getRandomValues(new Uint8Array(32));
      const key = await crypto.subtle.importKey('raw', secret, 'AES-GCM', false,
        ['encrypt', 'decrypt']);
      const id = 'post:/posts', version = crypto.randomUUID(), operation = crypto.randomUUID();
      const payload = {body, topic_id: 'legacy-topic', community_name: 'Saved contributor'};
      const values = [
        ['draft', id, {id, kind: 'post', path: '/posts', title: 'Legacy draft', fields: [],
          target: {}, version, payload, operation}],
        ['operation', operation, {id: operation, kind: 'post', target: id, title: 'Legacy send',
          payload, status: 'failed', attempts: 1, created: Date.now(),
          metadata: {draft: {id, version}}, message: 'Review before sending'}],
      ];
      const encrypted = [];
      for (const [kind, item, value] of values) {
        const iv = crypto.getRandomValues(new Uint8Array(12));
        const cipher = await crypto.subtle.encrypt({name: 'AES-GCM', iv}, key,
          new TextEncoder().encode(JSON.stringify(value)));
        encrypted.push({id: scope + ':' + tab + ':' + kind + ':' + item,
          scope, tab, kind, item, iv, cipher, saved: Date.now(), expires: Date.now() + 86400000});
      }
      const db = await new Promise(resolve => {
        const r = indexedDB.open('nurse-offline-v1'); r.onsuccess = () => resolve(r.result);
      });
      await new Promise((resolve, reject) => {
        const tx = db.transaction('records', 'readwrite');
        for (const row of encrypted) tx.objectStore('records').put(row);
        tx.oncomplete = resolve; tx.onabort = () => reject(tx.error);
      });
      db.close();
      sessionStorage.setItem('nurse-offline-context', JSON.stringify({scope, tab,
        secret: Array.from(secret)}));
      localStorage.setItem('nurse-offline-active', scope);
      return {scope, tab, id, version, operation, payload};
    })("""
        + json.dumps(body)
        + ")"
    )


def raw_rows(expression):
    return js(
        """(async () => {
      const db = await new Promise(resolve => {
        const r = indexedDB.open('nurse-offline-v1'); r.onsuccess = () => resolve(r.result);
      });
      const rows = await new Promise(resolve => {
        const r = db.transaction('records').objectStore('records').getAll();
        r.onsuccess = () => resolve(r.result);
      });
      db.close();
      return """
        + expression
        + "; })()"
    )


def fill(selector, value):
    js(f"document.querySelector({json.dumps(selector)}).value={json.dumps(value)}")


def submit(action):
    selector = f'form[method="post"][action="{action}"]'
    js(f"document.querySelector({json.dumps(selector)}).requestSubmit()")


def screenshot(name):
    js("new Promise(resolve => requestAnimationFrame(() => setTimeout(resolve, 250)))")
    assert js("""(() => {
      const panel = document.querySelector('[data-feedback-panel]');
      if (!panel || panel.hidden) return true;
      const rect = panel.getBoundingClientRect();
      const header = document.querySelector('.site-header').getBoundingClientRect();
      return rect.top >= header.bottom - 1 && rect.bottom <= innerHeight + 1;
    })()"""), f"Feedback must be visible below the header: {name}"
    (artifacts / name).write_bytes(
        base64.b64decode(
            cdp("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})["data"]
        )
    )


def feedback(title):
    return js(
        f'!document.querySelector("[data-feedback-panel]")?.hidden && '
        f'document.querySelector("#feedback-title")?.textContent === {json.dumps(title)}'
    )


def select_photo(path):
    node = cdp("DOM.getDocument")["root"]["nodeId"]
    input_id = cdp("DOM.querySelector", {"nodeId": node, "selector": "#profile-photo"})["nodeId"]
    cdp("DOM.setFileInputFiles", {"nodeId": input_id, "files": [str(path)]})


def viewport(width=390, height=844):
    cdp(
        "Emulation.setDeviceMetricsOverride",
        {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 900},
    )


def email_link():
    paths = list((artifacts / "mail").glob("*.eml"))
    if not paths:
        return None
    message = BytesParser(policy=policy.default).parsebytes(
        max(paths, key=lambda p: p.stat().st_mtime_ns).read_bytes()
    )
    match = re.search(r"http://[^\s]+#token=[A-Za-z0-9_-]{43}", message.get_content())
    return match.group(0) if match else None


from app.models.community import Connection
from app.services.community import (
    connection_pair_key,
    create_post,
    create_topic,
    set_community_name,
)

with SessionLocal() as db:
    staff = register_user(
        db,
        phone="+2348000000078",
        password="browser-password",
        full_name="Quality Staff",
        account_type="employer",
    )
    staff_id = str(staff.id)
    staff.is_staff = True
    db.commit()
    topic = create_topic(db, staff, name="Quality community", description="")
    topic_id = str(topic.id)
    set_community_name(db, staff, "Offline Staff")
    conversation = create_post(
        db, staff, topic_id=topic.id, body="Browser community conversation", external_video_url=""
    )
    post_id = str(conversation.id)
    db.add(
        Connection(
            requester_user_id=user_id,
            recipient_user_id=staff.id,
            pair_key=connection_pair_key(user_id, staff.id),
            status="accepted",
        )
    )
    db.commit()
    listing = create_job(
        db,
        staff,
        title="Offline browser opportunity",
        organization="Test Hospital",
        location="Abuja",
        job_type="full_time",
        work_mode="on_site",
        salary_min="",
        salary_max="",
        description="Original role details for the browser test.",
    )
    job_id = str(listing.id)

axe_path = Path(
    os.environ.get(
        "NURSE_NG_AXE_SCRIPT", "/tmp/nurse-quality-tools/node_modules/axe-core/axe.min.js"
    )
)
axe_source = axe_path.read_text()
audits = []


def key(name, code):
    cdp(
        "Input.dispatchKeyEvent",
        {
            "type": "keyDown",
            "key": name,
            "code": name,
            "windowsVirtualKeyCode": code,
            "nativeVirtualKeyCode": code,
            "text": "\r" if name == "Enter" else "",
        },
    )
    cdp(
        "Input.dispatchKeyEvent",
        {
            "type": "keyUp",
            "key": name,
            "code": name,
            "windowsVirtualKeyCode": code,
            "nativeVirtualKeyCode": code,
        },
    )


def audit(path, width=390, large=False):
    viewport(width, 1000)
    navigate(path)
    if large:
        js("document.documentElement.style.fontSize='32px'")
    js(axe_source)
    result = js(
        """axe.run(document, {runOnly: {type:'tag', values:[
'wcag2a','wcag2aa','wcag21aa','wcag22aa']}}).then(r => ({

violations:r.violations
.map(v => ({
id:v.id,
nodes:v.nodes
.map(n=>({target:n.target, summary:n.failureSummary}))})),
manual:r.incomplete
.map(v=>v.id)}))"""
    )
    overflow = js(
        """[...document.querySelectorAll('main *, .site-header *')]
.filter(e=>e.getClientRects().length &&
e.getBoundingClientRect().right > document.documentElement.clientWidth+2)
.slice(0,12)
.map(e=>({tag:e.tagName, cls:e.className, width:e.getBoundingClientRect().width, text:e.textContent
.slice(0,60)}))"""
    )
    result.update(path=path, width=width, large=large, overflow=overflow)
    audits.append(result)
    (artifacts / "audits.json").write_text(json.dumps(audits, indent=2))
    assert not result["violations"], result
    assert js("document.documentElement.scrollWidth <= document.documentElement.clientWidth+2"), (
        result
    )
    assert js(
        "[...document.querySelectorAll("
        "'.site-header a, .site-header button, .site-header summary')]"
        ".filter(e => e.getClientRects().length && e.getBoundingClientRect().width > 1)"
        ".every(e => e.getBoundingClientRect().right <= document.documentElement.clientWidth+2)"
    ), result
    (artifacts / (str(len(audits)) + "-page.png")).write_bytes(
        base64.b64decode(
            cdp("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})["data"]
        )
    )


def login(phone):
    navigate("/auth/login")
    fill("#phone", phone)
    fill("#password", "browser-password")
    submit("/auth/login")
    wait_for(lambda: js("location.pathname==='/' && document.readyState==='complete'"), "sign in")


def logout():
    js("document.querySelector('form[action=\"/auth/logout\"]').requestSubmit()")
    wait_for(
        lambda: js("location.pathname==='/' && !document.querySelector('.account-menu')"),
        "sign out",
    )


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
        log = (artifacts / (name + ".log")).open("w")
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
    ws = connect(
        next(t["webSocketDebuggerUrl"] for t in tabs if t["type"] == "page"),
        legacy=True,
        max_size=16 * 1024 * 1024,
    )
    cdp("Page.enable")
    cdp("Emulation.setFocusEmulationEnabled", {"enabled": True})
    cdp("Runtime.enable")
    cdp("Network.enable")
    cdp(
        "Emulation.setDeviceMetricsOverride",
        {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True},
    )
    login("+2348000000077")
    navigate("/profile/edit")
    assert js("NurseOffline.ready")
    wait_for(
        lambda: js("NurseOffline.store.get('record', 'profile:self').then(Boolean)"),
        "profile cached",
    )
    navigate("/jobs")
    wait_for(
        lambda: js(
            "NurseOffline.store.list('record').then(rows => rows.some(r => r.value.kind === 'job'))"
        ),
        "jobs cached",
    )
    navigate("/learning/materials/application-checklist")
    js("document.querySelector('[data-offline-download]').click()")
    wait_for(
        lambda: js(
            "NurseOffline.store.get('record','learning:application-checklist').then(Boolean)"
        ),
        "guide downloaded",
    )
    navigate("/posts/new")
    wait_for(
        lambda: js("!!document.querySelector('form[action=\"/posts\"] .offline-actions')"),
        "durable draft controls",
    )
    fill('form[action="/posts"] [name=body]', "A draft kept across browser closure")
    js(
        "[...document.querySelectorAll('form[action=\"/posts\"] button')]"
        ".find(b => b.textContent === 'Save draft locally').click()"
    )
    wait_for(
        lambda: js(
            "NurseOffline.store.get('draft', 'post:/posts')"
            ".then(d => d?.payload.body === 'A draft kept across browser closure')"
        ),
        "draft saved before closing",
    )
    navigate("/offline")
    assert js("NurseOffline.ready")
    wait_for(lambda: js("!!navigator.serviceWorker.controller"), "worker controlling page")
    js("NurseOffline.store.put('test', 'private', {body: 'Private offline text'})")
    assert (
        js("NurseOffline.store.get('test', 'private').then(v => v.body)") == "Private offline text"
    )
    assert js("""(async () => {
      const db = await new Promise((resolve, reject) => {
        const request = indexedDB.open('nurse-offline-v1');
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
      const rows = await new Promise((resolve, reject) => {
        const request = db.transaction('records').objectStore('records').getAll();
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
      db.close();
      const vault = rows.find(row => row.kind === '_vault');
      if (!(vault?.key instanceof CryptoKey) || vault.key.extractable) return false;
      let exported = false;
      try { await crypto.subtle.exportKey('raw', vault.key); exported = true; } catch {}
      return !exported && rows.filter(row => !row.kind.startsWith('_'))
        .every(row => row.cipher instanceof ArrayBuffer &&
          !('secret' in row) && !('value' in row)) &&
        sessionStorage.getItem('nurse-offline-context') === null &&
        !JSON.stringify(rows).includes('Private offline text');
    })()""")
    assert js("""(async () => {
      await NurseOffline.store.put('test', 'expired', {body: 'Expired text'}, {ttl: 1});
      await new Promise(resolve => setTimeout(resolve, 25));
      return await NurseOffline.store.get('test', 'expired') === null;
    })()""")
    # Stop the server too: page-level CDP emulation does not affect worker fetches.
    server_args = processes[0].args
    processes[0].terminate()
    processes[0].wait(timeout=10)
    cdp(
        "Network.emulateNetworkConditions",
        {"offline": True, "latency": 0, "downloadThroughput": 0, "uploadThroughput": 0},
    )
    navigate("/profile/edit", "[data-offline-workspace]")
    assert js("NurseOffline.ready")
    assert js("document.body.dataset.offlineShell === 'true'")
    assert (
        js("NurseOffline.store.get('test', 'private').then(v => v.body)") == "Private offline text"
    )
    wait_for(
        lambda: js("!!document.querySelector('[data-record-key=\"profile:self\"] button')"),
        "offline profile available",
    )
    js("document.querySelector('[data-record-key=\"profile:self\"] button').click()")
    fill("[data-offline-profile-form] [name=headline]", "Edited during disconnection")
    js("document.querySelector('[data-offline-profile-form]').requestSubmit()")
    wait_for(
        lambda: js("document.querySelector('[data-operation-status=pending]') !== null"),
        "truthful pending state",
    )
    fill("#offline-search", "Offline browser opportunity")
    js("document.querySelector('#offline-search').dispatchEvent(new Event('input'))")
    wait_for(
        lambda: js("document.querySelectorAll('[data-record-key]').length === 1"), "local search"
    )
    js("document.querySelector('[data-record-key] button').click()")
    wait_for(
        lambda: js("NurseOffline.store.list('operation').then(rows => rows.length === 2)"),
        "bookmark queued",
    )
    fill("#offline-search", "")
    js("document.querySelector('#offline-search').dispatchEvent(new Event('input'))")
    wait_for(
        lambda: js(
            "!!document.querySelector('[data-record-key=\"learning:application-checklist\"]')"
        ),
        "guide rendered after search",
    )
    assert js(
        "document.querySelector('[data-record-key=\"learning:application-checklist\"]').textContent.includes('consent')"
    )
    pending_ids = js(
        "NurseOffline.store.list('operation').then(rows => rows.map(r => r.id).sort())"
    )
    for close in [fresh_tab, restart_browser]:
        close(offline=True)
        navigate("/offline", "[data-offline-workspace]")
        assert js("NurseOffline.ready")
        assert js("document.body.dataset.offlineShell === 'true'")
        assert js("sessionStorage.getItem('nurse-offline-context')") is None
        assert (
            js("NurseOffline.store.get('test', 'private').then(v => v.body)")
            == "Private offline text"
        )
        assert (
            js("NurseOffline.store.get('draft', 'post:/posts').then(d => d.payload.body)")
            == "A draft kept across browser closure"
        )
        assert (
            js("NurseOffline.store.list('operation').then(rows => rows.map(r => r.id).sort())")
            == pending_ids
        )
    print("Passed: fresh tab and full browser restart while disconnected", flush=True)
    with SessionLocal() as db:
        stored = db.scalar(select(NurseProfile).where(NurseProfile.user_id == user_id))
        assert stored.headline == "Original headline"
        stored.headline = "Changed on another device"
        db.commit()
    processes[0] = subprocess.Popen(
        server_args,
        cwd=ROOT,
        env=os.environ.copy(),
        stdout=logs[0],
        stderr=logs[0],
    )
    wait_for(lambda: urllib.request.urlopen(base + "/healthz", timeout=1).status == 200, "restart")
    cdp(
        "Network.emulateNetworkConditions",
        {"offline": False, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1},
    )
    wait_for(
        lambda: js("document.querySelector('[data-operation-status=conflict]') !== null"),
        "conflict visible",
    )
    wait_for(
        lambda: js("document.querySelector('[data-operation-status=confirmed]') !== null"),
        "bookmark synchronized",
    )
    js(
        "[...document.querySelectorAll('button')]"
        ".find(b => b.textContent === 'Review profile and save again').click()"
    )
    assert js("document.querySelector('[name=headline]').value") == "Edited during disconnection"
    js("document.querySelector('[data-offline-profile-form]').requestSubmit()")
    wait_for(
        lambda: js("NurseOffline.store.list('operation').then(rows => rows.length >= 3)"),
        "reviewed change stored",
    )
    js("NurseOffline.sync(true)")
    wait_for(
        lambda: js(
            "NurseOffline.store.list('operation').then(rows => "
            "rows.filter(r => r.value.status==='confirmed').length === 2)"
        ),
        "reviewed profile synchronized",
    )
    with SessionLocal() as db:
        assert (
            db.scalar(select(NurseProfile.headline).where(NurseProfile.user_id == user_id))
            == "Edited during disconnection"
        )
    # Drop one acknowledgement after the real backend committed. Retrying must use the receipt.
    js("""(async () => {
      await NurseOffline.refresh('/profile');
      const saved = await NurseOffline.store.get('record','profile:self');
      window.actualFetch = NurseOffline.fetch;
      window.dropOnce = true;
      NurseOffline.fetch = async (...args) => {
        const response = await actualFetch(...args);
        if (args[0] === '/offline/operations' && dropOnce) {
          dropOnce=false; throw new TypeError('Lost response');
        }
        return response;
      };
      await NurseOffline.queue('profile','profile:self','Lost acknowledgement', {
        base:saved.data, values:{...saved.data.values, bio:'Retried without duplication'}
      });
      await NurseOffline.sync(true);
    })()""")
    assert js(
        "NurseOffline.store.list('operation').then(rows => "
        "rows.some(r => r.value.status==='pending'))"
    )
    lost = js(
        "NurseOffline.store.list('operation')"
        ".then(rows => rows.find(r => r.value.status==='pending').value)"
    )
    restart_browser(offline=True)
    navigate("/offline")
    assert (
        js(f"NurseOffline.store.get('operation', {json.dumps(lost['id'])}).then(op => op.payload)")
        == lost["payload"]
    )
    network(False)
    wait_for(
        lambda: js(
            "NurseOffline.store.list('operation').then(rows => "
            "rows.filter(r => r.value.status==='confirmed').length === 3)"
        ),
        "lost acknowledgement recovered",
    )
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(OfflineOperation)) == 3
        assert db.get(OfflineOperation, (user_id, UUID(lost["id"]))) is not None
    print("Passed: automatic resume with the original receipt after browser restart", flush=True)
    # Visiting login with a valid cookie redirects home and preserves the workspace.
    cdp("Page.navigate", {"url": base + "/auth/login"})
    wait_for(
        lambda: js("location.pathname === '/' && document.readyState === 'complete'"),
        "signed-in login redirect",
    )
    assert js("NurseOffline.ready")
    assert (
        js("NurseOffline.store.get('test', 'private').then(v => v.body)") == "Private offline text"
    )
    cdp(
        "Network.emulateNetworkConditions",
        {"offline": False, "latency": 3300, "downloadThroughput": 50000, "uploadThroughput": 25000},
    )
    js("NurseOffline.fetch('/offline/ping')")
    assert js("document.querySelector('[data-connectivity]').dataset.state") == "poor"
    assert js("NurseOffline.fetch('/offline/ping', {}, 50).then(() => false, () => true)")
    cdp(
        "Network.emulateNetworkConditions",
        {"offline": False, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1},
    )
    navigate("/missing-offline-test")
    assert js("NurseOffline.ready")
    assert (
        js("NurseOffline.store.get('test', 'private').then(v => v.body)") == "Private offline text"
    )
    # Prepare existing forms, then compose and queue through the offline workspace.
    for path in [f"/messages/{staff_id}", f"/jobs/{job_id}", "/posts/new", f"/posts/{post_id}"]:
        navigate(path)
        wait_for(
            lambda: js(
                "!![...document.querySelectorAll('button')]"
                ".find(b => b.textContent === 'Save draft locally')"
            ),
            "deferred form controls",
        )
    navigate("/offline")
    processes[0].terminate()
    processes[0].wait(timeout=10)
    cdp(
        "Network.emulateNetworkConditions",
        {"offline": True, "latency": 0, "downloadThroughput": 0, "uploadThroughput": 0},
    )
    navigate("/messages", "[data-offline-workspace]")
    for kind in ["message", "application", "post", "reply"]:
        wait_for(
            lambda kind=kind: js(f"!!document.querySelector('[data-draft-kind={kind}] button')"),
            "saved composer " + kind,
        )
        js(f"document.querySelector('[data-draft-kind={kind}] button').click()")
        form = f"[data-offline-compose={kind}]"
        fill(
            form + (" [name=cover_note]" if kind == "application" else " [name=body]"),
            "Offline browser " + kind,
        )
        if kind == "application":
            js(f"document.querySelector('{form} [name=consent]').checked=true")
        if kind in ["post", "reply"]:
            fill(form + " [name=community_name]", "Browser Contributor")
        if kind == "post":
            fill(form + " [name=topic_id]", topic_id)
        js(f"document.querySelector('{form}').requestSubmit()")
        wait_for(
            lambda: js("document.querySelector('[data-offline-editor]').hidden"), "queued " + kind
        )
    processes[0] = subprocess.Popen(
        server_args, cwd=ROOT, env=os.environ.copy(), stdout=logs[0], stderr=logs[0]
    )
    wait_for(
        lambda: urllib.request.urlopen(base + "/healthz", timeout=1).status == 200,
        "content reconnect",
    )
    cdp(
        "Network.emulateNetworkConditions",
        {"offline": False, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1},
    )
    js("NurseOffline.sync(true)")
    wait_for(
        lambda: js(
            "NurseOffline.store.list('operation').then(rows => "
            "rows.filter(r => r.value.status==='confirmed').length === 7)"
        ),
        "deferred contributions synchronized",
    )
    assert not js("document.querySelector('[data-operation-status=failed]') !== null")
    # A new submission from the same page needs a fresh idempotency key.
    navigate(f"/messages/{staff_id}")
    wait_for(
        lambda: js("!!document.querySelector('.message-compose .offline-actions')"),
        "message queue controls",
    )
    # Fail the second write in the queue transaction, as happens when quota is exhausted.
    assert js("""(async () => {
      const id = 'message:' + location.pathname;
      const draft = await NurseOffline.store.get('draft', id);
      const before = JSON.stringify(draft);
      draft.payload.body = 'Storage failure must not send this message';
      const original = IDBObjectStore.prototype.put;
      let rejected = false;
      IDBObjectStore.prototype.put = function (value) {
        if (value.kind === 'draft') throw new DOMException('Device full', 'QuotaExceededError');
        return original.apply(this, arguments);
      };
      try { await NurseOffline.queueDraft(draft); }
      catch { rejected = true; }
      finally { IDBObjectStore.prototype.put = original; }
      const operations = await NurseOffline.store.list('operation');
      return rejected && JSON.stringify(await NurseOffline.store.get('draft', id)) === before &&
        !operations.some(row => row.value.payload?.body === draft.payload.body);
    })()""")
    for text in ["First queued without reloading", "Second queued without reloading"]:
        previous_key = js("document.querySelector('.message-compose [name=client_key]').value")
        fill("#message-body", text)
        js(
            "[...document.querySelectorAll('.message-compose button')]"
            ".find(b => b.textContent === 'Queue for synchronization').click()"
        )
        wait_for(
            lambda: js(
                "NurseOffline.store.list('operation').then(rows => "
                "rows.some(r => r.value.status==='pending' || r.value.status==='syncing'))"
            ),
            "message queued",
        )
        newer_text = "Keep this newer edit" if text.startswith("Second") else ""
        if newer_text:
            fill("#message-body", newer_text)
        js("NurseOffline.sync(true)")
        wait_for(
            lambda: js(
                "NurseOffline.store.list('draft').then(rows => "
                "!rows.some(r => r.value.kind==='message'))"
            ),
            "message draft acknowledged",
        )
        assert js("document.querySelector('#message-body').value") == newer_text
        assert (
            js("document.querySelector('.message-compose [name=client_key]').value") != previous_key
        )
        with SessionLocal() as db:
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(DirectMessage)
                    .where(DirectMessage.body == text)
                )
                == 1
            )
    js(
        "[...document.querySelectorAll('.message-compose button')]"
        ".find(b => b.textContent === 'Save draft locally').click()"
    )
    wait_for(
        lambda: js(
            "NurseOffline.store.get('draft', 'message:' + location.pathname)"
            ".then(draft => draft?.payload.body === 'Keep this newer edit')"
        ),
        "local copy before ordinary send",
    )
    submit(f"/messages/{staff_id}")
    wait_for(
        lambda: js(
            "document.querySelector('.thread-status').textContent==='Message sent.' && "
            "document.querySelector('#message-body').value===''"
        ),
        "ordinary send after queued messages",
    )
    assert js("NurseOffline.store.get('draft', 'message:' + location.pathname)") is None
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(DirectMessage)
                .where(DirectMessage.body == "Keep this newer edit")
            )
            == 1
        )
    navigate("/posts/new")
    wait_for(
        lambda: js("!!document.querySelector('form[action=\"/posts\"] .offline-actions')"),
        "connected post draft controls",
    )
    fill('form[action="/posts"] [name=body]', "Clear the offline copy after ordinary publication")
    fill('form[action="/posts"] [name=topic_id]', topic_id)
    js(
        "[...document.querySelectorAll('form[action=\"/posts\"] button')]"
        ".find(b => b.textContent === 'Save draft locally').click()"
    )
    wait_for(
        lambda: js("NurseOffline.store.get('draft', 'post:/posts').then(d => !!d?.community)"),
        "connected post draft saved",
    )
    submit("/posts")
    wait_for(
        lambda: js(
            "location.pathname.startsWith('/posts/') && location.pathname !== '/posts/new' && "
            "document.readyState === 'complete'"
        ),
        "ordinary post published",
    )
    assert js("NurseOffline.ready")
    wait_for(
        lambda: js("NurseOffline.store.get('draft', 'post:/posts').then(d => !d)"),
        "ordinary publication cleared its offline copy",
    )
    navigate("/reels/new")
    wait_for(
        lambda: js(
            "!![...document.querySelectorAll('button')]"
            ".find(b => b.textContent === 'Save draft locally')"
        ),
        "Reel offline controls",
    )
    document_id = cdp("DOM.getDocument")["root"]["nodeId"]
    file_id = cdp("DOM.querySelector", {"nodeId": document_id, "selector": "#reel-file"})["nodeId"]
    cdp("DOM.setFileInputFiles", {"nodeId": file_id, "files": [str(video_path)]})
    fill("#reel-body", "A locally saved Reel")
    fill("#reel-topic", topic_id)
    js(
        "[...document.querySelectorAll('[data-reel-upload] button')]"
        ".find(b => b.textContent==='Save draft locally').click()"
    )
    wait_for(
        lambda: js(
            "NurseOffline.store.list('draft').then(rows => "
            "rows.some(r => r.value.kind==='reel' && !!r.value.file))"
        ),
        "encrypted Reel saved",
    )
    processes[0].terminate()
    processes[0].wait(timeout=10)
    cdp(
        "Network.emulateNetworkConditions",
        {"offline": True, "latency": 0, "downloadThroughput": 0, "uploadThroughput": 0},
    )
    navigate("/reels", "[data-offline-workspace]")
    wait_for(
        lambda: js("!!document.querySelector('[data-draft-kind=reel] button')"),
        "Reel draft offline",
    )
    js("document.querySelector('[data-draft-kind=reel] button').click()")
    assert (
        js("document.querySelector('[data-offline-compose=reel] [name=body]').value")
        == "A locally saved Reel"
    )
    js("document.querySelector('[data-offline-compose=reel] [name=consent]').checked=true")
    js("document.querySelector('[data-offline-compose=reel]').requestSubmit()")
    wait_for(
        lambda: js(
            "NurseOffline.store.list('operation').then(rows => "
            "rows.some(r => r.value.kind==='reel' && r.value.status==='pending'))"
        ),
        "Reel pending",
    )
    js("""window.actualUploadFetch=NurseOffline.fetch;
      window.dropChunk=true; window.chunkOffsets=[];
      NurseOffline.fetch=async (...args) => {
        if (args[1]?.method==='PUT') {
          chunkOffsets.push(Number(new URL(args[0],location.href).searchParams.get('offset')));
        }
        const response=await actualUploadFetch(...args);
        if (args[1]?.method==='PUT' && dropChunk) {
          dropChunk=false; throw new TypeError('Interrupted chunk acknowledgement');
        }
        return response;
      };""")
    processes[0] = subprocess.Popen(
        server_args, cwd=ROOT, env=os.environ.copy(), stdout=logs[0], stderr=logs[0]
    )
    wait_for(
        lambda: urllib.request.urlopen(base + "/healthz", timeout=1).status == 200,
        "upload reconnect",
    )
    cdp(
        "Network.emulateNetworkConditions",
        {"offline": False, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1},
    )
    js("NurseOffline.sync(true)")
    wait_for(
        lambda: js(
            "NurseOffline.store.list('operation').then(rows => rows.some(r => "
            "r.value.kind==='reel' && r.value.status==='pending' && r.value.attempts>0))"
        ),
        "interrupted upload awaiting retry",
    )
    with SessionLocal() as db:
        assert db.scalar(select(OfflineUpload.received)) == 1024 * 1024
        assert db.scalar(select(func.count()).select_from(Reel)) == 0
    interrupted = js(
        "NurseOffline.store.list('operation')"
        ".then(rows => rows.find(r => r.value.kind==='reel').value)"
    )
    assert js("chunkOffsets") == [0]
    processes[0].terminate()
    processes[0].wait(timeout=10)
    restart_browser(offline=True)
    navigate("/reels", "[data-offline-workspace]")
    assert js("NurseOffline.ready")
    assert (
        js(
            f"NurseOffline.store.get('operation', {json.dumps(interrupted['id'])})"
            ".then(op => op.payload)"
        )
        == interrupted["payload"]
    )
    assert js("NurseOffline.store.list('file-chunk').then(rows => rows.length)") == 3
    js("""window.resumedOffsets=[]; window.resumedFetch=NurseOffline.fetch;
      NurseOffline.fetch=async (...args) => {
        if (args[1]?.method==='PUT') {
          resumedOffsets.push(Number(new URL(args[0],location.href).searchParams.get('offset')));
        }
        return resumedFetch(...args);
      };""")
    processes[0] = subprocess.Popen(
        server_args, cwd=ROOT, env=os.environ.copy(), stdout=logs[0], stderr=logs[0]
    )
    wait_for(
        lambda: urllib.request.urlopen(base + "/healthz", timeout=1).status == 200,
        "resume after browser closure",
    )
    network(False)
    wait_for(
        lambda: js(
            "NurseOffline.store.list('operation').then(rows => "
            "rows.some(r => r.value.kind==='reel' && r.value.status==='confirmed'))"
        ),
        "Reel received after resuming",
        seconds=60,
    )
    assert js("resumedOffsets") == [1024 * 1024, 2 * 1024 * 1024]
    print("Passed: interrupted video resumed at the next chunk after browser restart", flush=True)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Reel)) == 1
        assert reel_worker.run_next(db)[1] == "ready"
    navigate("/reels/new")
    wait_for(
        lambda: js("!!document.querySelector('[data-reel-upload] .offline-actions')"),
        "Reel queue controls",
    )
    for caption in ["First Reel without reloading", "Second Reel without reloading"]:
        previous_key = js("document.querySelector('[name=upload_key]').value")
        document_id = cdp("DOM.getDocument")["root"]["nodeId"]
        input_id = cdp("DOM.querySelector", {"nodeId": document_id, "selector": "#reel-file"})[
            "nodeId"
        ]
        cdp("DOM.setFileInputFiles", {"nodeId": input_id, "files": [str(video_path)]})
        fill("#reel-body", caption)
        fill("#reel-topic", topic_id)
        js("document.querySelector('[data-reel-upload] [name=consent]').checked=true")
        js(
            "[...document.querySelectorAll('[data-reel-upload] button')]"
            ".find(b => b.textContent === 'Queue for synchronization').click()"
        )
        wait_for(
            lambda: js(
                "NurseOffline.store.list('operation').then(rows => "
                "rows.some(r => ['pending','syncing'].includes(r.value.status)))"
            ),
            "new Reel queued",
        )
        js("NurseOffline.sync(true)")
        wait_for(
            lambda: js(
                "NurseOffline.store.list('draft').then(rows => "
                "!rows.some(r => r.value.kind==='reel'))"
            ),
            "new Reel acknowledged",
        )
        assert js("document.querySelector('#reel-body').value") == ""
        assert js("document.querySelector('#reel-file').files.length") == 0
        assert js("document.querySelector('[name=upload_key]').value") != previous_key
        with SessionLocal() as db:
            assert reel_worker.run_next(db)[1] == "ready"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Reel)) == 3
    document_id = cdp("DOM.getDocument")["root"]["nodeId"]
    input_id = cdp("DOM.querySelector", {"nodeId": document_id, "selector": "#reel-file"})["nodeId"]
    cdp("DOM.setFileInputFiles", {"nodeId": input_id, "files": [str(video_path)]})
    fill("#reel-body", "Clear the offline video after an ordinary upload")
    js("document.querySelector('[data-reel-upload] [name=consent]').checked=true")
    js(
        "[...document.querySelectorAll('[data-reel-upload] button')]"
        ".find(b => b.textContent === 'Save draft locally').click()"
    )
    wait_for(
        lambda: js("NurseOffline.store.get('draft', 'reel:/reels').then(d => !!d?.file)"),
        "ordinary upload local copy",
    )
    submit("/reels")
    wait_for(
        lambda: js("location.pathname.endsWith('/status') && document.readyState==='complete'"),
        "ordinary Reel received",
    )
    assert js("NurseOffline.ready")
    assert js("NurseOffline.store.get('draft', 'reel:/reels')") is None
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Reel)) == 4
        assert reel_worker.run_next(db)[1] == "ready"
    assert js("""(async () => {
      const name=(await caches.keys()).find(name => name.startsWith('nurse-offline-shell-'));
      const cache=await caches.open(name);
      const paths=(await cache.keys()).map(r=>new URL(r.url).pathname);
      return paths.every(p=>p==='/offline-shell' || p.startsWith('/static/')) &&
        !(await (await cache.match('/offline-shell')).text()).includes('Browser Member');
    })()""")
    for width in [320, 390, 1280]:
        audit("/offline", width, large=width == 320)
    navigate("/offline")
    # Same-account tabs share the durable workspace; sign-out revokes every tab.
    original_ws = ws
    target_id = cdp("Target.createTarget", {"url": "about:blank"})["targetId"]
    attach(target_id)
    other_ws = ws
    navigate("/offline")
    assert js("NurseOffline.ready")
    assert (
        js("NurseOffline.store.get('test', 'private').then(v => v.body)") == "Private offline text"
    )

    # Both editors start with the same saved revision; the stale one must keep its text.
    for tab_ws in [original_ws, other_ws]:
        ws = tab_ws
        navigate(f"/messages/{staff_id}")
        wait_for(
            lambda: js("!!document.querySelector('.message-compose .offline-actions')"),
            "shared draft controls",
        )
    ws = original_ws
    fill("#message-body", "Newer draft in the first tab")
    js("document.querySelector('.message-compose .offline-actions button').click()")
    wait_for(
        lambda: js(
            "NurseOffline.store.get('draft', 'message:' + location.pathname)"
            ".then(d => d.payload.body === 'Newer draft in the first tab')"
        ),
        "first tab saved",
    )
    ws = other_ws
    fill("#message-body", "Keep this stale editor text")
    js("document.querySelector('.message-compose .offline-actions button').click()")
    wait_for(
        lambda: js(
            "document.querySelector('[data-feedback-panel]').textContent"
            ".includes('changed in another tab')"
        ),
        "stale draft save rejected",
    )
    assert js("document.querySelector('#message-body').value") == "Keep this stale editor text"
    assert (
        js(
            "NurseOffline.store.get('draft', 'message:' + location.pathname)"
            ".then(d => d.payload.body)"
        )
        == "Newer draft in the first tab"
    )
    navigate("/offline")
    network(True)
    ws = original_ws
    network(True)
    old_key = js("document.querySelector('[name=client_key]').value")
    js(
        "[...document.querySelectorAll('.offline-actions button')]"
        ".find(b => b.textContent === 'Queue for synchronization').click()"
    )
    wait_for(
        lambda: js(
            "NurseOffline.store.get('draft', 'message:' + location.pathname)"
            ".then(d => !!d.operation)"
        ),
        "shared message queued",
    )
    fill("#message-body", "New typing while the other tab sends")
    ws = other_ws
    network(False)
    wait_for(
        lambda: js(
            "NurseOffline.store.list('draft').then(rows => "
            "!rows.some(row => row.value.kind === 'message'))"
        ),
        "other tab acknowledged and cleared shared draft",
    )
    ws = original_ws
    wait_for(
        lambda: js("document.querySelector('[name=client_key]').value") != old_key,
        "confirmation rotated original tab reference",
    )
    assert (
        js("document.querySelector('#message-body').value")
        == "New typing while the other tab sends"
    )
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(DirectMessage)
                .where(DirectMessage.body == "Newer draft in the first tab")
            )
            == 1
        )

    # Queue insertion and foreground sending must be exclusive, including the lease fallback.
    for mode in ["web-locks", "lease-fallback"]:
        payload = {
            "recipient_id": staff_id,
            "body": "Shared send using " + mode,
            "client_key": js("crypto.randomUUID()"),
        }
        for tab_ws in [original_ws, other_ws]:
            ws = tab_ws
            network(True)
            if mode == "lease-fallback":
                js(
                    "Object.defineProperty(navigator, 'locks', "
                    "{configurable: true, value: undefined})"
                )
            js(
                """window.sentRequests=[]; window.sendFetch=NurseOffline.fetch;
              NurseOffline.fetch=async (...args) => {
                if (args[0] === '/offline/operations') {
                  sentRequests.push(JSON.parse(args[1].body).operation_id);
                  await new Promise(resolve => setTimeout(resolve, 400));
                }
                return sendFetch(...args);
              };"""
                if mode == "web-locks"
                else "window.sentRequests=[]"
            )
            js(
                "window.queueResult=null; void NurseOffline.queue('message', "
                + json.dumps("shared:" + mode)
                + ", 'Shared message', "
                + json.dumps(payload)
                + ").then(op => { queueResult={ok:true, id:op.id}; }, "
                "error => { queueResult={ok:false, error:error.message}; });"
            )
        outcomes = []
        for tab_ws in [original_ws, other_ws]:
            ws = tab_ws
            outcomes.append(wait_for(lambda: js("queueResult"), "competing queue result"))
        assert sorted(outcome["ok"] for outcome in outcomes) == [False, True], outcomes
        for tab_ws in [original_ws, other_ws]:
            ws = tab_ws
            network(False)
            js("void NurseOffline.sync(true)")
        identifier = next(outcome["id"] for outcome in outcomes if outcome["ok"])
        wait_for(
            lambda identifier=identifier: js(
                f"NurseOffline.store.get('operation', {json.dumps(identifier)})"
                ".then(op => op.status === 'confirmed')"
            ),
            "shared queue synchronized " + mode,
        )
        sent = []
        for tab_ws in [original_ws, other_ws]:
            ws = tab_ws
            sent.extend(js("sentRequests"))
        assert sent == [identifier], sent
        with SessionLocal() as db:
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(DirectMessage)
                    .where(DirectMessage.body == payload["body"])
                )
                == 1
            )

    # Simulate a frozen lease holder resuming after a second tab has taken over.
    ws = original_ws
    js("""window.lateResult=null; window.resumeLate=null;
      void NurseOffline.store.withLock('takeover-test', async fence => {
        window.lateFence=fence;
        await new Promise(resolve => { resumeLate=resolve; });
        await NurseOffline.store.put('test', 'fenced', {winner:'old'}, {}, fence);
      }).then(() => { lateResult='written'; }, () => { lateResult='rejected'; });""")
    wait_for(lambda: js("!!resumeLate"), "lease acquired")
    lease_id = js("lateFence.id")
    ws = other_ws
    js(
        """(async id => {
      const db = await new Promise(resolve => {
        const r=indexedDB.open('nurse-offline-v1'); r.onsuccess=()=>resolve(r.result);
      });
      await new Promise(resolve => {
        const tx=db.transaction('records','readwrite'), rows=tx.objectStore('records');
        rows.get(id).onsuccess=e=>rows.put({...e.target.result, expires:0});
        tx.oncomplete=resolve;
      });
      db.close();
      await NurseOffline.store.withLock('takeover-test', fence =>
        NurseOffline.store.put('test', 'fenced', {winner:'new'}, {}, fence));
    })("""
        + json.dumps(lease_id)
        + ")"
    )
    ws = original_ws
    js("resumeLate()")
    wait_for(lambda: js("lateResult === 'rejected'"), "late write fenced")
    assert js("NurseOffline.store.get('test', 'fenced').then(v => v.winner)") == "new"
    print("Passed: competing tabs, stale drafts and writes, and lease fallback", flush=True)

    # A late write cannot resurrect data after clear, even if a new workspace uses this scope.
    js("""window.releaseOld=null; window.oldResult=null;
      void NurseOffline.store.withLock('clear-race', async fence => {
        await new Promise(resolve => { releaseOld=resolve; });
        await NurseOffline.store.put('test', 'resurrected', {body:'old'}, {}, fence);
      }).then(() => { oldResult='written'; }, () => { oldResult='rejected'; });""")
    wait_for(lambda: js("!!releaseOld"), "old workspace saving")
    ws = other_ws
    js("NurseOffline.store.clear()")
    navigate("/offline")
    assert js("NurseOffline.ready")
    js("NurseOffline.store.put('test', 'new-workspace', {body:'keep'})")
    ws = original_ws
    js("releaseOld()")
    wait_for(lambda: js("oldResult === 'rejected'"), "old workspace write rejected")
    js("NurseOffline.store.clear()")
    ws = other_ws
    assert js("NurseOffline.store.get('test', 'resurrected')") is None
    assert js("NurseOffline.store.get('test', 'new-workspace').then(v => v.body)") == "keep"
    ws = original_ws
    network(False)
    navigate("/offline")
    previous_scope = js("NurseOffline.store.scope")
    ws = original_ws
    logout()
    ws = other_ws
    wait_for(lambda: js("!NurseOffline.store.available"), "other tab locked after sign-out")
    assert js("NurseOffline.store.get('test', 'private').then(() => false, () => true)")
    assert raw_rows("rows.every(row => row.scope !== " + json.dumps(previous_scope) + ")")
    ws = original_ws
    cdp("Target.closeTarget", {"targetId": target_id})
    other_ws.close()
    login("+2348000000078")
    navigate("/offline")
    assert js("NurseOffline.ready")
    assert js("NurseOffline.store.get('test', 'private')") is None

    # Upgrade open legacy tabs. A failed key commit must preserve the old raw key and rows.
    js("NurseOffline.store.clear()")
    legacy = seed_legacy("Original legacy draft")
    injection = cdp(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": """
      const originalPut=IDBObjectStore.prototype.put;
      IDBObjectStore.prototype.put=function(row) {
        if (row.kind === '_vault') throw new DOMException('Full device', 'QuotaExceededError');
        return originalPut.apply(this, arguments);
      };
    """
        },
    )["identifier"]
    navigate("/offline")
    assert not js("NurseOffline.ready")
    assert js("JSON.parse(sessionStorage.getItem('nurse-offline-context')).secret.length") == 32
    assert raw_rows("rows.length") == 2
    cdp("Page.removeScriptToEvaluateOnNewDocument", {"identifier": injection})
    navigate("/offline")
    assert js("NurseOffline.ready")
    assert js("sessionStorage.getItem('nurse-offline-context')") is None
    assert (
        js("NurseOffline.store.get('draft', 'post:/posts').then(d => d.payload.body)")
        == "Original legacy draft"
    )
    assert raw_rows("rows.some(row => row.kind === '_vault' && !row.key.extractable)")

    # Another old tab's same-named draft is recovered separately. Interrupt its merge after
    # its key is committed, then recover from a fresh tab with no legacy sessionStorage.
    secondary = seed_legacy("A different older tab's draft")
    injection = cdp(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": """
      const legacy=JSON.parse(sessionStorage.getItem('nurse-offline-context'));
      const originalPut=IDBObjectStore.prototype.put;
      IDBObjectStore.prototype.put=function(row) {
        if (row.kind === 'draft' && row.tab !== legacy.tab) {
          throw new DOMException('Full device during recovery', 'QuotaExceededError');
        }
        return originalPut.apply(this, arguments);
      };
    """
        },
    )["identifier"]
    navigate("/offline")
    assert js("NurseOffline.ready")
    assert js("!!NurseOffline.store.error")
    assert js("sessionStorage.getItem('nurse-offline-context')") is None
    assert raw_rows("rows.filter(row => row.kind === '_legacy').length") == 1
    cdp("Page.removeScriptToEvaluateOnNewDocument", {"identifier": injection})
    fresh_tab()
    navigate("/offline")
    assert js("NurseOffline.ready")
    recovered_id = secondary["id"] + ":recovered:" + secondary["tab"]
    assert (
        js("NurseOffline.store.get('draft', 'post:/posts').then(d => d.payload.body)")
        == "Original legacy draft"
    )
    assert (
        js(f"NurseOffline.store.get('draft', {json.dumps(recovered_id)}).then(d => d.payload.body)")
        == "A different older tab's draft"
    )
    recovered = js(f"NurseOffline.store.get('operation', {json.dumps(secondary['operation'])})")
    assert recovered["id"] == secondary["operation"]
    assert recovered["payload"] == secondary["payload"]
    assert recovered["target"] == recovered_id
    assert recovered["metadata"]["draft"]["id"] == recovered_id
    assert raw_rows("rows.filter(row => row.kind === '_legacy').length") == 0
    assert (
        raw_rows("rows.filter(row => row.tab === " + json.dumps(secondary["tab"]) + ").length") == 0
    )
    # Clearing must stay revoked even if deletion fails and the browser immediately closes.
    assert js("""(async () => {
      const original=IDBDatabase.prototype.transaction;
      IDBDatabase.prototype.transaction=function(name, mode) {
        if (mode === 'readwrite') throw new DOMException('Unavailable', 'UnknownError');
        return original.apply(this, arguments);
      };
      try { await NurseOffline.store.clear(); return false; }
      catch { return true; }
      finally { IDBDatabase.prototype.transaction=original; }
    })()""")
    processes[0].terminate()
    processes[0].wait(timeout=10)
    restart_browser(offline=True)
    navigate("/offline", "[data-offline-workspace]")
    assert not js("NurseOffline.ready")
    assert not js("NurseOffline.store.available")
    assert raw_rows("rows.length") == 0
    assert not errors, errors
    print(
        json.dumps(
            {
                "passed": True,
                "phase": "durable storage, browser restarts, shared tabs and resumable uploads",
                "artifacts": str(artifacts),
            }
        )
    )

except Exception:
    if ws:
        print("Failure page:", js("location.pathname"))
        (artifacts / "failure.png").write_bytes(
            base64.b64decode(cdp("Page.captureScreenshot", {"format": "png"})["data"])
        )
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
