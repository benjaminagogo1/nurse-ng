# ruff: noqa: E402, E501
"""Isolated notification and live-message browser journeys; file email only."""

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
from email import policy
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
artifacts = Path(tempfile.mkdtemp(prefix="nurse-notifications-browser-"))


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
        "NURSE_NG_SMTP_FROM": "Nurse.ng <no-reply@example.org>",
    }
)
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from websockets.sync.client import connect

from app.db.session import SessionLocal
from app.models.community import Connection
from app.models.messages import DirectMessage
from app.models.notifications import Notification
from app.models.user import User
from app.services.auth import register_user
from app.services.community import connection_pair_key
from app.services.messages import send_message
from app.services.notifications import preferences, save_preferences

command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
with SessionLocal() as db:
    first = register_user(
        db,
        phone="+2348000000077",
        password="browser-password",
        email="first@example.org",
        full_name="Ada Browser",
    )
    second = register_user(
        db,
        phone="+2348000000078",
        password="browser-password",
        email="second@example.org",
        full_name="Bola Browser",
    )
    first.community_name = "Ada Browser"
    second.community_name = "Bola Browser"
    first.email_verified_at = datetime.now(UTC)
    first_id, second_id = first.id, second.id
    connection = Connection(
        requester_user_id=first.id,
        recipient_user_id=second.id,
        pair_key=connection_pair_key(first.id, second.id),
        status="accepted",
    )
    db.add(connection)
    db.commit()
    connection_id = connection.id
    db.add_all(
        [
            DirectMessage(
                sender_id=second.id,
                recipient_id=first.id,
                body=f"Earlier message {i:03}",
                read_at=datetime.now(UTC),
                created_at=datetime.now(UTC) - timedelta(days=1, seconds=130 - i),
            )
            for i in range(125)
        ]
    )
    db.commit()
    send_message(db, second, first, "Welcome to your professional network")
processes, logs, errors, paused = [], [], [], []
ws, sequence = None, 0


def wait_for(fn, label, seconds=45):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            result = fn()
            if result:
                return result
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
    wait_for(
        lambda: js(
            f"location.pathname === {json.dumps(path.split('?')[0])} && "
            f'document.readyState === "complete" && !!document.querySelector({json.dumps(selector)})'
        ),
        path,
    )


