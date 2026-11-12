"""Worker readiness, recovery from transient errors, crashes and stale progress."""

import os
import signal
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.base import Base
from app.models.workers import WorkerHeartbeat
from app.services import worker_runtime as runtime
from app.services.worker_health import healthy, report, snapshot


@pytest.mark.parametrize("state", ["missing", "stale", "stopped", "error", "idle", "working"])
def test_readiness_requires_recent_progress_from_configured_workers(
    client, db_session, monkeypatch, state,
):
    monkeypatch.setattr(settings, "required_workers", "recruitment")
    now = datetime.now(UTC)
    if state != "missing":
        report(db_session, "recruitment", "a" * 32, "idle" if state == "stale" else state,
               started_at=now, at=now - timedelta(minutes=2) if state == "stale" else now)
    response = client.get('/readyz')
    assert response.status_code == (200 if state in {"idle", "working"} else 503)
    assert response.headers['cache-control'] == 'no-store'
    assert 'pid' not in response.text and 'recruitment' not in response.text
    assert client.get('/healthz').status_code == 200


def test_database_failure_is_unready_without_leaking_connection_details(client, monkeypatch):
    from app.services import worker_health

    def unavailable(db):
        raise OperationalError('SELECT', {}, Exception('private-database-secret'))

    monkeypatch.setattr(worker_health, 'readiness', unavailable)
    response = client.get('/readyz')
    assert response.status_code == 503
    assert response.json() == {'status': 'unavailable'}
    assert 'secret' not in response.text


def test_stopped_once_worker_does_not_hide_a_healthy_continuous_worker(db_session):
    now = datetime.now(UTC)
    report(db_session, 'recruitment', 'a' * 32, 'idle', started_at=now)
    report(db_session, 'recruitment', 'b' * 32, 'stopped', started_at=now)
    assert snapshot(db_session, ['recruitment'])[0]['healthy']


def test_worker_recovers_from_transient_failure_and_redacts_error(db_session, monkeypatch, capsys):
    stop = threading.Event()
    calls = []
    monkeypatch.setattr(runtime, 'SessionLocal', sessionmaker(bind=db_session.get_bind()))
    monkeypatch.setattr(runtime, '_startup', lambda *_: None)
    monkeypatch.setattr(stop, 'wait', lambda seconds: False)

    def step(name, db):
        calls.append(name)
        if len(calls) == 1:
            raise RuntimeError('secret-token-must-not-appear')
        stop.set()

    monkeypatch.setattr(runtime, '_step', step)
    assert runtime.run_worker('recruitment', stop=stop) == 0
    assert calls == ['recruitment', 'recruitment']
    assert 'secret-token' not in capsys.readouterr().out
    assert db_session.scalar(select(WorkerHeartbeat)).state == 'stopped'


def test_supervisor_restarts_worker_with_stale_progress(db_session, monkeypatch):
    from types import SimpleNamespace

    now = datetime.now(UTC)
    report(db_session, 'recruitment', 'c' * 32, 'working', started_at=now,
           at=now - timedelta(minutes=3))
    stopped = []
    spawned = []
    monkeypatch.setattr(runtime, 'stop_process', lambda process: stopped.append(process))
    clock = [100.0]
    supervisor = runtime.Supervisor(['recruitment'],
        popen=lambda *args, **kwargs: spawned.append(args) or SimpleNamespace(poll=lambda: None),
        clock=lambda: clock[0])
    child = supervisor.children[0]
    child.instance, child.started = 'c' * 32, 1
    child.process = SimpleNamespace(poll=lambda: None)
    supervisor.tick(db_session)
    assert len(stopped) == 1 and spawned == []
    clock[0] += 3
    supervisor.tick(db_session)
    assert len(spawned) == 1 and child.instance != 'c' * 32


def test_real_supervisor_recovers_a_killed_idle_worker(tmp_path):
    """No schedules, external requests, SMTP or live database are involved."""
    url = f"sqlite:///{tmp_path / 'worker.db'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    env = {**os.environ, 'NURSE_NG_DATABASE_URL': url, 'NURSE_NG_ACCOUNT_MAIL_BACKEND': 'disabled',
           'NURSE_NG_REQUIRED_WORKERS': 'recruitment'}
    log = (tmp_path / 'supervisor.log').open('w')
    process = subprocess.Popen(
        [sys.executable, '-m', 'app.cli', 'workers', '--roles', 'recruitment'],
        env=env, stdout=log, stderr=log, start_new_session=True,
    )
    children = set()

    def wait_for_worker(excluded_pid=None):
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            assert process.poll() is None, (tmp_path / 'supervisor.log').read_text()
            with Session(engine) as db:
                for row in db.scalars(select(WorkerHeartbeat)):
                    children.add(row.pid)
                    if row.pid != excluded_pid and healthy(row):
                        return row.pid
            time.sleep(0.1)
        pytest.fail('Supervisor did not start a healthy worker: ' +
                    (tmp_path / 'supervisor.log').read_text())

    try:
        first = wait_for_worker()
        os.kill(first, signal.SIGKILL)
        replacement = wait_for_worker(excluded_pid=first)
        assert replacement != first
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        for pid in children:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        log.close()
        engine.dispose()
