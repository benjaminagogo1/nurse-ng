"""In-memory fixed-window request limiting.

Used for per-IP throttling of the authentication endpoints. A fixed window
counts events from the first event in the window; when the window elapses the
counter is discarded and starts again.

State is process-local: it resets on restart and is not shared between worker
processes. That is acceptable while the pilot runs one server process; see
DECISIONS L37 for the trade-off and the trigger to move this to Redis or the
database.
"""

from dataclasses import dataclass
from math import ceil
from threading import Lock
from time import monotonic

_registry: list["FixedWindowLimiter"] = []
_registry_lock = Lock()


@dataclass
class _Window:
    started_at: float
    count: int = 0


class FixedWindowLimiter:
    """Count events per key and report when a key has spent its allowance."""

    def __init__(self, limit: int, window_seconds: int) -> None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if window_seconds < 1:
            raise ValueError("window_seconds must be at least 1")
        self.limit = limit
        self.window_seconds = window_seconds
        self._windows: dict[str, _Window] = {}
        self._lock = Lock()
        with _registry_lock:
            _registry.append(self)

    def is_limited(self, key: str) -> bool:
        """Return True when ``key`` has already spent its allowance."""
        now = monotonic()
        with self._lock:
            window = self._windows.get(key)
            if window is None:
                return False
            if now - window.started_at >= self.window_seconds:
                del self._windows[key]
                return False
            return window.count >= self.limit

    def record(self, key: str) -> None:
        """Count one event for ``key``, starting a new window when needed."""
        now = monotonic()
        with self._lock:
            window = self._windows.get(key)
            if window is None or now - window.started_at >= self.window_seconds:
                self._windows[key] = _Window(started_at=now, count=1)
            else:
                window.count += 1

    def retry_after(self, key: str) -> int:
        """Seconds until ``key``'s current window expires (at least 1)."""
        now = monotonic()
        with self._lock:
            window = self._windows.get(key)
            if window is None:
                return 0
            remaining = self.window_seconds - (now - window.started_at)
        return max(1, ceil(remaining))

    def reset(self, key: str) -> None:
        with self._lock:
            self._windows.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._windows.clear()


def reset_all_limiters() -> None:
    """Clear every limiter created in this process.

    Tests call this between cases because every TestClient request shares the
    same synthetic client address.
    """
    with _registry_lock:
        limiters = list(_registry)
    for limiter in limiters:
        limiter.clear()
