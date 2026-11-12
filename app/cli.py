"""Small operator commands.

Usage::

    python -m app.cli set-staff +2348012345678
    python -m app.cli unset-staff +2348012345678
    python -m app.cli cleanup-community-media --dry-run
    python -m app.cli check-config

Staff accounts can open the document-review queue. There is deliberately no
web route for granting the flag: it is an operator action, recorded in the
access audit when the reviewer opens evidence (DECISIONS L49).
"""

import argparse
import json
import sys
from collections.abc import Sequence

from sqlalchemy import select

from app.core.config import settings
from app.core.validators import normalize_phone
from app.db.session import SessionLocal
from app.models.user import User
from app.services.community import reconcile_community_media


def _set_staff(phone: str, *, enabled: bool) -> int:
    normalised = normalize_phone(phone)
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.phone == normalised))
        if user is None:
            print(f"No account found for {normalised}.", file=sys.stderr)
            return 1

        user.is_staff = enabled
        db.commit()

    state = "staff" if enabled else "not staff"
    print(f"{normalised} is now {state}.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "check-config", help="Validate startup settings without displaying secrets."
    )
    subparsers.add_parser("cleanup-account-files", help="Retry queued account file removals.")

    for name in ("set-staff", "unset-staff"):
        command = subparsers.add_parser(name)
        command.add_argument("phone", help="Phone number in international format.")

    cleanup = subparsers.add_parser("cleanup-community-media")
    cleanup.add_argument(
        "--dry-run",
        action="store_true",
        help="Report orphan files and quota drift without changing them.",
    )

    subparsers.add_parser(
        "recruitment-init", help="Set up Nigerian-first schedules and pending starter sources."
    )
    worker = subparsers.add_parser("recruitment-worker", help="Run the source-discovery queue.")
    worker.add_argument("--once", action="store_true", help="Process ready tasks, then exit.")
    worker.add_argument("--max-tasks", type=int, default=10, help="Task limit for --once (1–100).")

    reels = subparsers.add_parser("reels-worker", help="Process queued Reels videos.")
    reels.add_argument("--once", action="store_true", help="Drain ready work, then exit.")
    reels.add_argument("--max-tasks", type=int, default=10)

    notices = subparsers.add_parser(
        "notification-worker", help="Deliver opted-in notification emails."
    )
    notices.add_argument("--once", action="store_true", help="Drain ready emails, then exit.")
    notices.add_argument("--max-tasks", type=int, default=20)

    supervised = subparsers.add_parser("workers", help="Supervise and restart background workers.")
    supervised.add_argument("--roles", default=settings.required_workers or "recruitment,reels")
    health = subparsers.add_parser("worker-status", help="Check database and worker progress.")
    health.add_argument("--json", action="store_true")
    quality = subparsers.add_parser(
        "reconcile-vacancies", help="Clean duplicate/non-vacancy review work."
    )
    quality.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "workers":
        from app.services.worker_runtime import run_supervisor

        try:
            return run_supervisor(args.roles)
        except ValueError as exc:
            parser.error(str(exc))
    if args.command == "worker-status":
        from sqlalchemy.exc import SQLAlchemyError

        from app.services.worker_health import readiness, snapshot

        try:
            with SessionLocal() as db:
                result = {"ready": readiness(db), "workers": snapshot(db)}
        except SQLAlchemyError:
            result = {"ready": False, "database": "unavailable", "workers": []}
        print(json.dumps(result, default=str, indent=2))
        return 0 if result["ready"] else 1
    if args.command == "reconcile-vacancies":
        from app.services.vacancies import reconcile_pending_quality

        with SessionLocal() as db:
            result = reconcile_pending_quality(db, dry_run=args.dry_run)
        print(json.dumps({"dry_run": args.dry_run, **result}))
        return 0
    if args.command in {"recruitment-worker", "reels-worker", "notification-worker"}:
        from app.services.worker_runtime import COMMANDS, run_worker

        if not 1 <= args.max_tasks <= 100:
            parser.error("--max-tasks must be between 1 and 100")
        name = next(name for name, command in COMMANDS.items() if command == args.command)
        return run_worker(name, once=args.once, max_tasks=args.max_tasks)
    if args.command == "cleanup-account-files":
        from app.services.accounts import cleanup_account_files

        with SessionLocal() as db:
            result = cleanup_account_files(db)
        print(f"Removed {result['removed']} queued account file(s).")
        return 0
    if args.command == "check-config":
        # Settings validation already ran on import. Do not print the model,
        # database URL, or signing key, and do not open a database connection.
        print(f"Configuration valid: environment={settings.environment}")
        print(f"Allowed hosts: {settings.allowed_hosts}")
        print(f"Secure cookies: {settings.session_https_only}; debug: {settings.debug}")
        return 0
    if args.command == "set-staff":
        return _set_staff(args.phone, enabled=True)
    if args.command == "unset-staff":
        return _set_staff(args.phone, enabled=False)
    if args.command == "recruitment-init":
        from app.services.recruitment import initialize_discovery

        with SessionLocal() as db:
            result = initialize_discovery(db)
        print(f"Created {result['schedules']} schedules and {result['sources']} pending sources.")
        return 0
    with SessionLocal() as db:
        result = reconcile_community_media(db, dry_run=args.dry_run)
    mode = "Would remove" if args.dry_run else "Removed"
    print(
        f"{mode} {result['removed_files']} file(s); "
        f"{result['corrected_accounts']} account counter(s) needed correction."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
