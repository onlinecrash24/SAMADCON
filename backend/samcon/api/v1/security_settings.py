"""Security settings of one GPO — ``GptTmpl.inf``.

Computer configuration only. One setting at a time, because that is how the
file is edited and how a conflict is reported: the whole section is not the
unit anyone thinks in.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from samcon.ad.access import ad_read, ad_write
from samcon.api.common import Audit, DnQuery
from samcon.auth.deps import CurrentSession, VerifiedSession, VerifiedWorker, Worker
from samcon.gpo import security, security_catalogue
from samcon.schemas.requests import SetRestrictedGroupRequest, SetSecurityValueRequest

router = APIRouter(prefix="/gpos/security", tags=["group-policy"])


@router.get("/catalogue")
async def catalogue() -> dict[str, Any]:
    """Which settings the editor offers, and what shape each one has.

    The file carries no types — everything in it is text — so this is where
    the editor learns that a lockout duration counts minutes and an audit
    category has four states.
    """
    return security_catalogue.describe()


@router.get("")
async def read_settings(
    worker: Worker,
    session: CurrentSession,
    dn: DnQuery,
) -> dict[str, Any]:
    """Everything this policy sets, with user rights resolved to accounts."""

    def _run(conn: Any) -> dict[str, Any]:
        return security.read(conn, dn)

    return await ad_read(worker, session, _run, label="security.read")


@router.post("")
async def set_setting(
    payload: SetSecurityValueRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    """Set or clear one setting, and register the extension that applies it."""
    with audit.operation("security.set", target=dn) as record:

        def _run(conn: Any) -> dict[str, Any]:
            return security.write(
                conn,
                dn,
                payload.section,
                payload.key,
                payload.value,
                expected_version=payload.expected_version,
            )

        result = await ad_write(worker, session, _run, label="security.set")
        record["changes"] = {f"{payload.section}\\{payload.key}": {"new": payload.value}}
    return result


@router.post("/restricted-group")
async def set_restricted_group(
    payload: SetRestrictedGroupRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    """Add or remove a restricted group, both of its keys at once."""
    with audit.operation("security.restricted_group", target=dn) as record:

        def _run(conn: Any) -> dict[str, Any]:
            return security.set_restricted_group(
                conn,
                dn,
                payload.sid,
                present=payload.present,
                expected_version=payload.expected_version,
            )

        result = await ad_write(worker, session, _run, label="security.restricted_group")
        record["changes"] = {
            payload.sid: {"new": "restricted" if payload.present else None}
        }
    return result
