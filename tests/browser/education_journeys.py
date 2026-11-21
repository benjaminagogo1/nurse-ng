"""Exercise real learning pages in Chrome using isolated demonstration accounts.

Run ``venv/bin/python tests/browser/education_journeys.py``. The runner creates
a temporary SQLite database, disables mail/workers/provider credentials, and
checks enrollment, reading, grading, registration and educator authoring through
native forms. Screenshots and JSON evidence are written under /tmp. Use
``--keep-preview --port 14400`` to retain the isolated local app for review;
the result includes its PID, URL and demonstration logins. No real installation,
member, provider account or professional qualification is created or modified.
"""

import argparse
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

from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "NurseLearning2026!"
PHONES = {"educator": "+2348000000001", "learner": "+2348000000002"}

# Executed in a fresh process after the isolated environment is installed. App
# settings must never be imported before the temporary database URL is applied.
SEED = r"""
import json
from datetime import UTC, datetime, timedelta
import app.models
from app.db.base import Base
from app.db.session import engine, SessionLocal
from app.models.user import User
from app.models.tour import UserTour
from app.services import education as learning
from app.core.security import hash_password

Base.metadata.create_all(engine)
now = datetime.now(UTC)
with SessionLocal() as db:
    accounts = {}
    for role, number in [('educator', 1), ('learner', 2), ('staff', 3)]:
        user = User(phone=f'+234800000000{number}',
                    hashed_password=hash_password('NurseLearning2026!'),
                    full_name=f'Demonstration {role}',
                    community_name=f'Demo {role}',
                    is_staff=role == 'staff', onboarding_completed_at=now)
        db.add(user)
        db.flush()
        db.add(UserTour(user_id=user.id, status='skipped', version=1,
                        revision=0, offered_at=now, finished_at=now))
        accounts[role] = user
    db.commit()
    teacher = accounts['educator']
    learning.apply_educator(db, teacher, {
        'display_name':'Demo nursing educator',
        'headline':'Communication and collaborative learning',
        'bio':'An isolated demonstration profile for reviewing the learning experience.',
        'subjects':'Communication, Professional learning',
    })
    learning.review_educator(db, accounts['staff'], teacher.id, 'approved',
                            'Approved within the isolated demonstration database.')
    course = learning.create_course(db, teacher, {
        'title':'Clear communication in nursing',
        'summary':'Practice listening, clear explanations and considerate discussion.',
        'description':'A demonstration course for reviewing lessons and learning progress.',
        'category':'Communication', 'level':'beginner',
    })
    module = learning.save_module(db, teacher, course.id, {'title':'Start with listening'})
    reading = learning.save_lesson(db, teacher, module.id, {
        'title':'Listen before responding', 'kind':'text',
        'content':'Listen to the whole question. Ask for clarification before responding.',
        'duration_minutes':5,
    })
    quiz = learning.save_lesson(db, teacher, module.id, {
        'title':'Check your understanding', 'kind':'quiz',
        'content':'Choose the response that supports clear communication.',
        'pass_percentage':70,
    })
    question = learning.save_quiz_question(db, teacher, quiz.id, {
        'prompt':'What is a helpful first step before responding?',
        'options':['Interrupt with an immediate answer','Listen and clarify the question'],
        'correct_index':1,
        'explanation':'Listening and clarification help both participants understand each other.',
    })
    learning.set_course_status(db, teacher, course.id, 'published')
    session = learning.create_session(db, teacher, {
        'title':'Communication questions and discussion',
        'description':'An isolated lecture schedule for reviewing registration and setup.',
        'objectives':'Ask clear questions\nMake space for different perspectives',
        'starts_at':now + timedelta(days=1), 'ends_at':now + timedelta(days=1, hours=1),
        'timezone':'Africa/Lagos', 'capacity':20, 'status':'scheduled',
        'course_id':str(course.id), 'recording_enabled':True, 'chat_enabled':True,
    })
    print(json.dumps({'course':str(course.id), 'reading':str(reading.id),
                      'quiz':str(quiz.id), 'question':str(question.id),
                      'session':str(session.id), 'module':str(module.id)}))
"""


