# ruff: noqa: E402
# Isolated environment settings must be installed before application imports.
"""Standalone Chrome draft-recovery checks using an isolated local database.

Run: venv/bin/python tests/browser/community_drafts.py
Requires a local Chrome binary; does not touch the application database.
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
os.chdir(ROOT)
artifacts = Path(tempfile.mkdtemp(prefix="nurse-ng-draft-browser-"))
os.environ.update(
    {
        "NURSE_NG_ENVIRONMENT": "development",
        "NURSE_NG_DEBUG": "0",
        "NURSE_NG_SECRET_KEY": secrets.token_urlsafe(32),
        "NURSE_NG_ALLOWED_HOSTS": "127.0.0.1,localhost",
        "NURSE_NG_SESSION_HTTPS_ONLY": "0",
        "NURSE_NG_SESSION_SAME_SITE": "lax",
        "NURSE_NG_DATABASE_URL": f"sqlite:///{artifacts / 'browser.db'}",
        "NURSE_NG_COMMUNITY_MEDIA_DIR": str(artifacts / "media"),
    }
)

from alembic import command
from alembic.config import Config
from sqlalchemy import select
from websockets.sync.client import connect

from app.db.session import SessionLocal
from app.models.community import CommunityPost, CommunityReply, CommunityTopic
from app.models.user import User
from app.services.auth import register_user
from app.services.community import add_reply, set_community_name

command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
password = "browser-test-password"
with SessionLocal() as db:
    member = register_user(db, phone="+2348999000001", password=password, full_name="Browser Nurse")
    peer = register_user(db, phone="+2348999000002", password=password, full_name="Browser Peer")
    set_community_name(db, peer, "Bola Browser")
    peer_id = peer.id
    topic = db.scalar(select(CommunityTopic))
    for index in range(23):
        db.add(
            CommunityPost(
                author_id=peer.id,
                topic_id=topic.id,
                body=f"Browsercheck conversation {index:02}: experiences in nursing.",
            )
        )
    db.commit()


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


web_port, chrome_port = free_port(), free_port()
base_url = f"http://127.0.0.1:{web_port}"
processes = []
logs = []
errors = []
bad_responses = []
ws = None
sequence = 0


def wait_for(check, description, seconds=20):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            result = check()
            if result:
                return result
        except (OSError, ValueError, RuntimeError):
            pass
        time.sleep(0.1)
    raise AssertionError(f"Timed out: {description}")


def command_cdp(method, params=None):
    global sequence
    sequence += 1
    identifier = sequence
    ws.send(json.dumps({"id": identifier, "method": method, "params": params or {}}))
    while True:
        message = json.loads(ws.recv(timeout=20))
        if message.get("method") == "Runtime.exceptionThrown":
            errors.append(message["params"])
        if message.get("method") == "Network.responseReceived":
            response = message["params"]["response"]
            if response["status"] >= 400:
                bad_responses.append((response["status"], response["url"]))
        if message.get("id") == identifier:
            if "error" in message:
                raise RuntimeError(message["error"])
            return message.get("result", {})


def evaluate(expression):
    result = command_cdp(
        "Runtime.evaluate",
        {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        },
    )
    if "exceptionDetails" in result:
        raise RuntimeError(result["exceptionDetails"])
    return result.get("result", {}).get("value")


def navigate(path, selector="main"):
    command_cdp("Page.navigate", {"url": base_url + path})
    wait_for(
        lambda: evaluate(
            f"location.pathname + location.search === {json.dumps(path)} && "
            'document.readyState === "complete" && '
            f"!!document.querySelector({json.dumps(selector)})"
        ),
        path,
    )


def submit(selector):
    evaluate(f"document.querySelector({json.dumps(selector)}).requestSubmit()")


def exists(selector):
    return evaluate(f"!!document.querySelector({json.dumps(selector)})")


def feedback(title):
    return evaluate(
        '!document.querySelector("[data-feedback-panel]").hidden && '
        f'document.querySelector("#feedback-title").textContent === {json.dumps(title)}'
    )


def fill(selector, value):
    evaluate(
        f"(() => {{const element=document.querySelector({json.dumps(selector)}); "
        f"element.value={json.dumps(value)}; "
        'element.dispatchEvent(new Event("input", {bubbles:true}));})()'
    )


def check_reflow(label):
    assert evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), label


def screenshot(name):
    result = command_cdp(
        "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
    )
    (artifacts / name).write_bytes(base64.b64decode(result["data"]))


try:
    for name, args in (
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
                "--password-store=basic",
                "--disable-background-networking",
                f"--user-data-dir={artifacts / 'chrome-profile'}",
                f"--remote-debugging-port={chrome_port}",
                "about:blank",
            ],
        ),
    ):
        log = (artifacts / f"{name}.log").open("w")
        logs.append(log)
        processes.append(
            subprocess.Popen(args, cwd=ROOT, env=os.environ.copy(), stdout=log, stderr=log)
        )
    wait_for(
        lambda: urllib.request.urlopen(base_url + "/healthz", timeout=1).status == 200, "server"
    )
    tabs = wait_for(
        lambda: json.load(
            urllib.request.urlopen(f"http://127.0.0.1:{chrome_port}/json/list", timeout=1)
        ),
        "browser",
    )
    ws = connect(
        next(tab["webSocketDebuggerUrl"] for tab in tabs if tab["type"] == "page"), legacy=True
    )
    command_cdp("Page.enable")
    command_cdp("Runtime.enable")
    command_cdp("Network.enable")
    command_cdp(
        "Emulation.setDeviceMetricsOverride",
        {
            "width": 390,
            "height": 844,
            "deviceScaleFactor": 1,
            "mobile": True,
        },
    )
    navigate("/auth/login", "#phone")
    fill("#phone", "+2348999000001")
    fill("#password", password)
    submit('form[action="/auth/login"]')
    wait_for(
        lambda: evaluate('location.pathname === "/" && !!document.querySelector(".db")'), "login"
    )
    navigate("/posts/new", "#body")
    draft_text = "Which hospitals are accepting interns? <script>never execute</script>"
    fill("#community-name", "Draft Nurse")
    fill("#body", draft_text)
    fill("#external-video-url", "https://example.com/opportunity")
    saved_topic = evaluate('document.querySelector("#topic-id").value')
    first_scope = evaluate("document.body.dataset.draftScope")
    draft_key = "nurse-ng-draft:v1:" + first_scope + ":post"
    assert (
        evaluate("JSON.parse(sessionStorage.getItem(" + json.dumps(draft_key) + ")).fields.body")
        == draft_text
    )
    attachment = artifacts / "draft-fixture.jpg"
    attachment.write_bytes(b"\xff\xd8\xff\xe0fixture")
    document_node = command_cdp("DOM.getDocument")["root"]["nodeId"]
    upload_node = command_cdp(
        "DOM.querySelector",
        {
            "nodeId": document_node,
            "selector": "#images",
        },
    )["nodeId"]
    command_cdp("DOM.setFileInputFiles", {"nodeId": upload_node, "files": [str(attachment)]})
    assert evaluate('document.querySelector("#images").files.length') == 1
    navigate("/feed")
    navigate("/posts/new", "#body")
    assert evaluate('document.querySelector("#body").value') == draft_text
    assert evaluate('document.querySelector("#topic-id").value') == saved_topic
    assert evaluate('document.querySelector("#images").files.length') == 0
    assert (
        evaluate('document.querySelector("#external-video-url").value')
        == "https://example.com/opportunity"
    )
    assert evaluate(
        'document.querySelector("[data-draft-status]").textContent.includes("restored")'
    )
    check_reflow("restored question mobile")
    screenshot("restored-question-mobile.png")

    # A second tab keeps its own draft, including when the first tab publishes.
    main_ws = ws
    other_target = command_cdp("Target.createTarget", {"url": "about:blank"})["targetId"]
    tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{chrome_port}/json/list"))
    other_ws = connect(
        next(tab["webSocketDebuggerUrl"] for tab in tabs if tab["id"] == other_target), legacy=True
    )
    ws = other_ws
    command_cdp("Page.bringToFront")
    command_cdp("Page.enable")
    command_cdp("Runtime.enable")
    command_cdp("Network.enable")
    navigate("/posts/new", "#body")
    assert evaluate('document.querySelector("#body").value') == ""
    fill("#body", "Independent second-tab question")
    ws = main_ws
    command_cdp("Page.bringToFront")

    # An error page must not revoke a valid session or discard drafts in either tab.
    for error_path in ("/missing-draft-page", "/events/new", "/events?page=invalid"):
        saved_draft = evaluate("sessionStorage.getItem(" + json.dumps(draft_key) + ")")
        navigate(error_path)
        assert feedback("We couldn’t complete this action")
        assert evaluate("sessionStorage.getItem(" + json.dumps(draft_key) + ")") == saved_draft
        ws = other_ws
        command_cdp("Page.bringToFront")
        assert (
            evaluate('document.querySelector("#body").value') == "Independent second-tab question"
        )
        assert not evaluate('document.querySelector("#body").disabled')
        ws = main_ws
        command_cdp("Page.bringToFront")
        navigate("/posts/new", "#body")
        assert evaluate('document.querySelector("#body").value') == draft_text
        assert not evaluate('document.querySelector("#body").disabled')
        assert evaluate("document.body.dataset.draftScope") == first_scope

    # Known validation failures retain the exact submitted text and clear the unknown-outcome hint.
    fill("#community-name", "Admin")
    fill("#external-video-url", "")
    submit('form[action="/posts"]')
    wait_for(lambda: feedback("Please check this action"), "validation error")
    assert evaluate('document.querySelector("#body").value') == draft_text
    assert (
        evaluate("JSON.parse(sessionStorage.getItem(" + json.dumps(draft_key) + ")).pending")
        is False
    )
    navigate("/posts/new", "#body")
    assert evaluate('document.querySelector("#body").value') == draft_text
    fill("#community-name", "Draft Nurse")

    # Offline validation prevents a request, so it must not mark the draft as pending.
    command_cdp(
        "Network.emulateNetworkConditions",
        {
            "offline": True,
            "latency": 0,
            "downloadThroughput": 0,
            "uploadThroughput": 0,
        },
    )
    submit('form[action="/posts"]')
    wait_for(lambda: feedback("You’re offline"), "offline submission")
    assert evaluate('document.querySelector("#body").value') == draft_text
    assert not evaluate("JSON.parse(sessionStorage.getItem(" + json.dumps(draft_key) + ")).pending")
    command_cdp(
        "Network.emulateNetworkConditions",
        {
            "offline": False,
            "latency": 0,
            "downloadThroughput": -1,
            "uploadThroughput": -1,
        },
    )
    navigate("/posts/new", "#body")
    assert evaluate('document.querySelector("#body").value') == draft_text
    assert not evaluate(
        'document.querySelector("[data-draft-status]")'
        '.textContent.includes("Check the conversation")'
    )
    # A request with no response has an unknown outcome and retains its pending draft.
    evaluate("""window.draftReviewFetch = window.fetch;
