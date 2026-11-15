# ruff: noqa: E402, E501
"""Install entry, native-app suppression and mobile layouts in isolated Chrome."""

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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
artifacts = Path(tempfile.mkdtemp(prefix="nurse-mobile-app-browser-"))


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
    "NURSE_NG_ANDROID_APP_DOWNLOAD_URL": "", "NURSE_NG_IOS_APP_DOWNLOAD_URL": "",
})
from websockets.sync.client import connect

import app.models  # noqa: F401
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.services.auth import register_user

Base.metadata.create_all(engine)
with SessionLocal() as db:
    register_user(db, phone="+2348000000032", password="mobile-test-password", full_name="Mobile Tester")

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


def cdp(method, params=None):
    global sequence
    sequence += 1
    ws.send(json.dumps({"id": sequence, "method": method, "params": params or {}}))
    while True:
        message = json.loads(ws.recv(timeout=45))
        if message.get("method") == "Runtime.exceptionThrown":
            errors.append(message["params"])
        if message.get("id") == sequence:
            assert "error" not in message, message
            return message.get("result", {})


def js(expression):
    result = cdp("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
    assert "exceptionDetails" not in result, result
    return result.get("result", {}).get("value")


def navigate(path):
    cdp("Page.navigate", {"url": base + path})
    wait(lambda: js(f"location.pathname === {json.dumps(path)} && document.readyState === 'complete'"), path)


def screenshot(name):
    (artifacts / name).write_bytes(base64.b64decode(cdp("Page.captureScreenshot", {"format": "png"})["data"]))


try:
    for name, command in [
        ("server", [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(web_port), "--log-level", "warning"]),
        ("chrome", ["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--no-first-run", "--no-default-browser-check", f"--user-data-dir={artifacts / 'chrome'}", f"--remote-debugging-port={chrome_port}", "about:blank"]),
    ]:
        log = (artifacts / (name + ".log")).open("w")
        logs.append(log)
        processes.append(subprocess.Popen(command, cwd=ROOT, env=os.environ.copy(), stdout=log, stderr=log))
    wait(lambda: urllib.request.urlopen(base + "/healthz", timeout=1).status == 200, "server")
    tabs = wait(lambda: json.load(urllib.request.urlopen(f"http://127.0.0.1:{chrome_port}/json/list", timeout=1)), "Chrome")
    ws = connect(next(tab["webSocketDebuggerUrl"] for tab in tabs if tab["type"] == "page"), legacy=True)
    cdp("Page.enable")
    cdp("Runtime.enable")
    navigate("/auth/login")
    assert not js("!!document.querySelector('[data-mobile-install]')")
    js('document.querySelector("#phone").value="+2348000000032"; document.querySelector("#password").value="mobile-test-password"; document.querySelector("form[action=\\"/auth/login\\"]").requestSubmit()')
    wait(lambda: js("location.pathname === '/' && document.readyState === 'complete' && !document.querySelector('[data-mobile-install]')?.hidden"), "member install entry")
    for width in [320, 390, 1280]:
        cdp("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": width < 900})
        navigate("/")
        assert js("!document.querySelector('[data-mobile-install]').hidden")
        assert js("document.documentElement.scrollWidth <= innerWidth + 1")
        screenshot(f"install-entry-{width}.png")
        js("document.querySelector('[data-mobile-install] a').click()")
        wait(lambda: js("location.pathname === '/app' && document.readyState === 'complete'"), "app page")
        assert js("document.querySelector('main').textContent.includes('Android download is being prepared')")
        assert js("document.querySelector('main').textContent.includes('iPhone release is being prepared')")
        assert js("document.documentElement.scrollWidth <= innerWidth + 1")
        screenshot(f"download-page-{width}.png")
    cdp("Emulation.setDeviceMetricsOverride", {"width": 320, "height": 900, "deviceScaleFactor": 1, "mobile": True})
    js("document.documentElement.dataset.theme='dark'; document.documentElement.style.fontSize='200%'")
    assert js("document.documentElement.scrollWidth <= innerWidth + 1")
    screenshot("download-large-text-dark-320.png")
    navigate("/settings")
    assert js("!!document.querySelector('main a[href=\"/app\"]')")
    cdp("Page.addScriptToEvaluateOnNewDocument", {"source": "window.Capacitor = { isNativePlatform: () => true };"})
    navigate("/")
    assert js("document.querySelector('[data-mobile-install]').hidden")
    assert not errors, errors
    assert not (artifacts / "server.log").read_text().strip()
    report = {"passed": True, "widths": [320, 390, 1280], "native_detection": "simulated Capacitor API", "artifacts": str(artifacts)}
    (artifacts / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
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
