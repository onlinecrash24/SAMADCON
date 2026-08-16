"""Computer accounts."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from samadcon.ad import computers
from samadcon.ad.access import ad_read, ad_write
from samadcon.api.common import Audit, DnQuery
from samadcon.auth.deps import CurrentSession, VerifiedSession, VerifiedWorker, Worker
from samadcon.schemas.requests import CreateComputerRequest, UpdateComputerRequest

router = APIRouter(prefix="/computers", tags=["computers"])


@router.get("")
async def get_computer(worker: Worker, session: CurrentSession, dn: DnQuery) -> dict[str, Any]:
    return await ad_read(worker, session, computers.get_computer, dn, label="computer.get")


@router.post("")
async def create_computer(
    payload: CreateComputerRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
) -> dict[str, Any]:
    with audit.operation("computer.create", target=payload.parent_dn) as record:
        created = await ad_write(
            worker,
            session,
            computers.create_computer,
            parent_dn=payload.parent_dn,
            name=payload.name,
            description=payload.description,
            location=payload.location,
            enabled=payload.enabled,
            label="computer.create",
        )
        record["target"] = created["dn"]
        record["changes"] = {"name": {"new": payload.name}, "enabled": {"new": payload.enabled}}
    return created


@router.patch("")
async def update_computer(
    payload: UpdateComputerRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    with audit.operation("computer.update", target=dn) as record:
        applied = await ad_write(
            worker,
            session,
            computers.update_computer,
            dn,
            attributes=payload.attributes,
            flags=payload.flags,
            label="computer.update",
        )
        record["changes"] = applied
    return {"dn": dn, "applied": applied}


@router.post("/reset")
async def reset_account(
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    """Reset the machine account password so the computer can rejoin."""
    with audit.operation("computer.reset_account", target=dn):
        await ad_write(
            worker, session, computers.reset_computer_account, dn, label="computer.reset"
        )
    return {"dn": dn, "reset": True}


@router.get("/laps")
async def laps_status(worker: Worker, session: CurrentSession, dn: DnQuery) -> dict[str, Any]:
    """Whether a LAPS password exists — without reading it."""
    return await ad_read(worker, session, computers.laps_status, dn, label="computer.laps_status")


@router.post("/laps/reveal")
async def reveal_laps_password(
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    """Read the local administrator password managed by LAPS.

    A POST rather than a GET because it is an auditable event, not a lookup:
    handing out a live credential is recorded with who asked and when. The
    password itself is redacted from the audit entry.
    """
    with audit.operation("computer.reveal_laps_password", target=dn):
        result = await ad_write(
            worker, session, computers.read_laps_password, dn, label="computer.laps_reveal"
        )
    return {"dn": dn, **result}


@router.get("/stale")
async def stale_computers(
    worker: Worker,
    session: CurrentSession,
    days: Annotated[int, Query(ge=1, le=3650, description="Days without a logon")] = 90,
) -> dict[str, Any]:
    """Computers that have not authenticated recently.

    Based on lastLogonTimestamp, which lags by up to 14 days by design — good
    enough for a cleanup list, not for an audit.
    """
    result = await ad_read(
        worker, session, computers.list_stale_computers, days, label="computer.stale"
    )
    return {"computers": result, "count": len(result), "days": days}
