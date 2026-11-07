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
import sys
import time
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
        "recruitment-init", help="Create directory schedules and pending LSHSC source."
    )
    worker = subparsers.add_parser("recruitment-worker", help="Run the source-discovery queue.")
    worker.add_argument("--once", action="store_true", help="Process ready tasks, then exit.")
    worker.add_argument("--max-tasks", type=int, default=10, help="Task limit for --once (1–100).")

    args = parser.parse_args(argv)
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
    if args.command == "recruitment-worker":
        from app.services.recruitment_worker import enqueue_due, run_next

        if not 1 <= args.max_tasks <= 100:
            parser.error("--max-tasks must be between 1 and 100")
        completed = 0
        try:
            while True:
                with SessionLocal() as db:
                    enqueue_due(db)
                    task = run_next(db)
                    if task is not None:
                        print(
                            f"{task.kind}: {task.status}; {task.result_count} new sources; "
                            f"{task.outcome}",
                            flush=True,
                        )
                        completed += 1
                if args.once and (task is None or completed >= args.max_tasks):
                    break
                if task is None:
                    time.sleep(5)
        except KeyboardInterrupt:
            print("Discovery worker stopped; unfinished leases can be recovered.")
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
