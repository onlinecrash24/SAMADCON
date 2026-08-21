"""Organizational units."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from samadcon.ad import ou
from samadcon.ad.access import ad_read, ad_write
from samadcon.api.common import Audit, DnQuery
from samadcon.auth.deps import CurrentSession, VerifiedSession, VerifiedWorker, Worker
from samadcon.schemas.requests import CreateOURequest, UpdateOURequest

router = APIRouter(prefix="/ous", tags=["organizational-units"])


@router.get("")
async def get_ou(worker: Worker, session: CurrentSession, dn: DnQuery) -> dict[str, Any]:
    return await ad_read(worker, session, ou.get_ou, dn, label="ou.get")


@router.post("")
async def create_ou(
    payload: CreateOURequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
) -> dict[str, Any]:
    """Create an OU, protected against accidental deletion by default."""
    with audit.operation("ou.create", target=payload.parent_dn) as record:
        created = await ad_write(
            worker,
            session,
            ou.create_ou,
            parent_dn=payload.parent_dn,
            name=payload.name,
            description=payload.description,
            protect_from_deletion=payload.protect_from_deletion,
            label="ou.create",
        )
        record["target"] = created["dn"]
        record["changes"] = {
            "name": {"new": payload.name},
            "delete_protected": {"new": payload.protect_from_deletion},
        }
    return created


@router.patch("")
async def update_ou(
    payload: UpdateOURequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    with audit.operation("ou.update", target=dn) as record:
        applied = await ad_write(
            worker,
            session,
            ou.update_ou,
            dn,
            attributes=payload.attributes,
            protect_from_deletion=payload.protect_from_deletion,
            label="ou.update",
        )
        record["changes"] = applied
    return {"dn": dn, "applied": applied}


@router.delete("")
async def delete_ou(
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
    recursive: Annotated[bool, Query(description="Delete contained objects as well")] = False,
) -> dict[str, Any]:
    """Delete an OU.

    Refuses while deletion protection is set: clearing it is a separate,
    deliberate step.
    """
    with audit.operation("ou.delete", target=dn, recursive=recursive):
        await ad_write(worker, session, ou.delete_ou, dn, recursive=recursive, label="ou.delete")
    return {"dn": dn, "deleted": True}
