"""Package the neutral web workspace with its assets, never account data.

Uses the application's installed Python dependencies. No server, database request
or authenticated page is involved. The native hosts load this trusted document
at the configured site's origin so its existing IndexedDB workspace is retained.
"""

import base64
import html
import mimetypes
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from app.web.offline_routes import shell  # noqa: E402

STATIC = ROOT / "app/static"


def asset(url, parent=STATIC):
    parsed = urlsplit(url)
    if parsed.scheme or parsed.netloc:
        raise ValueError(f"Offline bundle cannot depend on an external asset: {url}")
    name = unquote(parsed.path)
    path = (STATIC / name[8:] if name.startswith("/static/") else parent / name).resolve()
    if not path.is_relative_to(STATIC):
        raise ValueError("Offline asset must remain inside app/static")
    return path


def data_url(path):
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def stylesheet(path):
    def replace(match):
        url = match[1].strip("\"' ")
        if url.startswith("data:"):
            return match[0]
        resource = asset(url, path.parent)
        # Shared CSS still names some retired landing-page backgrounds. They
        # are not part of the offline workspace and must not cause network IO.
        if not resource.exists() and resource.suffix in {".jpg", ".webp", ".png"}:
            return "none"
        return 'url("' + data_url(resource) + '")'

    return re.sub(r"url\(([^)]+)\)", replace, path.read_text()).replace("</style", "<\\/style")


class Bundle(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.output = []
        self.scripts = []
        self.skip_script_end = False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "script" and values.get("src"):
            script = asset(values["src"]).read_text().replace("</script", "<\\/script")
            self.scripts.append("<script>\n" + script + "\n</script>")
            self.skip_script_end = True
        elif tag == "link":
            if values.get("rel") == "stylesheet":
                self.output.append("<style>" + stylesheet(asset(values["href"])) + "</style>")
            elif values.get("rel") == "icon":
                self.output.append(
                    '<link rel="icon" href="' + data_url(asset(values["href"])) + '">'
                )
            # A bundled document has no dependency on the web manifest.
        elif tag == "body":
            self.output.append(self.get_starttag_text())
            self.output.append("<script>window.NurseNativeOffline = true;</script>")
        elif tag == "img" and values.get("src"):
            values["src"] = data_url(asset(values["src"]))
            self.output.append("<img " + " ".join(
                key + '="' + html.escape(value or "", quote=True) + '"'
                for key, value in values.items()
            ) + ">")
        else:
            self.output.append(self.get_starttag_text())

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == "script" and self.skip_script_end:
            self.skip_script_end = False
            return
        if tag == "body":
            # Preserve deferred ordering and run after the workspace DOM exists.
            self.output.extend(self.scripts)
        self.output.append(f"</{tag}>")

    def handle_data(self, data):
        self.output.append(data)

    def handle_entityref(self, name):
        self.output.append(f"&{name};")

    def handle_charref(self, name):
        self.output.append(f"&#{name};")

    def handle_decl(self, decl):
        self.output.append(f"<!{decl}>")


def build():
    app = FastAPI()
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    request = Request({
        "type": "http", "method": "GET", "scheme": "https", "path": "/offline-shell",
        "root_path": "", "query_string": b"", "headers": [],
        "server": ("bundle.invalid", 443), "router": app.router,
    })
    document = shell(request).body.decode().replace("https://bundle.invalid/static/", "/static/")
    document = document.replace("this browser", "this device")
    parser = Bundle()
    parser.feed(document)
    parser.close()
    return "".join(parser.output)


if __name__ == "__main__":
    destination = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "mobile/www/offline.html"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(build())
