# ruff: noqa: E402
"""Run isolated Chrome account feedback checks; never uses live accounts or SMTP."""

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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
artifacts = Path(tempfile.mkdtemp(prefix="nurse-quality-browser-"))


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
        "NURSE_NG_REQUIRED_WORKERS": "recruitment,reels",
        "NURSE_NG_GOOGLE_CLIENT_ID": "",
        "NURSE_NG_LINKEDIN_CLIENT_ID": "",
        "NURSE_NG_ACCOUNT_MAIL_DIR": str(artifacts / "mail"),
        "NURSE_NG_AVATAR_DIR": str(artifacts / "avatars"),
        "NURSE_NG_SMTP_FROM": "Nurse.ng <no-reply@example.org>",
    }
)
from alembic import command
from alembic.config import Config
from PIL import Image
from websockets.sync.client import connect

from app.db.session import SessionLocal
from app.services.auth import register_user
from tests.helpers import approve_test_employer

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
picture = artifacts / "photo.jpg"
Image.new("RGB", (640, 480), "#087c72").save(picture)
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


from sqlalchemy import func, select

from app.models.jobs import Job
from app.services.community import create_topic

with SessionLocal() as db:
    staff = register_user(
        db,
        phone="+2348000000078",
        password="browser-password",
        full_name="Quality Staff",
        account_type="employer",
    )
    approve_test_employer(db, staff, "Quality hospital")
    staff.is_staff = True
    db.commit()
    topic = create_topic(db, staff, name="Quality community", description="")
    topic_id = str(topic.id)

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
    if path in {"/auth/register", "/auth/login"}:
        assert js("""(() => {
          const heading = document.querySelector('.auth-panel h2');
          const range = document.createRange(); range.selectNodeContents(heading);
          for (const rect of range.getClientRects()) {
            if (!rect.width || !rect.height) continue;
            if (rect.left < 0 || rect.right > innerWidth + 1) return false;
            for (let parent = heading; parent; parent = parent.parentElement) {
              const style = getComputedStyle(parent), bounds = parent.getBoundingClientRect();
              if (['hidden', 'clip'].includes(style.overflowX) &&
                  (rect.left < bounds.left - 1 || rect.right > bounds.right + 1)) return false;
              if (['hidden', 'clip'].includes(style.overflowY) &&
                  (rect.top < bounds.top - 1 || rect.bottom > bounds.bottom + 1)) return false;
            }
          }
          return !/communitythat|supportsyour|support\\.A|ofpossibilities/.test(heading.innerText);
        })()"""), "Auth heading text must remain separated and visible"
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
e.getBoundingClientRect().right > innerWidth+2)
.slice(0,12)
.map(e=>({tag:e.tagName, cls:e.className, width:e.getBoundingClientRect().width, text:e.textContent
.slice(0,60)}))"""
    )
    result.update(path=path, width=width, large=large, overflow=overflow)
    audits.append(result)
    (artifacts / "audits.json").write_text(json.dumps(audits, indent=2))
    assert not result["violations"], result
    assert js("document.documentElement.scrollWidth <= innerWidth+2"), result
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
    ws = connect(next(t["webSocketDebuggerUrl"] for t in tabs if t["type"] == "page"), legacy=True)
    cdp("Page.enable")
    cdp("Emulation.setFocusEmulationEnabled", {"enabled": True})
    cdp("Runtime.enable")
    cdp("Network.enable")
    cdp(
        "Emulation.setDeviceMetricsOverride",
        {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True},
    )
    for path in ["/auth/register", "/auth/login", "/events"]:
        audit(path, 320, True)
    navigate("/auth/register")
    js("document.querySelector('form[action=\"/auth/social/google/start\"] button').click()")
    wait_for(lambda: feedback("Sign-in needs attention"), "unconfigured provider feedback")
    assert js("document.querySelector('#feedback-body').textContent.includes('not connected')")
    login("+2348000000077")
    navigate("/profile/edit")
    fill("#display_name", "Quality Member")
    fill("#headline", "Preserved profile work")
    cdp(
        "Network.emulateNetworkConditions",
        {"offline": True, "latency": 0, "downloadThroughput": 0, "uploadThroughput": 0},
    )
    submit("/profile/edit")
    wait_for(lambda: feedback("You’re offline"), "offline profile feedback")
    assert js("document.querySelector('#headline').value==='Preserved profile work'")
    cdp(
        "Network.emulateNetworkConditions",
        {"offline": False, "latency": 800, "downloadThroughput": 50000, "uploadThroughput": 20000},
    )
    submit("/profile/edit")
    assert js(
        """document.querySelector('form[action=\"/profile/edit\"]').getAttribute('aria-busy')==='true'"""
    )
    wait_for(lambda: feedback("Profile saved"), "slow profile save")
    cdp(
        "Network.emulateNetworkConditions",
        {"offline": False, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1},
    )
    navigate("/posts/new")
    fill("#community-name", "Quality Member")
    fill("#body", "A browser conversation with a retained draft.")
    fill("#topic-id", topic_id)
    js("document.querySelector('#body').dispatchEvent(new Event('input', {bubbles:true}))")
    submit("/posts")
    wait_for(lambda: feedback("Conversation published"), "post feedback")
    post_path = js("location.pathname")
    fill("#reply-body", "A reply from the complete browser journey.")
    js("document.querySelector('#reply-body').dispatchEvent(new Event('input', {bubbles:true}))")
    submit(post_path + "/replies")
    wait_for(lambda: feedback("Reply published"), "reply confirmation with anchor")
    assert js("location.hash.startsWith('#reply-')")
    navigate("/posts/new")
    assert js("document.querySelector('#body').value === ''"), "Published draft should be cleared"
    navigate("/settings")
    js("document.querySelector('main [data-display-open]').focus()")
    key("Enter", 13)
    assert js("document.querySelector('#display-preferences').open")
    for _ in range(8):
        key("Tab", 9)
        assert js(
            """document.activeElement===document.body ||
            document.querySelector('#display-preferences').contains(document.activeElement)"""
        )
    key("Escape", 27)
    assert js(
        """!document.querySelector('#display-preferences').open &&
