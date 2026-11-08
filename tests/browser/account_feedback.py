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
from datetime import timedelta
from email import policy
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
artifacts = Path(tempfile.mkdtemp(prefix="nurse-account-feedback-"))


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
from app.models.user import User
from app.services.accounts import now
from app.services.auth import register_user

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
            f'location.pathname === {json.dumps(target_path)} && '
            f'document.readyState === "complete" && '
            f'!!document.querySelector({json.dumps(selector)})'
        ),
        path,
    )


def fill(selector, value):
    js(f"document.querySelector({json.dumps(selector)}).value={json.dumps(value)}")


def submit(action):
    selector = f'form[action="{action}"]'
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
    cdp("Runtime.enable")
    cdp("Network.enable")
    cdp(
        "Emulation.setDeviceMetricsOverride",
        {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True},
    )
    navigate("/auth/login", "#phone")
    assert js("Array.from(document.links).some(a => a.pathname === '/auth/forgot-password')")
    fill("#phone", "+2348000000077")
    fill("#password", "browser-password")
    submit("/auth/login")
    wait_for(
        lambda: js('location.pathname === "/" && document.readyState === "complete"'), "sign in"
    )
    navigate("/settings", "#profile-photo")
    assert js("document.documentElement.scrollWidth <= innerWidth+1")
    bad_photo = artifacts / "invalid.jpg"
    bad_photo.write_bytes(b"not an image")
    select_photo(bad_photo)
    submit("/settings/photo")
    wait_for(lambda: feedback("Photo wasn’t uploaded"), "invalid photo feedback")
    assert js('document.querySelector("#profile-photo").getAttribute("aria-invalid") === "true"')
    assert js('document.querySelector("#profile-photo").files.length === 1')
    screenshot("photo-error-mobile.png")
    select_photo(picture)
    wait_for(lambda: js('!document.querySelector("[data-photo-preview]").hidden'), "photo preview")
    cdp(
        "Network.emulateNetworkConditions",
        {"offline": True, "latency": 0, "downloadThroughput": 0, "uploadThroughput": 0},
    )
    submit("/settings/photo")
    wait_for(lambda: feedback("You’re offline"), "offline feedback")
    assert js('document.querySelector("#profile-photo").files.length === 1')
    screenshot("offline-mobile.png")
    cdp(
        "Network.emulateNetworkConditions",
        {"offline": False, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1},
    )
    paused.clear()
    cdp(
        "Fetch.enable",
        {"patterns": [{"urlPattern": "*/settings/photo", "requestStage": "Request"}]},
    )
    submit("/settings/photo")
    wait_for(lambda: js("true") and paused, "paused upload")
    assert js(
        'document.querySelector("[data-pending-label=\\"Uploading photo…\\"]")'
        '.getAttribute("aria-busy") === "true"'
    )
    assert js(
        'document.querySelector("[data-pending-label=\\"Uploading photo…\\"] button")'
        '.textContent.includes("Uploading photo")'
    )
    submit("/settings/photo")
    js("true")
    assert len(paused) == 1
    js(
        'document.querySelector("[data-pending-label=\\"Uploading photo…\\"] button")'
        '.scrollIntoView({block:"center",behavior:"instant"})'
    )
    screenshot("upload-pending-mobile.png")
    cdp("Fetch.continueRequest", {"requestId": paused[0]["requestId"]})
    cdp("Fetch.disable")
    wait_for(lambda: feedback("Profile photo updated"), "photo upload")
    wait_for(lambda: js(
        'document.querySelector(".pf-avatar img")?.complete && '
        'document.querySelector(".pf-avatar img").naturalWidth === 512'
    ), "saved photo loads")
    contrast = []
    for theme in ("light", "dark"):
        js(f"document.documentElement.dataset.theme={json.dumps(theme)}")
        result = js("""(() => {
   const style=getComputedStyle(document.querySelector('#feedback-body'));
   const panel=document.querySelector('[data-feedback-panel]');
   const background=getComputedStyle(panel).backgroundColor;
   const lum=color => color.match(/\\d+/g).slice(0,3).map(Number).map(v=>v/255)
    .map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4)
    .reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
   const a=lum(style.color),b=lum(background);
   return {theme:document.documentElement.dataset.theme,
           ratio:(Math.max(a,b)+.05)/(Math.min(a,b)+.05)};
  })()""")
        assert result["ratio"] >= 4.5, result
        contrast.append(result)
        screenshot("settings-" + theme + "-mobile.png")
    assert js('document.activeElement.matches("[data-feedback-panel]")')
    for width in (320, 390, 1280):
        viewport(width, 900 if width == 1280 else 844)
        assert js("document.documentElement.scrollWidth <= innerWidth+1")
        if width == 320:
            js('document.documentElement.dataset.textSize="large"')
            assert js("document.documentElement.scrollWidth <= innerWidth+1")
            screenshot("feedback-large-text-320.png")
            js("delete document.documentElement.dataset.textSize")
        if width == 1280:
            screenshot("photo-success-desktop.png")
    viewport()
    js('document.querySelector("[data-feedback-dismiss]").click()')
    assert js('document.querySelector("[data-feedback-panel]").hidden')
    # Drop a response after the server saves it. The UI must not claim success or
    # submit again automatically, and must retain the user's entered data.
    fill("#full_name", "Updated Browser Member")
    paused.clear()
    cdp("Fetch.enable", {"patterns": [{"urlPattern": "*/settings", "requestStage": "Response"}]})
    submit("/settings")
    wait_for(lambda: js("true") and paused, "save response")
    cdp("Fetch.failRequest", {"requestId": paused[0]["requestId"], "errorReason": "Failed"})
    cdp("Fetch.disable")
    wait_for(lambda: feedback("We couldn’t confirm the result"), "lost response feedback")
    assert js('document.querySelector("#full_name").value === "Updated Browser Member"')
    assert js('!document.querySelector("form[action=\\"/settings\\"] button").disabled')
    screenshot("connection-interrupted-mobile.png")
    with SessionLocal() as db:
        assert db.get(User, user_id).full_name == "Updated Browser Member"
    navigate("/settings", "#profile-photo")
    assert js('document.querySelector("#full_name").value === "Updated Browser Member"')
    # Browsers may retain Set-Cookie before the interrupted response body. A
    # confirmation on this subsequent server-rendered GET is therefore valid.
    js('window.scrollTo({top:document.body.scrollHeight,behavior:"instant"})')
    submit("/settings/verify-email")
    wait_for(lambda: feedback("Check your email"), "verification request")
    link = wait_for(email_link, "verification email")
    navigate(link.removeprefix(base), "#account-token")
    assert js('document.querySelector("#account-token").type === "hidden" && !location.hash')
    submit("/auth/verify-email")
    wait_for(lambda: feedback("Email verified"), "verify email")
    assert js(
        'document.querySelector(".account-status--success").textContent.includes("Email verified")'
    )
    screenshot("email-verified-mobile.png")
    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user.email_verified_at
        user.account_mail_requested_at = now() - timedelta(minutes=2)
        db.commit()
    navigate("/auth/forgot-password", "#recovery-phone")
    fill("#recovery-phone", "+2348000000077")
    submit("/auth/forgot-password")
    wait_for(lambda: js('document.body?.innerText.includes("Check your email")'), "reset request")
    reset_link = wait_for(lambda: email_link() if email_link() != link else None, "reset email")
    navigate(reset_link.removeprefix(base), "#new-password")
    assert js('!location.hash && document.querySelector("#account-token").type === "hidden"')
    assert js("document.documentElement.scrollWidth <= innerWidth+1")
    screenshot("reset-mobile.png")
    fill("#new-password", "browser-new-password")
    fill("#confirm-password", "different-password")
    submit("/auth/reset-password")
    wait_for(lambda: feedback("Check your details"), "password mismatch")
    assert js('document.querySelector("#confirm-password").getAttribute("aria-invalid") === "true"')
    screenshot("password-error-mobile.png")
    fill("#new-password", "browser-new-password")
    fill("#confirm-password", "browser-new-password")
    submit("/auth/reset-password")
    wait_for(lambda: feedback("Password updated"), "reset result")
    screenshot("password-updated-mobile.png")
    fill("#phone", "+2348000000077")
    fill("#password", "browser-new-password")
    submit("/auth/login")
    wait_for(
        lambda: js('location.pathname === "/" && document.readyState === "complete"'),
        "new password login",
    )
    cdp(
        "Emulation.setDeviceMetricsOverride",
        {"width": 1280, "height": 900, "deviceScaleFactor": 1, "mobile": False},
    )
    navigate("/settings", "#profile-photo")
    screenshot("settings-desktop.png")
    assert js("document.documentElement.scrollWidth <= innerWidth+1")
    navigate("/settings/delete-account", "#delete-password")
    screenshot("delete-desktop.png")
    cdp(
        "Emulation.setDeviceMetricsOverride",
        {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True},
    )
    assert js("document.documentElement.scrollWidth <= innerWidth+1")
    fill("#delete-password", "browser-new-password")
    fill("#delete-confirmation", "DELETE")
    submit("/settings/delete-account")
    wait_for(lambda: feedback("Account deleted"), "account deletion")
    with SessionLocal() as db:
        assert db.get(User, user_id) is None
    assert not list((artifacts / "avatars").iterdir())
    assert not errors, errors
    print(
        json.dumps(
            {
                "passed": True,
                "artifacts": str(artifacts),
                "flows": [
                    "photo success/error/preview",
                    "offline entry preservation",
                    "pending and duplicate submission",
                    "lost response without false success",
                    "email verification",
                    "password validation and success",
                    "account deletion",
                ],
                "widths": [320, 390, 1280],
                "notice_contrast": contrast,
            }
        )
    )
except Exception:
    if ws:
        print("Page:", js("location.pathname"))
        print("Visible message:", js('document.querySelector("#feedback-title")?.textContent'))
        screenshot("failure.png")
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
