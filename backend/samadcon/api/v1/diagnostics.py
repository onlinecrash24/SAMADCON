"""Domain health: roles, replication, policies, problem accounts.

Read-only throughout — there is no write path in this router, and that is
deliberate. Seizing an FSMO role or forcing replication are operations with
consequences that a web console should not make easy; they belong on the DC,
with `samba-tool fsmo seize` and `samba-tool drs replicate`.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from samadcon.ad import diagnostics
from samadcon.ad.access import ad_read
from samadcon.auth.deps import CurrentSession, Worker

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
