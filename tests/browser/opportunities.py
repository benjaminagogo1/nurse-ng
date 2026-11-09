# ruff: noqa: E402, E501
"""Isolated opportunity saves, alerts, deadline and mobile browser journeys."""

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
artifacts = Path(tempfile.mkdtemp(prefix="nurse-opportunities-browser-"))


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
from app.services.auth import register_user

command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
from app.models.opportunities import SavedOpportunity
from app.services.jobs import create_job


def create_opportunity(title="Public health fellowship"):
    with SessionLocal() as db:
        employer = db.get(User, employer_id)
        job = create_job(
            db,
            employer,
            title=title,
            organization="Example Health Team",
            location="Lagos, Nigeria",
            country_code="NG",
            job_type="fellowship",
            work_mode="on_site",
            salary_min="",
            salary_max="",
            description="Join a supervised programme. Read the eligibility requirements before applying.",
        )
        job.closes_at = datetime.now(UTC) + timedelta(hours=24)
        job.normalized_data = {
            "closing_date": job.closes_at.isoformat(),
            "deadline_timezone": "Africa/Lagos",
        }
        db.commit()
        return job.id


with SessionLocal() as db:
    member = register_user(
        db,
        phone="+2348000000077",
        password="browser-password",
        email="member@example.org",
        full_name="Ada Browser",
    )
    member.is_staff = True
    member.email_verified_at = datetime.now(UTC)
    employer = register_user(
        db,
        phone="+2348000000078",
        password="browser-password",
        email="employer@example.org",
        full_name="Example Health Team",
        account_type="employer",
    )
    member_id, employer_id = member.id, employer.id
    db.commit()
job_id = create_opportunity()
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
    navigate("/auth/login", "#phone")
    js(
        'document.querySelector("#phone").value="+2348000000077"; document.querySelector("#password").value="browser-password"; document.querySelector("form[action=\\"/auth/login\\"]").requestSubmit()'
    )
    wait_for(
        lambda: js('location.pathname === "/" && document.readyState === "complete"'), "sign in"
    )
    navigate("/jobs")
    js('document.documentElement.dataset.theme="light"')
    for width in [320, 390, 1280]:
        viewport(width)
        assert js("document.documentElement.scrollWidth <= innerWidth+1")
        screenshot(f"opportunities-{width}.png")
    viewport()
    navigate(f"/jobs/{job_id}")
    js('document.querySelector(`form[action$="/save"]`).requestSubmit()')
    wait_for(
        lambda: js(
            'document.querySelector("#feedback-title")?.textContent === "Opportunity saved"'
        ),
        "save feedback",
    )
    screenshot("save-feedback-mobile.png")
    navigate("/jobs/saved")
    assert js('document.querySelectorAll(".saved-opportunity").length === 1')
    assert js('document.querySelector("input[name=remind]").checked')
    screenshot("saved-mobile.png")
    navigate("/jobs/preferences")
    js(
        'document.querySelector("#interest-keyword").value="health"; document.querySelector("input[name=enabled]").click(); document.querySelector(`form[action="/jobs/preferences"]`).requestSubmit()'
    )
    wait_for(
        lambda: js(
            'document.querySelector("#feedback-title")?.textContent === "Opportunity preferences saved"'
        ),
        "interests saved",
    )
    screenshot("interests-mobile.png")
    navigate("/notifications/preferences")
    assert js('!document.querySelector("input[name=opportunities_email]").checked')
    js(
        'document.querySelector("input[name=opportunities_email]").click(); document.querySelector(`form[action="/notifications/preferences"]`).requestSubmit()'
    )
    wait_for(
        lambda: js(
            'document.querySelector("#feedback-title")?.textContent === "Preferences saved"'
        ),
        "email opt-in",
    )
    new_id = create_opportunity("Digital health fellowship")
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "notification-worker", "--once"],
        cwd=ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=40,
    )
    (artifacts / "worker.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0 and result.stdout.count("state=sent") == 2
    assert len(list((artifacts / "mail").glob("*.eml"))) == 2
    navigate("/notifications?category=opportunities")
    assert js('document.querySelectorAll(".notice-item").length === 2')
    assert js('document.querySelector("main").textContent.includes("closes soon")')
    assert js('document.querySelector("main").textContent.includes("matches your interests")')
    screenshot("opportunity-notifications-mobile.png")
    navigate("/jobs/matches")
    assert js('document.querySelectorAll(".job-row").length === 2')
    navigate("/jobs/saved")
    js('document.querySelector(`form[action$="/unsave"]`).requestSubmit()')
    wait_for(
        lambda: js(
            'document.querySelector("#feedback-title")?.textContent === "Opportunity removed"'
        ),
        "remove bookmark",
    )
    with SessionLocal() as db:
        assert db.get(SavedOpportunity, (member_id, job_id)) is None
    navigate("/recruitment/coverage")
    assert js(
        'document.querySelector("main").textContent.includes("Nigerian opportunity coverage")'
    )
    assert js("document.documentElement.scrollWidth <= innerWidth+1")
    screenshot("coverage-mobile.png")
    assert not errors, errors
    assert not (artifacts / "server.log").read_text().strip()
    print(
        json.dumps(
            {
                "passed": True,
                "artifacts": str(artifacts),
                "widths": [320, 390, 1280],
                "flows": [
                    "save and remove",
                    "reminder controls",
                    "interest matching",
                    "email opt-in",
                    "actual worker match and deadline alerts",
                    "coverage dashboard",
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
