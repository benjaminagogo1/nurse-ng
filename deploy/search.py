"""Build and supervise a private, isolated SearXNG service for hosted discovery.

Installation runs during the build. Runtime reads the prepared files, binds only
localhost, and keeps search credentials/configuration separate from the app.
"""

import argparse
import hashlib
import os
import secrets
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVISION = "3a3dd15bfafcb645a1b45c2c6c0798a8f786aaaf"
ARCHIVE_SHA256 = "1a10d9278f9b75aafab368f9f03ebc9bec653390b28091d60f961f325acb52ed"
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024


@dataclass(frozen=True)
class SearchService:
    command: list[str]
    directory: Path
    environment: dict[str, str]
    url: str


def paths(root=ROOT):
    base = Path(root) / ".local-tools" / "searxng"
    return base, base / f"searxng-{REVISION}"


def verify_archive(archive):
    """Reject unpinned source before any extraction or installation."""
    with Path(archive).open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != ARCHIVE_SHA256:
        raise ValueError("Search source archive did not match the pinned checksum.")


def download_archive(destination):
    """Fetch a bounded archive atomically; interrupted builds cannot retain a partial file."""
    temporary = destination.with_suffix(".download")
    try:
        request = urllib.request.Request(
            f"https://github.com/searxng/searxng/archive/{REVISION}.tar.gz",
            headers={"User-Agent": "NurseNgSearchBuild/1.0"},
        )
        with urllib.request.urlopen(request, timeout=90) as response, temporary.open("wb") as out:
            size = 0
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_ARCHIVE_BYTES:
                    raise ValueError("Search source archive exceeded the build size limit.")
                out.write(chunk)
        verify_archive(temporary)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def install(root=ROOT):
    """Prepare pinned source, separate dependencies and private settings during the build."""
    base, source = paths(root)
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    base.chmod(0o700)
    cache = base / "runtime-cache"
    cache.mkdir(exist_ok=True, mode=0o700)
    cache.chmod(0o700)
    archive = base / "source.tar.gz"
    if not source.is_dir():
        print("Preparing pinned private search source.", flush=True)
        if not archive.exists():
            download_archive(archive)
        verify_archive(archive)
        with tarfile.open(archive) as package:
            if any(Path(member.name).parts[0] != source.name for member in package.getmembers()):
                raise ValueError("Search archive contains an unexpected source directory.")
            package.extractall(base, filter="data")
    if not (source / "searx" / "webapp.py").is_file():
        raise ValueError("The pinned search source is incomplete.")
    python = base / "venv" / "bin" / "python"
    if not python.is_file():
        subprocess.run([sys.executable, "-m", "venv", str(base / "venv")], check=True)
    subprocess.run(
        [str(python), "-m", "pip", "install", "--no-cache-dir", "--disable-pip-version-check",
         "-r", str(source / "requirements.txt"), "-r", str(source / "requirements-server.txt")],
        check=True,
    )
    settings = base / "settings.yml"
    if not settings.exists():
        template = (ROOT / "deploy" / "searxng" / "settings.yml").read_text()
        settings.write_text(template.replace(
            "server:\n", "server:\n  secret_key: " + secrets.token_hex(32) + "\n", 1,
        ))
    settings.chmod(0o600)
    print("Private search installed in its own environment; startup downloads nothing.", flush=True)


def configured_service(root=ROOT, environ=None):
    """Use bundled search when installed and no external search provider is configured."""
    environ = dict(os.environ if environ is None else environ)
    mode = environ.get("NURSE_NG_BUNDLED_SEARCH", "auto").strip().lower()
    if mode not in {"auto", "off", "required"}:
        raise ValueError("NURSE_NG_BUNDLED_SEARCH must be auto, off or required.")
    external = environ.get("NURSE_NG_RECRUITMENT_SEARXNG_URLS", "").strip() or (
        environ.get("NURSE_NG_RECRUITMENT_SEARCH_KEY", "").strip()
        and environ.get("NURSE_NG_RECRUITMENT_SEARCH_PERMISSION_REFERENCE", "").strip()
    )
    if mode == "off" or external:
        return None
    base, source = paths(root)
    executable = base / "venv" / "bin" / "granian"
    installed = (base / "runtime-cache").is_dir() and all(path.is_file() for path in (
        executable, base / "settings.yml", source / "searx" / "webapp.py",
    ))
    if not installed:
        if mode == "required":
            raise ValueError("Private search is missing. Use bash deploy/render-build.sh to build.")
        return None
    try:
        port = int(environ.get("NURSE_NG_BUNDLED_SEARCH_PORT", "8888"))
        if not 1 <= port <= 65535 or port == int(environ.get("PORT", "8000")):
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError("Bundled search needs a valid port distinct from the web PORT.") from None
    search_environment = {key: value for key, value in environ.items()
                          if not key.startswith("NURSE_NG_")}
    search_environment.update({
        "SEARXNG_SETTINGS_PATH": str(base / "settings.yml"),
        "TMPDIR": str(base / "runtime-cache"),
        "PYTHONPATH": str(source), "PYTHONUNBUFFERED": "1",
    })
    return SearchService(
        command=[str(executable), "--interface", "wsgi", "--host", "127.0.0.1",
                 "--port", str(port), "--workers", "1", "--blocking-threads", "4",
                 "searx.webapp:app"],
        directory=source, environment=search_environment, url=f"http://127.0.0.1:{port}",
    )


def wait_until_ready(service, process, stop, timeout=30):
    """Wait for local health before starting workers; do not query upstream engines."""
    deadline = time.monotonic() + timeout
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while not stop.is_set() and time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Private search stopped before it became ready.")
        try:
            with opener.open(service.url + "/healthz", timeout=1) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError):
            pass
        stop.wait(0.25)
    if not stop.is_set():
        raise RuntimeError("Private search did not become ready before the startup deadline.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install"])
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        install(args.root.resolve())
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"Private search build failed ({type(exc).__name__}).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
