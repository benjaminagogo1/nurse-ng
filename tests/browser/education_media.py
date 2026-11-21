"""Real Chrome pre-join media checks with synthetic camera/microphone devices.

Run ``venv/bin/python tests/browser/education_media.py``. A temporary loopback
fixture serves only the classroom controller and pinned SDK. No app database,
provider account, external meeting, email or real camera is used. Assertions
exercise negotiated HD capture, actual transmitted-track lighting processing,
device controls and complete capture/processor cleanup. This is deliberately
separate from an eventual real-provider room transport acceptance test.
"""

import json
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[2]
HTML = """<!doctype html><html><head><meta charset="utf-8"></head><body>
<div data-education-room data-session-id="00000000-0000-4000-8000-000000000001"
 data-is-host="true" data-live-unavailable="true" data-csrf="synthetic-csrf">
<p data-room-status role="status"></p><p data-room-error role="alert" hidden></p>
<div data-room-stage><p data-room-welcome>Classroom fixture</p></div>
<video data-room-local-preview autoplay muted playsinline hidden></video>
<div data-room-preview-placeholder>Private preview</div>
<select data-room-camera-device><option value="">Default camera</option></select>
<select data-room-mic-device><option value="">Default microphone</option></select>
<select data-room-quality><option value="1080">1080</option>
<option value="720">720</option><option value="360">360</option></select>
<select data-room-lighting><option value="neutral">Natural</option>
<option value="gentle">Gentle</option></select>
<p data-room-camera-settings></p>
<button data-room-preview-start>Preview</button>
<button data-room-preview-stop disabled>Stop preview</button>
<button data-room-join disabled>Join</button><button data-room-leave disabled>Leave</button>
<button data-room-mic disabled>Mic</button><button data-room-camera disabled>Camera</button>
<button data-room-screen disabled>Screen</button><button data-room-hand disabled>Hand</button>
<button data-room-audio-only>Audio only</button><button data-room-send disabled>Send</button>
<div data-room-participants></div></div>
<script>
window.fixtureTracks=[];
const capture=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
navigator.mediaDevices.getUserMedia=async (...args)=>{
 const stream=await capture(...args);
 window.fixtureTracks.push(...stream.getTracks());
 if(window.delayFixtureCapture) await new Promise(resolve=>window.releaseFixtureCapture=resolve);
 return stream;
};
const request=window.fetch.bind(window);
window.fetch=async (...args)=>{
 if(window.delayFixtureToken && String(args[0]).endsWith('/token')) {
  return await new Promise(resolve=>window.releaseFixtureToken=resolve);
 }
 return request(...args);
};
</script>
<script src="/livekit-client.umd.js"></script>
<script>
window.fixtureConnectCalls=0;
LivekitClient.Room.prototype.connect=async ()=>{
 window.fixtureConnectCalls+=1;
 throw new Error('Provider transport is intentionally absent from this fixture.');
};
</script><script src="/education-room.js"></script>
</body></html>"""


