"""Contact-number normalisation and validation."""

import re

E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")


def normalize_phone(value: str) -> str:
    """Return an E.164-style number.

    Accepts spaced or punctuated input, the ``00`` international prefix, and
    Nigerian local numbers beginning with ``0``. The stored form always starts
    with ``+``.
    """
    raw = re.sub(r"[\s\-().]", "", str(value or ""))

    if raw.startswith("00"):
        raw = "+" + raw[2:]
    if raw.startswith("0") and len(raw) == 11:
        raw = "+234" + raw[1:]
    if raw and not raw.startswith("+"):
        raw = "+" + raw

    return raw
