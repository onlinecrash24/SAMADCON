"""Audit log for every write operation.

The domain controller logs the LDAP side of things, but it cannot record what
a user *meant* to do — which SAMADCON action ran, which attributes changed, and
what the previous values were. This module keeps that record locally as JSON
Lines, one object per operation.

Secrets never reach it: password-bearing attributes are redacted before the
entry is built, not afterwards.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("samadcon.audit")

REDACTED = "***"

# Anything that is or reveals a credential. Matched case-insensitively.
SENSITIVE_ATTRIBUTES = frozenset(
    {
        "unicodepwd",
        "dbcspwd",
        "userpassword",
        "cleartextpassword",
        "ntpwdhistory",
        "lmpwdhistory",
        "supplementalcredentials",
        "msds-managedpassword",
        "ms-mcs-admpwd",
        "mslaps-password",
        "mslaps-encryptedpassword",
        "msds-keycredentiallink",
        "password",
        "new_password",
        "old_password",
    }
)


def redact(value: Any, key: str | None = None) -> Any:
    """Return *value* with credential material replaced by ``***``."""
    if key is not None and key.lower() in SENSITIVE_ATTRIBUTES:
        return REDACTED
    if isinstance(value, dict):
        return {k: redact(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, key) for v in value]
    if isinstance(value, bytes):
        # Binary attributes (objectSid, nTSecurityDescriptor, ...) are noise in
        # an audit trail; record the size instead.
        return f"<{len(value)} bytes>"
    return value


class AuditLog:
    """Append-only JSON Lines writer."""

    def __init__(self, path: Path | None) -> None:
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self._degraded = False

        if self.path is not None:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                logger.error("audit directory not writable (%s): %s", self.path.parent, exc)
                self._degraded = True

    def record(
        self,
        *,
        action: str,
        actor: str | None,
        result: str = "ok",
        target: str | None = None,
        changes: dict[str, Any] | None = None,
        error: str | None = None,
        error_code: str | None = None,
        duration_ms: int | None = None,
        session_id: str | None = None,
        client_ip: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds").replace(
                "+00:00", "Z"
            ),
            "action": action,
            "actor": actor,
            "result": result,
        }
        if target:
            entry["target"] = target
        if changes:
            entry["changes"] = redact(changes)
        if error:
            entry["error"] = error
        if error_code:
            entry["error_code"] = error_code
        if duration_ms is not None:
            entry["duration_ms"] = duration_ms
        if session_id:
            # Enough to correlate entries, not enough to replay a session.
            entry["session"] = session_id[:8]
        if client_ip:
            entry["client_ip"] = client_ip
        if extra:
            entry.update(redact(extra))

        line = json.dumps(entry, ensure_ascii=False, default=str)

        # Also goes to stdout so `docker logs` shows the trail even when no
        # audit file is mounted.
        logger.info("%s", line)

        if self.path is None or self._degraded:
            return

        with self._lock:
            try:
                # Opened per entry so logrotate can move the file underneath us.
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
            except OSError as exc:
                # An unwritable audit file must not take the application down,
                # but it must be loud.
                logger.error("failed to write audit entry: %s", exc)
                self._degraded = True

    @contextmanager
    def operation(
        self,
        action: str,
        *,
        actor: str | None,
        target: str | None = None,
        session_id: str | None = None,
        client_ip: str | None = None,
        changes: dict[str, Any] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Record an operation together with its outcome and duration.

        The yielded dict can be filled in while the operation runs::

            with audit.operation("user.create", actor=a, target=dn) as rec:
                rec["changes"] = {...}
        """
        record: dict[str, Any] = {"changes": dict(changes) if changes else {}, "extra": {}}
        started = time.monotonic()
        try:
            yield record
        except Exception as exc:
            self.record(
                action=action,
                actor=actor,
                result="error",
                target=record.get("target", target),
                changes=record.get("changes"),
                error=str(exc),
                error_code=getattr(exc, "code", None),
                duration_ms=int((time.monotonic() - started) * 1000),
                session_id=session_id,
                client_ip=client_ip,
                extra=record.get("extra") or None,
            )
            raise
        self.record(
            action=action,
            actor=actor,
            result="ok",
            target=record.get("target", target),
            changes=record.get("changes"),
            duration_ms=int((time.monotonic() - started) * 1000),
            session_id=session_id,
            client_ip=client_ip,
            extra=record.get("extra") or None,
        )


_audit: AuditLog | None = None


def get_audit() -> AuditLog:
    global _audit
    if _audit is None:
        from samadcon.config import get_settings

        _audit = AuditLog(get_settings().audit_file)
    return _audit


def reset_audit() -> None:
    """Test hook."""
    global _audit
    _audit = None
