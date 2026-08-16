"""Folder redirection of one GPO.

User configuration only — there is no computer half for this. One folder and
one group at a time, because that is what a redirection *is*: the file pairs
them up, and each pairing carries its own path.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from samadcon.ad.access import ad_read, ad_write
from samadcon.api.common import Audit, DnQuery
from samadcon.auth.deps import CurrentSession, VerifiedSession, VerifiedWorker, Worker
from samadcon.gpo import folders
from samadcon.schemas.requests import RedirectFolderRequest

router = APIRouter(prefix="/gpos/redirection", tags=["group-policy"])


@router.get("/folders")
async def list_known_folders() -> dict[str, Any]:
    """The folders that can be redirected.

    Read off Windows' own table under
    ``HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Explorer\\FolderDescriptions``
    rather than written from memory: a guessed id would offer to redirect
    "Documents" and move somebody's music instead.
    """
    return {"folders": folders.known_folders()}


@router.get("")
async def read_redirection(
    worker: Worker,
    session: CurrentSession,
    dn: DnQuery,
) -> dict[str, Any]:
    """Which user folders this policy redirects, and where to."""

    def _run(conn: Any) -> dict[str, Any]:
        return folders.read(conn, dn)

    return await ad_read(worker, session, _run, label="redirection.read")


@router.post("")
async def redirect_folder(
    payload: RedirectFolderRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    """Redirect one folder for one group, or stop redirecting it.

    The options beside the path — the ``Flags`` number — are carried, not
    computed: which bit means what is not on evidence, and inventing one would
    change how a client treats files that are already there.
    """
    with audit.operation("redirection.set", target=dn) as record:

        def _run(conn: Any) -> dict[str, Any]:
            return folders.write(
                conn,
                dn,
                payload.folder,
                payload.sid,
                payload.path,
                expected_version=payload.expected_version,
            )

        result = await ad_write(worker, session, _run, label="redirection.set")
        record["changes"] = {f"{payload.folder}/{payload.sid}": {"new": payload.path}}
    return result
