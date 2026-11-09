# ruff: noqa: E402, E501
"""Real-browser tour journeys against a temporary migrated database.

Run: venv/bin/python tests/browser/tour.py
Add --loading-only to check repeated input and pause during a delayed save.
Uses the existing Chrome/CDP harness pattern; never signs into the working DB.
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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
artifacts = Path(tempfile.mkdtemp(prefix="nurse-tour-browser-"))


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


port, chrome_port = free_port(), free_port()
base = f"http://127.0.0.1:{port}"
os.environ.update({
    "NURSE_NG_ENVIRONMENT": "development",
    "NURSE_NG_DEBUG": "0",
    "NURSE_NG_SECRET_KEY": secrets.token_urlsafe(32),
    "NURSE_NG_SESSION_HTTPS_ONLY": "0",
    "NURSE_NG_ALLOWED_HOSTS": "127.0.0.1,localhost",
    "NURSE_NG_DATABASE_URL": f"sqlite:///{artifacts / 'browser.db'}",
    "NURSE_NG_PUBLIC_BASE_URL": base,
    "NURSE_NG_ACCOUNT_MAIL_BACKEND": "disabled",
})
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from websockets.sync.client import connect

from app.db.session import SessionLocal
from app.models.profile import NurseProfile
from app.models.tour import UserTour
from app.models.user import User
from app.services.auth import register_user
from app.services.tours import snapshot, transition

command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
roles = [
    ("+2348000000101", "employer", False),
    ("+2348000000102", "nurse", True),
    ("+2348000000103", "partner", False),
]
with SessionLocal() as db:
    for phone, role, staff in roles:
        user = register_user(db, phone=phone, password="browser-password",
                             full_name="Tour Test " + role, account_type=role)
        user.is_staff = staff
        db.commit()

processes, logs, errors, paused = [], [], [], []
navigation_requests = {}
ws, sequence = None, 0


def wait_for(fn, label, seconds=35):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            result = fn()
            if result:
                return result
        except (OSError, ValueError, AttributeError):
            pass
        time.sleep(0.08)
    raise AssertionError("Timed out: " + label)


def cdp(method, params=None):
    global sequence
    sequence += 1
    ws.send(json.dumps({"id": sequence, "method": method, "params": params or {}}))
    deadline = time.monotonic() + 40
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Browser command timed out: " + method)
        response = json.loads(ws.recv(timeout=remaining))
        if response.get("method") == "Runtime.exceptionThrown":
            errors.append(response["params"])
        if response.get("method") == "Fetch.requestPaused":
            paused.append(response["params"])
        if response.get("method") == "Network.requestWillBeSent":
            event = response["params"]
            if event.get("type") == "Document":
                navigation_requests.setdefault(event["requestId"], {}).update(
                    url=event["request"]["url"],
                )
        if response.get("method") == "Network.requestWillBeSentExtraInfo":
            event = response["params"]
            metadata = {key.lower(): value for key, value in event["headers"].items()
                        if key.lower().startswith("sec-fetch-")}
            if metadata.get("sec-fetch-dest") == "document":
                navigation_requests.setdefault(event["requestId"], {}).update(metadata)
        if response.get("id") == sequence:
            assert "error" not in response, response
            return response.get("result", {})


def js(expression):
    result = cdp("Runtime.evaluate", {
        "expression": expression, "returnByValue": True, "awaitPromise": True,
    })
    assert "exceptionDetails" not in result, result
    return result.get("result", {}).get("value")


def navigate(path):
    previous_origin = js("performance.timeOrigin")
    navigation = cdp("Page.navigate", {"url": base + path})
    if navigation.get("loaderId"):
        wait_for(lambda: js(f"performance.timeOrigin !== {previous_origin}"), "new document")
    wait_for(lambda: js(
        f"location.pathname === {json.dumps(path.split('?')[0].split('#')[0])} && "
        'document.readyState === "complete" && !!document.querySelector("main")'
    ), path)


def viewport(width=390, height=844):
    cdp("Emulation.setDeviceMetricsOverride", {
        "width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 900,
    })


def screenshot(name):
    (artifacts / name).write_bytes(base64.b64decode(
        cdp("Page.captureScreenshot", {"format": "png"})["data"]
    ))


def click(selector):
    cdp("Page.bringToFront")
    point = js(f"""(async () => {{
      const el = document.querySelector({json.dumps(selector)});
      if (!el || el.hidden || el.closest('[hidden]')) throw new Error('Unavailable click: ' + {json.dumps(selector)});
      el.scrollIntoView({{block: 'center', behavior: 'instant'}});
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      const r = el.getBoundingClientRect();
      const x=r.x+r.width/2, y=r.y+r.height/2;
      const hit=document.elementFromPoint(x,y);
      window.tourTestClicks=[];
      for (const type of ['pointerdown','pointerup','click']) {{
        document.addEventListener(type, event => window.tourTestClicks.push({{
          type, target:event.target.tagName, intended:el===event.target || el.contains(event.target),
          x:event.clientX,y:event.clientY
        }}), {{once:true,capture:true}});
      }}
      // CDP input uses the visual viewport; DOM rectangles use the layout
      // viewport. Mobile focus/zoom can pan one relative to the other.
      return {{x:x-(visualViewport?.offsetLeft||0),y:y-(visualViewport?.offsetTop||0),
        clickable:hit===el || el.contains(hit),hit:hit?.tagName}};
    }})()""")
    assert point.pop("clickable"), (selector, point)
    point.pop("hit")
    cdp("Input.dispatchMouseEvent", {"type": "mousePressed", **point, "button": "left", "clickCount": 1})
    cdp("Input.dispatchMouseEvent", {"type": "mouseReleased", **point, "button": "left", "clickCount": 1})


def key(name, code):
    cdp("Input.dispatchKeyEvent", {"type": "keyDown", "key": name, "code": name,
                                 "windowsVirtualKeyCode": code})
    cdp("Input.dispatchKeyEvent", {"type": "keyUp", "key": name, "code": name,
                                 "windowsVirtualKeyCode": code})


def tour_step(name):
    wait_for(lambda: js(
        'document.readyState === "complete" && '
        f'document.querySelector("#guided-tour[open]")?.dataset.step === {json.dumps(name)} && '
        'document.querySelector(".tour-card").getAttribute("aria-busy") === "false"'
    ), "tour: " + name)
    cdp("Page.bringToFront")


def state():
    return js("fetch('/tour', {cache:'no-store'}).then(r => r.json())")


def geometry(name, *, capture=True):
    # Wait for resize observers and the short spotlight transition.
    time.sleep(0.22)
    result = js("""(() => {
      const d = document.querySelector('#guided-tour');
      const c = d.querySelector('.tour-card').getBoundingClientRect();
      const s = d.querySelector('.tour-spotlight').getBoundingClientRect();
      const r = document.querySelector('[data-tour="'+d.dataset.step+'"]').getBoundingClientRect();
      return {
        width:innerWidth, height:innerHeight, pageWidth:document.documentElement.scrollWidth,
        card:{x:c.x,y:c.y,right:c.right,bottom:c.bottom},
        spot:{x:s.x,y:s.y,width:s.width,height:s.height},
        targetVisible:r.bottom>0 && r.top<innerHeight,
        position:d.querySelector('#tour-position').textContent
      };
    })()""")
    assert result["pageWidth"] <= result["width"] + 1, result
    box = result["card"]
    assert box["x"] >= 0 and box["y"] >= 0, result
    assert box["right"] <= result["width"] + 1, result
    assert box["bottom"] <= result["height"] + 1, result
    assert result["spot"]["width"] > 0 and result["spot"]["height"] > 0, result
    assert result["targetVisible"], result
    if capture:
        screenshot(name + ".png")


def logout():
    navigate("/settings")
    js('document.querySelector(\'form[action="/auth/logout"]\').requestSubmit()')
    wait_for(lambda: js('document.readyState === "complete" && document.body?.classList.contains("is-public")'), "sign out")


def login(phone):
    navigate("/auth/login")
    js(f"""(() => {{
      document.querySelector('#phone').value={json.dumps(phone)};
      document.querySelector('#password').value='browser-password';
      document.querySelector('form[action="/auth/login"]').requestSubmit();
    }})()""")
    wait_for(lambda: js('document.readyState === "complete" && location.pathname === "/" && document.body?.classList.contains("is-app")'), "sign in")


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
        log = (artifacts / f"{name}.log").open("w")
        logs.append(log)
        processes.append(subprocess.Popen(args, cwd=ROOT, env=os.environ.copy(),
                                          stdout=log, stderr=log))
    wait_for(lambda: urllib.request.urlopen(base + "/healthz", timeout=1).status == 200, "server")
    tabs = wait_for(lambda: json.load(urllib.request.urlopen(
        f"http://127.0.0.1:{chrome_port}/json/list", timeout=1,
    )), "Chrome")
    ws = connect(next(t["webSocketDebuggerUrl"] for t in tabs if t["type"] == "page"), legacy=True)
    for method in ["Page.enable", "Runtime.enable", "Network.enable"]:
        cdp(method)
    cdp("Page.bringToFront")
    viewport()
    navigate("/auth/register")
    # Registration must run after the offline worker controls the page: its
    # forwarded navigation previously suppressed the one-time invitation.
    js("navigator.serviceWorker.ready.then(() => true)")
    wait_for(lambda: js("!!navigator.serviceWorker.controller"), "offline worker control")
    js("""document.querySelector('#full_name').value='Ada Tour';
      document.querySelector('#phone').value='+2348000000088';
      document.querySelector('#password').value='browser-password';
      document.querySelector('#register-form').requestSubmit()""")
    wait_for(lambda: js('location.pathname === "/welcome" && document.readyState === "complete"'), "welcome")
    assert js('!document.querySelector(".tour-prompt").hidden')
    assert not js('document.querySelector("#guided-tour").open')
    assert js('JSON.parse(document.querySelector("#tour-config").textContent).offer')
    js("""(() => {const f=document.querySelector('#display-form');
      f.elements.theme.value='light'; f.dispatchEvent(new Event('change',{bubbles:true}));})()""")
    screenshot("first-sign-in-invitation.png")
    click(".tour-prompt [data-tour-start]")
    tour_step("dashboard")
    old_url = js("location.pathname + location.search")
    first_run = state()["state"]["run_id"]
    # The real page remains visible, while native modal focus contains interaction.
    for _ in range(8):
        key("Tab", 9)
        focused = js("""({inside:document.querySelector('#guided-tour').contains(document.activeElement),
          active:document.activeElement.outerHTML.slice(0,180), focused:document.hasFocus()})""")
        assert focused["inside"], focused
    js("document.querySelector('.brand').focus()")
    assert js('document.querySelector("#guided-tour").contains(document.activeElement)')
    key("ArrowRight", 39)
    tour_step("profile")
    key("ArrowLeft", 37)
    tour_step("dashboard")
    # A delayed save response must not allow repeated clicks to skip a step.
    cdp("Fetch.enable", {"patterns": [{
        "urlPattern": base + "/tour", "requestStage": "Response",
    }]})
    click("[data-tour-next]")
    wait_for(lambda: (js("true"), paused)[1], "delayed tour save")
    navigation_request = paused.pop()
    click("[data-tour-next]")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.phone == "+2348000000088"))
        assert db.get(UserTour, user.id).step_key == "profile"
    cdp("Fetch.continueResponse", {"requestId": navigation_request["requestId"]})
    cdp("Fetch.disable")
    tour_step("profile")
    click('#guided-tour [data-tour-action="previous"]')
    tour_step("dashboard")
    # Pausing before the save response arrives must prevent its navigation.
    cdp("Fetch.enable", {"patterns": [{
        "urlPattern": base + "/tour", "requestStage": "Response",
    }]})
    click("[data-tour-next]")
    wait_for(lambda: (js("true"), paused)[1], "save to pause")
    pending_save = paused.pop()
    click("[data-tour-pause]")
    cdp("Fetch.continueResponse", {"requestId": pending_save["requestId"]})
    cdp("Fetch.disable")
    wait_for(lambda: js('document.querySelector(".tour-card").getAttribute("aria-busy") === "false"'),
             "paused save settles")
    assert js('location.pathname === "/auth/dashboard" && !document.querySelector("#guided-tour").open')
    assert state()["state"]["index"] == 1
    click(".tour-prompt [data-tour-resume]")
    tour_step("profile")
    click('#guided-tour [data-tour-action="previous"]')
    tour_step("dashboard")
    if "--loading-only" in sys.argv:
        assert not errors, errors
        assert not (artifacts / "server.log").read_text().strip()
        print(json.dumps({
            "passed": True, "artifacts": str(artifacts),
            "flows": ["first invitation", "keyboard focus", "delayed save",
                      "repeated input", "pause during save", "resume saved progress"],
        }), flush=True)
        raise SystemExit(0)
    for index, step in enumerate(state()["steps"]):
        if index:
            click("[data-tour-next]")
            tour_step(step["key"])
        for width in [320, 390, 1280]:
            viewport(width, 844 if width < 900 else 900)
            geometry(step["key"] + "-" + str(width))
    assert js('document.querySelector("[data-tour-next]").textContent === "Finish"')
    click("[data-tour-next]")
    wait_for(lambda: js('!document.querySelector("#guided-tour").open'), "finish")
    assert state()["state"]["status"] == "completed"
    assert js('document.querySelector("#tour-prompt-title").getBoundingClientRect().top < innerHeight')
    navigate(old_url)
    assert not js('document.querySelector("#guided-tour").open')
    assert js('document.querySelector(".tour-prompt").hidden')
    logout()
    login("+2348000000088")
    assert state()["state"]["status"] == "completed"
    assert js('document.querySelector(".tour-prompt").hidden')
    print("PASS: invitation, keyboard, all steps at 320/390/1280, completion and repeat login", flush=True)

    # Restart, skip halfway, then pause and browse while keeping the saved step.
    navigate("/settings")
    click("#guided-tour-settings [data-tour-start]")
    tour_step("dashboard")
    assert state()["state"]["run_id"] != first_run
    click("[data-tour-next]")
    tour_step("profile")
    click('#guided-tour [data-tour-action="skip"]')
    wait_for(lambda: js('!document.querySelector("#guided-tour").open'), "skip")
    logout()
    login("+2348000000088")
    assert state()["state"]["status"] == "skipped"
    assert js('document.querySelector(".tour-prompt").hidden')
    navigate("/settings")
    click("#guided-tour-settings [data-tour-start]")
    tour_step("dashboard")
    for name in ["profile", "jobs"]:
        click("[data-tour-next]")
        tour_step(name)
    saved = state()["state"]
    key("Escape", 27)
    assert not js('document.querySelector("#guided-tour").open')
    assert js('document.activeElement.matches("[data-tour-resume]")')
    navigate("/learning")
    assert not js('document.querySelector("#guided-tour").open')
    assert state()["state"] == saved
    click(".tour-prompt [data-tour-resume]")
    tour_step("jobs")
    previous_origin = js("performance.timeOrigin")
    cdp("Page.reload")
    wait_for(lambda: js(f"performance.timeOrigin !== {previous_origin}"), "reload document")
    tour_step("jobs")
    assert state()["state"] == saved
    navigate("/network")  # Browser navigation while the modal is active.
    assert not js('document.querySelector("#guided-tour").open')
    click(".tour-prompt [data-tour-resume]")
    tour_step("jobs")
    print("PASS: restart, skip persistence, pause, manual navigation and reload", flush=True)

    # Drop an already-committed response; recovery must show just the next step.
    cdp("Fetch.enable", {"patterns": [{"urlPattern": base + "/tour", "requestStage": "Response"}]})
    click("[data-tour-next]")
    wait_for(lambda: (js("true"), paused)[1], "paused saved response")
    intercepted = paused.pop()
    assert intercepted["request"]["method"] == "POST"
    assert intercepted["responseStatusCode"] == 200
    cdp("Fetch.failRequest", {"requestId": intercepted["requestId"], "errorReason": "Failed"})
    cdp("Fetch.disable")
    wait_for(lambda: js('!document.querySelector(".tour-error").hidden'), "save failure feedback")
    click("#guided-tour [data-tour-sync]")
    tour_step("people")
    assert state()["state"]["index"] == saved["index"] + 1
    # Simulate another tab/device restarting the same account.
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.phone == "+2348000000088"))
        row = db.get(UserTour, user.id)
        restarted = transition(db, user, action="start", revision=row.revision, run_id=row.run_id)
    click("[data-tour-next]")
    wait_for(lambda: js('!document.querySelector(".tour-error").hidden'), "stale-tab feedback")
    click("#guided-tour [data-tour-sync]")
    tour_step("dashboard")
    assert state()["state"] == restarted["state"]
    print("PASS: lost response recovery and stale-tab restart fencing", flush=True)

    # Hidden targets are passed in the current direction; no previous/next loop.
    hidden_hook = cdp("Page.addScriptToEvaluateOnNewDocument", {"source": """
      document.addEventListener('DOMContentLoaded', () => {
        const target=document.querySelector('[data-tour="profile"]');
        if(target) target.hidden=true;
      });
    """})["identifier"]
    click("[data-tour-next]")
    tour_step("jobs")
    assert not js('document.querySelector("[data-tour-note]").hidden')
    click('#guided-tour [data-tour-action="previous"]')
    tour_step("dashboard")
    assert state()["state"]["index"] == 0
    cdp("Page.removeScriptToEvaluateOnNewDocument", {"identifier": hidden_hook})
    key("Escape", 27)
    navigate("/settings")
    missing_hook = cdp("Page.addScriptToEvaluateOnNewDocument", {"source": """
      document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('[data-tour]').forEach(target => target.remove());
      });
    """})["identifier"]
    click("#guided-tour-settings [data-tour-start]")
    wait_for(lambda: js(
        'document.readyState === "complete" && !document.querySelector("#guided-tour")?.open && '
        'document.querySelector("#tour-prompt-title")?.textContent === "Tour skipped"'
    ), "all unavailable targets end", seconds=50)
    assert state()["state"]["status"] == "skipped"
    cdp("Page.removeScriptToEvaluateOnNewDocument", {"identifier": missing_hook})
    print("PASS: hidden/missing targets, both directions, no false completion", flush=True)

    # Existing mobile navigation and display preferences keep working.
    viewport(320, 700)
    navigate("/settings")
    click(".nav-toggle")
    assert js('document.querySelector("#mobile-navigation").open')
    click("[data-navigation-close]")
    click(".settings-display [data-display-open]")
    assert js('document.querySelector("#display-preferences").open')
    js("""(() => {const f=document.querySelector('#display-form');
      f.elements.theme.value='dark'; f.elements.largeText.checked=true;
      f.elements.highContrast.checked=true; f.elements.reduceMotion.checked=true;
      f.dispatchEvent(new Event('change',{bubbles:true}));})()""")
    click("[data-display-close]")
    click("#guided-tour-settings [data-tour-start]")
    tour_step("dashboard")
    geometry("dark-large-high-contrast-320")
    assert js('getComputedStyle(document.querySelector(".tour-card")).animationName === "none"')
    assert js('getComputedStyle(document.querySelector(".tour-spotlight")).transitionDuration.split(",").every(value => parseFloat(value) <= 0.001)')
    click("[data-tour-next]")
    tour_step("profile")
    geometry("dark-large-profile-320")
    viewport(844, 390)
    geometry("landscape-large-profile")
    assert js("""(() => {
      const target=document.querySelector('[data-tour="profile"]').getBoundingClientRect();
      const card=document.querySelector('.tour-card').getBoundingClientRect();
      const overlapX=Math.max(0,Math.min(target.right,card.right)-Math.max(target.left,card.left));
      const overlapY=Math.max(0,Math.min(target.bottom,card.bottom)-Math.max(target.top,card.top));
      return target.top >= document.querySelector('.site-header').getBoundingClientRect().bottom &&
        overlapX*overlapY < target.width*target.height*0.6;
    })()"""), "The landscape popover must leave a readable portion of the profile field visible"
    cdp("Emulation.setEmulatedMedia", {"features": [{"name": "forced-colors", "value": "active"}]})
    geometry("forced-colors-profile")
    cdp("Emulation.setEmulatedMedia", {"features": []})
    key("Escape", 27)
    navigate("/settings")
    js("""(() => {const f=document.querySelector('#display-form');
      f.elements.theme.value='light'; f.elements.largeText.checked=false;
      f.elements.highContrast.checked=false; f.elements.reduceMotion.checked=false;
      f.dispatchEvent(new Event('change',{bubbles:true}));})()""")
    print("PASS: mobile navigation, dark/large/contrast/reduced-motion and landscape", flush=True)

    # The backend supplies each role's real destinations; each completes in-browser.
    viewport(1280, 900)
    for phone, role, staff in roles:
        logout()
        login(phone)
        assert not js('document.querySelector(".tour-prompt").hidden')
        click(".tour-prompt [data-tour-start]")
        tour_step("dashboard")
        steps = state()["steps"]
        assert ("analytics" in [step["key"] for step in steps]) is staff
        assert ("employers" in [step["key"] for step in steps]) is (role == "employer")
        for step in steps[1:]:
            click("[data-tour-next]")
            tour_step(step["key"])
        geometry("role-" + ("staff" if staff else role))
        click("[data-tour-next]")
        wait_for(lambda: js('!document.querySelector("#guided-tour").open'), "role finish")
        assert state()["state"]["status"] == "completed"
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.phone == "+2348000000088"))
        assert db.scalar(select(NurseProfile).where(NurseProfile.user_id == user.id)) is None
        assert user.onboarding_completed_at is None
        assert snapshot(db, user)["state"]["status"] == "active"
    assert not errors, errors
    assert not (artifacts / "server.log").read_text().strip()
    print(json.dumps({"passed": True, "artifacts": str(artifacts),
                      "roles": ["nurse", "employer", "partner", "staff"],
                      "screenshots": len(list(artifacts.glob("*.png")))}), flush=True)
except Exception:
    if ws:
        screenshot("failure.png")
        print("Page:", js("location.pathname + location.search"))
        print("Tour:", js("document.querySelector('#tour-title')?.textContent"))
        print("Invitation:", js("""(() => {
          const config = document.querySelector('#tour-config');
          const tour = config ? JSON.parse(config.textContent) : null;
          return {offer: tour?.offer, status: tour?.state.status,
            worker: !!navigator.serviceWorker?.controller};
        })()"""))
        print("Navigations:", list(navigation_requests.values()))
        print("Input:", js("""({events:window.tourTestClicks,focus:document.hasFocus(),
          viewport:{scale:visualViewport?.scale,x:visualViewport?.offsetLeft,y:visualViewport?.offsetTop},
          dialogs:[...document.querySelectorAll('dialog[open]')].map(el=>el.id),
          start:document.querySelector('#guided-tour-settings [data-tour-start]')?.outerHTML,
          error:document.querySelector('[data-tour-prompt-error]')?.textContent})"""))
    print("Artifacts:", artifacts, flush=True)
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