def free_port():
    """Reserve a loopback candidate for a temporary test process."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def wait_for(check, label, seconds=30):
    """Bound every browser/startup wait and preserve the failing step's name."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except (OSError, ValueError):
            pass
        time.sleep(0.1)
    raise AssertionError("Timed out: " + label)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--keep-preview", action="store_true")
    options = parser.parse_args()
    artifacts = Path(tempfile.mkdtemp(prefix="nurse-education-journeys-"))
    web_port, debug_port = options.port or free_port(), free_port()
    base = f"http://127.0.0.1:{web_port}"
    environment = {
        **os.environ,
        "NURSE_NG_ENVIRONMENT": "development",
        "NURSE_NG_DEBUG": "false",
        "NURSE_NG_DATABASE_URL": f"sqlite:///{artifacts / 'preview.db'}",
        "NURSE_NG_SECRET_KEY": secrets.token_urlsafe(32),
        "NURSE_NG_ALLOWED_HOSTS": "127.0.0.1,localhost",
        "NURSE_NG_PUBLIC_BASE_URL": base,
        "NURSE_NG_SESSION_HTTPS_ONLY": "false",
        "NURSE_NG_ACCOUNT_MAIL_BACKEND": "disabled",
        "NURSE_NG_REQUIRED_WORKERS": "",
        "NURSE_NG_LIVEKIT_URL": "",
        "NURSE_NG_LIVEKIT_API_KEY": "",
        "NURSE_NG_LIVEKIT_API_SECRET": "",
        "NURSE_NG_SMTP_HOST": "",
        "NURSE_NG_GOOGLE_CLIENT_ID": "",
        "NURSE_NG_LINKEDIN_CLIENT_ID": "",
        "NURSE_NG_AVATAR_DIR": str(artifacts / "avatars"),
        "NURSE_NG_EVIDENCE_DIR": str(artifacts / "evidence"),
    }
    seeded = subprocess.run(
        [sys.executable, "-c", SEED],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    ids = json.loads(seeded.stdout.strip())
    server_log = (artifacts / "server.log").open("w")
    app_process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(web_port),
        ],
        cwd=ROOT,
        env=environment,
        stdout=server_log,
        stderr=server_log,
        start_new_session=options.keep_preview,
    )
    browser = None
    websocket = None
    errors, bad_responses, checks = [], [], []
    sequence = 0
    success = False
    try:
        wait_for(
            lambda: urllib.request.urlopen(base + "/healthz", timeout=2).status == 200,
            "isolated app startup",
        )
        browser = subprocess.Popen(
            [
                "/usr/bin/google-chrome",
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--no-first-run",
                "--no-default-browser-check",
                "--use-fake-device-for-media-stream",
                "--use-fake-ui-for-media-stream",
                "--remote-allow-origins=*",
                f"--remote-debugging-port={debug_port}",
                f"--user-data-dir={artifacts / 'chrome'}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        def target():
            targets = json.loads(
                urllib.request.urlopen(f"http://127.0.0.1:{debug_port}/json", timeout=2).read()
            )
            return next(item["webSocketDebuggerUrl"] for item in targets if item["type"] == "page")

        websocket = connect(wait_for(target, "Chrome startup"), legacy=True)

        def cdp(method, params=None):
            nonlocal sequence
            sequence += 1
            websocket.send(json.dumps({"id": sequence, "method": method, "params": params or {}}))
            while True:
                reply = json.loads(websocket.recv(timeout=30))
                if reply.get("method") == "Runtime.exceptionThrown":
                    errors.append(reply["params"])
                if reply.get("method") == "Network.responseReceived":
                    response = reply["params"]["response"]
                    path = urlsplit(response["url"]).path
                    expected = path == "/offline/session" and response["status"] == 401
                    if (
                        response["url"].startswith(base)
                        and response["status"] >= 400
                        and not expected
                    ):
                        bad_responses.append({"path": path, "status": response["status"]})
                if reply.get("id") == sequence:
                    assert "error" not in reply, reply
                    return reply.get("result", {})

        def js(expression):
            response = cdp(
                "Runtime.evaluate",
                {
                    "expression": expression,
                    "returnByValue": True,
                    "awaitPromise": True,
                },
            )
            assert "exceptionDetails" not in response, response
            return response.get("result", {}).get("value")

        def navigate(path):
            previous = js("performance.timeOrigin")
            cdp("Page.navigate", {"url": base + path})
            wait_for(
                lambda: js(
                    f"performance.timeOrigin!=={previous} && document.readyState==='complete'"
                ),
                path,
            )
            js("document.fonts.ready")

        def submit(selector, values=None):
            previous = js("performance.timeOrigin")
            js(f"""(() => {{
              const form=document.querySelector({json.dumps(selector)});
              for (const [name,value] of Object.entries({json.dumps(values or {})})) {{
                form.elements.namedItem(name).value=value;
              }}
              form.requestSubmit();
            }})()""")
            wait_for(
                lambda: js(
                    f"performance.timeOrigin!=={previous} && document.readyState==='complete'"
                ),
                "form submission: " + selector,
            )

        def login(role):
            cdp("Network.clearBrowserCookies")
            navigate("/auth/login?next=/learning/live")
            submit('form[action="/auth/login"]', {"phone": PHONES[role], "password": PASSWORD})
            navigate("/learning/live")
            assert js("Boolean(document.querySelector('a[href=\"/learning/live/mine\"]'))")

        def inspect_page(label, width):
            result = js("""(() => {
              const page=document.querySelector('.edu-page');
              const controls=[...page.querySelectorAll('input:not([type=hidden]),textarea,select')];
              const unlabeled=controls.filter(el=>!el.closest('label') &&
                !el.getAttribute('aria-label') && !el.getAttribute('aria-labelledby') &&
                !page.querySelector(`label[for="${el.id}"]`));
              const ids=[...page.querySelectorAll('[id]')].map(el=>el.id);
              return {horizontalOverflow:document.documentElement.scrollWidth>innerWidth+1,
                unlabeled:unlabeled.map(el=>el.name || el.id),
                duplicateIds:ids.filter((id,index)=>ids.indexOf(id)!==index)};
            })()""")
            assert not result["horizontalOverflow"], (label, width, result)
            assert not result["unlabeled"] and not result["duplicateIds"], (label, result)
            checks.append({"page": label, "width": width, **result})
            screenshot = cdp(
                "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True}
            )
            (artifacts / f"{label}-{width}.png").write_bytes(base64.b64decode(screenshot["data"]))

        cdp("Runtime.enable")
        cdp("Page.enable")
        cdp("Network.enable")
        login("learner")
        navigate(f"/learning/live/courses/{ids['course']}")
        submit(f'form[action="/learning/live/courses/{ids["course"]}/enroll"]')
        assert js("document.body.textContent.includes('You are enrolled in this course')")
        navigate(f"/learning/live/lessons/{ids['reading']}")
        submit(f'form[action="/learning/live/lessons/{ids["reading"]}/complete"]')
        assert js("document.body.textContent.includes('You have completed this lesson')")
        navigate(f"/learning/live/lessons/{ids['quiz']}")
        js(
            f'document.querySelector(\'input[name="question_{ids["question"]}"][value="1"]\').checked=true'
        )
        submit("form.edu-quiz")
        assert js("document.body.textContent.includes('100%')")
        assert js(
            "document.body.textContent.includes('Listening and clarification help '"
            "+ 'both participants')"
        )
        navigate(f"/learning/live/courses/{ids['course']}")
        assert js("document.querySelector('progress').value===100")
        navigate(f"/learning/live/sessions/{ids['session']}")
        submit(f'form[action="/learning/live/sessions/{ids["session"]}/register"]')
        assert js("document.body.textContent.includes('You are registered')")
        navigate(f"/learning/live/sessions/{ids['session']}/room")
        assert js("document.querySelector('[data-room-join]').disabled")
        assert js("document.querySelector('[data-room-recording-consent]')!==null")

        for width in (1280, 390, 320):
            cdp(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": width,
                    "height": 1000,
                    "deviceScaleFactor": 1,
                    "mobile": width < 700,
                },
            )
            for label, path in [
                ("catalog", "/learning/live"),
                ("mine", "/learning/live/mine"),
                ("course", f"/learning/live/courses/{ids['course']}"),
                ("quiz", f"/learning/live/lessons/{ids['quiz']}"),
                ("session", f"/learning/live/sessions/{ids['session']}"),
                ("room", f"/learning/live/sessions/{ids['session']}/room"),
            ]:
                navigate(path)
                inspect_page(label, width)

        login("educator")
        for width in (1280, 390, 320):
            cdp(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": width,
                    "height": 1000,
                    "deviceScaleFactor": 1,
                    "mobile": width < 700,
                },
            )
            for label, path in [
                ("studio", "/learning/live/studio"),
                ("course-editor", f"/learning/live/courses/{ids['course']}/edit"),
                ("quiz-editor", f"/learning/live/lessons/{ids['quiz']}/edit"),
                ("session-editor", f"/learning/live/sessions/{ids['session']}/edit"),
            ]:
                navigate(path)
                if label == "session-editor":
                    assert js(
                        f"document.querySelector('[name=course_id]').value==='{ids['course']}'"
                    )
                inspect_page(label, width)
        navigate("/learning/live/courses/new")
        submit(
            "form.edu-form",
            {
                "title": "A new demonstration draft",
                "summary": "A concise teaching purpose.",
                "description": "Draft content created through the real educator form.",
                "category": "Communication",
                "level": "beginner",
            },
        )
        assert js("document.body.textContent.includes('A new demonstration draft')")
        navigate("/learning/live/studio")
        assert js("document.body.textContent.includes('A new demonstration draft')")
        assert not errors, errors
        assert not bad_responses, bad_responses
        success = True
        report = {
            "passed": True,
            "artifacts": str(artifacts),
            "checks": checks,
            "enrollment_reading_quiz_registration": True,
            "quiz_progress_percent": 100,
            "educator_created_draft_through_form": True,
            "linked_course_preserved_in_editor": True,
            "provider_join_disabled_without_credentials": True,
            "javascript_errors": errors,
            "unexpected_http_errors": bad_responses,
            "real_provider_transport_verified": False,
            "preview": {
                "url": base + "/learning/live",
                "pid": app_process.pid,
                "retained": options.keep_preview,
                "phones": PHONES,
                "password": PASSWORD,
            },
        }
        (artifacts / "results.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report))
    finally:
        if websocket is not None:
            websocket.close()
        if browser is not None:
            browser.terminate()
            try:
                browser.wait(timeout=10)
            except subprocess.TimeoutExpired:
                browser.kill()
                browser.wait(timeout=5)
        if not (success and options.keep_preview):
            app_process.terminate()
            try:
                app_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                app_process.kill()
                app_process.wait(timeout=5)
        server_log.close()


if __name__ == "__main__":
    main()
