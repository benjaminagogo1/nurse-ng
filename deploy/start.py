"""Portable production web/worker entry point, with a configuration-only check."""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def command_for(settings, role, port):
    if settings.environment != "production":
        raise ValueError("Hosted startup requires NURSE_NG_ENVIRONMENT=production.")
    if not settings.required_workers:
        raise ValueError(
            "Set NURSE_NG_REQUIRED_WORKERS so hosted readiness checks the background roles."
        )
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=["web", "workers"])
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
    os.execv(sys.executable, command)


if __name__ == "__main__":
    raise SystemExit(main())
