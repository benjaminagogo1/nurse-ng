"""Private hosted search starts before workers, stays private and preserves operator choices."""

import hashlib
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
import yaml
from sqlalchemy import select

from app.core.config import settings
from app.models.recruitment import DiscoverySchedule
from app.services import recruitment
from app.services.worker_runtime import _startup
from deploy import search
from deploy.start import run_together


def installed(root):
    base, source = search.paths(root)
    for path in (base / "venv" / "bin" / "granian", base / "settings.yml",
                 source / "searx" / "webapp.py"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")
    (base / "runtime-cache").mkdir()
    return base, source


def test_missing_installation_and_external_providers_are_explicit(tmp_path):
    assert search.configured_service(tmp_path, {}) is None
    with pytest.raises(ValueError, match="render-build.sh"):
        search.configured_service(tmp_path, {"NURSE_NG_BUNDLED_SEARCH": "required"})
    with pytest.raises(ValueError, match="auto, off or required"):
        search.configured_service(tmp_path, {"NURSE_NG_BUNDLED_SEARCH": "invalid"})
    installed(tmp_path)
    assert search.configured_service(tmp_path, {"NURSE_NG_BUNDLED_SEARCH": "off"}) is None
    for configuration in (
        {"NURSE_NG_RECRUITMENT_SEARXNG_URLS": "https://private-search.example"},
        {"NURSE_NG_RECRUITMENT_SEARCH_KEY": "fixture-key",
         "NURSE_NG_RECRUITMENT_SEARCH_PERMISSION_REFERENCE": "https://example.org/terms"},
    ):
        assert search.configured_service(tmp_path, configuration) is None


def test_search_binds_localhost_and_does_not_inherit_application_secrets(tmp_path):
    base, source = installed(tmp_path)
    environment = {"NURSE_NG_DATABASE_URL": "private-database-credential",
                   "NURSE_NG_SECRET_KEY": "private-signing-key", "PATH": os.environ["PATH"]}
    service = search.configured_service(tmp_path, environment)
    assert service.url == "http://127.0.0.1:8888"
    assert service.command[service.command.index("--host") + 1] == "127.0.0.1"
    assert service.command[service.command.index("--workers") + 1] == "1"
    assert service.directory == source
    assert service.environment["SEARXNG_SETTINGS_PATH"] == str(base / "settings.yml")
    assert service.environment["TMPDIR"] == str(base / "runtime-cache")
    assert not any(key.startswith("NURSE_NG_") for key in service.environment)
    assert "NURSE_NG_RECRUITMENT_SEARXNG_URLS" not in environment


@pytest.mark.parametrize("port", ["0", "65536", "invalid", "8000"])
def test_invalid_or_conflicting_search_ports_fail_before_start(tmp_path, port):
    installed(tmp_path)
    with pytest.raises(ValueError, match="port distinct"):
        search.configured_service(tmp_path, {"NURSE_NG_BUNDLED_SEARCH_PORT": port})


def test_build_rejects_modified_archive_before_extraction(tmp_path):
    archive = tmp_path / "source.tar.gz"
    archive.write_bytes(b"a modified upstream archive")
    with pytest.raises(ValueError, match="pinned checksum"):
        search.verify_archive(archive)
    archive.write_bytes(b"fixture source")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(search, "ARCHIVE_SHA256", hashlib.sha256(b"fixture source").hexdigest())
        search.verify_archive(archive)


def test_search_template_explicitly_enables_maintained_engines():
    template = yaml.safe_load((search.ROOT / "deploy/searxng/settings.yml").read_text())
    expected = set(template["use_default_settings"]["engines"]["keep_only"])
    enabled = {engine["name"] for engine in template["engines"] if not engine["disabled"]}
    assert enabled == expected
    assert "json" in template["search"]["formats"]
    assert not template["server"]["public_instance"]


def test_health_wait_uses_local_service_without_querying_engines(monkeypatch):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("http_proxy", "http://unreachable.invalid:1234")
    try:
        search.wait_until_ready(
            SimpleNamespace(url=f"http://127.0.0.1:{server.server_port}"),
            SimpleNamespace(poll=lambda: None), threading.Event(), timeout=2,
        )
        assert requests == ["/healthz"]
        with pytest.raises(RuntimeError, match="stopped"):
            search.wait_until_ready(SimpleNamespace(url="unused"),
                                    SimpleNamespace(poll=lambda: 1), threading.Event())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_search_failure_stops_all_started_processes(tmp_path, monkeypatch):
    processes = []
    original = subprocess.Popen

    def spawn(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", spawn)
    service = search.SearchService(
        command=[sys.executable, "-c", "raise SystemExit(2)"], directory=tmp_path,
        environment=dict(os.environ), url="http://127.0.0.1:1",
    )
    with pytest.raises(RuntimeError, match="stopped"):
        run_together({"web": [sys.executable, "-c", "import time; time.sleep(30)"]}, service)
    assert len(processes) == 1
    assert all(process.poll() is not None for process in processes)


def test_worker_initializes_all_searches_and_preserves_paused_schedules(db_session, monkeypatch):
    monkeypatch.setattr(settings, "recruitment_searxng_urls", "http://127.0.0.1:8888")
    recruitment.ensure_search_schedule(db_session)
    existing = db_session.scalar(select(DiscoverySchedule))
    existing.enabled, existing.next_page = False, 17
    db_session.commit()
    _startup("recruitment", db_session)
    first = list(db_session.scalars(select(DiscoverySchedule)))
    assert len(first) == 6
    assert not existing.enabled and existing.next_page == 17
    _startup("recruitment", db_session)
    assert len(list(db_session.scalars(select(DiscoverySchedule)))) == 6
    assert not existing.enabled and existing.next_page == 17


def test_worker_does_not_queue_searches_without_a_provider(db_session, monkeypatch):
    monkeypatch.setattr(settings, "recruitment_searxng_urls", "")
    monkeypatch.setattr(settings, "recruitment_search_key", "")
    _startup("recruitment", db_session)
    assert db_session.scalar(select(DiscoverySchedule)) is None
