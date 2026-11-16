# ruff: noqa: E402
"""Isolated Chrome journeys for communities, answers, learning and invitations.

Run: venv/bin/python tests/browser/community_growth.py
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
from urllib.parse import parse_qs, urlsplit

ROOT = Path("/home/recoding/nurse-ng")
sys.path.insert(0, str(ROOT))
artifacts = Path(tempfile.mkdtemp(prefix="nurse-community-browser-"))


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


web_port, chrome_port = free_port(), free_port()
base = f"http://127.0.0.1:{web_port}"
os.environ.update(
    {
        "NURSE_NG_ENVIRONMENT": "development",
        "NURSE_NG_DEBUG": "0",
        "NURSE_NG_SECRET_KEY": secrets.token_urlsafe(32),
        "NURSE_NG_ALLOWED_HOSTS": "127.0.0.1,localhost",
        "NURSE_NG_SESSION_HTTPS_ONLY": "0",
        "NURSE_NG_SESSION_SAME_SITE": "lax",
        "NURSE_NG_PUBLIC_BASE_URL": base,
        "NURSE_NG_DATABASE_URL": f"sqlite:///{artifacts / 'browser.db'}",
        "NURSE_NG_ACCOUNT_MAIL_BACKEND": "disabled",
        "NURSE_NG_REQUIRED_WORKERS": "",
        "NURSE_NG_COMMUNITY_MEDIA_DIR": str(artifacts / "media"),
        "NURSE_NG_GOOGLE_CLIENT_ID": "",
        "NURSE_NG_LINKEDIN_CLIENT_ID": "",
    }
)

from alembic import command
from alembic.config import Config
from sqlalchemy import select
from websockets.sync.client import connect

from app.db.session import SessionLocal
from app.models.community import CommunityPost, CommunityReply, CommunityTopic
from app.services.auth import register_user
from app.services.community import set_community_name

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
        "NURSE_NG_AXE_SCRIPT", "/tmp/nurse-community-browser-tools/node_modules/axe-core/axe.min.js"
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


def navigate(path, selector="main"):
    url = base + path if path.startswith("/") else path
    js("window.communityBrowserNavigation = true")
    cdp("Page.navigate", {"url": url})
    wait_for(
        lambda: js(
            '!window.communityBrowserNavigation && document.readyState === "complete" && '
            f"!!document.querySelector({json.dumps(selector)}) && "
            f"location.pathname === {json.dumps(urlsplit(url).path)}"
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

    print("Customize a community example, then host a question", flush=True)
    login("+2348999000301")
    navigate("/feed")
    assert js("!!document.querySelector('a[href=\"/communities/new\"]')")
    navigate("/posts/new", "#topic-id")
    assert js("document.querySelector('#topic-id').value") == ""
    navigate("/communities")
    example_link = '/communities/new?example=critical-care#community-details'
    assert js(f"!!document.querySelector('a[href={json.dumps(example_link)}]')")
    navigate(example_link, "#circle-name")
    assert js("document.querySelector('#circle-name').value") == "Emergency & Critical Care"
    assert js("document.querySelector('#circle-rules').value.includes('patient privacy')")
    with SessionLocal() as db:
        assert len(list(db.scalars(select(CommunityTopic)))) == 1
    navigate("/communities/new#community-details", "#circle-name")
    assert js("document.querySelector('#circle-name').value") == ""
    navigate(example_link, "#circle-name")
    for selector, value in [
        ("#circle-name", "Critical care colleagues"),
        ("#circle-description", "All career stages learn and share together."),
        ("#circle-interest", "Critical care"),
        ("#circle-welcome", "Welcome, colleague."),
        ("#circle-rules", "Respect colleagues and protect patient privacy."),
    ]:
        fill(selector, value)
    submit('form[action="/communities"]')
    wait_for(
        lambda: js(
            'document.readyState === "complete" && '
            'location.pathname.startsWith("/topics/") && '
            '!!document.querySelector(".community-membership-bar")'
        ),
        "community creation",
    )
    topic_path = js("location.pathname")
    feedback("Community created")
    assert js(
        "document.querySelector('.community-membership-bar').textContent.includes('1 member')"
    )
    invite_url = js("document.querySelector('[data-share-url]').dataset.shareUrl")
    topic_id = parse_qs(
        urlsplit(js("document.querySelector('a[href*=\"/posts/new?topic=\"]').href")).query
    )["topic"][0]
    navigate(f"/posts/new?topic={topic_id}", "#body")
    assert js("document.querySelector('#topic-id').value") == topic_id
    fill("#post-title", "How do you prepare for a critical care shift?")
    fill("#body", "Share one useful preparation practice with your colleagues.")
    submit('form[action="/posts"]')
    wait_for(
        lambda: js(
            'document.readyState === "complete" && '
            'location.pathname.startsWith("/posts/") && location.pathname!=="/posts/new" && '
            '!!document.querySelector("[data-share-url]")'
        ),
        "question",
    )
    post_path = js("location.pathname")
    post_invite = js("document.querySelector('[data-share-url]').dataset.shareUrl")
    navigate("/feed/unanswered")
    assert js(f"!!document.querySelector('a[href={json.dumps(post_path)}]')")
    print("Verify chosen-community draft recovery and discard", flush=True)
    navigate(f"/posts/new?topic={topic_id}", "#body")
    fill("#body", "An unfinished conversation for my chosen community.")
    navigate("/feed")
    navigate("/posts/new", "#body")
    assert js("document.querySelector('#body').value") == "An unfinished conversation for my chosen community."
    assert js("document.querySelector('#topic-id').value") == topic_id
    click('[data-discard-draft]')
    navigate("/feed")
    navigate("/posts/new", "#body")
    assert js("document.querySelector('#body').value") == ""
    assert js("document.querySelector('#topic-id').value") == ""
    print("Audit community examples and creation entry points", flush=True)
    paths = ["/communities", "/communities/new", "/communities/new?example=local-network#community-details", "/feed", "/posts/new", "/welcome/discover"]
    requested_width = next((int(arg.split("=", 1)[1]) for arg in sys.argv[1:] if arg.startswith("--width=")), None)
    audit_modes = [(390, "light", False), (320, "dark", True), (1280, "light", False)]
    for width, theme, large in audit_modes:
        if requested_width and width != requested_width:
            continue
        for path in paths:
            audit(path, width, theme, large)
            if path == "/communities":
                js("document.querySelector('.community-examples').scrollIntoView({behavior:'instant',block:'start'})")
                screenshot(f"community-examples-{width}-{theme}.png")
            elif "example=local-network" in path:
                screenshot(f"community-example-form-{width}-{theme}.png")
            elif path == "/feed":
                screenshot(f"community-create-feed-{width}-{theme}.png")
        print(f"Passed {width}px {theme} enlarged={large}", flush=True)
    assert not errors, errors
    with SessionLocal() as db:
        assert len(list(db.scalars(select(CommunityTopic)))) == 2
        assert len(list(db.scalars(select(CommunityPost)))) == 1
    result = {"status":"passed", "audits":len(audits), "javascript_errors":errors, "scope":"editable community examples", "journeys":["editable example and own blank idea", "no community created by viewing an example", "ordinary member creation and automatic membership", "post in chosen community", "generic composer blank, explicit link selected", "draft restores chosen community, discard restores blank choice", "creation links in feed, composer and onboarding"]}
    (artifacts / "results.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({"status":"passed", "artifacts":str(artifacts), "audits":len(audits)}), flush=True)

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