class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        files = {
            "/livekit-client.umd.js": ROOT / "app/static/vendor/livekit-client.umd.js",
            "/education-room.js": ROOT / "app/static/js/education-room.js",
        }
        if self.path == "/":
            data, content_type = HTML.encode(), "text/html; charset=utf-8"
        elif self.path in files:
            data, content_type = files[self.path].read_bytes(), "application/javascript"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    artifacts = Path(tempfile.mkdtemp(prefix="nurse-education-media-"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    debug_port = free_port()
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
            "--autoplay-policy=no-user-gesture-required",
            "--remote-allow-origins=*",
            f"--remote-debugging-port={debug_port}",
            f"--user-data-dir={artifacts / 'chrome'}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    websocket = None
    errors, sequence = [], 0
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                targets = json.loads(
                    urllib.request.urlopen(f"http://127.0.0.1:{debug_port}/json", timeout=2).read()
                )
                websocket = connect(
                    next(
                        item["webSocketDebuggerUrl"] for item in targets if item["type"] == "page"
                    ),
                    legacy=True,
                )
                break
            except (OSError, ValueError, StopIteration):
                time.sleep(0.1)
        assert websocket is not None, "Chrome did not start"

        def cdp(method, params=None):
            nonlocal sequence
            sequence += 1
            websocket.send(json.dumps({"id": sequence, "method": method, "params": params or {}}))
            while True:
                message = json.loads(websocket.recv(timeout=30))
                if message.get("method") == "Runtime.exceptionThrown":
                    errors.append(message["params"])
                if message.get("id") == sequence:
                    assert "error" not in message, message
                    return message.get("result", {})

        def js(expression):
            response = cdp(
                "Runtime.evaluate",
                {"expression": expression, "returnByValue": True, "awaitPromise": True},
            )
            assert "exceptionDetails" not in response, response
            return response.get("result", {}).get("value")

        def wait(expression, label):
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                if js(expression):
                    return
                time.sleep(0.1)
            raise AssertionError(
                label + ": " + str(js("document.querySelector('[data-room-error]').textContent"))
            )

        cdp("Runtime.enable")
        cdp("Page.enable")
        cdp("Page.navigate", {"url": f"http://127.0.0.1:{server.server_port}/"})
        wait(
            "document.readyState==='complete' && Boolean(window.LivekitClient)", "SDK did not load"
        )
        assert js("document.querySelector('[data-room-join]').disabled"), (
            "Unconfigured provider must not enable joining"
        )
        js("document.querySelector('[data-room-preview-start]').click()")
        wait(
            "!document.querySelector('[data-room-local-preview]').hidden && "
            "document.querySelector('[data-room-local-preview]').videoWidth>=1280",
            "HD preview failed",
        )
        raw_dimensions = js(
            "({width:document.querySelector('[data-room-local-preview]').videoWidth,height:document.querySelector('[data-room-local-preview]').videoHeight})"
        )
        assert raw_dimensions["width"] >= 1280 and raw_dimensions["height"] >= 720
        assert js("document.querySelector('[data-room-camera-device]').options.length") >= 2
        js(
            "window.neutralPreviewId=document.querySelector('[data-room-local-preview]')"
            ".srcObject.getVideoTracks()[0].id; "
            "const lighting=document.querySelector('[data-room-lighting]');"
            "lighting.value='gentle';lighting.dispatchEvent(new Event('change'))"
        )
        wait(
            "document.querySelector('[data-room-local-preview]').srcObject.getVideoTracks()[0].id!==window.neutralPreviewId",
            "Lighting did not create a processed outgoing track",
        )
        js(
            "window.processedFixtureTrack=document.querySelector('[data-room-local-preview]').srcObject.getVideoTracks()[0]"
        )
        assert js("document.querySelector('[data-room-local-preview]').videoWidth") >= 1280
        js(
            "const q=document.querySelector('[data-room-quality]');"
            "q.value='720';q.dispatchEvent(new Event('change'))"
        )
        wait(
            "document.querySelector('[data-room-local-preview]').videoWidth===1280",
            "Quality selector did not restart real capture",
        )
        js("document.querySelector('[data-room-preview-stop]').click()")
        wait(
            "document.querySelector('[data-room-local-preview]').hidden && "
            "window.fixtureTracks.every(track=>track.readyState==='ended') && "
            "window.processedFixtureTrack.readyState==='ended'",
            "Capture or lighting processor leaked after preview stop",
        )
        # Audio-only mode must stop actual camera capture, including its pixel
        # processor. Hiding the private video element would still use the camera.
        js("document.querySelector('[data-room-preview-start]').click()")
        wait("!document.querySelector('[data-room-local-preview]').hidden", "Second preview failed")
        js("document.querySelector('[data-room-audio-only]').click()")
        wait(
            "document.querySelector('[data-room-local-preview]').hidden && "
            "window.fixtureTracks.filter(track=>track.kind==='video').every(track=>track.readyState==='ended')",
            "Audio-only mode retained camera capture",
        )
        assert js(
            "window.fixtureTracks.some(track=>track.kind==='audio' && track.readyState==='live')"
        )
        js("document.querySelector('[data-room-preview-stop]').click()")
        wait(
            "window.fixtureTracks.every(track=>track.readyState==='ended')",
            "Audio-only microphone leaked",
        )
        js(
            "window.audioOnlyTrackCount=window.fixtureTracks.length; "
            "document.querySelector('[data-room-preview-start]').click()"
        )
        wait(
            "window.fixtureTracks.length>window.audioOnlyTrackCount && "
            "!document.querySelector('[data-room-preview-stop]').disabled",
            "Audio-only setup failed",
        )
        assert js(
            "window.fixtureTracks.slice(window.audioOnlyTrackCount)"
            ".every(track=>track.kind==='audio')"
        ), "Audio-only setup must not request a camera"
        js(
            "document.querySelector('[data-room-preview-stop]').click(); "
            "document.querySelector('[data-room-audio-only]').click()"
        )

        # Permission prompts are asynchronous. A late getUserMedia result must
        # be disposed after Stop or pagehide, rather than reviving private media.
        js(
            "window.delayFixtureCapture=true; window.releaseFixtureCapture=null; "
            "document.querySelector('[data-room-preview-start]').click()"
        )
        wait("Boolean(window.releaseFixtureCapture)", "Delayed capture did not start")
        assert not js("document.querySelector('[data-room-preview-stop]').disabled")
        js(
            "document.querySelector('[data-room-preview-stop]').click(); "
            "window.releaseFixtureCapture()"
        )
        wait(
            "window.fixtureTracks.every(track=>track.readyState==='ended') && "
            "!document.querySelector('[data-room-preview-start]').disabled",
            "Stopped pending capture revived or leaked tracks",
        )
        js(
            "window.releaseFixtureCapture=null; "
            "document.querySelector('[data-room-preview-start]').click()"
        )
        wait("Boolean(window.releaseFixtureCapture)", "Pagehide delayed capture did not start")
        js(
            "window.dispatchEvent(new PageTransitionEvent('pagehide')); "
            "window.releaseFixtureCapture()"
        )
        wait(
            "window.fixtureTracks.every(track=>track.readyState==='ended') && "
            "document.querySelector('[data-room-local-preview]').hidden",
            "Pending capture leaked after pagehide",
        )
        # A room grant may also finish after leaving the page. Reconnecting must
        # require a fresh explicit join; this fixture never opens a provider room.
        js(
            "window.delayFixtureCapture=false; window.delayFixtureToken=true; "
            "document.querySelector('[data-education-room]').dataset.liveUnavailable='false'; "
            "window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true})); "
            "document.querySelector('[data-room-join]').click()"
        )
        wait("Boolean(window.releaseFixtureToken)", "Delayed room grant did not start")
        js(
            "window.dispatchEvent(new PageTransitionEvent('pagehide')); "
            "window.releaseFixtureToken({ok:true,redirected:false,"
            "json:async()=>({url:'wss://fixture.invalid',token:'fixture',can_publish:true})})"
        )
        wait(
            "document.querySelector('[data-room-error]').textContent.includes('entry was stopped')",
            "Late room grant was not cancelled",
        )
        assert js("window.fixtureConnectCalls===0"), "Late room grant opened provider transport"

        # The member dependency uses an HTML sign-in redirect. Fetch follows it,
        # so explicitly recognize expired sessions and release private capture.
        js(
            "window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true})); "
            "window.releaseFixtureToken=null; "
            "document.querySelector('[data-room-preview-start]').click()"
        )
        wait(
            "!document.querySelector('[data-room-local-preview]').hidden", "Session preview failed"
        )
        js("document.querySelector('[data-room-join]').click()")
        wait("Boolean(window.releaseFixtureToken)", "Expired-session grant did not start")
        js(
            "window.releaseFixtureToken({ok:true,redirected:true,"
            "url:location.origin+'/auth/login',json:async()=>({})})"
        )
        wait(
            "window.fixtureTracks.every(track=>track.readyState==='ended') && "
            "document.querySelector('[data-room-error]').textContent"
            ".includes('sign-in has expired')",
            "Expired sign-in retained capture or accepted HTML as classroom JSON",
        )
        assert js("window.fixtureConnectCalls===0")
        assert not errors, errors
        report = {
            "hd_dimensions": raw_dimensions,
            "real_processed_track": True,
            "quality_control": "720p capture",
            "capture_cleanup": "all tracks ended",
            "provider_join_disabled_without_credentials": True,
            "audio_only_camera_stopped": True,
            "audio_only_setup_requests_microphone_only": True,
            "pending_capture_stopped_without_leaks": True,
            "pending_capture_pagehide_cleanup": True,
            "pending_room_grant_pagehide_cancelled": True,
            "expired_sign_in_redirect_stops_capture": True,
            "javascript_errors": errors,
            "real_provider_transport_verified": False,
        }
        (artifacts / "results.json").write_text(json.dumps(report, indent=2))
        print(json.dumps({"passed": True, "artifacts": str(artifacts), **report}))
    finally:
        if websocket is not None:
            websocket.close()
        browser.terminate()
        try:
            browser.wait(timeout=10)
        except subprocess.TimeoutExpired:
            browser.kill()
            browser.wait(timeout=5)
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
