"""UUIDv7 generation.

Python 3.14 ships ``uuid.uuid7``; use it when available. Otherwise generate an
RFC 9562 UUIDv7 locally.

UUIDv7 is time-ordered, which keeps B-tree inserts sequential while remaining
unguessable. It is the identifier format set out in the build plan.
"""

import os
import time
import uuid as _uuid


def _local_uuid7() -> _uuid.UUID:
    timestamp_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand_a = int.from_bytes(os.urandom(2), "big") & 0x0FFF
    rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)

    value = (
        (timestamp_ms << 80)
        | (0x7 << 76)  # version 7
        | (rand_a << 64)
        | (0b10 << 62)  # RFC 4122 variant
        | rand_b
    )
    return _uuid.UUID(int=value)


def uuid7() -> _uuid.UUID:
    """Return a UUIDv7, preferring the standard library implementation."""
    native = getattr(_uuid, "uuid7", None)
    if native is not None:
        return native()
    return _local_uuid7()
