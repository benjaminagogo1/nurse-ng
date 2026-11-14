# ruff: noqa: E402, E501
"""Isolated staff analytics, ID copying, live updates and honest browser activity.

All members and history in this runner are synthetic fixtures in a temporary DB.
No real accounts, application data, emails or external services are used.
"""

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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
artifacts = Path(tempfile.mkdtemp(prefix="nurse-activity-browser-"))


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
    "NURSE_NG_RECRUITMENT_SEARXNG_URLS": "", "NURSE_NG_RECRUITMENT_SEARCH_KEY": "",
})

from alembic import command
from alembic.config import Config
from websockets.sync.client import connect

from app.db.session import SessionLocal
from app.models.user import User
from app.services.activity import activity_report, record_activity

command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
names = ["Ada Okafor", "Chika Eze", "Amina Bello", "Tosin Adeyemi", "Ngozi Obi", "Emeka Nwosu",
         "Fatima Yusuf", "Blessing James", "Ibrahim Musa", "Grace Udo"]
identifiers = []
timestamp = datetime.now(UTC)
with SessionLocal() as db:
    staff = User(phone="+2348000010000", full_name="Analytics Operator", is_staff=True)
    staff.set_password("browser-only-password")
    db.add(staff)
    for number in range(30):
        member = User(phone=f"+234800002{number:04}", full_name=names[number % 10] + (f" {number // 10 + 1}" if number >= 10 else ""))
        member.set_password("browser-only-password")
        db.add(member)
        db.flush()
        identifiers.append(member.id)
    for number, role in enumerate(["employer", "employer", "partner"]):
        db.add(User(phone=f"+234800003{number:04}", full_name=f"Example {role.title()} {number}", account_type=role, hashed_password="unused"))
    db.commit()
    staff_id = staff.id
    counts = [5, 6, 4, 10, 8, 11, 9, 14, 16, 15, 12, 18, 20, 17]
    for offset, count in enumerate(reversed(counts)):
        for identifier in identifiers[:count]:
            record_activity(db, identifier, 0, at=timestamp - timedelta(days=offset, minutes=2))
    db.commit()

processes, logs, errors, requests = [], [], [], []
ws, sequence = None, 0


def wait_for(fn, label, seconds=40):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
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
        response = json.loads(ws.recv(timeout=40))
        if response.get("method") == "Runtime.exceptionThrown":
            errors.append(response["params"])
        if response.get("method") == "Network.requestWillBeSent":
            requests.append(response["params"]["request"]["url"])
        if response.get("id") == sequence:
            assert "error" not in response, response
            return response.get("result", {})


