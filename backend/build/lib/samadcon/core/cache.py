"""Small TTL cache.

Used for data that is expensive to fetch but changes rarely: the LDAP schema,
the rootDSE, the parsed ADMX catalogue. Keeping it in-process is fine because
SAMADCON runs as a single API worker (session state and Samba handles are bound
to worker threads, so scaling out means separate containers, not more workers).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any, Generic, TypeVar

T = TypeVar("T")


class TTLCache(Generic[T]):
    def __init__(self, ttl_seconds: float = 300.0, max_entries: int = 256) -> None:
        self.ttl = ttl_seconds
        self.max_entries = max_entries
        self._data: dict[str, tuple[float, T]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> T | None:
        now = time.monotonic()
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at < now:
                del self._data[key]
                return None
            return value

    def set(self, key: str, value: T, ttl: float | None = None) -> None:
        with self._lock:
            if len(self._data) >= self.max_entries:
                # Cheap eviction: drop whatever expires first.
                oldest = min(self._data, key=lambda k: self._data[k][0])
                del self._data[oldest]
            self._data[key] = (time.monotonic() + (ttl if ttl is not None else self.ttl), value)

    def get_or_set(self, key: str, factory: Callable[[], T], ttl: float | None = None) -> T:
        cached = self.get(key)
        if cached is not None:
            return cached
        value = factory()
        self.set(key, value, ttl)
        return value

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def invalidate_prefix(self, prefix: str) -> None:
        with self._lock:
            for key in [k for k in self._data if k.startswith(prefix)]:
                del self._data[key]

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        return len(self._data)


# Shared caches. Kept separate so one can be cleared without the other —
# `samadconctl cache clear admx` after an ADMX upload, for instance.
schema_cache: TTLCache[Any] = TTLCache(ttl_seconds=3600.0, max_entries=32)
rootdse_cache: TTLCache[Any] = TTLCache(ttl_seconds=300.0, max_entries=32)
admx_cache: TTLCache[Any] = TTLCache(ttl_seconds=1800.0, max_entries=8)

_ALL_CACHES = {
    "schema": schema_cache,
    "rootdse": rootdse_cache,
    "admx": admx_cache,
}


def clear_caches(name: str | None = None) -> list[str]:
    """Clear one or all caches; returns the names that were cleared."""
    if name is None:
        for cache in _ALL_CACHES.values():
            cache.clear()
        return list(_ALL_CACHES)
    cache = _ALL_CACHES.get(name)
    if cache is None:
        raise KeyError(name)
    cache.clear()
    return [name]
