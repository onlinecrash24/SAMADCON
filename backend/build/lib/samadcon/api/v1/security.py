"""Object permissions and delegation."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from samadcon.ad import delegation, sacl
from samadcon.ad.access import ad_read, ad_write
from samadcon.api.common import Audit, DnQuery
from samadcon.auth.deps import CurrentSession, VerifiedSession, VerifiedWorker, Worker
from samadcon.schemas.requests import (
    AddAceRequest,
    DelegateRequest,
    DeleteProtectionRequest,
    RemoveAceRequest,
)

router = APIRouter(prefix="/security", tags=["security"])


@router.get("/acl")
async def read_acl(worker: Worker, session: CurrentSession, dn: DnQuery) -> dict[str, Any]:
    """The object's permissions with SIDs and GUIDs resolved to names.

    The returned `sddl` is passed back on write so a concurrent change is
    caught instead of silently overwritten.
    """
    return await ad_read(worker, session, sacl.read_acl, dn, label="security.read_acl")


@router.post("/acl/entries")
async def add_entry(
    payload: AddAceRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    """Grant or deny a set of rights to one account."""
    ace = sacl.build_ace(
        trustee_sid=payload.trustee_sid,
        mask=payload.mask,
        deny=payload.deny,
        object_guid=payload.object_guid,
        applies_to_guid=payload.applies_to_guid,
        inherit_to_children=payload.inherit_to_children,
    )

    with audit.operation("security.add_ace", target=dn, ace=ace) as record:
        result = await ad_write(
            worker,
            session,
            sacl.add_ace,
            dn,
            ace=ace,
            expected_sddl=payload.expected_sddl,
            label="security.add_ace",
        )
        record["changes"] = {"dacl": {"added": ace}}
    return result


@router.delete("/acl/entries")
async def remove_entry(
    payload: RemoveAceRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    """Remove one permission entry, identified by its position in the ACL."""
    with audit.operation("security.remove_ace", target=dn) as record:
        result = await ad_write(
            worker,
            session,
            sacl.remove_ace,
            dn,
            index=payload.index,
            expected_sddl=payload.expected_sddl,
            label="security.remove_ace",
        )
        record["changes"] = {"dacl": {"removed": result.get("removed")}}
    return result


@router.get("/delegation/templates")
def delegation_templates() -> dict[str, Any]:
    """The delegation tasks the UI offers, mirroring ADUC's wizard."""
    return {"templates": delegation.describe_templates()}


@router.post("/delegation")
async def delegate(
    payload: DelegateRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    """Grant a delegation task to an account on this container.

    A task expands to several ACEs. They are applied one after another; if one
    fails, the earlier ones stay — the operation reports what was applied
    rather than pretending it was atomic, because LDAP gives us no transaction
    to make that true.
    """
    aces = delegation.build_aces(payload.template_id, payload.trustee_sid)

    applied: list[str] = []
    with audit.operation(
        "security.delegate", target=dn, template=payload.template_id
    ) as record:
        try:
            expected = payload.expected_sddl
            for ace in aces:
                await ad_write(
                    worker,
                    session,
                    sacl.add_ace,
                    dn,
                    ace=ace,
                    # Only the first write can check against what the caller
                    # saw; the later ones follow our own change.
                    expected_sddl=expected,
                    label="security.delegate",
                )
                applied.append(ace)
                expected = None
        finally:
            record["changes"] = {"dacl": {"added": applied}}

    return {"dn": dn, "template_id": payload.template_id, "applied": applied}


@router.get("/protection")
async def read_protection(
    worker: Worker, session: CurrentSession, dn: DnQuery
) -> dict[str, Any]:
    """Whether the object is protected against accidental deletion."""
    return await ad_read(
        worker, session, sacl.describe_protection, dn, label="security.protection"
    )


@router.post("/protection")
async def set_protection(
    payload: DeleteProtectionRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    with audit.operation("security.set_protection", target=dn, protect=payload.protect) as record:
        changed = await ad_write(
            worker,
            session,
            sacl.set_delete_protection,
            dn,
            payload.protect,
            label="security.set_protection",
        )
        record["changes"] = {"delete_protected": {"new": payload.protect}}
    return {"dn": dn, "delete_protected": payload.protect, "changed": changed}
