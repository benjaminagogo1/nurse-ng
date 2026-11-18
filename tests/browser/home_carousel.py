# ruff: noqa: E402
"""Homepage carousel checks in isolated Chrome; --baseline captures the original hero."""

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
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--baseline", action="store_true")
parser.add_argument("--baseline-report", type=Path)
parser.add_argument("--rotation-only", action="store_true")
parser.add_argument("--url", help="Check an already running homepage instead of a temporary server")
options = parser.parse_args()
artifacts = Path(tempfile.mkdtemp(prefix="nurse-home-carousel-"))
baseline = {}
if options.baseline_report:
    baseline = {
        check["width"]: check for check in json.loads(options.baseline_report.read_text())["checks"]
    }
print(f"Artifacts: {artifacts}", flush=True)


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


web_port, chrome_port = free_port(), free_port()
base = options.url.rstrip("/") if options.url else f"http://127.0.0.1:{web_port}"
environment = {
    **os.environ,
    "NURSE_NG_ENVIRONMENT": "development",
    "NURSE_NG_DEBUG": "0",
    "NURSE_NG_SECRET_KEY": secrets.token_urlsafe(32),
    "NURSE_NG_SESSION_HTTPS_ONLY": "0",
    "NURSE_NG_ALLOWED_HOSTS": "127.0.0.1,localhost",
    "NURSE_NG_DATABASE_URL": f"sqlite:///{artifacts / 'browser.db'}",
    "NURSE_NG_ACCOUNT_MAIL_BACKEND": "disabled",
    "NURSE_NG_REQUIRED_WORKERS": "",
}
processes, logs, errors, failed_requests, checks = [], [], [], [], []
ws = None
sequence = 0