def js(expression):
    result = cdp("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
    assert "exceptionDetails" not in result, result
    return result.get("result", {}).get("value")


def navigate(path, selector="main"):
    cdp("Page.navigate", {"url": base + path})
    wait_for(lambda: js(f"location.pathname === {json.dumps(path.split('?')[0])} && document.readyState === 'complete' && !!document.querySelector({json.dumps(selector)})"), path)


def viewport(width):
    cdp("Emulation.setDeviceMetricsOverride", {"width": width, "height": 1000, "deviceScaleFactor": 1, "mobile": width < 900})


def screenshot(name):
    (artifacts / name).write_bytes(base64.b64decode(cdp("Page.captureScreenshot", {"format": "png"})["data"]))


def visible_metrics():
    return js("Object.fromEntries([...document.querySelectorAll('[data-metric]')].map(n => [n.dataset.metric, Number(n.textContent)]))")


try:
    for name, args in [
        ("server", [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"]),
        ("chrome", ["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--disable-extensions", "--disable-sync", "--no-first-run", "--no-default-browser-check", "--password-store=basic", "--disable-background-networking", f"--user-data-dir={artifacts / 'chrome'}", f"--remote-debugging-port={chrome_port}", "about:blank"]),
    ]:
        log = (artifacts / f"{name}.log").open("w")
        logs.append(log)
        processes.append(subprocess.Popen(args, cwd=ROOT, env=os.environ.copy(), stdout=log, stderr=log))
    wait_for(lambda: urllib.request.urlopen(base + "/healthz", timeout=1).status == 200, "server")
    tabs = wait_for(lambda: json.load(urllib.request.urlopen(f"http://127.0.0.1:{chrome_port}/json/list", timeout=1)), "Chrome")
    tab = next(t for t in tabs if t["type"] == "page")
    ws = connect(tab["webSocketDebuggerUrl"], legacy=True)
    for method in ["Page.enable", "Runtime.enable", "Network.enable"]:
        cdp(method)
    cdp("Page.bringToFront")
    # A controllable browser clock/timer tests the real handlers without waiting
    # minutes or changing the server clock. This is not part of the application.
    cdp("Page.addScriptToEvaluateOnNewDocument", {"source": """
      window.__clockOffset = 0;
      const originalNow = Date.now;
      Date.now = () => originalNow() + window.__clockOffset;
      const originalInterval = window.setInterval;
      window.setInterval = (callback, delay, ...args) => {
        if (delay === 60000) { window.__activityTick = callback; return 999999; }
        return originalInterval(callback, delay, ...args);
      };
    """})
    viewport(1440)
    navigate("/auth/login", "#phone")
    js("document.querySelector('#phone').value='+2348000010000'; document.querySelector('#password').value='browser-only-password'; document.querySelector('#password').form.requestSubmit()")
    wait_for(lambda: js("!!document.querySelector('.account-menu') && document.readyState === 'complete'"), "staff sign-in")
    for width in (1280, 320):
        viewport(width)
        assert js("document.querySelector('[data-feedback-panel]').dataset.feedbackCompact") == "true"
        assert js("document.querySelector('[data-feedback-panel]').getBoundingClientRect().width <= Math.min(400, innerWidth)")
        assert js("document.documentElement.scrollWidth <= innerWidth + 1")
        screenshot(f"sign-in-compact-{width}.png")
    js("document.querySelector('form[action=\"/auth/logout\"]').requestSubmit()")
    wait_for(lambda: js("document.querySelector('#feedback-title')?.textContent === 'Signed out'"), "sign-out notice")
    for width in (1280, 320):
        viewport(width)
        assert js("document.querySelector('[data-feedback-panel]').getBoundingClientRect().width <= Math.min(400, innerWidth)")
        screenshot(f"sign-out-compact-{width}.png")
    navigate("/jobs", ".jobs-page")
    assert js("!!document.querySelector('.jobs-guest-note') && !document.querySelector('.sidebar')")
    navigate("/auth/login", "#phone")
    js("document.querySelector('#phone').value='+2348000010000'; document.querySelector('#password').value='browser-only-password'; document.querySelector('#password').form.requestSubmit()")
    wait_for(lambda: js("!!document.querySelector('.account-menu') && document.readyState === 'complete'"), "staff signs in again")
    viewport(1440)
    cdp("Emulation.setScriptExecutionDisabled", {"value": True})
    navigate("/staff/users", "[data-analytics-page]")
    assert js("document.querySelector('[data-live-label]').textContent") == "Updated on page load"
    assert js("document.querySelector('[data-analytics-fallback]').hidden") is False
    assert visible_metrics()["total"] == 30
    cdp("Emulation.setScriptExecutionDisabled", {"value": False})
    navigate("/staff/users", "[data-analytics-page]")
    js("document.querySelector('#display-form').elements.theme.value='light'; document.querySelector('#display-form').dispatchEvent(new Event('change', {bubbles:true})); document.documentElement.style.scrollBehavior='auto'")
    assert visible_metrics()["total"] == 30 and visible_metrics()["today"] == 17
    assert js("document.querySelectorAll('[data-member-id]').length") == 25
    assert js("document.querySelectorAll('[data-chart-point]').length") == 14
    assert js("document.querySelector('[data-copy-id]').hidden") is False
    for width in [1440, 1280, 390, 320]:
        viewport(width)
        js("scrollTo({top:0, behavior:'instant'})")
        assert js("document.documentElement.scrollWidth <= innerWidth + 1"), (width, "page overflow")
        assert js("[...document.querySelectorAll('.analytics-chart-y span')].every(n => { const size = parseFloat(getComputedStyle(n).fontSize); return size >= 10 && size <= 24; })"), (width, "chart label readability")
        screenshot(f"overview-{width}.png")
        js("document.querySelector('.analytics-chart-panel').scrollIntoView({block:'start', behavior:'instant'})")
        screenshot(f"chart-{width}.png")
        js("document.querySelector('.analytics-members').scrollIntoView({block:'start', behavior:'instant'})")
        screenshot(f"members-{width}.png")
    print("Responsive dashboard and 14 days of fixture history passed.", flush=True)

    viewport(1280)
    cdp("Page.bringToFront")
    js("scrollTo({top:0, behavior:'instant'}); document.activeElement.blur(); document.querySelector('[data-chart-point]').focus(); new Promise(requestAnimationFrame)")
    chart_focus = js("({selected:document.querySelector('[data-chart-value]').textContent, expected:document.querySelector('[data-chart-point]').dataset.count, focused:document.activeElement.outerHTML.slice(0,500), ready:document.querySelector('[data-analytics-refresh]').hidden, documentFocused:document.hasFocus(), hidden:document.hidden})")
    assert chart_focus['selected'] == chart_focus['expected'], (chart_focus, errors)
    js("document.querySelector('a[rel=next]').click()")
    wait_for(lambda: js("location.search.includes('page=2') && document.querySelectorAll('[data-member-id]').length === 5"), "member pagination")
    navigate("/staff/users?q=" + str(identifiers[0]), "[data-member-id]")
    assert js("document.querySelectorAll('[data-member-id]').length") == 1
    assert visible_metrics()["total"] == 30
    cdp("Browser.grantPermissions", {"origin": base, "permissions": ["clipboardReadWrite", "clipboardSanitizedWrite"]})
    js("document.querySelector('[data-copy-id]').click()")
    wait_for(lambda: js("document.querySelector('[data-copy-status]').textContent === 'User ID copied.'"), "copy member ID")
    assert js("navigator.clipboard.readText()") == str(identifiers[0])
    js("Object.defineProperty(navigator, 'clipboard', {configurable:true, value:{writeText:async()=>{throw Error('blocked')}}}); document.querySelector('[data-copy-id]').click()")
    wait_for(lambda: js("document.querySelector('[data-copy-status]').textContent.includes('selected')"), "copy fallback")
    assert js("getSelection().toString()") == str(identifiers[0])
    navigate("/settings", "#account-user-id")
    assert js("document.querySelector('#account-user-id').textContent") == str(staff_id)
    assert js("document.body.textContent.includes('" + str(identifiers[0]) + "')") is False
    print("Search, pagination, private account IDs and both copy paths passed.", flush=True)

    navigate("/staff/users", "[data-analytics-page]")
    initial = visible_metrics()["today"]
    with SessionLocal() as db:
        record_activity(db, identifiers[-1], 0)
        db.commit()
    js("document.querySelector('[data-analytics-refresh]').click()")
    wait_for(lambda: visible_metrics()["today"] == initial + 1, "live metric refresh")
    with SessionLocal() as db:
        actual = activity_report(db)
    assert {key: actual[key] for key in visible_metrics()} == visible_metrics()
    navigate("/staff/users?account_type=all&include_staff=1&days=30", "[data-analytics-page]")
    assert visible_metrics()["total"] == 34
    assert js("document.querySelector('.analytics-ranges [aria-current]').textContent") == "30 days"
    print("Live refresh and account/staff scope passed.", flush=True)

    navigate("/staff/users", "[data-analytics-page]")
    pulse_before = len([url for url in requests if url.endswith('/activity/pulse')])
    js("window.__clockOffset += 120000; window.__activityTick(); document.dispatchEvent(new KeyboardEvent('keydown', {key:'a', bubbles:true})); scrollTo({top:500, behavior:'instant'}); window.__activityTick(); new Promise(resolve=>setTimeout(resolve, 150))")
    assert len([url for url in requests if url.endswith('/activity/pulse')]) == pulse_before
    cdp("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Tab", "code": "Tab", "windowsVirtualKeyCode": 9})
    cdp("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Tab", "code": "Tab", "windowsVirtualKeyCode": 9})
    js("new Promise(resolve=>setTimeout(resolve, 200))")
    assert len([url for url in requests if url.endswith('/activity/pulse')]) == pulse_before + 1
    js("window.__clockOffset += 120000; window.__activityTick(); new Promise(resolve=>setTimeout(resolve, 100))")
    assert len([url for url in requests if url.endswith('/activity/pulse')]) == pulse_before + 1
    hidden_tab = cdp("Target.createTarget", {"url": "about:blank"})["targetId"]
    cdp("Target.activateTarget", {"targetId": hidden_tab})
    wait_for(lambda: js("document.hidden"), "hidden dashboard tab")
    js("window.__clockOffset += 120000; window.__activityTick(); new Promise(resolve=>setTimeout(resolve, 100))")
    assert len([url for url in requests if url.endswith('/activity/pulse')]) == pulse_before + 1
    cdp("Target.closeTarget", {"targetId": hidden_tab})
    cdp("Target.activateTarget", {"targetId": tab["id"]})
    wait_for(lambda: js("!document.hidden"), "visible dashboard")
    print("Idle, synthetic and hidden activity excluded; trusted interaction sends a pulse.", flush=True)

    for theme in ["light", "dark"]:
        js(f"document.querySelector('#display-form').elements.theme.value='{theme}'; document.querySelector('#display-form').dispatchEvent(new Event('change', {{bubbles:true}}))")
        for width in [1280, 390]:
            viewport(width)
            js("document.activeElement.blur(); scrollTo({top:0, behavior:'instant'})")
            assert js("document.documentElement.scrollWidth <= innerWidth+1")
            assert js("[...document.querySelectorAll('.analytics-chart-y span')].every(n => parseFloat(getComputedStyle(n).fontSize) <= 24)")
            screenshot(f"{theme}-{width}.png")
    js("document.documentElement.dataset.contrast='high'; document.documentElement.style.fontSize='24px'")
    viewport(390)
    assert js("document.documentElement.scrollWidth <= innerWidth+1"), "enlarged text overflow"
    screenshot("large-text.png")
    js("document.documentElement.style.fontSize=''; delete document.documentElement.dataset.contrast")
    cdp("Network.emulateNetworkConditions", {"offline": True, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1})
    js("document.querySelector('[data-analytics-refresh]').click()")
    wait_for(lambda: js("document.querySelector('[data-live-label]').textContent.includes('Offline')"), "offline indication")
    assert visible_metrics()["total"] == 30
    cdp("Network.emulateNetworkConditions", {"offline": False, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1})
    wait_for(lambda: js("document.querySelector('[data-live-label]').textContent === 'Updates every 30 seconds'"), "online recovery")
    print("Light/dark themes, enlarged text and offline recovery passed.", flush=True)

    navigate("/staff/admins?q=" + str(identifiers[0]), ".admin-page")
    js("document.querySelector('.admin-member details').open=true; document.querySelector('.admin-member [name=current_password]').value='browser-only-password'; document.querySelector('.admin-member form').requestSubmit()")
    wait_for(lambda: js("document.querySelector('#feedback-title')?.textContent === 'Administrator added'"), "grant administrator")
    with SessionLocal() as db:
        assert db.get(User, identifiers[0]).is_staff
    for width in (1280, 320):
        viewport(width)
        assert js("document.documentElement.scrollWidth <= innerWidth + 1")
        screenshot(f"administrators-{width}.png")
    selector = f'form[action="/staff/admins/{identifiers[0]}"]'
    js(f"const roleForm = document.querySelector({json.dumps(selector)}); roleForm.closest('details').open=true; roleForm.elements.current_password.value='browser-only-password'; roleForm.requestSubmit()")
    wait_for(lambda: js("document.querySelector('#feedback-title')?.textContent === 'Administrator access removed'"), "revoke administrator")
    with SessionLocal() as db:
        assert not db.get(User, identifiers[0]).is_staff
    navigate("/staff/users", "[data-analytics-page]")
    with SessionLocal() as db:
        operator = db.get(User, staff_id)
        operator.is_staff = False
        db.commit()
    js("document.querySelector('[data-analytics-refresh]').click()")
    wait_for(lambda: js("document.querySelector('[data-live-label]').textContent.includes('Access changed')"), "revoked staff access")
    assert js("document.querySelectorAll('[data-member-id]').length") == 0
    assert not errors, errors
    (artifacts / "report.json").write_text(json.dumps({"passed": True, "javascript_errors": errors, "fixture_accounts": 34, "screenshots": len(list(artifacts.glob('*.png')))}, indent=2))
    print(f"Activity browser journey passed. Artifacts: {artifacts}", flush=True)
finally:
    (artifacts / "javascript-errors.json").write_text(json.dumps(errors, indent=2))
    if ws:
        ws.close()
    for process in reversed(processes):
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    for log in logs:
        log.close()
    print(f"Browser artifacts: {artifacts}", flush=True)
