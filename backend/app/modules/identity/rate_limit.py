"""Small process-local sliding-window limiter; DB lockout remains authoritative."""

from __future__ import annotations

import threading
import time
from collections import deque


class InMemoryRateLimiter:
    """Bounded per-process limiter. Use a shared store before multi-replica rollout."""

    def __init__(self, max_keys: int = 20_000) -> None:
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._max_keys = max_keys

    def check(self, key: str, limit: int, window_seconds: int) -> int:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                return max(1, int(window_seconds - (now - events[0]) + 0.999))
            events.append(now)
            if len(self._events) > self._max_keys:
                stale_keys = [k for k, v in self._events.items() if not v or v[-1] <= cutoff]
                for stale in stale_keys[: len(self._events) - self._max_keys]:
                    self._events.pop(stale, None)
            return 0

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


login_limiter = InMemoryRateLimiter()
registration_limiter = InMemoryRateLimiter()
