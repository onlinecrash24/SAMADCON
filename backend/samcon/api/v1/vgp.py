"""Samba's own group policies — the ones ``samba-gpupdate`` applies on Linux.

Windows clients ignore these, which is the first thing anyone looking at an
empty ``gpresult`` needs to know. No client-side extension is registered:
``samba-tool gpo manage`` does not register one either, and Samba runs every
extension against every applicable policy regardless.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from samcon.ad.access import ad_read, ad_write
from samcon.api.common import Audit, DnQuery
from samcon.auth.deps import CurrentSession, VerifiedSession, VerifiedWorker, Worker
from samcon.gpo import vgp
from samcon.schemas.requests import SetVgpEntriesRequest

router = APIRouter(prefix="/gpos/vgp", tags=["group-policy"])

PolicyQuery = Annotated[str, Query(min_length=1, max_length=32, pattern=r"^[a-z_]+$")]


@router.get("/kinds")
async def kinds() -> dict[str, Any]:
    """Which Samba policies the editor offers, and where each one is stored."""
    return {
        "kinds": [
            {
                "id": kind.id,
                "path": kind.path,
                "name": kind.name,
                "description": kind.description,
            }
            for kind in vgp.KINDS.values()
        ]
    }


@router.get("")
async def read_all(worker: Worker, session: CurrentSession, dn: DnQuery) -> dict[str, Any]:
    """Every Samba policy of one GPO."""

    def _run(conn: Any) -> dict[str, Any]:
        return vgp.read_all(conn, dn)

    return await ad_read(worker, session, _run, label="vgp.read")


@router.get("/policy")
async def read_one(
    worker: Worker,
    session: CurrentSession,
    dn: DnQuery,
    policy: PolicyQuery,
) -> dict[str, Any]:
    """One Samba policy, with the version to write back against."""

    def _run(conn: Any) -> dict[str, Any]:
        return vgp.read(conn, dn, policy)

    return await ad_read(worker, session, _run, label="vgp.read_one")


@router.post("")
async def set_entries(
    payload: SetVgpEntriesRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    """Replace one Samba policy's entries."""
    with audit.operation("vgp.set", target=dn) as record:

        def _run(conn: Any) -> dict[str, Any]:
            return vgp.write(
                conn,
                dn,
                payload.policy,
                payload.entries,
                expected_version=payload.expected_version,
            )

        result = await ad_write(worker, session, _run, label="vgp.set")
        record["changes"] = {payload.policy: {"new": f"{len(payload.entries)} entries"}}
    return result
