"""Check migration ordering and real child-process cleanup for one-service hosting."""

import json
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import settings
from deploy import search, start

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("migration_code", [0, 7])
@pytest.mark.parametrize("bundled_search", [False, True])
def test_all_startup_migrates_before_launch(monkeypatch, migration_code, bundled_search):
    monkeypatch.setenv("NURSE_NG_ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "required_workers", "recruitment,reels,notifications")
    monkeypatch.setenv("NURSE_NG_RECRUITMENT_SEARXNG_URLS", "")
    service = SimpleNamespace(url="http://127.0.0.1:18888") if bundled_search else None
    monkeypatch.setattr(search, "configured_service", lambda: service)
    monkeypatch.setattr(sys, "argv", ["deploy/start.py", "all"])
    # main changes cwd, sys.path and umask for the hosted process. Isolate those
    # process-global mutations when checking it in the test runner.
    monkeypatch.setattr(start.os, "chdir", lambda _: None)
    monkeypatch.setattr(start.os, "umask", lambda _: None)
    monkeypatch.setattr(sys, "path", list(sys.path))
    steps = []

    def migrate(command, *, check):
        assert command == [sys.executable, "-m", "alembic", "upgrade", "head"]
        steps.append("migration")
        return subprocess.CompletedProcess(command, migration_code)

    def launch(commands, search_service, worker_roles):
        steps.append("launch")
        web = commands["web"]
        assert web[web.index("--workers") + 1] == "1"
        assert commands["workers"][-2:] == ["app.cli", "workers"]
        assert search_service is service
        assert worker_roles == "recruitment,reels,notifications"
        return 0

    monkeypatch.setattr(start.subprocess, "run", migrate)
    monkeypatch.setattr(start, "run_together", launch)
    assert start.main() == migration_code
    assert steps == (["migration", "launch"] if migration_code == 0 else ["migration"])


def wait_for_files(files, launcher):
    deadline = time.monotonic() + 10
    while not all(path.is_file() for path in files):
        assert launcher.poll() is None, launcher.communicate(timeout=5)
        if time.monotonic() >= deadline:
            pytest.fail("Hosted child processes did not report startup")
        time.sleep(0.02)


@pytest.mark.parametrize("shutdown", ["signal", "web_failure", "workers_exit"])
def test_hosted_group_stops_on_signal_or_either_child_exit(tmp_path, shutdown):
    child = tmp_path / "child.py"
    child.write_text("""import signal
import sys
import time
from pathlib import Path
name, directory = sys.argv[1:]
root = Path(directory)
def stop(*_):
    (root / (name + '.stopped')).touch()
    raise SystemExit(0)
signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
(root / (name + '.started')).touch()
while True:
    exit_file = root / (name + '.exit')
    if exit_file.exists():
        raise SystemExit(int(exit_file.read_text()))
    time.sleep(0.02)
""")
    commands = {
        name: [sys.executable, str(child), name, str(tmp_path)]
        for name in ("web", "workers")
    }
    launcher = subprocess.Popen(
        [
            sys.executable, "-c",
            "import json, sys; from deploy.start import run_together; "
            "raise SystemExit(run_together(json.loads(sys.argv[1])))",
            json.dumps(commands),
        ], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        wait_for_files([tmp_path / "web.started", tmp_path / "workers.started"], launcher)
        if shutdown == "signal":
            launcher.send_signal(signal.SIGTERM)
            expected_code, stopped = 0, ("web", "workers")
        elif shutdown == "web_failure":
            (tmp_path / "web.exit").write_text("7")
            expected_code, stopped = 7, ("workers",)
        else:
            (tmp_path / "workers.exit").write_text("0")
            expected_code, stopped = 1, ("web",)
        output, errors = launcher.communicate(timeout=10)
        assert launcher.returncode == expected_code, output + errors
        assert all((tmp_path / f"{name}.stopped").is_file() for name in stopped)
    finally:
        if launcher.poll() is None:
            launcher.terminate()
            launcher.communicate(timeout=10)
