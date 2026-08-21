"""Session store and login throttling.

A session is little more than a pointer to a Kerberos credential cache plus the
metadata needed to expire it. It lives in memory only: restarting the container
invalidates every session, which is the honest behaviour given that the caches
live on tmpfs and are gone anyway.
"""

from __future__ import annotations

import logging
import secrets
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from samadcon.ad.target import ConnectionTarget
from samadcon.auth.kerberos import Principal, destroy_ticket
from samadcon.core.errors import AuthenticationError, SessionExpired
from samadcon.core.executor import get_registry

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Session:
    id: str
    principal: Principal
    # The domain this session is signed in to. Chosen at sign-in, not at
    # container start — different sessions may target different domains.
    target: ConnectionTarget
    ccache: Path
    csrf_token: str
    ticket_expires_at: datetime
    idle_timeout: timedelta
    created_at: datetime = field(default_factory=_now)
    last_seen: datetime = field(default_factory=_now)
    client_ip: str | None = None
    user_agent: str | None = None

    @property
    def expires_at(self) -> datetime:
        """Whichever comes first: the ticket's end or the idle timeout."""
        return min(self.ticket_expires_at, self.last_seen + self.idle_timeout)

    def is_expired(self, now: datetime | None = None) -> bool:
        return self.expires_at <= (now or _now())

    def touch(self) -> None:
        self.last_seen = _now()


class SessionStore:
    def __init__(self, idle_minutes: int = 60) -> None:
        self.idle_timeout = timedelta(minutes=idle_minutes)
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(
        self,
        *,
        session_id: str,
        principal: Principal,
        target: ConnectionTarget,
        ccache: Path,
        ticket_expires_at: datetime,
        client_ip: str | None = None,
        user_agent: str | None = None,
    ) -> Session:
        session = Session(
            id=session_id,
            principal=principal,
            target=target,
            ccache=ccache,
            csrf_token=secrets.token_urlsafe(32),
            ticket_expires_at=ticket_expires_at,
            idle_timeout=self.idle_timeout,
            client_ip=client_ip,
            user_agent=user_agent,
        )
        with self._lock:
            self._sessions[session_id] = session
        logger.info(
            "session opened",
            extra={
                "session": session_id[:8],
                "actor": principal.full,
                "domain": target.display_name,
            },
        )
        return session

    def get(self, session_id: str | None) -> Session:
        if not session_id:
            raise SessionExpired("Not signed in.", code="not_authenticated")

        with self._lock:
            session = self._sessions.get(session_id)

        if session is None:
            raise SessionExpired("The session is unknown or has ended.")
        if session.is_expired():
            self.drop(session_id, reason="expired")
            raise SessionExpired(
                "The session has expired.",
                hint="Kerberos tickets are time-limited; sign in again.",
            )

        session.touch()
        return session

    def drop(self, session_id: str, *, reason: str = "logout") -> None:
        with self._lock:
            session = self._sessions.pop(session_id, None)

        if session is None:
            return

        # Order matters: release the Samba handles on their own worker thread
        # first, then remove the ticket they authenticate with.
        get_registry().drop(session_id)
        destroy_ticket(session.ccache)
        logger.info(
            "session closed",
            extra={"session": session_id[:8], "actor": session.principal.full, "reason": reason},
        )

    def sweep(self) -> int:
        """Drop expired sessions. Returns how many were removed."""
        now = _now()
        with self._lock:
            stale = [sid for sid, s in self._sessions.items() if s.is_expired(now)]
        for session_id in stale:
            self.drop(session_id, reason="expired")
        return len(stale)

    def close_all(self) -> None:
        for session_id in list(self._sessions):
            self.drop(session_id, reason="shutdown")

    def count(self) -> int:
        return len(self._sessions)

    @staticmethod
    def new_id() -> str:
        return secrets.token_urlsafe(32)


class LoginThrottle:
    """Stops repeated failures before they reach the DC.

    Without this, the login form would be a convenient way to lock out every
    account in the domain. Accounts and source addresses are counted
    separately, so an attacker from one address cannot lock an administrator
    out of a different one — the account counter still protects AD, but the
    address counter is what usually trips first.
    """

    def __init__(self, max_attempts: int = 5, lockout_minutes: int = 5) -> None:
        self.max_attempts = max_attempts
        self.lockout = timedelta(minutes=lockout_minutes)
        self._failures: dict[str, tuple[int, datetime]] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        """Zero for either setting turns throttling off.

        Without this, a lockout window of zero would compare ``now - last > 0``
        against a clock whose resolution is coarser than the two calls, and
        block forever instead of never.
        """
        return self.max_attempts > 0 and self.lockout > timedelta(0)

    def _keys(self, username: str, client_ip: str | None) -> list[str]:
        keys = [f"user:{username.lower()}"]
        if client_ip:
            keys.append(f"ip:{client_ip}")
        return keys

    def check(self, username: str, client_ip: str | None = None) -> None:
        if not self.enabled:
            return
        now = _now()
        with self._lock:
            for key in self._keys(username, client_ip):
                entry = self._failures.get(key)
                if entry is None:
                    continue
                count, last = entry
                if now - last > self.lockout:
                    del self._failures[key]
                    continue
                if count >= self.max_attempts:
                    remaining = int((self.lockout - (now - last)).total_seconds())
                    raise AuthenticationError(
                        "Too many failed sign-in attempts.",
                        code="login_throttled",
                        status_code=429,
                        hint=(
                            "SAMADCON pauses further attempts so the AD account "
                            "is not locked out."
                        ),
                        context={"retry_after_seconds": max(remaining, 1)},
                    )

    def record_failure(self, username: str, client_ip: str | None = None) -> None:
        if not self.enabled:
            return
        now = _now()
        with self._lock:
            for key in self._keys(username, client_ip):
                count, last = self._failures.get(key, (0, now))
                if now - last > self.lockout:
                    count = 0
                self._failures[key] = (count + 1, now)

    def record_success(self, username: str, client_ip: str | None = None) -> None:
        with self._lock:
            for key in self._keys(username, client_ip):
                self._failures.pop(key, None)


_store: SessionStore | None = None
_throttle: LoginThrottle | None = None


def get_store() -> SessionStore:
    global _store
    if _store is None:
        from samadcon.config import get_settings

        _store = SessionStore(idle_minutes=get_settings().session_idle_minutes)
    return _store


def get_throttle() -> LoginThrottle:
    global _throttle
    if _throttle is None:
        from samadcon.config import get_settings

        settings = get_settings()
        _throttle = LoginThrottle(
            max_attempts=settings.login_max_attempts,
            lockout_minutes=settings.login_lockout_minutes,
        )
    return _throttle


def reset_auth_state() -> None:
    """Test hook."""
    global _store, _throttle
    if _store is not None:
        _store.close_all()
    _store = None
    _throttle = None
