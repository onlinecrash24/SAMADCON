"""Domain health: roles, replication, policies, problem accounts.

Read-only throughout — there is no write path in this router, and that is
deliberate. Seizing an FSMO role or forcing replication are operations with
consequences that a web console should not make easy; they belong on the DC,
with `samba-tool fsmo seize` and `samba-tool drs replicate`.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Query

from samadcon.ad import diagnostics
from samadcon.ad.access import ad_read
from samadcon.auth.deps import CurrentSession, Worker
from samadcon.core import findings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


@router.get("")
async def overview(worker: Worker, session: CurrentSession) -> dict[str, Any]:
    """Everything the diagnosis page shows, in one call."""
    return await ad_read(worker, session, diagnostics.overview, label="diag.overview")


@router.get("/roles")
async def fsmo_roles(worker: Worker, session: CurrentSession) -> dict[str, Any]:
    roles = await ad_read(worker, session, diagnostics.fsmo_roles, label="diag.roles")
    return {"roles": roles}


@router.get("/controllers")
async def domain_controllers(worker: Worker, session: CurrentSession) -> dict[str, Any]:
    found = await ad_read(
        worker, session, diagnostics.domain_controllers, label="diag.controllers"
    )
    return {"controllers": found}


@router.get("/replication")
async def replication(worker: Worker, session: CurrentSession) -> dict[str, Any]:
    """Inbound replication status of the DC this session is connected to."""
    return await ad_read(worker, session, diagnostics.replication, label="diag.replication")


@router.get("/policy")
async def password_policy(worker: Worker, session: CurrentSession) -> dict[str, Any]:
    return await ad_read(worker, session, diagnostics.password_policy, label="diag.policy")


@router.get("/accounts")
async def account_problems(
    worker: Worker,
    session: CurrentSession,
    limit: Annotated[int, Query(ge=1, le=2000)] = 200,
) -> dict[str, Any]:
    """Locked, disabled and expired accounts."""
    return await ad_read(
        worker, session, diagnostics.account_problems, limit=limit, label="diag.accounts"
    )


@router.get("/findings")
async def security_findings(worker: Worker, session: CurrentSession) -> dict[str, Any]:
    """What is worth telling an administrator about this domain.

    The binding half of the security report: rules over values the tool
    already reads, each carrying what it was decided from. Nothing is asked
    of a language model here — see :mod:`samadcon.core.findings`.
    """

    def _run(conn: Any) -> dict[str, Any]:
        # Read section by section. A part that cannot be read leaves its
        # findings out and says so, which beats failing the whole report
        # over one unreachable corner — and beats reporting a clean bill of
        # health for a section nobody looked at.
        gathered: dict[str, Any] = {}
        unreadable: list[str] = []
        for name, read in (("policy", diagnostics.password_policy),
                           ("replication", diagnostics.replication)):
            try:
                gathered[name] = read(conn)
            except Exception:
                logger.warning("cannot read %s for the findings", name, exc_info=True)
                unreadable.append(name)

        found = findings.evaluate(
            policy=gathered.get("policy"),
            replication=gathered.get("replication"),
            connection=conn.transport.describe() if conn.transport else None,
        )
        return {
            "findings": [item.describe() for item in found],
            "unreadable": unreadable,
        }

    return await ad_read(worker, session, _run, label="diag.findings")
