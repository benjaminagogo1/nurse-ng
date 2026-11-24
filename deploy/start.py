"""Production web/worker entry point, including a single-service hosting option.

This process launcher validates configuration, then execs web or supervised
workers. Separate web/workers roles need a prior migration step. The single-host
all role applies migrations before launching both process groups. --check
validates startup arguments without migrating or starting services.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def command_for(settings, role, port):
    if settings.environment != "production":
        raise ValueError("Hosted startup requires NURSE_NG_ENVIRONMENT=production.")
    if not settings.required_workers:
        raise ValueError(
            "Set NURSE_NG_REQUIRED_WORKERS so hosted readiness checks the background roles."
        )
    if role == "all":
        return {
            "web": command_for(settings, "web", port),
            "workers": command_for(settings, "workers", port),
        }
    if role == "workers":
        return [sys.executable, "-m", "app.cli", "workers"]
    try:
        port = int(port)
        if not 1 <= port <= 65535:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError("PORT must be an integer between 1 and 65535.") from None
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        str(port),
        "--workers",
        "1",
    ]
    if settings.trusted_proxy_ips:
        command += ["--proxy-headers", "--forwarded-allow-ips", settings.trusted_proxy_ips]
    else:
        command += ["--no-proxy-headers"]
    return command


def run_together(commands):
    """Exit if either service stops, and forward shutdown to both process groups."""
    stop = threading.Event()
    previous = {
        number: signal.signal(number, lambda *_: stop.set())
        for number in (signal.SIGINT, signal.SIGTERM)
    }
    processes = {}
    try:
        for name, command in commands.items():
            processes[name] = subprocess.Popen(command, start_new_session=True)
        while not stop.wait(0.5):
            for name, process in processes.items():
                code = process.poll()
                if code is not None:
                    print(f"{name} process stopped ({code}); stopping hosted service.", flush=True)
                    return code if code and code > 0 else 1
        return 0
    finally:
        # Send both signals before waiting so web and workers stop concurrently.
        for process in processes.values():
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 25
        for process in processes.values():
            try:
                process.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
        for number, handler in previous.items():
            signal.signal(number, handler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=["web", "workers", "all"])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    try:
        if os.environ.get("NURSE_NG_ENVIRONMENT") != "production":
            raise ValueError("Hosted startup requires NURSE_NG_ENVIRONMENT=production.")
        from app.core.config import settings

        command = command_for(settings, args.role, os.environ.get("PORT", "8000"))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.check:
        print(
            json.dumps(
                {
                    "public_site": settings.public_base_url,
                    "required_workers": settings.required_workers,
                    "command": command,
                }
            )
        )
        return 0
    os.umask(0o077)
    if args.role == "all":
        print("Applying database migrations before starting web and workers.", flush=True)
        migration = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"], check=False,
        )
        if migration.returncode:
            return migration.returncode if migration.returncode > 0 else 1
        return run_together(command)
    os.execv(sys.executable, command)


if __name__ == "__main__":
    raise SystemExit(main())
