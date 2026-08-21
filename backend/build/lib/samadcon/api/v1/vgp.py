"""Samba's own group policies — the ones ``samba-gpupdate`` applies on Linux.

Windows clients ignore these, which is the first thing anyone looking at an
empty ``gpresult`` needs to know. No client-side extension is registered:
``samba-tool gpo manage`` does not register one either, and Samba runs every
extension against every applicable policy regardless.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, File, Query, UploadFile

from samadcon.ad.access import ad_read, ad_write
from samadcon.api.common import Audit, DnQuery
from samadcon.auth.deps import CurrentSession, VerifiedSession, VerifiedWorker, Worker
from samadcon.core.errors import InvalidRequest
from samadcon.gpo import vgp
from samadcon.schemas.requests import SetVgpEntriesRequest

router = APIRouter(prefix="/gpos/vgp", tags=["group-policy"])

PolicyQuery = Annotated[str, Query(min_length=1, max_length=32, pattern=r"^[a-z_]+$")]

# A file that gets copied onto every member in scope. Large enough for the
# configuration files and banners these policies exist for, small enough that
# a wrong upload does not fill SYSVOL.
MAX_PAYLOAD_BYTES = 8 * 1024 * 1024


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


# ---------------------------------------------------------------------------
# Files an entry refers to
#
# Unix/Files is the one kind whose entries name a file instead of carrying
# their content, and the file is half the policy: without it a member logs
# "Source file does not exist" and applies nothing, while the console shows the
# entry as configured. Uploading and referring to it stay separate steps, the
# way scripts already work.
# ---------------------------------------------------------------------------


@router.get("/payloads")
async def list_payloads(
    worker: Worker, session: CurrentSession, dn: DnQuery, policy: PolicyQuery
) -> dict[str, Any]:
    """The files sitting beside this policy's manifest."""

    def _run(conn: Any) -> dict[str, Any]:
        return {"payloads": vgp.list_payloads(conn, dn, policy)}

    return await ad_read(worker, session, _run, label="vgp.payloads")


@router.post("/payloads")
async def upload_payload(
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
    policy: PolicyQuery,
    file: Annotated[UploadFile, File()],
) -> dict[str, Any]:
    """Store a file this policy's entries can refer to."""
    data = await file.read(MAX_PAYLOAD_BYTES + 1)
    if len(data) > MAX_PAYLOAD_BYTES:
        raise InvalidRequest(
            "This file is too large to hand out through a policy.",
            code="vgp_payload_too_large",
            context={"limit": MAX_PAYLOAD_BYTES},
        )

    name = (file.filename or "").strip()
    with audit.operation("vgp.upload", target=dn) as record:

        def _run(conn: Any) -> dict[str, Any]:
            return vgp.write_payload(conn, dn, policy, name, data)

        result = await ad_write(worker, session, _run, label="vgp.upload")
        record["changes"] = {f"{policy}/{name}": {"new": f"{len(data)} bytes"}}
    return result
