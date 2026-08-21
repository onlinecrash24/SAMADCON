"""Helpers shared by the routers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Any

from fastapi import Depends, Query, Request

from samadcon.auth.deps import client_ip, current_session
from samadcon.auth.session import Session
from samadcon.core.audit import AuditLog, get_audit


class AuditContext:
    """Binds the audit log to the caller behind the current request."""

    def __init__(self, log: AuditLog, session: Session, address: str | None) -> None:
        self.log = log
        self.session = session
        self.address = address

    @contextmanager
    def operation(
        self, action: str, target: str | None = None, **changes: Any
    ) -> Iterator[dict[str, Any]]:
        with self.log.operation(
            action,
            actor=self.session.principal.full,
            target=target,
            session_id=self.session.id,
            client_ip=self.address,
            changes=changes or None,
        ) as record:
            yield record

    def record(self, action: str, target: str | None = None, **extra: Any) -> None:
        self.log.record(
            action=action,
            actor=self.session.principal.full,
            target=target,
            session_id=self.session.id,
            client_ip=self.address,
            extra=extra or None,
        )


def audit_context(request: Request, session: Session = Depends(current_session)) -> AuditContext:
    return AuditContext(get_audit(), session, client_ip(request))


Audit = Annotated[AuditContext, Depends(audit_context)]

# Distinguished names travel as query parameters; they contain commas and
# spaces, so clients must URL-encode them.
DnQuery = Annotated[str, Query(min_length=3, description="Distinguished name")]
OptionalDnQuery = Annotated[str | None, Query(description="Distinguished name")]


def split_csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or None
