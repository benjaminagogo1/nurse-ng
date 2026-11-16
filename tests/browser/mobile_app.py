# ruff: noqa: E402, E501
"""Install actions, browser eligibility, fallback steps and layouts in isolated Chrome."""

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
    previous_document = js("performance.timeOrigin")
    cdp("Page.navigate", {"url": base + path})
    wait(lambda: js(f"performance.timeOrigin !== {previous_document} && location.pathname === {json.dumps(path)} && document.readyState === 'complete'"), path)


def reset_reminder():
    # Reset this browser preference between independent installation examples.
    js("localStorage.removeItem('nurse-ng-install-reminder'); sessionStorage.removeItem('nurse-ng-install-reminder')")


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
    cdp("Emulation.setFocusEmulationEnabled", {"enabled": True})
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
        # An eligible banner opens Chrome's OS prompt; its mocked choice is checked below.
        navigate("/app")
        assert js("!!document.querySelector('[data-install-platform=android]') && !!document.querySelector('[data-install-platform=apple]')")
        for device in ["android", "apple"]:
            js(f"document.querySelector('[data-install-platform={device}]').click()")
            assert js(f"document.querySelector('[data-install-help={device}]').open")
        assert js("document.documentElement.scrollWidth <= innerWidth + 1")
        screenshot(f"download-page-{width}.png")
    navigate("/")
    assert js("!!document.querySelector('[data-dismiss-install]')")
    js("document.querySelector('[data-dismiss-install]').focus()")
    cdp("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, "text": "\r", "unmodifiedText": "\r"})
    cdp("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13})
    wait(lambda: js("document.querySelector('[data-mobile-install]').hidden"), "keyboard reminder dismissal")
    assert js("document.querySelector('[data-mobile-install]').hidden && document.activeElement.id === 'main'")
    for path in ["/jobs", "/settings", "/"]:
        navigate(path)
        assert js("document.querySelector('[data-mobile-install]').hidden")
    navigate("/settings")
    assert js("!!document.querySelector('main a[href=\"/app\"]')")
    screenshot("dismissed-reminder-settings.png")
    navigate("/app")
    assert js("!!document.querySelector('[data-install-platform=android]') && !!document.querySelector('[data-install-platform=apple]')")
    cdp("Emulation.setDeviceMetricsOverride", {"width": 320, "height": 900, "deviceScaleFactor": 1, "mobile": True})
    js("document.documentElement.dataset.theme='dark'; document.documentElement.style.fontSize='200%'")
    assert js("document.documentElement.scrollWidth <= innerWidth + 1")
    screenshot("download-large-text-dark-320.png")
    # Chrome checks the real manifest/icons/service worker; OS prompt choices are simulated below.
    js("navigator.serviceWorker.ready.then(() => true)")
    manifest = cdp("Page.getAppManifest")
    eligibility = cdp("Page.getInstallabilityErrors")
    assert not manifest["errors"], manifest
    assert not eligibility["installabilityErrors"], eligibility
    real_prompt_offered = js("!document.querySelector('button[data-web-install]').hidden")
    assert {"192x192", "512x512"} <= {icon["sizes"] for icon in json.loads(manifest["data"])["icons"]}
    assert js("document.querySelector('link[rel=apple-touch-icon]').href.endsWith('/app-icon-180.png')")
    js("""window.installCalls = 0;
      window.offerInstall = (outcome, fail = false, pending = false) => {
        const event = new Event('beforeinstallprompt', {cancelable: true});
        event.prompt = () => { window.installCalls += 1;
          return fail ? Promise.reject(new Error('Test prompt unavailable')) : Promise.resolve(); };
        event.userChoice = pending ? new Promise(resolve => { window.finishInstall = resolve; })
          : Promise.resolve({outcome});
        window.dispatchEvent(event);
        return event.defaultPrevented;
      };""")
    assert js("offerInstall('dismissed')")
    assert js("installCalls === 0 && !document.querySelector('button[data-web-install]').hidden")
    js("document.querySelector('button[data-web-install]').click()")
    wait(lambda: js("document.querySelector('[data-install-status]').textContent.includes('cancelled')"), "dismissed install fallback")
    assert js("installCalls === 1 && document.querySelector('button[data-web-install]').hidden && document.querySelector('[data-install-help=desktop]').open")
    js("document.querySelector('button[data-web-install]').click()")
    assert js("installCalls === 1")
    assert js("offerInstall('accepted', true)")
    js("document.querySelector('button[data-web-install]').click()")
    wait(lambda: js("document.querySelector('[data-install-status]').textContent.includes('couldn’t open')"), "prompt error fallback")
    assert js("installCalls === 2")
    # A fresh offer can be retried; overlapping clicks do not open duplicate OS prompts.
    assert js("offerInstall('accepted', false, true)")
    js("document.querySelector('button[data-web-install]').click(); document.querySelector('button[data-web-install]').click()")
    assert js("installCalls === 3 && document.querySelector('button[data-web-install]').disabled")
    js("finishInstall({outcome: 'accepted'})")
    wait(lambda: js("document.querySelector('[data-install-status]').textContent.includes('Installation started')"), "accepted install")
    js("window.dispatchEvent(new Event('appinstalled'))")
    assert js("document.querySelector('[data-install-status]').textContent.includes('already using') && document.querySelector('button[data-web-install]').hidden")
    screenshot("installed-state-320.png")
    navigate("/")
    assert js("document.querySelector('[data-mobile-install]').hidden")
    reset_reminder()
    navigate("/")
    # The existing banner itself now invokes an available prompt without navigating away.
    assert js("!document.querySelector('[data-mobile-install]').hidden")
    js("""window.bannerInstallCalls = 0;
      const offer = new Event('beforeinstallprompt', {cancelable: true});
      offer.prompt = () => { bannerInstallCalls += 1; return Promise.resolve(); };
      offer.userChoice = Promise.resolve({outcome: 'accepted'});
      window.dispatchEvent(offer);
      document.querySelector('[data-mobile-install] a').click();""")
    wait(lambda: js("document.querySelector('[data-mobile-install]').hidden"), "accepted banner install")
    assert js("location.pathname === '/' && bannerInstallCalls === 1")
    navigate("/jobs")
    assert js("document.querySelector('[data-mobile-install]').hidden")
    # Device emulation verifies that Android uses its available prompt and Safari shows steps.
    cdp("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 900, "deviceScaleFactor": 1, "mobile": True})
    cdp("Emulation.setUserAgentOverride", {"userAgent": "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Mobile Safari/537.36", "platform": "Linux armv8l"})
    navigate("/app")
    js("""window.androidInstallCalls = 0;
      const androidOffer = new Event('beforeinstallprompt', {cancelable: true});
      androidOffer.prompt = () => { androidInstallCalls += 1; return Promise.resolve(); };
      androidOffer.userChoice = Promise.resolve({outcome: 'dismissed'});
      window.dispatchEvent(androidOffer);
      document.querySelector('[data-install-platform=android]').click();""")
    wait(lambda: js("document.querySelector('[data-install-status]').textContent.includes('cancelled')"), "Android summary prompt")
    assert js("androidInstallCalls === 1 && document.querySelector('[data-install-help=android]').open")
    screenshot("android-install-390.png")
    cdp("Emulation.setUserAgentOverride", {"userAgent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1", "platform": "iPhone"})
    navigate("/app")
    js("document.querySelector('[data-install-platform=apple]').click()")
    assert js("document.querySelector('[data-install-help=apple]').open && document.querySelector('[data-install-help=apple]').textContent.includes('Add to Home Screen')")
    assert js("document.documentElement.scrollWidth <= innerWidth + 1")
    screenshot("iphone-install-390.png")
    reset_reminder()
    navigate("/")
    # Safari's help link suppresses further reminders even without an OS prompt event.
    js("document.querySelector('[data-mobile-install] a').click()")
    wait(lambda: js("location.pathname === '/app' && document.readyState === 'complete'"), "manual install help")
    navigate("/")
    assert js("document.querySelector('[data-mobile-install]').hidden")
    reset_reminder()
    navigate("/")
    # A storage quota failure must still allow immediate dismissal and installation help.
    js("""const originalSetItem = Storage.prototype.setItem;
      Storage.prototype.setItem = function(key, value) {
        if (key === 'nurse-ng-install-reminder') throw new DOMException('Test quota', 'QuotaExceededError');
        return originalSetItem.call(this, key, value);
      };
      document.querySelector('[data-dismiss-install]').click();""")
    assert js("document.querySelector('[data-mobile-install]').hidden && document.activeElement.id === 'main'")
    navigate("/app")
    assert js("!!document.querySelector('[data-install-platform=apple]')")
    standalone_script = cdp("Page.addScriptToEvaluateOnNewDocument", {"source": "Object.defineProperty(navigator, 'standalone', {value: true});"})["identifier"]
    navigate("/")
    assert js("document.querySelector('[data-mobile-install]').hidden")
    navigate("/app")
    assert js("document.querySelector('[data-install-status]').textContent.includes('already using') && document.querySelector('[data-install-help=apple]').hidden")
    cdp("Page.removeScriptToEvaluateOnNewDocument", {"identifier": standalone_script})
    navigate("/settings")
    assert js("!!document.querySelector('main a[href=\"/app\"]')")
    cdp("Page.addScriptToEvaluateOnNewDocument", {"source": "window.Capacitor = { isNativePlatform: () => true };"})
    navigate("/")
    assert js("document.querySelector('[data-mobile-install]').hidden")
    assert not errors, errors
    assert not (artifacts / "server.log").read_text().strip()
    report = {"passed": True, "widths": [320, 390, 1280],
              "browser_installability": eligibility, "device_steps": ["android", "apple", "desktop"],
              "real_browser_prompt_offered": real_prompt_offered,
              "prompt_choices": "simulated acceptance, dismissal, failure and overlapping clicks",
              "device_detection": "Android/iPhone user agent emulation and simulated iOS standalone",
              "banner_prompt": True, "reminder_dismissal": "keyboard action, navigation, reload and storage failure",
              "reminder_suppression": "accepted installation, appinstalled and Safari help-link navigation",
              "native_detection": "simulated Capacitor API", "artifacts": str(artifacts)}
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
