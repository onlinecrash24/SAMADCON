"""Tree navigation, object lists, search and generic object operations."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from samadcon.ad import directory
from samadcon.ad.access import ad_read, ad_write
from samadcon.api.common import Audit, DnQuery, split_csv
from samadcon.auth.deps import CurrentSession, VerifiedSession, VerifiedWorker, Worker
from samadcon.schemas.requests import AttributeUpdateRequest, MoveRequest, RenameRequest

router = APIRouter(prefix="/directory", tags=["directory"])


@router.get("/roots")
async def roots(worker: Worker, session: CurrentSession) -> dict[str, Any]:
    """Naming contexts the tree can be rooted at."""
    contexts = await ad_read(worker, session, directory.naming_contexts, label="directory.roots")
    return {"roots": contexts}


@router.get("/tree")
async def tree(
    worker: Worker,
    session: CurrentSession,
    dn: DnQuery,
    advanced: Annotated[bool, Query(description="Include objects marked advanced-only")] = False,
) -> dict[str, Any]:
    """Container objects one level below *dn*."""
    nodes = await ad_read(
        worker,
        session,
        directory.list_tree_children,
        dn,
        include_advanced=advanced,
        label="directory.tree",
    )
    return {"parent": dn, "nodes": nodes}


@router.get("/children")
async def children(
    worker: Worker,
    session: CurrentSession,
    dn: DnQuery,
    types: Annotated[str | None, Query(description="Comma-separated object types")] = None,
    q: Annotated[str | None, Query(description="Free-text filter (ANR)")] = None,
    advanced: bool = False,
    limit: Annotated[int, Query(ge=1, le=10000)] = 2000,
) -> dict[str, Any]:
    """Objects directly below *dn* — the list pane."""
    return await ad_read(
        worker,
        session,
        directory.list_children,
        dn,
        types=split_csv(types),
        query=q,
        include_advanced=advanced,
        max_results=limit,
        label="directory.children",
    )


@router.get("/search")
async def search(
    worker: Worker,
    session: CurrentSession,
    q: Annotated[str | None, Query(description="Free-text query (ANR)")] = None,
    base: Annotated[str | None, Query(description="Search base; defaults to the domain")] = None,
    types: Annotated[str | None, Query(description="Comma-separated object types")] = None,
    scope: Annotated[str, Query(pattern="^(base|one|subtree)$")] = "subtree",
    limit: Annotated[int, Query(ge=1, le=10000)] = 2000,
) -> dict[str, Any]:
    return await ad_read(
        worker,
        session,
        directory.search_objects,
        base=base,
        query=q,
        types=split_csv(types),
        scope=directory.base_scope(scope),
        max_results=limit,
        label="directory.search",
    )


@router.get("/object")
async def get_object(worker: Worker, session: CurrentSession, dn: DnQuery) -> dict[str, Any]:
    return await ad_read(worker, session, directory.get_object, dn, label="directory.get")


@router.get("/object/attributes")
async def get_attributes(worker: Worker, session: CurrentSession, dn: DnQuery) -> dict[str, Any]:
    """Every attribute of an object — the raw attribute editor."""
    return await ad_read(
        worker, session, directory.get_attributes, dn, label="directory.attributes"
    )


@router.get("/object/path")
async def get_path(worker: Worker, session: CurrentSession, dn: DnQuery) -> dict[str, Any]:
    """Breadcrumb from the domain root down to *dn*."""
    path = await ad_read(worker, session, directory.get_ancestors, dn, label="directory.path")
    return {"dn": dn, "path": path}


@router.patch("/object/attributes")
async def update_attributes(
    payload: AttributeUpdateRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    """Write raw attributes.

    The generic escape hatch for everything the typed editors do not cover.
    Protected attributes are refused rather than sent to the DC.
    """
    from samadcon.core.errors import InvalidRequest

    protected = [
        name for name in payload.attributes if name.lower() in directory_protected_attributes()
    ]
    if protected:
        raise InvalidRequest(
            "These attributes are managed by the directory and cannot be edited here.",
            code="protected_attribute",
            context={"attributes": protected},
        )

    with audit.operation("directory.update_attributes", target=dn) as record:
        applied = await ad_write(
            worker,
            session,
            lambda conn: conn.modify_attributes(dn, payload.attributes),
            label="directory.update_attributes",
        )
        record["changes"] = applied
    return {"dn": dn, "applied": applied}


@router.post("/object/move")
async def move(
    payload: MoveRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    with audit.operation("directory.move", target=dn, target_dn=payload.target_dn) as record:
        new_dn = await ad_write(
            worker, session, directory.move_object, dn, payload.target_dn, label="directory.move"
        )
        record["changes"] = {"dn": {"old": dn, "new": new_dn}}
    return {"dn": new_dn, "previous_dn": dn}


@router.post("/object/rename")
async def rename(
    payload: RenameRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    with audit.operation("directory.rename", target=dn) as record:
        new_dn = await ad_write(
            worker, session, directory.rename_object, dn, payload.name, label="directory.rename"
        )
        record["changes"] = {"dn": {"old": dn, "new": new_dn}}
    return {"dn": new_dn, "previous_dn": dn}


@router.delete("/object")
async def delete(
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
    recursive: Annotated[bool, Query(description="Delete child objects as well")] = False,
) -> dict[str, Any]:
    with audit.operation("directory.delete", target=dn, recursive=recursive):
        await ad_write(
            worker,
            session,
            directory.delete_object,
            dn,
            recursive=recursive,
            label="directory.delete",
        )
    return {"dn": dn, "deleted": True}


@router.get("/resolve")
async def resolve(
    worker: Worker,
    session: CurrentSession,
    identifier: Annotated[str, Query(description="DN, SID, GUID or sAMAccountName")],
) -> dict[str, Any]:
    dn = await ad_read(
        worker, session, directory.resolve_name, identifier, label="directory.resolve"
    )
    return {"identifier": identifier, "dn": dn}


def directory_protected_attributes() -> frozenset[str]:
    from samadcon.ad.users import PROTECTED_ATTRS

    return PROTECTED_ATTRS
