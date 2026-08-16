"""A small sliding-window rate limiter.

Used for endpoints that are reachable before sign-in. The server probe in
particular opens outbound connections on behalf of an unauthenticated caller,
so it must not be usable as a scanning tool: the ports are fixed in code, and
this limits how often anyone can ask.
"""

from __future__ import annotations

import threading
import time
from collections import deque

from samcon.core.errors import SamconError


class RateLimiter:
    def __init__(self, max_events: int, window_seconds: float) -> None:
        self.max_events = max_events
        self.window = window_seconds
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        """Record an attempt for *key*, raising once the limit is exceeded."""
        now = time.monotonic()
        with self._lock:
            bucket = self._events.setdefault(key, deque())
            while bucket and now - bucket[0] > self.window:
                bucket.popleft()

            if len(bucket) >= self.max_events:
                retry_after = int(self.window - (now - bucket[0])) + 1
                raise SamconError(
                    "Too many requests.",
                    code="rate_limited",
                    status_code=429,
                    context={"retry_after_seconds": retry_after},
                )

            bucket.append(now)

            # Keep the table from growing without bound on a busy instance.
            if len(self._events) > 1024:
                for stale_key in [k for k, v in self._events.items() if not v]:
                    del self._events[stale_key]

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._events.clear()
            else:
                self._events.pop(key, None)


# 20 probes a minute is generous for someone filling in a form and useless for
# anyone trying to enumerate a network.
probe_limiter = RateLimiter(max_events=20, window_seconds=60.0)