window.fetch = (...args) => String(args[0]).endsWith('/posts')
  ? Promise.reject(new TypeError('Interrupted request')) : window.draftReviewFetch(...args);""")
    submit('form[action="/posts"]')
    wait_for(lambda: feedback("We couldn’t confirm the result"), "interrupted submission")
    assert evaluate("JSON.parse(sessionStorage.getItem(" + json.dumps(draft_key) + ")).pending")
    evaluate("window.fetch = window.draftReviewFetch")
    navigate("/posts/new", "#body")
    assert evaluate('document.querySelector("#body").value') == draft_text
    assert evaluate(
        'document.querySelector("[data-draft-status]")'
        '.textContent.includes("Check the conversation")'
    )
    submit('form[action="/posts"]')
    wait_for(
        lambda: evaluate(
            'location.pathname.startsWith("/posts/") && location.pathname !== "/posts/new" && '
            '!!document.querySelector("#reply-body")'
        ),
        "publish question",
    )
    post_path = evaluate("location.pathname")
    assert evaluate("sessionStorage.getItem(" + json.dumps(draft_key) + ")") is None
    ws = other_ws
    command_cdp("Page.bringToFront")
    assert evaluate('document.querySelector("#body").value') == "Independent second-tab question"
    assert evaluate("sessionStorage.getItem(" + json.dumps(draft_key) + ")") is not None
    ws = main_ws
    command_cdp("Page.bringToFront")

    # Returning through browser history must not resurrect a published draft.
    evaluate("history.back()")
    wait_for(
        lambda: evaluate(
            'location.pathname === "/posts/new" && document.readyState === "complete" && '
            '!!document.querySelector("#body") && document.querySelector("#body").value === ""'
        ),
        "back to composer",
    )
    assert evaluate('document.querySelector("#body").value') == ""
    navigate(post_path, "#reply-body")
    fill("#reply-body", "An unfinished reply about the application process.")
    with SessionLocal() as db:
        other_post = db.scalar(
            select(CommunityPost).where(CommunityPost.body.like("Browsercheck%"))
        )
        other_post_path = f"/posts/{other_post.id}"
    navigate(other_post_path, "#reply-body")
    assert evaluate('document.querySelector("#reply-body").value') == ""
    fill("#reply-body", "A different discussion draft.")
    navigate(post_path, "#reply-body")
    assert (
        evaluate('document.querySelector("#reply-body").value')
        == "An unfinished reply about the application process."
    )
    submit('form[action$="/replies"]')
    wait_for(
        lambda: evaluate(
            'location.hash.startsWith("#reply-") && document.readyState === "complete" && '
            'document.querySelector(".reply-list").textContent.includes("unfinished reply")'
        ),
        "publish reply",
    )
    assert evaluate('document.querySelector("#reply-body").value') == ""

    # Specific-response context survives page changes, draft restoration, and moderation.
    from uuid import UUID

    with SessionLocal() as db:
        current_post = db.get(CommunityPost, UUID(post_path.rsplit("/", 1)[-1]))
        peer = db.get(User, peer_id)
        sources = [
            add_reply(
                db,
                peer,
                current_post,
                f"Hospital placement update {index:02}: contact the nursing office.",
            )
            for index in range(40)
        ]
        source_id, alternative_id = str(sources[0].id), str(sources[1].id)
    source_context_path = post_path + "/reply-context/" + source_id

    def target_value():
        return evaluate('document.querySelector("[name=in_reply_to_id]").value')

    def context_includes(text):
        return evaluate(
            'document.querySelector("[data-reply-context-content]").textContent.includes('
            + json.dumps(text)
            + ")"
        )

    def choose_reply(identifier):
        evaluate(
            "document.querySelector("
            + json.dumps('[data-reply-to="' + identifier + '"]')
            + ").click()"
        )

    navigate(post_path, "#reply-body")
    reply_text = "Which department should I contact, and what documents are needed?"
    fill("#reply-body", reply_text)
    choose_reply(source_id)
    wait_for(lambda: context_includes("Hospital placement update 00"), "selected response")
    assert target_value() == source_id
    assert evaluate('document.querySelector("#reply-body").value') == reply_text
    assert evaluate("document.activeElement.id") == "reply-body"
    try:
        wait_for(
            lambda: evaluate(
                '(() => { const top = document.getElementById("reply-form")'
                '.getBoundingClientRect().top; '
                "return top >= 0 && top < 300; })()"
            ),
            "reply composer scroll settles",
        )
    except AssertionError:
        print("Composer geometry:", evaluate(
            '({scrollY, height: innerHeight, total: document.documentElement.scrollHeight, '
            'formTop: document.getElementById("reply-form").getBoundingClientRect().top, '
            'bodyTop: document.getElementById("reply-body").getBoundingClientRect().top, '
            'contextTop: document.querySelector("[data-reply-context]")'
            '.getBoundingClientRect().top})'
        ), flush=True)
        screenshot("composer-scroll-failure.png")
        print(f"Artifacts: {artifacts}", flush=True)
        raise
    screenshot("reply-target-mobile.png")
    evaluate('document.querySelector(".reply-pagination a[rel=next]").click()')
    wait_for(
        lambda: (
            evaluate('location.search.includes("page=2") && document.readyState === "complete"')
            and context_includes("Hospital placement update 00")
        ),
        "target across pages",
    )
    assert target_value() == source_id
    assert evaluate('document.querySelector("#reply-body").value') == reply_text
    navigate("/feed")
    navigate(post_path + "?page=3", "#reply-body")
    wait_for(lambda: context_includes("Hospital placement update 00"), "target restored off-page")
    navigate(post_path + "?page=2&reply_to=" + alternative_id, "#reply-body")
    wait_for(
        lambda: context_includes("Hospital placement update 01"), "explicit target overrides draft"
    )
    assert target_value() == alternative_id
    assert evaluate('document.querySelector("#reply-body").value') == reply_text
    navigate("/feed")
    navigate(post_path + "?page=3", "#reply-body")
    wait_for(lambda: context_includes("Hospital placement update 01"), "new selection saved")
    evaluate('document.querySelector("[data-clear-reply-target]").click()')
    assert target_value() == ""
    assert evaluate('document.querySelector("#reply-body").value') == reply_text
    navigate("/feed")
    navigate(post_path + "?page=3", "#reply-body")
    assert target_value() == ""
    assert evaluate('document.querySelector("[data-reply-context]").hidden')
    navigate(post_path + "?page=1&reply_to=" + source_id, "#reply-body")
    wait_for(lambda: context_includes("Hospital placement update 00"), "select before discard")
    evaluate('document.querySelector("[data-discard-draft]").click()')
    assert target_value() == ""
    navigate("/feed")
    navigate(post_path + "?page=1&reply_to=", "#reply-body")
    assert target_value() == "" and evaluate('document.querySelector("#reply-body").value') == ""
    choose_reply(source_id)
    fill("#reply-body", reply_text)
    navigate("/feed")
    with SessionLocal() as db:
        db.get(CommunityReply, UUID(source_id)).status = "removed"
        db.commit()
    navigate(post_path + "?page=2", "#reply-body")
    wait_for(lambda: context_includes("no longer available"), "removed target on restoration")
    assert not context_includes("Hospital placement update 00")
    assert target_value() == source_id
    assert evaluate('document.querySelector("#reply-body").value') == reply_text
    submit('form[action$="/replies"]')
    wait_for(lambda: feedback("Please check this action"), "removed target rejected")
    assert evaluate('document.querySelector("#reply-body").value') == reply_text
    navigate(post_path + "?page=2&reply_to=" + alternative_id, "#reply-body")
    wait_for(lambda: context_includes("Hospital placement update 01"), "choose available target")
    submit('form[action$="/replies"]')
    wait_for(
        lambda: (
            evaluate('location.search === "?page=3" && document.readyState === "complete"')
            and exists(".reply-card .reply-reference")
        ),
        "publish targeted reply on final page",
    )
    assert evaluate(
        'document.querySelector(".reply-card .reply-reference")'
        '.textContent.includes("Hospital placement update 01")'
    )
    assert target_value() == "" and evaluate('document.querySelector("#reply-body").value') == ""
    check_reflow("targeted reply mobile")
    wait_for(lambda: feedback("Reply published"), "published reply confirmation")
    assert evaluate('document.activeElement.matches("[data-feedback-panel]")')
    screenshot("targeted-reply-mobile.png")
    with SessionLocal() as db:
        submitted = db.scalar(select(CommunityReply).where(CommunityReply.body == reply_text))
        assert str(submitted.in_reply_to_id) == alternative_id
    evaluate('document.querySelector(".reply-card .reply-reference a").click()')
    wait_for(
        lambda: evaluate(
            'location.search === "?page=1" && location.hash === '
            + json.dumps("#reply-" + alternative_id)
        ),
        "reference link across pages",
    )
    navigate(other_post_path, "#reply-body")
    assert (
        evaluate('document.querySelector("#reply-body").value') == "A different discussion draft."
    )
    evaluate('document.querySelector("[data-discard-draft]").click()')
    navigate(other_post_path, "#reply-body")
    assert evaluate('document.querySelector("#reply-body").value') == ""

    # Expired or malformed drafts are removed without breaking the normal form.
    navigate("/posts/new", "#body")
    fill("#body", "An expired draft")
    evaluate(
        "(() => { const key = "
        + json.dumps(draft_key)
        + "; const record = JSON.parse(sessionStorage.getItem(key)); "
        "record.savedAt -= 25 * 60 * 60 * 1000; "
        "sessionStorage.setItem(key, JSON.stringify(record)); })()"
    )
    navigate("/feed")
    navigate("/posts/new", "#body")
    assert evaluate('document.querySelector("#body").value') == ""
    evaluate("sessionStorage.setItem(" + json.dumps(draft_key) + ', "{broken")')
    navigate("/feed")
    navigate("/posts/new", "#body")
    assert evaluate('document.querySelector("#body").value') == ""
    blocked_script = command_cdp(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": (
                "Storage.prototype.setItem = function() { "
                'throw new DOMException("Blocked", "SecurityError"); };'
            ),
        },
    )["identifier"]
    navigate("/feed")
    navigate("/posts/new", "#body")
    assert evaluate(
        'document.querySelector("[data-draft-status]").textContent.includes("unavailable")'
    )
    fill("#body", "Ordinary form still works when browser storage is blocked.")
    submit('form[action="/posts"]')
    wait_for(
        lambda: evaluate(
            'location.pathname.startsWith("/posts/") && location.pathname !== "/posts/new" && '
            '!!document.querySelector("#reply-body")'
        ),
        "publish without draft storage",
    )
    command_cdp("Page.removeScriptToEvaluateOnNewDocument", {"identifier": blocked_script})

    navigate(post_path, "#reply-body")
    fill("#reply-body", "Private unfinished text before logout")
    evaluate('localStorage.setItem("nurse-ng-display", JSON.stringify({theme:"dark"}))')
    submit('form[action="/auth/logout"]')
    wait_for(
        lambda: evaluate('location.pathname === "/" && document.body.dataset.draftScope === ""'),
        "logout",
    )
    assert (
        evaluate(
            'Object.keys(sessionStorage).filter(key => key.startsWith("nurse-ng-draft:v1:")).length'
        )
        == 0
    )
    assert evaluate('localStorage.getItem("nurse-ng-display")') is not None
    ws = other_ws
    command_cdp("Page.bringToFront")
    wait_for(
        lambda: evaluate(
            'document.querySelector("#body").value === "" && '
            'document.querySelector("#body").disabled'
        ),
        "other tab cleared",
    )
    assert (
        evaluate(
            'Object.keys(sessionStorage).filter(key => key.startsWith("nurse-ng-draft:v1:")).length'
        )
        == 0
    )
    fill("#body", "A stale tab must not save this")
    assert (
        evaluate(
            'Object.keys(sessionStorage).filter(key => key.startsWith("nurse-ng-draft:v1:")).length'
        )
        == 0
    )
    ws = main_ws
    command_cdp("Page.bringToFront")
    navigate("/auth/login", "#phone")
    fill("#phone", "+2348999000002")
    fill("#password", password)
    submit('form[action="/auth/login"]')
    wait_for(
        lambda: evaluate('location.pathname === "/" && !!document.querySelector(".db")'),
        "other account login",
    )
    navigate("/posts/new", "#body")
    assert evaluate('document.querySelector("#body").value') == ""
    assert evaluate("document.body.dataset.draftScope") != first_scope
    command_cdp(
        "Emulation.setDeviceMetricsOverride",
        {
            "width": 320,
            "height": 844,
            "deviceScaleFactor": 1,
            "mobile": True,
        },
    )
    check_reflow("draft composer at 320 pixels")
    screenshot("draft-composer-320.png")
    command_cdp(
        "Emulation.setDeviceMetricsOverride",
        {
            "width": 1440,
            "height": 1000,
            "deviceScaleFactor": 1,
            "mobile": False,
        },
    )
    check_reflow("draft composer desktop")
    assert not errors, errors
    expected_failures = {
        # Anonymous pages verify sign-out before clearing durable offline storage.
        (401, base_url + "/offline/session"),
        (404, base_url + "/missing-draft-page"),
        (403, base_url + "/events/new"),
        (422, base_url + "/events?page=invalid"),
        (400, base_url + "/posts"),
        (400, base_url + post_path + "/replies"),
        (404, base_url + source_context_path),
    }
    assert all((code, url) in expected_failures for code, url in bad_responses), bad_responses
    print(
        "Reply-context and draft browser checks passed: response selection across pages, "
        "changed/removed targets, linked publication, restore, validation, offline submission, "
        "confirmation, "
        "history, error-page preservation, tab/discussion isolation, discard, expiry, "
        "malformed/blocked storage, "
        "logout across tabs, account switch, and mobile/desktop reflow."
    )
    print(f"Screenshots and logs: {artifacts}")
finally:
    for connection in {ws, globals().get("main_ws"), globals().get("other_ws")} - {None}:
        connection.close()
    for process in reversed(processes):
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    for log in logs:
        log.close()
