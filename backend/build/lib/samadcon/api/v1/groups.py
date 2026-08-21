"""Groups and membership."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from samadcon.ad import groups
from samadcon.ad.access import ad_read, ad_write
from samadcon.api.common import Audit, DnQuery
from samadcon.auth.deps import CurrentSession, VerifiedSession, VerifiedWorker, Worker
from samadcon.schemas.requests import CreateGroupRequest, MembersRequest, UpdateGroupRequest

router = APIRouter(prefix="/groups", tags=["groups"])


@router.get("")
async def get_group(worker: Worker, session: CurrentSession, dn: DnQuery) -> dict[str, Any]:
    return await ad_read(worker, session, groups.get_group, dn, label="group.get")


@router.post("")
async def create_group(
    payload: CreateGroupRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
) -> dict[str, Any]:
    with audit.operation("group.create", target=payload.parent_dn) as record:
        created = await ad_write(
            worker,
            session,
            groups.create_group,
            parent_dn=payload.parent_dn,
            name=payload.name,
            sam_account_name=payload.sam_account_name,
            scope=payload.scope,
            security=payload.security,
            description=payload.description,
            label="group.create",
        )
        record["target"] = created["dn"]
        record["changes"] = {
            "name": {"new": payload.name},
            "scope": {"new": payload.scope},
            "security": {"new": payload.security},
        }
    return created


@router.patch("")
async def update_group(
    payload: UpdateGroupRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    with audit.operation("group.update", target=dn) as record:
        applied = await ad_write(
            worker,
            session,
            groups.update_group,
            dn,
            attributes=payload.attributes,
            scope=payload.scope,
            security=payload.security,
            label="group.update",
        )
        record["changes"] = applied
    return {"dn": dn, "applied": applied}


@router.get("/members")
async def list_members(
    worker: Worker,
    session: CurrentSession,
    dn: DnQuery,
    recursive: Annotated[bool, Query(description="Resolve nested groups")] = False,
    include_primary: Annotated[
        bool, Query(description="Include accounts whose primary group this is")
    ] = True,
) -> dict[str, Any]:
    """Members of a group.

    ``include_primary`` matters for the built-in groups: primary membership
    lives on the member object, so "Domain Users" looks empty without it.
    """
    return await ad_read(
        worker,
        session,
        groups.list_members,
        dn,
        recursive=recursive,
        include_primary=include_primary,
        label="group.members",
    )


@router.post("/members")
async def add_members(
    payload: MembersRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    with audit.operation("group.add_members", target=dn) as record:
        result = await ad_write(
            worker, session, groups.add_members, dn, payload.members, label="group.add_members"
        )
        record["changes"] = {"member": {"added": result["added"]}}
    return {"dn": dn, **result}


@router.delete("/members")
async def remove_members(
    payload: MembersRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    with audit.operation("group.remove_members", target=dn) as record:
        result = await ad_write(
            worker,
            session,
            groups.remove_members,
            dn,
            payload.members,
            label="group.remove_members",
        )
        record["changes"] = {"member": {"removed": result["removed"]}}
    return {"dn": dn, **result}


@router.get("/member-of")
async def member_of(
    worker: Worker,
    session: CurrentSession,
    dn: DnQuery,
    recursive: Annotated[bool, Query(description="Include indirect memberships")] = False,
) -> dict[str, Any]:
    """Groups an object belongs to, including its primary group."""
    result = await ad_read(
        worker, session, groups.list_member_of, dn, recursive=recursive, label="group.member_of"
    )
    return {"dn": dn, "groups": result, "recursive": recursive}
