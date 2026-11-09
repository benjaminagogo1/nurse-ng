# ruff: noqa: E402, E501
"""Isolated registration, discovery, privacy and responsive onboarding journeys."""

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
artifacts = Path(tempfile.mkdtemp(prefix="nurse-discovery-browser-"))


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
from websockets.sync.client import connect

from app.db.session import SessionLocal
from app.models.user import User

command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
from sqlalchemy import select

from app.models.community import Connection
from app.models.profile import NurseProfile
from app.services.community import connection_pair_key
from app.services.jobs import create_job
from app.services.profiles import get_visibility_map
from tests.test_member_discovery import person

with SessionLocal() as db:
    for number in range(1, 15):
        public = person(
            db,
            number,
            name=f"Nurse Colleague {number:02}",
            location="Lagos",
            interests="Digital health",
            fields=("location", "interests"),
        )
    hidden = person(db, 15, name="Private Preferences", location="Abuja", interests="Research")
    hidden.user.photo_storage_name = "b" * 32
    db.commit()
    hidden_photo = hidden.user.photo_storage_name
    public_id = str(public.public_id)
    employer = public.user
    employer.account_type = "employer"
    db.commit()
    job = create_job(
        db,
        employer,
        title="Digital health fellowship",
        organization="Example Health",
        location="Lagos",
        country_code="NG",
        job_type="fellowship",
        work_mode="on_site",
        salary_min="",
        salary_max="",
        description="A supervised learning programme.",
    )
    job_id = str(job.id)
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
    navigate("/auth/register", "#full_name")
    js(
        'document.querySelector("#full_name").value="Ada Discovery"; document.querySelector("#phone").value="+2348000000077"; document.querySelector("#password").value="browser-password"; document.querySelector("#register-form").requestSubmit()'
    )
    wait_for(
        lambda: js('location.pathname === "/welcome" && document.readyState === "complete"'),
        "registration to welcome",
    )
    js(
        'const displayForm = document.querySelector("#display-form"); displayForm.elements.theme.value="light"; displayForm.dispatchEvent(new Event("change", {bubbles:true}))'
    )
    for width in [320, 390, 1280]:
        viewport(width)
        assert js("document.documentElement.scrollWidth <= innerWidth+1"), (
            width,
            "welcome overflow",
        )
        screenshot(f"welcome-{width}.png")
    viewport()
    js(
        'document.querySelector(`input[name="interests"][value="Digital health"]`).click(); document.querySelector("#welcome-location").value="Lagos"; document.querySelector(".welcome-form").requestSubmit()'
    )
    wait_for(
        lambda: js(
            'location.pathname === "/welcome/discover" && !!document.querySelector("#feedback-title")'
        ),
        "suggestions",
    )
    assert js(
        'document.querySelector("#feedback-title").textContent === "Your interests are saved"'
    )
    assert js('document.querySelector("#feedback-title").getBoundingClientRect().top < innerHeight')
    assert js('document.querySelectorAll(".person-card").length === 6')
    assert js('document.querySelector(".job-title").textContent === "Digital health fellowship"')
    for width in [320, 390, 1280]:
        viewport(width)
        assert js("document.documentElement.scrollWidth <= innerWidth+1"), (
            width,
            "suggestions overflow",
        )
        screenshot(f"suggestions-{width}.png")
    with SessionLocal() as db:
        member = db.scalar(select(User).where(User.phone == "+2348000000077"))
        profile = db.scalar(select(NurseProfile).where(NurseProfile.user_id == member.id))
        assert not profile.discoverable and not member.photo_public
        assert set(get_visibility_map(db, profile).values()) == {"private"}
        assert member.onboarding_completed_at
    navigate("/nurses")
    for width in [320, 390, 1280]:
        viewport(width)
        assert js("document.documentElement.scrollWidth <= innerWidth+1"), (
            width,
            "directory overflow",
        )
        screenshot(f"directory-{width}.png")
    viewport()
    js(
        'document.querySelector("#people-location").value="Lagos"; document.querySelector("#people-interest").value="Digital health"; document.querySelector(".directory-search").requestSubmit()'
    )
    wait_for(
        lambda: js(
            'location.search.includes("interest=Digital") && document.readyState === "complete"'
        ),
        "filtered directory",
    )
    assert js('document.querySelector(".discovery-results h2").textContent === "14 colleagues found"')
    assert js('document.querySelectorAll(".person-card").length === 12')
    js('document.querySelector(`a[rel="next"]`).click()')
    wait_for(
        lambda: js(
            'location.search.includes("page=2") && document.querySelectorAll(".person-card").length === 2'
        ),
        "pagination",
    )
    assert js('document.querySelector("#people-location").value === "Lagos"')
    navigate("/nurses?location=Abuja")
    assert js('document.querySelectorAll(".person-card").length === 0')
    navigate("/nurses?interest=Research")
    assert js('document.querySelectorAll(".person-card").length === 0')
    navigate("/nurses?q=Private")
    assert js('document.querySelectorAll(".person-card").length === 1')
    assert not js(f'document.querySelector(`img[src="/account/photos/{hidden_photo}"]`) !== null')
    js('document.querySelector(".nav-toggle").click()')
    assert js('document.querySelector(`#mobile-navigation[open] a[href="/nurses"]`) !== null')
    screenshot("directory-mobile-navigation.png")
    js('document.querySelector("[data-navigation-close]").click()')
    navigate(f"/p/{public_id}")
    js('document.querySelector(`form[action$="/follow"]`).requestSubmit()')
    wait_for(
        lambda: js('!!document.querySelector(`form[action$="/unfollow"]`)'),
        "follow from private account",
    )
    js('document.querySelector(`form[action$="/connect"]`).requestSubmit()')
    wait_for(
        lambda: js(
            'document.querySelector("main")?.textContent.includes("Connection request pending")'
        ),
        "connection request",
    )

    # Accept/Decline buttons are named "action"; their names must not mask the form URL.
    with SessionLocal() as db:
        member = db.scalar(select(User).where(User.phone == "+2348000000077"))
        colleagues = db.scalars(
            select(NurseProfile).where(
                NurseProfile.display_name.in_(["Nurse Colleague 01", "Nurse Colleague 02"])
            ).order_by(NurseProfile.display_name)
        ).all()
        requests = [
            Connection(
                requester_user_id=colleague.user_id,
                recipient_user_id=member.id,
                pair_key=connection_pair_key(colleague.user_id, member.id),
                status="pending",
            )
            for colleague in colleagues
        ]
        db.add_all(requests)
        db.commit()
        request_ids = [item.id for item in requests]
    for request_id, decision in zip(request_ids, ["accept", "decline"], strict=True):
        navigate("/network")
        selector = f'form[action="/connections/{request_id}/respond"]'
        js(f'document.querySelector({json.dumps(selector + " button[value=" + decision + "]")}).click()')
        wait_for(
            lambda selector=selector: js(
                'document.querySelector("#feedback-title")?.textContent === "Connection request updated" && '
                f'!document.querySelector({json.dumps(selector)})'
            ),
            decision + " connection request",
        )
        with SessionLocal() as db:
            assert db.get(Connection, request_id).status == (
                "accepted" if decision == "accept" else "declined"
            )
    navigate("/auth/dashboard")
    assert js('document.querySelector("#dashboard-people") !== null')
    assert js('document.querySelector(".dashboard-onboarding") === null')
    js(
        '(() => { const f = document.querySelector("#display-form"); f.elements.theme.value="dark"; f.elements.largeText.checked=true; f.dispatchEvent(new Event("change", {bubbles:true})); })()'
    )
    viewport(320)
    assert js("document.documentElement.scrollWidth <= innerWidth+1"), (
        "large-text dashboard overflow"
    )
    screenshot("dashboard-dark-large-text.png")
    navigate("/welcome")
    assert js('document.documentElement.dataset.textSize === "large"')
    assert js('document.querySelector(`input[value="Digital health"]`).checked')
    assert js("document.documentElement.scrollWidth <= innerWidth+1"), "large-text welcome overflow"
    screenshot("welcome-dark-large-text.png")
    assert not errors, errors
    assert not (artifacts / "server.log").read_text().strip()
    print(
        json.dumps(
            {
                "passed": True,
                "artifacts": str(artifacts),
                "widths": [320, 390, 1280],
                "flows": [
                    "registration",
                    "onboarding",
                    "privacy",
                    "recommendations",
                    "filtering",
                    "pagination",
                    "mobile navigation",
                    "following",
                    "connection requests",
                    "accept and decline connection requests",
                    "dashboard",
                    "dark theme and enlarged text",
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
