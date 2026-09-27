"""The advanced audit policy of one GPO — ``audit.csv``.

Computer configuration only. Its own routes rather than the security
settings': the file is a different one, in a different format, applied by a
different client-side extension.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from samadcon.ad.access import ad_read, ad_write
from samadcon.api.common import Audit, DnQuery
from samadcon.auth.deps import CurrentSession, VerifiedSession, VerifiedWorker, Worker
from samadcon.gpo import audit_csv
from samadcon.schemas.requests import SetAuditRequest

router = APIRouter(prefix="/gpos/audit", tags=["group-policy"])


@router.get("/catalogue")
async def catalogue() -> dict[str, Any]:
    """The categories and subcategories, with GUIDs and names in both languages."""
    return audit_csv.describe_catalogue()


@router.get("")
async def read_audit(worker: Worker, session: CurrentSession, dn: DnQuery) -> dict[str, Any]:
    """The configured subcategories of one policy."""

    def _run(conn: Any) -> dict[str, Any]:
        return audit_csv.read(conn, dn)

    return await ad_read(worker, session, _run, label="audit.read")


@router.post("")
async def set_audit(
    payload: SetAuditRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    """Set or clear subcategories, and register the extension that applies them."""
    with audit.operation("audit_policy.set", target=dn) as record:

        def _run(conn: Any) -> dict[str, Any]:
            return audit_csv.write(
                conn, dn, payload.changes, expected_version=payload.expected_version
            )

        result = await ad_write(worker, session, _run, label="audit_policy.set")
        record["changes"] = {guid: {"new": value} for guid, value in payload.changes.items()}
    return result