def wait_for(check, label, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
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
        if response.get("method") == "Network.responseReceived":
            reply = response["params"]["response"]
            anonymous_session = (
                urlsplit(reply["url"]).path == "/offline/session" and reply["status"] == 401
            )
            if reply["url"].startswith(base) and reply["status"] >= 400 and not anonymous_session:
                failed_requests.append({"url": reply["url"], "status": reply["status"]})
        if response.get("id") == identifier:
            assert "error" not in response, response
            return response.get("result", {})


def js(expression):
    result = cdp(
        "Runtime.evaluate",
        {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        },
    )
    assert "exceptionDetails" not in result, result
    return result.get("result", {}).get("value")


def viewport(width):
    cdp(
        "Emulation.setDeviceMetricsOverride",
        {
            "width": width,
            "height": 1000,
            "deviceScaleFactor": 1,
            "mobile": width < 700,
        },
    )


def navigate():
    previous = js("performance.timeOrigin")
    cdp("Page.navigate", {"url": base + "/"})
    wait_for(
        lambda: js(f"performance.timeOrigin !== {previous} && document.readyState === 'complete'"),
        "homepage",
    )
    js("document.fonts.ready")


def screenshot(name):
    (artifacts / name).write_bytes(
        base64.b64decode(
            cdp(
                "Page.captureScreenshot",
                {
                    "format": "png",
                    "captureBeyondViewport": True,
                    "clip": {
                        "x": 0,
                        "y": 0,
                        "width": js("innerWidth"),
                        "height": js("document.documentElement.scrollHeight"),
                        "scale": 1,
                    },
                },
            )["data"]
        )
    )


def active():
    return js("document.querySelector('[data-home-carousel]').dataset.active")


def click(selector):
    js(f"document.querySelector({json.dumps(selector)}).click()")


def mouse_over(selector):
    position = js(f"""(() => {{
      const bounds = document.querySelector({json.dumps(selector)}).getBoundingClientRect();
      return {{x: bounds.left + bounds.width / 2, y: bounds.top + bounds.height / 2}};
    }})()""")
    cdp("Input.dispatchMouseEvent", {"type": "mouseMoved", **position})
    return position


def mouse_click(selector):
    position = mouse_over(selector)
    for kind in ["mousePressed", "mouseReleased"]:
        cdp(
            "Input.dispatchMouseEvent",
            {"type": kind, **position, "button": "left", "clickCount": 1},
        )


def fully_visible(name):
    return js(f"""(() => {{
      const slide = document.querySelector('[data-hero-slide="{name}"]');
      return slide.getAttribute('aria-hidden') === 'false' &&
        Number(getComputedStyle(slide).opacity) === 1;
    }})()""")


def slide_visibility(name):
    return js(f"""(() => {{
      const slide = document.querySelector('[data-hero-slide="{name}"]');
      return {{hidden: slide.getAttribute('aria-hidden'),
        opacity: Number(getComputedStyle(slide).opacity),
        animations: slide.getAnimations().map(animation => ({{
          time: animation.currentTime, state: animation.playState,
          duration: animation.effect.getTiming().duration
        }}))}};
    }})()""")


def settled():
    js("new Promise(resolve => setTimeout(resolve, 550))")


def attribute(selector, name):
    return js(f"document.querySelector({json.dumps(selector)}).getAttribute({json.dumps(name)})")


def geometry():
    return js("""(() => {
      const carousel = document.querySelector('[data-home-carousel]').getBoundingClientRect();
      const next = document.querySelector('.why-section').getBoundingClientRect();
      return {height: carousel.height, nextTop: next.top, scrollY};
    })()""")


try:
    for name, command in [
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
                "--disable-gpu",
                "--disable-extensions",
                "--disable-background-networking",
                "--no-first-run",
                "--no-default-browser-check",
                f"--user-data-dir={artifacts / 'chrome'}",
                f"--remote-debugging-port={chrome_port}",
                "about:blank",
            ],
        ),
    ]:
        if name == "server" and options.url:
            continue
        log = (artifacts / (name + ".log")).open("w")
        logs.append(log)
        processes.append(
            subprocess.Popen(command, cwd=ROOT, env=environment, stdout=log, stderr=log)
        )
    wait_for(lambda: urllib.request.urlopen(base + "/healthz", timeout=1).status == 200, "server")
    tabs = wait_for(
        lambda: json.load(
            urllib.request.urlopen(
                f"http://127.0.0.1:{chrome_port}/json/list",
                timeout=1,
            )
        ),
        "Chrome",
    )
    ws = connect(
        next(tab["webSocketDebuggerUrl"] for tab in tabs if tab["type"] == "page"),
        legacy=True,
        max_size=16 * 1024 * 1024,
    )
    for method in ["Page.enable", "Runtime.enable", "Network.enable"]:
        cdp(method)
    cdp("Emulation.setFocusEmulationEnabled", {"enabled": True})
    for width in ([] if options.rotation_only else [1440, 1024, 768, 390, 320]):
        viewport(width)
        navigate()
        assert js("document.documentElement.scrollWidth <= innerWidth + 1")
        if options.baseline:
            screenshot(f"first-{width}.png")
            checks.append(
                {
                    "width": width,
                    "hero": js("document.querySelector('.hero').outerHTML"),
                    "height": js("document.querySelector('.hero').getBoundingClientRect().height"),
                }
            )
            continue
        wait_for(lambda: active() == "careers", "first slide")
        if attribute("[data-hero-pause]", "aria-label") == "Pause automatic slides":
            click("[data-hero-pause]")
        assert js("document.querySelectorAll('[data-hero-slide]').length") == 2
        assert js("document.querySelector('[data-hero-slide]').dataset.heroSlide") == "careers"
        assert js("document.querySelectorAll('[data-hero-slide]')[1].dataset.heroSlide") == "care"
        hero = js("document.querySelector('.hero').outerHTML")
        height = js("document.querySelector('.hero').getBoundingClientRect().height")
        screenshot(f"first-{width}.png")
        if width in baseline:
            assert hero == baseline[width]["hero"], "Original hero content changed"
            assert abs(height - baseline[width]["height"]) < 1, (
                width,
                height,
                baseline[width]["height"],
            )
        before = geometry()
        assert js("document.querySelector('[data-hero-slide=care]').inert")
        fade = js("""(() => {
          const slide = document.querySelector('[data-hero-slide=care]');
          const from = Number(getComputedStyle(slide).opacity);
          document.querySelector('[data-hero-next]').click();
          getComputedStyle(slide).opacity;
          window.homeTestFade = slide.getAnimations().find(
            animation => animation.transitionProperty === 'opacity');
          if (!window.homeTestFade) return {from, animation: false};
          const duration = window.homeTestFade.effect.getTiming().duration;
          window.homeTestFade.pause();
          window.homeTestFade.currentTime = duration / 2;
          return {from, animation: true, duration,
                  middle: Number(getComputedStyle(slide).opacity)};
        })()""")
        assert active() == "care"
        if js("document.documentElement.dataset.motion") != "reduce":
            assert fade["animation"], (width, fade)
            assert fade["from"] == 0 and 0 < fade["middle"] < 1, (width, fade)
            assert 0 < fade["duration"] <= 1000
            js("window.homeTestFade.play()")
        settled()
        assert geometry() == before, "Slide transition changed page geometry"
        assert js("document.querySelector('[data-hero-slide=careers]').inert")
        assert attribute("[data-hero-slide=care]", "aria-hidden") == "false"
        wait_for(
            lambda: js("""(() => {
          const image = document.querySelector('.care-visual img');
          return image.complete && image.naturalWidth > 0;
        })()"""),
            "care image",
        )
        assert js("""document.querySelector('.care-support')
          .textContent.replace(/\\s+/g, ' ').trim()""") == (
            "Nurses, Doctors, Pharmacists and other health professionals working "
            "together for one goal — your well-being."
        )
        assert (
            js("document.querySelector('.care-closing').textContent")
            == "A United Health Team. A Healthier You."
        )
        assert js("document.documentElement.scrollWidth <= innerWidth + 1")
        assert js("""Array.from(document.querySelectorAll('[data-hero-controls] button'))
          .every(button => {
            const bounds = button.getBoundingClientRect();
            return bounds.width >= 44 && bounds.height >= 44;
          })""")
        screenshot(f"second-{width}.png")
        click("[data-hero-next]")
        assert active() == "careers"
        click("[data-hero-prev]")
        assert active() == "care"
        click('[data-hero-go="0"]')
        assert active() == "careers"
        click('[data-hero-go="1"]')
        assert active() == "care"
        assert attribute('[data-hero-go="1"]', "aria-current") == "true"
        js("document.querySelector('[data-hero-next]').focus()")
        cdp("Input.dispatchKeyEvent", {"type": "keyDown", "key": "ArrowRight"})
        cdp("Input.dispatchKeyEvent", {"type": "keyUp", "key": "ArrowRight"})
        assert active() == "careers"
        assert js("document.activeElement.hasAttribute('data-hero-next')")
        assert geometry() == before
        checks.append(
            {
                "width": width,
                "first_content_preserved": True,
                "first_height": height,
                "stable_geometry": before,
                "manual_and_keyboard_navigation": True,
            }
        )

    if not options.baseline:
        # Check both site appearances and readable, noncropped mobile composition.
        for width, preferences, name in ([] if options.rotation_only else [
            (1440, {"theme": "light"}, "second-light-desktop"),
            (390, {"theme": "light"}, "second-light-mobile"),
            (320, {"theme": "dark", "largeText": True}, "second-large-dark-320"),
            (
                768,
                {"theme": "light", "largeText": True, "highContrast": True},
                "second-contrast-tablet",
            ),
        ]):
            js(f"localStorage.setItem('nurse-ng-display', {json.dumps(json.dumps(preferences))})")
            viewport(width)
            navigate()
            click("[data-hero-next]")
            settled()
            assert js("document.documentElement.scrollWidth <= innerWidth + 1")
            assert js("""(() => {
              const bounds = document.querySelector('.care-visual').getBoundingClientRect();
              return bounds.left >= 0 && bounds.right <= innerWidth;
            })()""")
            assert geometry()["height"] >= js(
                "document.querySelector('.care-inner').getBoundingClientRect().height"
            )
            screenshot(name + ".png")
            checks.append({"appearance": preferences, "width": width, "no_overflow": True})

        viewport(1440)
        if options.rotation_only:
            navigate()
        js("localStorage.removeItem('nurse-ng-display')")
        navigate()
        assert active() == "careers"
        # A pointer resting over the homepage must not silently disable autoplay.
        mouse_over(".hero-copy")
        wait_for(lambda: active() == "care", "automatic rotation after ten seconds", seconds=13)
        # Reading visibility also flushes styles in headless Chrome before waiting
        # for the rendered fade, rather than assuming a timer advances every frame.
        slide_visibility("care")
        wait_for(lambda: fully_visible("care"), "second slide's completed fade", seconds=2)
        js("new Promise(resolve => setTimeout(resolve, 8500))")
        assert active() == "care" and fully_visible("care"), slide_visibility("care")
        wait_for(lambda: active() == "careers", "next automatic rotation", seconds=4)
        settled()
        mouse_click("[data-hero-next]")
        slide_visibility("care")
        wait_for(lambda: fully_visible("care"), "second slide after mouse click", seconds=2)
        assert active() == "care" and fully_visible("care")
        assert attribute("[data-hero-pause]", "aria-label") == "Pause automatic slides"
        wait_for(lambda: active() == "careers", "rotation after a real mouse click", seconds=13)
        mouse_click("[data-hero-pause]")
        assert attribute("[data-hero-pause]", "aria-label") == "Play automatic slides"
        js("new Promise(resolve => setTimeout(resolve, 10500))")
        assert active() == "careers", "Pause did not stop rotation"
        mouse_click("[data-hero-pause]")
        wait_for(lambda: active() == "care", "resumed automatic rotation", seconds=13)
        mouse_click('[data-hero-go="0"]')
        js("document.querySelector('#hero-q').focus()")
        assert attribute("[data-hero-pause]", "aria-label") == "Play automatic slides"
        checks.append(
            {
                "autoplay": True,
                "pointer_does_not_stop_rotation": True,
                "second_slide_stays_visible": True,
                "mouse_controls_preserve_rotation": True,
                "pause": True,
                "resume": True,
                "focus_stops_rotation": True,
            }
        )

        cdp(
            "Emulation.setEmulatedMedia",
            {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]},
        )
        navigate()
        assert js("document.documentElement.dataset.motion") == "reduce"
        assert attribute("[data-hero-pause]", "aria-label") == "Play automatic slides"
        click("[data-hero-next]")
        assert active() == "care"
        assert (
            js("""getComputedStyle(document.querySelector('[data-hero-slide=care]'))
          .transitionDuration""")
            == "0s"
        )
        checks.append({"system_reduced_motion": True})

        # Progressive enhancement retains both messages and the original search.
        cdp("Emulation.setScriptExecutionDisabled", {"value": True})
        cdp("Page.navigate", {"url": base + "/"})
        wait_for(
            lambda: js("""document.readyState === 'complete' &&
          !document.querySelector('.home-carousel.is-ready')"""),
            "no-JavaScript page",
        )
        assert js("document.querySelector('[data-hero-controls]').hidden")
        assert js("document.querySelector('.care-hero').getBoundingClientRect().height > 0")
        assert js("document.querySelector('.hero-search').getAttribute('action')") == "/jobs"
        checks.append({"no_javascript_fallback": True})
        cdp("Emulation.setScriptExecutionDisabled", {"value": False})
    assert not errors, errors
    assert not failed_requests, failed_requests
    (artifacts / "report.json").write_text(
        json.dumps(
            {
                "baseline": options.baseline,
                "base_url": base,
                "rotation_only": options.rotation_only,
                "checks": checks,
                "errors": errors,
                "failed_requests": failed_requests,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"Homepage checks passed. Artifacts: {artifacts}", flush=True)
finally:
    if ws:
        ws.close()
    for process in reversed(processes):
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
    for log in logs:
        log.close()
