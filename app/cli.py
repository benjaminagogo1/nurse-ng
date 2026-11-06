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
