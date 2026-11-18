# ruff: noqa: E402
"""Isolated Chrome journeys for support, welcomes, sessions, invitations and digest.

Run: venv/bin/python tests/browser/participation.py
Uses local Chrome and axe-core; never sends mail or an actual invitation.
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
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
artifacts = Path(tempfile.mkdtemp(prefix="nurse-participation-browser-"))


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


web_port, chrome_port = free_port(), free_port()
base = f"http://127.0.0.1:{web_port}"
public_origin = "https://members.nurse.example"
os.environ.update(
    {
        "NURSE_NG_ENVIRONMENT": "development",
        "NURSE_NG_DEBUG": "0",
        "NURSE_NG_SECRET_KEY": secrets.token_urlsafe(32),
        "NURSE_NG_ALLOWED_HOSTS": "127.0.0.1,localhost",
        "NURSE_NG_SESSION_HTTPS_ONLY": "0",
        "NURSE_NG_SESSION_SAME_SITE": "lax",
        "NURSE_NG_PUBLIC_BASE_URL": public_origin,
        "NURSE_NG_DATABASE_URL": f"sqlite:///{artifacts / 'browser.db'}",
        "NURSE_NG_ACCOUNT_MAIL_BACKEND": "disabled",
        "NURSE_NG_REQUIRED_WORKERS": "",
        "NURSE_NG_COMMUNITY_MEDIA_DIR": str(artifacts / "media"),
        "NURSE_NG_GOOGLE_CLIENT_ID": "",
        "NURSE_NG_LINKEDIN_CLIENT_ID": "",
    }
)

from datetime import UTC, datetime, timedelta

from alembic import command
from alembic.config import Config
from sqlalchemy import select
from websockets.sync.client import connect

from app.db.session import SessionLocal
from app.models.community import CommunityPost
from app.models.participation import ActivitySeries, MemberReferral
from app.models.user import User
from app.services.auth import register_user
from app.services.community import set_community_name
from app.services.community_growth import create_community

command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
password = "browser-community-password"
with SessionLocal() as db:
    owner = register_user(
        db, phone="+2348999000301", password=password, full_name="PRIVATE HOST ACCOUNT"
    )
    set_community_name(db, owner, "Learning host")
    owner_id = owner.id

axe_path = Path(
    os.environ.get(
        "NURSE_NG_AXE_SCRIPT",
        "/tmp/nurse-community-browser-tools/node_modules/axe-core/axe.min.js",
    )
)
axe_source = axe_path.read_text()
processes, logs, errors, audits = [], [], [], []
ws = None
sequence = 0


def wait_for(check, label, seconds=45):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            value = check()
            if value:
                return value
        except (OSError, ValueError):
            pass
        time.sleep(0.1)
    raise AssertionError("Timed out: " + label)


def cdp(method, params=None):
    global sequence
    sequence += 1
    identifier = sequence
    ws.send(json.dumps({"id": identifier, "method": method, "params": params or {}}))
    while True:
        response = json.loads(ws.recv(timeout=30))
        if response.get("method") == "Runtime.exceptionThrown":
            errors.append(response["params"])
        if response.get("id") == identifier:
            assert "error" not in response, response
            return response.get("result", {})


def js(expression):
    result = cdp(
        "Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True}
    )
    assert "exceptionDetails" not in result, result
    return result.get("result", {}).get("value")


def navigate(path, selector="main", *, expected_path=None):
    # Route the test's public links to its isolated transport; do not rewrite shared URLs.
    if path.startswith(public_origin + "/"):
        path = path[len(public_origin) :]
    url = base + path if path.startswith("/") else path
    expected_path = expected_path or urlsplit(url).path
    js("window.communityBrowserNavigation = true")
    cdp("Page.navigate", {"url": url})
    wait_for(
        lambda: js(
            '!window.communityBrowserNavigation && document.readyState === "complete" && '
            f"!!document.querySelector({json.dumps(selector)}) && "
            f"location.pathname === {json.dumps(expected_path)}"
        ),
        path,
    )


def fill(selector, value):
    js(
        f"(() => {{const e=document.querySelector({json.dumps(selector)});"
        f"e.value={json.dumps(value)};e.dispatchEvent(new Event('input',{{bubbles:true}}));"
        "e.dispatchEvent(new Event('change',{bubbles:true}));})()"
    )


def click(selector):
    js(f"document.querySelector({json.dumps(selector)}).click()")


def submit(selector):
    assert js(f"document.querySelector({json.dumps(selector)}).checkValidity()"), selector
    js(f"document.querySelector({json.dumps(selector)}).requestSubmit()")


def feedback(title):
    wait_for(
        lambda: js(
            '!!document.querySelector("#feedback-title") && '
            f'document.querySelector("#feedback-title").textContent === {json.dumps(title)}'
        ),
        title,
    )
    if js('!!document.querySelector("[data-feedback-dismiss]")'):
        click("[data-feedback-dismiss]")


def login(phone):
    navigate("/auth/login", "#phone")
    fill("#phone", phone)
    fill("#password", password)
    submit('form[action="/auth/login"]')
    wait_for(lambda: js('location.pathname === "/" && document.readyState === "complete"'), "login")


def logout():
    js(
        "fetch('/auth/logout', {method:'POST', "
        "headers:{'Content-Type':'application/x-www-form-urlencoded'},"
        "body:new URLSearchParams({csrf_token:document.querySelector('[name=csrf_token]').value})})"
        ".then(r=>r.ok)"
    )
    navigate("/auth/login", "#phone")


def screenshot(name):
    data = cdp("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
    (artifacts / name).write_bytes(base64.b64decode(data["data"]))


def audit(path, width, theme, large=False):
    cdp(
        "Emulation.setDeviceMetricsOverride",
        {"width": width, "height": 1000, "deviceScaleFactor": 1, "mobile": width < 700},
    )
    js(
        "localStorage.setItem('nurse-ng-display', JSON.stringify({"
        f"theme:{json.dumps(theme)},largeText:false,highContrast:false,reduceMotion:false}}))"
    )
    navigate(path)
    assert js("document.documentElement.dataset.theme") == theme
    js(f"document.documentElement.style.fontSize={json.dumps('32px' if large else '14px')}")
    js("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
    js(axe_source)
    result = js(
        "axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})"
        ".then(r=>({violations:r.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>"
        "({target:n.target,summary:n.failureSummary}))})),manual:r.incomplete.map(v=>v.id)}))"
    )
    result.update(
        path=path,
        width=width,
        theme=theme,
        large=large,
        overflow=js("document.documentElement.scrollWidth > innerWidth + 1"),
    )
    audits.append(result)
    (artifacts / "audits.json").write_text(json.dumps(audits, indent=2))
    assert not result["violations"] and not result["overflow"], result


with SessionLocal() as db:
    topic = create_community(
        db,
        db.get(User, owner_id),
        name="School, practice and teaching circle",
        description="A community for every nursing stage.",
        rules="Respect colleagues and protect patient privacy.",
        welcome_text="Everyone is welcome.",
        interest="Research",
    )
    topic_id, topic_slug = str(topic.id), topic.slug

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
                str(web_port),
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
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-background-networking",
                "--password-store=basic",
                f"--user-data-dir={artifacts / 'chrome-profile'}",
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
        "browser",
    )
    ws = connect(
        next(tab["webSocketDebuggerUrl"] for tab in tabs if tab["type"] == "page"), legacy=True
    )
    for method in ["Page.enable", "Runtime.enable", "Network.enable"]:
        cdp(method)
    cdp(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "localStorage.setItem('nurse-ng-install-reminder','hidden');"},
    )

    print("Offer support and create a recurring learning session", flush=True)
    login("+2348999000301")
    navigate("/mentorship/offer")
    fill("[name=introduction]", "Study and teaching support across every nursing stage.")
    fill("[name=availability]", "Weekend conversations")
    click("[name=topics][value=school]")
    click("[name=topics][value=research]")
    click("[name=accepting]")
    submit('form[action="/mentorship/offer"]')
    feedback("Support offer saved")
    navigate("/activities/series/new")
    fill("[name=topic_id]", topic_id)
    fill("[name=title]", "Weekly study and research circle")
    fill("[name=instructions]", "Bring a practice question or a research idea to discuss.")
    fill("[name=starts_at]", (datetime.now(UTC) + timedelta(days=2)).strftime("%Y-%m-%dT18:00"))
    click("[name=public_consent]")
    submit('form[action="/activities/series"]')
    feedback("Learning series created")
    with SessionLocal() as db:
        activity = db.scalar(select(CommunityPost).where(CommunityPost.post_kind == "activity"))
        activity_id = str(activity.id)
        series_id = str(db.scalar(select(ActivitySeries.id)))
    navigate(f"/activities/series/{series_id}/sessions")
    assert js('document.querySelector("main").innerText.includes("Weekly study")')
    print("Share an invitation and register a new nursing student", flush=True)
    navigate("/invitations")
    fill("[name=destination]", "/topics/" + topic_slug)
    fill("[name=label]", "My school colleagues")
    submit('form[action="/invitations"]')
    feedback("Invitation ready")
    invite_url = js('document.querySelector("[data-share-url]").dataset.shareUrl')
    assert invite_url.startswith(public_origin + "/invite/")
    logout()
    navigate(invite_url)
    assert js('document.querySelector("main").innerText.includes("aggregate")')
    register_path = js(
        "[...document.querySelectorAll('main a')].find(a => "
        "a.getAttribute('href').startsWith('/auth/register')).getAttribute('href')"
    )
    navigate(register_path)
    fill("#phone", "+2348999000399")
    fill("[name=full_name]", "PRIVATE STUDENT ACCOUNT")
    fill("#password", password)
    submit('form[action="/auth/register"]')
    feedback("Account created")
    assert js("location.pathname") == "/topics/" + topic_slug
    with SessionLocal() as db:
        assert db.scalar(select(MemberReferral.inviter_id)) == owner_id
    print("Introduce the newcomer, ask for support and join a session", flush=True)
    navigate("/community/start")
    fill("[name=goal]", "school")
    submit('form[action="/community/start/preferences"]')
    feedback("Your choices are saved")
    fill("[name=community_name]", "New nursing student")
    fill("[name=topic_id]", topic_id)
    fill(
        "[name=body]",
        "Hello! It is my first day in nursing school and I would love study partners.",
    )
    click("[name=public_consent]")
    submit('form[action="/community/start/introduction"]')
    feedback("Introduction published")
    intro_path = js("location.pathname")
    navigate("/mentorship/offers/" + str(owner_id))
    fill("[name=topic]", "school")
    fill("[name=goal]", "Help me prepare for my first clinical placement.")
    submit('form[action^="/mentorship/offers/"]')
    feedback("Support request saved")
    request_path = js("location.pathname")
    navigate("/posts/" + activity_id)
    submit('form[action$="/attendance"]')
    feedback("Activity choice saved")
    assert js('document.querySelector("main").innerText.includes("1 colleague has joined")')
    navigate("/digest")
    assert js('document.querySelector("main").innerText.includes("verify your email")')
    logout()
    print("Welcome the newcomer and accept peer support", flush=True)
    login("+2348999000301")
    navigate("/communities/" + topic_slug + "/welcomes")
    assert js('document.querySelector("main").innerText.includes("New nursing student")')
    navigate(intro_path + "#reply-form")
    fill("#reply-body", "Welcome! We are glad you are here. Bring your questions.")
    submit('form[action$="/replies"]')
    feedback("Reply published")
    navigate("/communities/" + topic_slug + "/welcomes")
    submit('form[action^="/community/welcomes/"]')
    feedback("Welcome recorded")
    navigate(request_path)
    submit('form[action$="/accept"]')
    feedback("Support request updated")
    assert js('document.querySelector("main").innerText.includes("Open our messages")')
    navigate("/invitations")
    assert js(
        '[...document.querySelectorAll(".participation-metrics dd")].map(e=>e.textContent)'
    ) == ["1", "1", "1", "0"]
    with SessionLocal() as db:
        mentor = db.get(User, owner_id)
        mentor.email = "browser-mentor@example.org"
        mentor.email_verified_at = datetime.now(UTC)
        db.commit()
    navigate("/digest")
    click("[name=enabled]")
    submit('form[action="/digest"]')
    feedback("Digest preferences saved")
    print("Audit phone, enlarged-text dark and desktop layouts", flush=True)
    paths = [
        "/community/start",
        "/mentorship",
        "/mentorship/offer",
        "/mentorship/requests",
        request_path,
        "/activities/series/new",
        "/activities/series",
        "/activities/series/" + series_id + "/sessions",
        "/posts/" + activity_id,
        "/invitations",
        "/digest",
        "/communities/" + topic_slug + "/welcomes",
    ]
    for width, theme, large in [(390, "light", False), (320, "dark", True), (1280, "light", False)]:
        for path in paths:
            audit(path, width, theme, large)
        navigate("/mentorship")
        screenshot(f"support-{width}-{theme}.png")
        navigate("/community/start")
        screenshot(f"start-{width}-{theme}.png")
    assert not errors, errors
    (artifacts / "results.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "audits": len(audits),
                "javascript_errors": errors,
                "journeys": [
                    "voluntary support offer and request",
                    "recurring session creation and attendance",
                    "personal invitation signup attribution",
                    "newcomer introduction and host welcome",
                    "support acceptance and messaging connection",
                    "verified email digest opt-in",
                ],
            },
            indent=2,
        )
    )
    print(
        json.dumps({"status": "passed", "artifacts": str(artifacts), "audits": len(audits)}),
        flush=True,
    )

except BaseException:
    if ws:
        try:
            (artifacts / "failure-state.json").write_text(
                json.dumps(
                    js(
                        "({url:location.href,text:document.querySelector('main')?.innerText,"
                        "fields:[...document.querySelectorAll("
                        "'main input, main select, main textarea')]"
                        ".map(e=>({name:e.name,value:e.value,disabled:e.disabled,required:e.required,"
                        "valid:e.validity.valid,message:e.validationMessage}))})"
                    ),
                    indent=2,
                )
            )
            screenshot("failure.png")
        except Exception:
            pass
    print("Artifacts: " + str(artifacts), flush=True)
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
            process.wait(timeout=5)
    for log in logs:
        log.close()