document.activeElement.matches('[data-display-open]')"""
    )
    js("document.querySelector('.nav-toggle').focus()")
    key("Enter", 13)
    assert js("document.querySelector('#mobile-navigation').open")
    key("Escape", 27)
    assert js("document.activeElement.matches('.nav-toggle')")
    for path in [
        "/profile/edit",
        "/profile/sharing",
        "/profile/verification",
        "/settings",
        "/settings/social",
        "/jobs",
        "/applications",
        "/notifications",
        "/network",
        "/messages",
        "/posts/new",
        "/events",
    ]:
        audit(path, 320, True)
    logout()
    login("+2348000000078")
    navigate("/jobs/new")
    fill("#title", "Quality browser job")
    fill("#organization", "Quality hospital")
    fill("#salary_min", "500000")
    fill("#salary_max", "200000")
    submit("/jobs")
    wait_for(lambda: feedback("Please check this action"), "server-side job validation")
    assert js("document.querySelector('#title').value==='Quality browser job'")
    fill("#salary_max", "600000")
    js(
        """window.realFetch=window.fetch;
 window.sends=0;
 window.fetch=async (...args)=>{if(args[0].endsWith('/jobs')){window.sends++;
 await new Promise(r=>setTimeout(r,700));
} return window.realFetch(...args);
}"""
    )
    submit("/jobs")
    submit("/jobs")
    assert js("window.sends===1"), "Duplicate submit must not send another job"
    wait_for(lambda: feedback("Job published"), "job publication")
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count()).select_from(Job).where(Job.title == "Quality browser job")
            )
            == 1
        )
    navigate("/events/new")
    fill("#event-title", "Quality browser event")
    fill("#event-description", "Meet and learn with other nurses.")
    fill("#event-location", "Lagos")
    fill("#event-start", "2030-06-01T10:00")
    fill("#event-end", "2030-06-01T11:00")
    submit("/events")
    wait_for(lambda: feedback("Event published"), "event publication")
    event_path = js("location.pathname")
    for path in [
        "/events/new",
        event_path,
        event_path + "/edit",
        "/jobs/new",
        "/review",
        "/moderation",
        "/recruitment",
        "/recruitment/vacancies?state=pending",
        "/recruitment/vacancies?state=duplicate",
    ]:
        audit(path, 320, True)
    navigate("/recruitment")
    assert js(
        "!!document.querySelector('a[href=\"/recruitment/vacancies?state=pending\"]')"
    )
    js("document.querySelector('a[href=\"/recruitment/vacancies?state=pending\"]').click()")
    wait_for(
        lambda: js("location.pathname==='/recruitment/vacancies' && "
                   "document.readyState==='complete'"),
        "pending vacancy link",
    )
    assert js("document.querySelector('select[name=state]').value==='pending'")
    navigate("/recruitment")
    js("document.querySelector('a[href=\"#add-source\"]').click()")
    assert js("location.hash==='#add-source'")
    js("document.querySelector('#add-source summary').click()")
    assert js("document.querySelector('#add-source').open && "
              "!!document.querySelector('#add-source input[name=source_url]')")
    js("document.querySelector('a[href=\"#worker-health\"]').click()")
    assert js("location.hash==='#worker-health' && "
              "document.body.textContent.includes('historical failed tasks')")
    assert js("!document.body.textContent.includes('Notifications worker')")
    audit("/events", 1280)
    logout()
    login("+2348000000077")
    navigate(event_path)
    cdp("Network.overrideNetworkState", {
        "offline": False, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1,
    })
    wait_for(lambda: js("navigator.onLine"), "online RSVP environment")
    submit(event_path + "/rsvp")
    wait_for(lambda: feedback("RSVP saved"), "member RSVP")
    assert js("document.body.textContent.includes('You are planning to attend')")
    submit(event_path + "/rsvp")
    wait_for(lambda: feedback("RSVP cancelled"), "cancel RSVP")
    navigate("/profile/edit")
    fill("#headline", "Lost response update")
    js(
        """window.realFetch=window.fetch;
 window.fetch=async (...args)=>{const r=await window.realFetch(...args);
 if(args[0].endsWith('/profile/edit')) throw new TypeError('Interrupted response');
 return r;
}"""
    )
    submit("/profile/edit")
    wait_for(lambda: feedback("We couldn’t confirm the result"), "lost-response feedback")
    assert js("document.querySelector('#headline').value==='Lost response update'")
    assert js("!document.querySelector('form[action=\"/profile/edit\"]').hasAttribute('aria-busy')")
    assert not errors, errors
    print(
        json.dumps(
            {
                "passed": True,
                "artifacts": str(artifacts),
                "audited_states": len(audits),
                "checks": [
                    "profile offline/slow/lost-response",
                    "community drafts and replies",
                    "keyboard dialogs",
                    "job validation and duplicate prevention",
                    "event publishing and RSVP",
                    "vacancy review, source URL and worker navigation",
                    "320px at 200% text",
                    "axe accessibility",
                ],
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
