# ruff: noqa: E402, E501
"""Check member-page reflow, separated controls and mobile navigation in real Chrome.

Run: venv/bin/python tests/browser/mobile_layout.py
Optional: --record docs/verification/2026-11-21/mobile-layout
All accounts, uploads and mail stay in a temporary migrated SQLite environment.
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
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--record", type=Path)
parser.add_argument("--capture-only", action="store_true")
parser.add_argument("--quick", action="store_true", help="Verify final mobile visual fixes and representative desktop layouts")
parser.add_argument("--header-greeting", action="store_true", help="Verify shared header controls, theme access and professional dashboard greetings")
args = parser.parse_args()
artifacts = Path(tempfile.mkdtemp(prefix="nurse-mobile-layout-"))
record = args.record or artifacts
record.mkdir(parents=True, exist_ok=True)


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


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
        "NURSE_NG_AVATAR_DIR": str(artifacts / "avatars"),
        "NURSE_NG_COMMUNITY_MEDIA_DIR": str(artifacts / "community-media"),
        "NURSE_NG_REQUIRED_WORKERS": "",
        "NURSE_NG_GOOGLE_CLIENT_ID": "",
        "NURSE_NG_LINKEDIN_CLIENT_ID": "",
    }
)

from alembic import command
from alembic.config import Config
from PIL import Image
from websockets.sync.client import connect

from app.db.session import SessionLocal
from app.models.profile import NurseProfile
from app.services.auth import register_user
from app.services.tours import transition
from tests.test_member_discovery import person

command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
password, phone = "browser-layout-password", "+2348999000951"
with SessionLocal() as db:
    member = register_user(
        db, phone=phone, password=password,
        full_name="Ada Nursing", email="layout@example.org",
    )
    member.email_verified_at = datetime.now(UTC)
    member.onboarding_completed_at = datetime.now(UTC)
    profile = NurseProfile(
        user_id=member.id, display_name="Ada Nursing", location="Lagos",
        interests="Digital health", headline="Registered nurse",
        bio="Learning with my nursing community.", skills="Public health",
        qualification="Registered nurse", professional_status="registered",
        years_experience=3,
    )
    db.add(profile)
    db.commit()
    profile_id, member_id = profile.id, member.id
    transition(db, member, action="skip", revision=0, run_id=None)
    person(
        db, 902,
        name="Nurse Elizabeth Chiamaka Nwankwo",
        location="Lagos", interests="Digital health",
        headline="Community health and clinical education",
        professional_status="registered",
        fields=("headline", "location", "interests", "professional_status"),
    )
picture = artifacts / "sample-photo.jpg"
Image.new("RGB", (640, 480), "#087c72").save(picture)
processes, logs, errors, checks = [], [], [], []
ws, sequence = None, 0


def wait_for(check, label, seconds=45):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            value = check()
            if value:
                return value
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
        if response.get("id") == sequence:
            assert "error" not in response, response
            return response.get("result", {})


def js(expression):
    response = cdp("Runtime.evaluate", {
        "expression": expression, "returnByValue": True, "awaitPromise": True,
    })
    assert "exceptionDetails" not in response, response
    return response.get("result", {}).get("value")


def navigate(path, selector="main"):
    js("window.layoutNavigationPending=true")
    cdp("Page.navigate", {"url": base + path})
    wait_for(lambda: js(
        f"!window.layoutNavigationPending && location.pathname === {json.dumps(path.split('?')[0])} && "
        f"document.readyState === 'complete' && !!document.querySelector({json.dumps(selector)})"
    ), path)
    js("document.fonts.ready.then(() => new Promise(resolve => requestAnimationFrame(() => resolve(true))))")


def viewport(width):
    cdp("Emulation.setDeviceMetricsOverride", {
        "width": width, "height": 900, "deviceScaleFactor": 1, "mobile": width < 900,
    })


def screenshot(name, selector=None):
    if selector:
        js(f"document.querySelector({json.dumps(selector)}).scrollIntoView({{block:'center'}})")
    else:
        js("scrollTo(0,0)")
    js("new Promise(resolve => requestAnimationFrame(() => setTimeout(resolve, 100)))")
    (record / name).write_bytes(base64.b64decode(cdp("Page.captureScreenshot", {
        "format": "png", "captureBeyondViewport": False,
    })["data"]))


def layout_check(path, width, mode):
    result = js(r"""(() => {
      const visible = e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
      const overlaps = (a,b) => Math.min(a.right,b.right)-Math.max(a.left,b.left)>1 &&
        Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>1;
      const issues = [];
      const groups = document.querySelectorAll(
        '.button-row,.community-heading-actions,.notice-filters,.community-view-nav,.community-shortcuts,.participation-nav'
      );
      for (const group of groups) {
        const items = [...group.children].filter(e => e.matches('a,button') && visible(e));
        for (let i=0;i<items.length;i++) {
          if(items[i].getClientRects().length>1) issues.push('Action splits across lines: '+items[i].textContent.trim());
          const walker=document.createTreeWalker(items[i],NodeFilter.SHOW_TEXT);
          while(walker.nextNode()) for(const match of walker.currentNode.textContent.matchAll(/\S+/g)) {
            const range=document.createRange();
            range.setStart(walker.currentNode,match.index);
            range.setEnd(walker.currentNode,match.index+match[0].length);
            if(range.getClientRects().length>1) issues.push('Action word splits across lines: '+match[0]);
            const itemRect=items[i].getBoundingClientRect();
            for(const textRect of range.getClientRects()) {
              if(textRect.left<itemRect.left-1 || textRect.right>itemRect.right+1 || textRect.top<itemRect.top-1 || textRect.bottom>itemRect.bottom+1)
                issues.push('Action text overflows its control: '+match[0]);
            }
          }
          for(let j=i+1;j<items.length;j++) {
            const a=items[i].getBoundingClientRect(), b=items[j].getBoundingClientRect();
            if(overlaps(a,b)) issues.push('Actions overlap: '+items[i].textContent.trim()+' / '+items[j].textContent.trim());
            const sameRow=Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>1;
            const sameColumn=Math.min(a.right,b.right)-Math.max(a.left,b.left)>1;
            if (sameRow && Math.max(b.left-a.right,a.left-b.right)<4) issues.push('Action horizontal gap < 4px');
            if (sameColumn && Math.max(b.top-a.bottom,a.top-b.bottom)<4) issues.push('Action vertical gap < 4px');
          }
        }
      }
      for(const form of document.querySelectorAll('main form')) {
        const fields=[...form.querySelectorAll('input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"]),select,textarea')].filter(visible);
        for(let i=0;i<fields.length;i++) for(let j=i+1;j<fields.length;j++) {
          if(overlaps(fields[i].getBoundingClientRect(),fields[j].getBoundingClientRect())) issues.push('Form controls overlap');
        }
      }
      const digest=document.querySelector('#digest-preview');
      const save=document.querySelector('form[action="/digest"] button[type="submit"],form[action="/digest"] button');
      const digestGap=digest && save ? Math.round(digest.getBoundingClientRect().top-save.getBoundingClientRect().bottom) : null;
      if(digest && save) {
        const a=digest.getBoundingClientRect(), b=save.getBoundingClientRect();
        const sameColumn=Math.min(a.right,b.right)-Math.max(a.left,b.left)>1;
        if(sameColumn && digestGap<16) issues.push('Digest heading gap < 16px');
        if(!sameColumn && Math.max(a.left-b.right,b.left-a.right)<16) issues.push('Digest column gap < 16px');
      }
      return {width:innerWidth,scrollWidth:document.documentElement.scrollWidth,
        headerHeight:Math.round(document.querySelector('.site-header').getBoundingClientRect().height),
        digestGap,issues};
    })()""")
    result.update({"path": path, "mode": mode})
    checks.append(result)
    if not args.capture_only:
        assert result["scrollWidth"] <= width + 1, result
        assert not result["issues"], result
        if width < 900:
            assert result["headerHeight"] <= 70, result


def header_greeting_check(path, width, mode):
    layout_check(path, width, mode)
    state = js("""(() => {
      const visible = element => !!element?.getClientRects().length;
      const header = document.querySelector('.site-header');
      const actions = header.querySelector('.header-actions');
      const controls = [...actions.children].filter(visible);
      const bounds = controls.map(element => {
        const target=element.matches('details')?element.querySelector('summary'):element;
        const rect=target.getBoundingClientRect();
        return {className:element.className,left:rect.left,right:rect.right,width:rect.width,height:rect.height};
      });
      const brand=header.querySelector('.brand');
      const greeting=document.querySelector('.db-hello');
      let greetingTextContained=true;
      if(greeting) {
        const heading=greeting.querySelector('h1'), rect=heading.getBoundingClientRect();
        const range=document.createRange(); range.selectNodeContents(heading);
        greetingTextContained=[...range.getClientRects()].every(text=>text.left>=rect.left-1 && text.right<=rect.right+1);
      }
      return {path:location.pathname,width:innerWidth,controls:bounds,
        logoVisible:visible(brand.querySelector('svg')),brandText:brand.textContent.trim(),
        themeVisible:visible(header.querySelector('[data-display-open]')),
        statusVisible:visible(header.querySelector('.connectivity-link')),
        searchVisible:visible(header.querySelector('.header-search')),
        messagesVisible:visible(header.querySelector('.header-messages')),
        profileImageVisible:visible(header.querySelector('.account-menu img')),
        greeting:greeting?.querySelector('h1').textContent.trim().replace(/\\s+/g,' ')||null,
        support:greeting?.querySelector('p:last-child').textContent.trim()||null,
        greetingTextContained};
    })()""")
    state["mode"] = mode
    if width <= 899:
        assert state["logoVisible"] and state["brandText"] == "Nurse.ng", state
        assert not state["themeVisible"] and not state["statusVisible"], state
        assert not state["searchVisible"] and not state["messagesVisible"], state
        assert len(state["controls"]) == 3, state
        assert [control["className"] for control in state["controls"]] == [
            "icon-button notification-bell", "header-popover account-menu", "nav-toggle",
        ], state
        assert all(control["width"] >= 44 and control["height"] >= 44 for control in state["controls"]), state
        assert all(state["controls"][i+1]["left"]-state["controls"][i]["right"] >= 7 for i in range(2)), state
        assert state["profileImageVisible"], state
    else:
        assert state["themeVisible"] and state["statusVisible"], state
        assert state["searchVisible"] and state["messagesVisible"], state
    if state["greeting"]:
        assert state["greeting"] == "Welcome back, Ada.", state
        assert state["support"] == "Here's what's happening in your nursing journey.", state
        assert state["greetingTextContained"], state
    header_checks.append(state)


def open_mobile_theme():
    js("document.querySelector('.nav-toggle').click()")
    assert js("document.querySelector('#mobile-navigation').open"), "Mobile navigation opens"
    assert js("!!document.querySelector('#mobile-navigation [data-display-open]').getClientRects().length"), "Theme control is visible in menu"
    js("document.querySelector('#mobile-navigation [data-display-open]').click()")
    assert js("document.querySelector('#display-preferences').open && !document.querySelector('#mobile-navigation').open"), "Menu closes before display dialog opens"


def escape():
    cdp("Input.dispatchKeyEvent", {"type":"keyDown", "key":"Escape", "code":"Escape", "windowsVirtualKeyCode":27})
    cdp("Input.dispatchKeyEvent", {"type":"keyUp", "key":"Escape", "code":"Escape", "windowsVirtualKeyCode":27})


def click(selector):
    point=js(f"(() => {{ const rect=document.querySelector({json.dumps(selector)}).getBoundingClientRect(); return {{x:rect.left+rect.width/2,y:rect.top+rect.height/2}}; }})()")
    cdp("Input.dispatchMouseEvent", {"type":"mousePressed","button":"left","clickCount":1,**point})
    cdp("Input.dispatchMouseEvent", {"type":"mouseReleased","button":"left","clickCount":1,**point})


def theme_palette():
    return js("""(() => {
      const root=getComputedStyle(document.documentElement), dialog=getComputedStyle(document.querySelector('#display-preferences')), body=getComputedStyle(document.body);
      return {theme:document.documentElement.dataset.theme,contrast:document.documentElement.dataset.contrast,
        surface:root.getPropertyValue('--surface').trim(),foreground:root.getPropertyValue('--fg').trim(),
        rootBackground:root.getPropertyValue('--bg').trim(),
        dialogSurface:dialog.getPropertyValue('--surface').trim(),dialogForegroundToken:dialog.getPropertyValue('--fg').trim(),
        bodySurface:body.getPropertyValue('--surface').trim(),bodyForeground:body.getPropertyValue('--fg').trim(),bodyBackgroundToken:body.getPropertyValue('--bg').trim(),
        rootColourScheme:root.colorScheme,dialogColourScheme:dialog.colorScheme,
        dialogBackground:dialog.backgroundColor,dialogForeground:dialog.color,bodyBackground:body.backgroundColor,
        forcedColours:matchMedia('(forced-colors: active)').matches,
        dialogForcedColorAdjust:dialog.forcedColorAdjust,
        animations:document.getAnimations().map(animation=>({playState:animation.playState,currentTime:animation.currentTime}))};
    })()""")


def run_header_greeting():
    global header_checks
    header_checks = []
    functional_checks = []
    navigate("/settings", "#profile-photo")
    js("document.querySelector('[data-dismiss-install]')?.click()")
    node = cdp("DOM.getDocument")["root"]["nodeId"]
    input_id = cdp("DOM.querySelector", {"nodeId": node, "selector": "#profile-photo"})["nodeId"]
    cdp("DOM.setFileInputFiles", {"nodeId": input_id, "files": [str(picture)]})
    js("document.querySelector('form[action=\"/settings/photo\"]').requestSubmit()")
    wait_for(lambda: js("!!document.querySelector('form[action=\"/settings/photo/remove\"]') && document.readyState === 'complete'"), "photo upload")

    shared_pages = ["/auth/dashboard", "/settings", "/profile", "/notifications", "/messages", "/welcome/discover", "/nurses", "/activities", "/digest", "/jobs", "/learning"]
    cases = [(360,"default",shared_pages)]
    cases += [(width,"default",["/auth/dashboard"]) for width in [320,390,639,640,768,899,900,1440]]
    cases += [(width,"large-high-contrast",["/auth/dashboard","/settings","/notifications"]) for width in [320,390,768,1440]]
    if args.quick:
        cases=[]
        js("localStorage.setItem('nurse-ng-display',JSON.stringify({theme:'light',largeText:true,highContrast:true,reduceMotion:true}))")
    for width, mode, paths in cases:
        print(json.dumps({"stage":"header-greeting-mode","width":width,"mode":mode}), flush=True)
        viewport(width)
        preferences={"theme":"light","largeText":mode=="large-high-contrast","highContrast":mode=="large-high-contrast","reduceMotion":True}
        js(f"localStorage.setItem('nurse-ng-display',{json.dumps(json.dumps(preferences))})")
        for path in paths:
            navigate(path)
            header_greeting_check(path, width, mode)
            if path == "/auth/dashboard" and (width,mode) in [(320,"default"),(360,"default"),(390,"large-high-contrast"),(1440,"default")]:
                screenshot(f"dashboard-{width}-{mode}.png", ".db-top" if width < 900 else None)
            if path == "/settings" and width == 360:
                screenshot("settings-mobile.png")
            if path == "/learning" and width == 360:
                screenshot("learning-mobile.png")

    viewport(360)
    navigate("/auth/dashboard")
    open_mobile_theme()
    click('#display-form input[name="theme"][value="dark"] + span')
    assert js("document.documentElement.dataset.theme==='dark' && JSON.parse(localStorage.getItem('nurse-ng-display')).theme==='dark'"), "Dark theme applies and persists"
    def dark_palette_ready():
        palette=theme_palette()
        return palette if palette["dialogBackground"]=="rgb(16, 27, 37)" and palette["dialogForeground"]=="rgb(255, 255, 255)" and palette["bodyBackground"]=="rgb(8, 14, 20)" else None
    theme_colours=wait_for(dark_palette_ready,"Visible dark theme colours",seconds=5)
    (record/"theme-colours.json").write_text(json.dumps(theme_colours,indent=2)+"\n")
    assert theme_colours["surface"].lower()=="#101b25" and theme_colours["foreground"].lower()=="#fff", theme_colours
    assert theme_colours["dialogBackground"]=="rgb(16, 27, 37)" and theme_colours["dialogForeground"]=="rgb(255, 255, 255)", theme_colours
    assert theme_colours["rootColourScheme"]=="dark" and theme_colours["dialogColourScheme"]=="dark", theme_colours
    screenshot("theme-dialog-mobile.png")
    escape()
    wait_for(lambda: js("!document.querySelector('#display-preferences').open && document.activeElement.matches('.nav-toggle')"), "Theme Escape restores focus to navigation toggle")
    open_mobile_theme()
    click('#display-form input[name="theme"][value="system"] + span')
    cdp("Emulation.setEmulatedMedia", {"features":[{"name":"prefers-color-scheme","value":"dark"}]})
    wait_for(lambda: js("document.documentElement.dataset.theme==='dark'"), "System dark theme")
    cdp("Emulation.setEmulatedMedia", {"features":[{"name":"prefers-color-scheme","value":"light"}]})
    wait_for(lambda: js("document.documentElement.dataset.theme==='light'"), "System light theme")
    click('#display-form input[name="theme"][value="light"] + span')
    wait_for(lambda: theme_palette()["dialogBackground"]=="rgb(255, 255, 255)" and theme_palette()["bodyBackground"]=="rgb(245, 248, 252)","Visible light theme colours",seconds=5)
    js("document.querySelector('#display-preferences [data-display-close]').click()")
    wait_for(lambda: js("document.activeElement.matches('.nav-toggle')"), "Theme close restores focus")
    functional_checks += ["menu theme access", "light/dark/system theme persistence", "theme dialog Escape and focus return"]

    js("document.querySelector('.account-menu summary').click()")
    assert js("document.querySelector('.account-menu').open"), "Profile account menu opens"
    state=js("""(() => {
      const rect=document.querySelector('.account-menu .popover-content').getBoundingClientRect();
      return {left:rect.left,right:rect.right,width:innerWidth,status:document.querySelector('.account-connectivity [data-connectivity]').textContent.trim()};
    })()""")
    assert state["left"] >= 0 and state["right"] <= state["width"]+1 and state["status"], state
    cdp("Network.emulateNetworkConditions", {"offline":True,"latency":0,"downloadThroughput":-1,"uploadThroughput":-1})
    wait_for(lambda: js("document.querySelector('.account-connectivity [data-connectivity]').textContent.startsWith('Offline')"), "Offline status still updates")
    screenshot("account-menu-mobile.png")
    cdp("Network.emulateNetworkConditions", {"offline":False,"latency":0,"downloadThroughput":-1,"uploadThroughput":-1})
    wait_for(lambda: js("document.querySelector('.account-connectivity [data-connectivity]').textContent.startsWith('Online')"), "Online status recovers")
    js("document.querySelector('.account-menu a[href=\"/profile\"]').click()")
    wait_for(lambda: js("location.pathname==='/profile' && document.readyState==='complete'"), "Profile navigation")
    js("document.querySelector('[data-notification-bell]').click()")
    wait_for(lambda: js("location.pathname==='/notifications' && document.readyState==='complete'"), "Notification navigation")
    functional_checks += ["profile image and account navigation", "notification navigation", "online/offline status in account menu"]

    navigate("/auth/dashboard")
    cdp("Network.setBlockedURLs", {"urls":["*/static/js/*"]})
    navigate("/auth/dashboard")
    assert js("document.querySelector('.db-hello h1').textContent.trim().replace(/\\s+/g,' ')==='Welcome back, Ada.'"), "Greeting is correct without application JavaScript"
    functional_checks.append("server-rendered greeting without application JavaScript")
    cdp("Network.setBlockedURLs", {"urls":[]})

    from app.models.user import User
    long_name = "ElizabethChiamakaNwankwoAlexandra"
    with SessionLocal() as db:
        db.get(NurseProfile, profile_id).display_name=long_name
        db.commit()
    viewport(320)
    navigate("/auth/dashboard")
    assert js(f"document.querySelector('.db-hello h1').textContent.trim().replace(/\\s+/g,' ') === {json.dumps('Welcome back, '+long_name+'.')}")
    assert js("document.documentElement.scrollWidth<=innerWidth+1"), "Long dynamic name wraps without horizontal scrolling"
    screenshot("dashboard-long-name-mobile.png", ".db-top")
    with SessionLocal() as db:
        db.get(NurseProfile, profile_id).display_name=""
        db.get(User, member_id).full_name=""
        db.get(User, member_id).community_name=""
        db.commit()
    navigate("/auth/dashboard")
    assert js("document.querySelector('.db-hello h1').textContent.trim()==='Welcome back.'"), "Empty name has no stray punctuation"
    functional_checks += ["dynamic profile name", "long name wrapping", "empty name fallback"]

    js("document.querySelector('.account-menu summary').click();document.querySelector('.account-menu form[action=\"/auth/logout\"]').requestSubmit()")
    wait_for(lambda: js("document.readyState==='complete' && !!document.body && !document.body.classList.contains('is-app')"), "Sign out")
    viewport(360)
    for path in ["/", "/jobs", "/nurses"]:
        navigate(path)
        assert js("!document.querySelector('.site-header [data-display-open]').getClientRects().length && !document.querySelector('.site-header .connectivity-link').getClientRects().length"), (path,"public mobile header simplification")
        assert js("document.documentElement.scrollWidth<=innerWidth+1"), (path,"public horizontal overflow")
        open_mobile_theme()
        js("document.querySelector('#display-preferences [data-display-close]').click()")
        wait_for(lambda: js("document.activeElement.matches('.nav-toggle')"), path+" public menu focus")
    navigate("/auth/login")
    assert js("!!document.querySelector('.site-header [data-display-open]').getClientRects().length"), "Auth header keeps accessible theme control"
    functional_checks += ["public shared-header theme access", "uncrowded auth header theme access"]
    assert not errors, errors
    result={"checks":checks,"headerChecks":header_checks,"functionalChecks":functional_checks,"themeColours":theme_colours,"javascriptErrors":errors}
    (record/"browser.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({"ok":True,"layouts":len(checks),"headerChecks":len(header_checks),"functionalChecks":len(functional_checks),"record":str(record)}),flush=True)


try:
    for name, command_line in [
        ("server", [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"]),
        ("chrome", ["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--disable-extensions", "--disable-sync", "--no-first-run", "--no-default-browser-check", "--password-store=basic", "--disable-background-networking", f"--user-data-dir={artifacts / 'chrome'}", f"--remote-debugging-port={chrome_port}", "about:blank"]),
    ]:
        log = (artifacts / f"{name}.log").open("w")
        logs.append(log)
        processes.append(subprocess.Popen(command_line, cwd=ROOT, env=os.environ.copy(), stdout=log, stderr=log))
    wait_for(lambda: urllib.request.urlopen(base + "/healthz", timeout=1).status == 200, "server")
    tabs = wait_for(lambda: json.load(urllib.request.urlopen(f"http://127.0.0.1:{chrome_port}/json/list", timeout=1)), "Chrome")
    ws = connect(next(tab["webSocketDebuggerUrl"] for tab in tabs if tab["type"] == "page"), legacy=True)
    print(json.dumps({"stage":"browser-ready","temporaryArtifacts":str(artifacts)}), flush=True)
    for method in ["Page.enable", "Runtime.enable", "Network.enable"]:
        cdp(method)
    cdp("Network.setCacheDisabled", {"cacheDisabled": True})
    viewport(360)
    navigate("/auth/login", "#phone")
    js(f"document.querySelector('#phone').value={json.dumps(phone)};document.querySelector('#password').value={json.dumps(password)};document.querySelector('form[action=\"/auth/login\"]').requestSubmit()")
    wait_for(lambda: js("location.pathname === '/' && document.readyState === 'complete'"), "sign in")
    if args.header_greeting:
        run_header_greeting()
        raise SystemExit(0)
    navigate("/settings", "#profile-photo")
    js("document.querySelector('[data-dismiss-install]')?.click()")
    layout_check("/settings", 360, "default-no-photo")
    screenshot("settings-no-photo-mobile.png", "#photo-heading")
    node = cdp("DOM.getDocument")["root"]["nodeId"]
    input_id = cdp("DOM.querySelector", {"nodeId": node, "selector": "#profile-photo"})["nodeId"]
    cdp("DOM.setFileInputFiles", {"nodeId": input_id, "files": [str(picture)]})
    wait_for(lambda: js("!document.querySelector('[data-photo-preview-card]').hidden"), "photo preview")
    layout_check("/settings", 360, "default-photo-preview")
    screenshot("photo-preview-mobile.png", ".photo-preview-card")
    js("document.querySelector('form[action=\"/settings/photo\"]').requestSubmit()")
    wait_for(lambda: js("document.querySelector('form[action=\"/settings/photo/remove\"]') && document.readyState === 'complete'"), "photo upload")
    paths = ["/settings", "/auth/dashboard", "/welcome/discover", "/nurses", "/notifications", "/activities", "/digest"]
    modes = [(320,"default"),(360,"default"),(390,"default"),(360,"large-high-contrast"),(390,"large-high-contrast"),(1440,"default"),(1440,"large-high-contrast"),(390,"dark")]
    if args.quick:
        modes = [(320,"large-high-contrast"),(360,"default"),(360,"large-high-contrast"),(1440,"default")]
    for width, mode in modes:
        print(json.dumps({"stage":"layout-mode","width":width,"mode":mode}), flush=True)
        viewport(width)
        preferences = {"theme": "dark" if mode == "dark" else "light", "largeText": mode == "large-high-contrast", "highContrast": mode == "large-high-contrast", "reduceMotion": True}
        js(f"localStorage.setItem('nurse-ng-display',{json.dumps(json.dumps(preferences))})")
        for path in paths:
            navigate(path)
            layout_check(path, width, mode)
            if width == 360 and mode == "large-high-contrast":
                label = path.rstrip('/').split('/')[-1]
                screenshot(f"{label}-mobile.png", ".db-top" if path == "/auth/dashboard" else ".community-session-actions" if path == "/activities" else None)
                if path == "/settings":
                    screenshot("profile-photo-mobile.png", "#photo-heading")
                elif path == "/digest":
                    screenshot("digest-highlights-mobile.png", "#digest-preview")
                elif path == "/nurses":
                    screenshot("colleague-card-mobile.png", ".people-grid")
                elif path == "/auth/dashboard":
                    screenshot("dashboard-stats-mobile.png", ".db-stats")
                elif path == "/activities":
                    screenshot("activities-navigation-mobile.png", ".community-view-nav")
            if width == 360 and mode == "default":
                screenshot(f"{path.split('/')[-1]}-default-mobile.png", ".db-top" if path == "/auth/dashboard" else None)
            if width == 1440 and mode == "default" and path in {"/auth/dashboard", "/settings", "/activities"}:
                screenshot(f"{path.split('/')[-1]}-desktop.png")
        if width < 900:
            js("document.querySelector('.nav-toggle').click()")
            assert js("document.querySelector('#mobile-navigation').open && document.querySelector('.nav-toggle').getAttribute('aria-expanded')==='true'"), (width, mode)
            assert js("document.documentElement.scrollWidth<=innerWidth+1"), (width, mode, "navigation overflow")
            js("document.querySelector('[data-navigation-close]').click()")
            assert js("!document.querySelector('#mobile-navigation').open"), (width, mode)
            if width <= 639:
                js("document.querySelector('.account-menu summary').click()")
                account_state = js("""(() => {
                  const menu=document.querySelector('.account-menu');
                  const content=menu.querySelector('.popover-content').getBoundingClientRect();
                  const connectivity=menu.querySelector('.account-connectivity');
                  return {open:menu.open,left:content.left,right:content.right,
                    connectivityVisible:!!connectivity.getClientRects().length,
                    connectivityText:connectivity.textContent.trim(),width:innerWidth};
                })()""")
                if not (account_state["open"] and account_state["left"] >= 0 and account_state["right"] <= width + 1 and account_state["connectivityVisible"] and account_state["connectivityText"]):
                    screenshot(f"account-menu-failure-{width}-{mode}.png")
                    raise AssertionError((width, mode, "account and connectivity menu", account_state))
                if width == 360 and mode == "large-high-contrast":
                    screenshot("account-menu-mobile.png")
                js("document.querySelector('.account-menu summary').click()")
    viewport(360)
    navigate("/nurses", "#people-query")
    js("document.querySelector('#people-query').value='Elizabeth';document.querySelector('.directory-search').requestSubmit()")
    wait_for(lambda: js("location.search.includes('Elizabeth') && document.readyState==='complete'"), "directory search")
    assert js("document.querySelector('.people-grid').textContent.includes('Elizabeth')"), "Search must keep returning public colleagues"
    navigate("/notifications?unread=true")
    assert js("document.querySelector('.notice-filters [aria-current=\"page\"]').textContent.trim()==='Unread'"), "Unread filter state"
    navigate("/digest")
    js("document.querySelector('select[name=\"weekday\"]').value='2';document.querySelector('form[action=\"/digest\"]').requestSubmit()")
    wait_for(lambda: js("document.querySelector('#feedback-title')?.textContent==='Digest preferences saved'"), "digest saved")
    assert js("document.querySelector('select[name=\"weekday\"]').value==='2'"), "Digest preferences must persist"
    navigate("/settings")
    js("document.querySelector('main [data-display-open]').click()")
    assert js("document.querySelector('#display-preferences').open"), "Display settings button"
    js("document.querySelector('#display-preferences [data-display-close]').click()")
    assert not errors, errors
    result = {"checks": checks, "javascriptErrors": errors, "functionalChecks": ["photo upload", "colleague search", "unread filter", "digest save", "display settings", "mobile navigation"], "temporaryArtifacts": str(artifacts)}
    (record / "browser.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"ok": True, "layouts": len(checks), "record": str(record), "temporaryArtifacts": str(artifacts)}))
finally:
    if ws:
        ws.close()
    for process in processes:
        process.terminate()
    for process in processes:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
    for log in logs:
        log.close()
