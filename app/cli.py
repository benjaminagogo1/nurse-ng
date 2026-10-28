"""Small operator commands.

Usage::

    python -m app.cli set-staff +2348012345678
    python -m app.cli unset-staff +2348012345678

Staff accounts can open the document-review queue. There is deliberately no
web route for granting the flag: it is an operator action, recorded in the
access audit when the reviewer opens evidence (DECISIONS L49).
"""

import argparse
import sys
from collections.abc import Sequence

from sqlalchemy import select

from app.core.validators import normalize_phone
from app.db.session import SessionLocal
from app.models.user import User


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

    for name in ("set-staff", "unset-staff"):
        command = subparsers.add_parser(name)
        command.add_argument("phone", help="Phone number in international format.")

    args = parser.parse_args(argv)
    if args.command == "set-staff":
        return _set_staff(args.phone, enabled=True)
    return _set_staff(args.phone, enabled=False)


if __name__ == "__main__":
    raise SystemExit(main())