def viewport(width=390):
    cdp(
        "Emulation.setDeviceMetricsOverride",
        {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": width < 900},
    )


def screenshot(name):
    (artifacts / name).write_bytes(
        base64.b64decode(cdp("Page.captureScreenshot", {"format": "png"})["data"])
    )


def incoming(text):
    with SessionLocal() as db:
        return send_message(db, db.get(User, second_id), db.get(User, first_id), text).id


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
        "Chrome",
    )
    ws = connect(next(t["webSocketDebuggerUrl"] for t in tabs if t["type"] == "page"), legacy=True)
    for method in ["Page.enable", "Runtime.enable", "Network.enable"]:
        cdp(method)
    viewport()
    navigate("/auth/login", "#phone")
    js(
        'document.querySelector("#phone").value="+2348000000077"; document.querySelector("#password").value="browser-password"; document.querySelector("form[action=\\"/auth/login\\"]").requestSubmit()'
    )
    wait_for(
        lambda: js('location.pathname === "/" && document.readyState === "complete"'), "sign in"
    )
    navigate("/notifications", "[data-notice-feed]")
    js('document.documentElement.dataset.theme="light"')
    assert js('!document.querySelector("[data-notification-badge]").hidden')
    assert js('document.querySelectorAll(".notice-item.is-unread").length === 1')
    for width in [320, 390, 1280]:
        viewport(width)
        assert js("document.documentElement.scrollWidth <= innerWidth+1")
        screenshot(f"notifications-{width}.png")
    viewport()
    navigate("/notifications/preferences", ".notice-switch")
    assert js('document.querySelectorAll("input[name$=\\"_email\\"]:checked").length === 0')
    js(
        'document.querySelector("input[name=messages_email]").click(); document.querySelector("form[action=\\"/notifications/preferences\\"]").requestSubmit()'
    )
    wait_for(
        lambda: js(
            'document.querySelector("#feedback-title")?.textContent === "Preferences saved"'
        ),
        "preferences saved",
    )
    screenshot("preferences-mobile.png")
    for width in [320, 390, 1280]:
        viewport(width)
        assert js('document.documentElement.scrollWidth <= innerWidth+1')
    viewport()
    navigate(f"/messages/{second_id}", "#message-body")
    assert js('document.querySelectorAll("[data-message-id]").length === 40')
    js('document.querySelector("#message-body").value="Keep this draft"')
    incoming("An automatic incoming message")
    wait_for(
        lambda: js(
            'document.querySelector(".thread-messages").textContent.includes("An automatic incoming message")'
        ),
        "live arrival",
    )
    assert js('document.querySelector("#message-body").value === "Keep this draft"')
    js('document.querySelector(".thread-messages").scrollTop=0')
    incoming("Do not move my reading position")
    # A previous live arrival can already have made the jump button visible.
    wait_for(
        lambda: js(
            '!document.querySelector(".thread-new").hidden && '
            'document.querySelector(".thread-messages").textContent.includes('
            '"Do not move my reading position")'
        ),
        "new message arrival and affordance",
    )
    assert js('document.querySelector(".thread-messages").scrollTop < 10')
    for _ in range(3):
        js('document.querySelector("[data-older]").click()')
        wait_for(
            lambda: js('!document.querySelector("[data-older]").hasAttribute("aria-busy")'),
            "older messages",
        )
    assert js('document.querySelectorAll("[data-message-id]").length === 128')
    assert js('document.querySelector("[data-older]").hidden')
    js('document.querySelector(".thread-new").click()')
    cdp(
        "Network.emulateNetworkConditions",
        {"offline": True, "latency": 0, "downloadThroughput": 0, "uploadThroughput": 0},
    )
    js('document.querySelector("form.message-compose").requestSubmit()')
    wait_for(
        lambda: js(
            'document.querySelector(".thread-status").textContent.includes("not confirmed")'
        ),
        "offline failure",
    )
    assert js('document.querySelector("#message-body").value === "Keep this draft"')
    cdp(
        "Network.emulateNetworkConditions",
        {"offline": False, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1},
    )
    # Drop the server's successful response, then retry with the same client key.
    paused.clear()
    cdp(
        "Fetch.enable",
        {"patterns": [{"urlPattern": f"*/messages/{second_id}", "requestStage": "Response"}]},
    )
    js('document.querySelector("form.message-compose").requestSubmit()')
    wait_for(lambda: js("true") and paused, "successful response intercepted")
    cdp(
        "Fetch.failRequest",
        {"requestId": paused[0]["requestId"], "errorReason": "ConnectionClosed"},
    )
    cdp("Fetch.disable")
    wait_for(
        lambda: js('!document.querySelector(".message-compose button").disabled'),
        "send failed visibly",
    )
    assert js('document.querySelector("#message-body").value === "Keep this draft"')
    js('document.querySelector("form.message-compose").requestSubmit()')
    wait_for(
        lambda: js('document.querySelector(".thread-status").textContent === "Message sent."'),
        "safe retry",
    )
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(DirectMessage)
                .where(DirectMessage.body == "Keep this draft")
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(Notification)
                .where(Notification.recipient_id == second_id)
            )
            == 1
        )
    for width in [320, 390, 1280]:
        viewport(width)
        assert js("document.documentElement.scrollWidth <= innerWidth+1")
        screenshot(f"messages-{width}.png")
    js('document.documentElement.dataset.theme="dark"')
    screenshot("messages-dark.png")
    # Pausing JS retains working server forms and historical navigation.
    cdp("Emulation.setScriptExecutionDisabled", {"value": True})
    cdp("Page.navigate", {"url": base + f"/messages/{second_id}"})
    time.sleep(1)
    cdp("Emulation.setScriptExecutionDisabled", {"value": False})
    wait_for(lambda: js('document.readyState === "complete"'), "no-JS document")
    assert js('document.querySelector("[data-older]").href.includes("before=")')
    navigate(f"/messages/{second_id}", "#message-body")
    with SessionLocal() as db:
        db.delete(db.get(Connection, connection_id))
        db.commit()
    wait_for(
        lambda: js('document.querySelector("#message-body").disabled'), "connection revocation"
    )
    assert js('document.querySelectorAll("[data-message-id]").length === 0')
    # Exercise the actual CLI worker against the isolated database and file mailbox.
    with SessionLocal() as db:
        first, second = db.get(User, first_id), db.get(User, second_id)
        db.add(
            Connection(
                requester_user_id=first.id,
                recipient_user_id=second.id,
                pair_key=connection_pair_key(first.id, second.id),
                status="accepted",
            )
        )
        db.commit()
        values = preferences(db, first)
        values["messages"]["email"] = True
        save_preferences(db, first, values)
        delivery_message = send_message(db, second, first, "File delivery only")
        delivery_notice_id = db.scalar(select(Notification.id).where(
            Notification.message_id == delivery_message.id,
            Notification.recipient_id == first_id,
        ))
        assert delivery_notice_id is not None
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "notification-worker", "--once"],
        cwd=ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    (artifacts / "worker.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    with SessionLocal() as db:
        delivery_notice = db.get(Notification, delivery_notice_id)
        assert delivery_notice.email_state == "sent"
        assert delivery_notice.email_attempts == 1
        assert delivery_notice.email_lease_token is None
    messages = [BytesParser(policy=policy.default).parsebytes(path.read_bytes())
                for path in (artifacts / "mail").glob("*.eml")]
    assert any("first@example.org" in str(mail["To"])
               and f"{base}/notifications" in mail.get_body(preferencelist=("plain",)).get_content()
               and "File delivery only" not in mail.get_body(preferencelist=("plain",)).get_content()
               for mail in messages)
    assert not errors, errors
    assert not (artifacts / "server.log").read_text().strip()
    print(
        json.dumps(
            {
                "passed": True,
                "artifacts": str(artifacts),
                "widths": [320, 390, 1280],
                "checks": [
                    "inbox and unread badge",
                    "preferences",
                    "automatic arrival and draft preservation",
                    "128-message history",
                    "no scroll jumps",
                    "offline and lost-response retry",
                    "revoked access",
                    "actual worker file delivery",
                    "clean server and JS logs",
                ],
            }
        )
    )
except Exception:
    if ws:
        screenshot("failure.png")
        print("Page:", js("location.pathname"))
        print("Status:", js('document.querySelector(".thread-status")?.textContent'))
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
