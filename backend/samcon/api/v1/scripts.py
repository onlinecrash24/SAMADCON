"""Startup, shutdown, logon and logoff scripts of one GPO.

Reading answers for a whole half at once — both engines, every event — because
that is one SMB round trip and what the editor draws. Writing takes the
complete list for one event: the numbering in the file *is* the execution
order, so reordering and removing are the same operation as adding.
"""

from __future__ import annotations

from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, File, Query, Response, UploadFile

from samcon.ad.access import ad_read, ad_write
from samcon.api.common import Audit, DnQuery
from samcon.auth.deps import CurrentSession, VerifiedSession, VerifiedWorker, Worker
from samcon.core.errors import InvalidRequest
from samcon.gpo import scripts
from samcon.schemas.requests import SetScriptsRequest

router = APIRouter(prefix="/gpos/scripts", tags=["group-policy"])

HalfQuery = Annotated[str, Query(pattern="^(Machine|User)$")]


@router.get("")
async def read_scripts(
    worker: Worker,
    session: CurrentSession,
    dn: DnQuery,
    half: HalfQuery,
) -> dict[str, Any]:
    """Every script of one half, with the version to write back against."""

    def _run(conn: Any) -> dict[str, Any]:
        return scripts.read(conn, dn, half)

    return await ad_read(worker, session, _run, label="scripts.read")


@router.post("")
async def set_scripts(
    payload: SetScriptsRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    """Replace one event's scripts, and register the extension that runs them."""
    with audit.operation("scripts.set", target=dn) as record:

        def _run(conn: Any) -> dict[str, Any]:
            return scripts.write(
                conn,
                dn,
                payload.half,
                payload.event,
                payload.engine,
                [
                    scripts.Script(command=item.command, parameters=item.parameters)
                    for item in payload.scripts
                ],
                expected_version=payload.expected_version,
                ps_first=payload.ps_first,
            )

        result = await ad_write(worker, session, _run, label="scripts.set")
        record["changes"] = {
            f"{payload.half}/{payload.event}": {
                "new": f"{len(payload.scripts)} {payload.engine} script(s)"
            }
        }
    return result


# ---------------------------------------------------------------------------
# The script files themselves
# ---------------------------------------------------------------------------
#
# A script does not have to live inside its GPO — Windows runs whatever path
# the client can reach. Keeping it there is a convenience: the file travels
# with a backup and with a copy.


EventQuery = Annotated[str, Query(pattern="^(Startup|Shutdown|Logon|Logoff)$")]
NameQuery = Annotated[str, Query(min_length=1, max_length=255)]

# A script is text or a small binary. The ceiling stops a wrong file from
# being read into memory whole and pushed onto a share the whole domain reads.
MAX_SCRIPT_BYTES = 8 * 1024 * 1024


@router.get("/files")
async def list_files(
    worker: Worker,
    session: CurrentSession,
    dn: DnQuery,
    half: HalfQuery,
    event: EventQuery,
) -> dict[str, Any]:
    """The script files stored in one event's directory."""

    def _run(conn: Any) -> dict[str, Any]:
        return {"files": scripts.list_files(conn, dn, half, event)}

    return await ad_read(worker, session, _run, label="scripts.files")


@router.get("/files/content")
async def download_file(
    worker: Worker,
    session: CurrentSession,
    dn: DnQuery,
    half: HalfQuery,
    event: EventQuery,
    name: NameQuery,
) -> Response:
    """One script file, as it is on the share."""

    def _run(conn: Any) -> bytes:
        return scripts.read_file(conn, dn, half, event, name)

    data = await ad_read(worker, session, _run, label="scripts.download")
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{quote(name)}"'},
    )


@router.post("/files")
async def upload_file(
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
    half: HalfQuery,
    event: EventQuery,
    file: Annotated[UploadFile, File()],
) -> dict[str, Any]:
    """Store a script file in its event's directory.

    It is not added to the list of scripts to run — that is a separate,
    deliberate step. A helper script that another one calls belongs on the
    share without being scheduled.
    """
    data = await file.read(MAX_SCRIPT_BYTES + 1)
    if len(data) > MAX_SCRIPT_BYTES:
        raise InvalidRequest(
            "This file is too large for a script.",
            code="script_too_large",
            context={"limit": MAX_SCRIPT_BYTES},
        )

    name = (file.filename or "").strip()
    with audit.operation("scripts.upload", target=dn) as record:

        def _run(conn: Any) -> dict[str, Any]:
            return scripts.write_file(conn, dn, half, event, name, data)

        result = await ad_write(worker, session, _run, label="scripts.upload")
        record["changes"] = {f"{half}/{event}/{name}": {"new": f"{len(data)} bytes"}}
    return result


@router.delete("/files")
async def delete_file(
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
    half: HalfQuery,
    event: EventQuery,
    name: NameQuery,
) -> dict[str, Any]:
    """Remove a script file. An entry naming it stays — and then points at
    nothing, which the list shows."""
    with audit.operation("scripts.delete_file", target=dn) as record:

        def _run(conn: Any) -> dict[str, Any]:
            scripts.delete_file(conn, dn, half, event, name)
            return {"name": name}

        result = await ad_write(worker, session, _run, label="scripts.delete_file")
        record["changes"] = {f"{half}/{event}/{name}": {"old": "present", "new": None}}
    return result
