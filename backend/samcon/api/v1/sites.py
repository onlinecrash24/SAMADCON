"""Sites, subnets and site links."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from samcon.ad import sites
from samcon.ad.access import ad_read, ad_write
from samcon.api.common import Audit, DnQuery
from samcon.auth.deps import CurrentSession, VerifiedSession, VerifiedWorker, Worker
from samcon.schemas.requests import (
    CreateSiteLinkRequest,
    CreateSiteRequest,
    CreateSubnetRequest,
    MoveServerRequest,
    RenameSiteRequest,
    UpdateSiteLinkRequest,
    UpdateSiteRequest,
    UpdateSubnetRequest,
)

router = APIRouter(prefix="/sites", tags=["sites"])


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


@router.get("/topology")
async def topology(worker: Worker, session: CurrentSession) -> dict[str, Any]:
    """Sites, subnets and links in one response.

    They reference each other by DN; fetching them separately would leave the
    front end stitching together snapshots taken at different moments.
    """
    return await ad_read(worker, session, sites.topology, label="sites.topology")


# ---------------------------------------------------------------------------
# Sites
# ---------------------------------------------------------------------------


@router.get("")
async def list_sites(worker: Worker, session: CurrentSession) -> dict[str, Any]:
    found = await ad_read(worker, session, sites.list_sites, label="sites.list")
    return {"sites": found}


@router.get("/site")
async def get_site(worker: Worker, session: CurrentSession, dn: DnQuery) -> dict[str, Any]:
    return await ad_read(worker, session, sites.get_site, dn, label="sites.get")


@router.post("")
async def create_site(
    payload: CreateSiteRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
) -> dict[str, Any]:
    with audit.operation("sites.create") as record:
        created = await ad_write(
            worker,
            session,
            sites.create_site,
            payload.name,
            description=payload.description,
            label="sites.create",
        )
        record["target"] = created["dn"]
        record["changes"] = {"name": {"new": payload.name}}
    return created


@router.patch("")
async def update_site(
    payload: UpdateSiteRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    with audit.operation("sites.update", target=dn) as record:
        applied = await ad_write(
            worker,
            session,
            sites.update_site,
            dn,
            description=payload.description,
            location=payload.location,
            label="sites.update",
        )
        record["changes"] = applied
    return {"dn": dn, "applied": applied}


@router.post("/rename")
async def rename_site(
    payload: RenameSiteRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    with audit.operation("sites.rename", target=dn) as record:
        renamed = await ad_write(
            worker, session, sites.rename_site, dn, payload.name, label="sites.rename"
        )
        record["changes"] = {"name": {"old": dn, "new": renamed["dn"]}}
    return renamed


@router.delete("")
async def delete_site(
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    """Delete a site. Refused while DCs or subnets still point at it."""
    with audit.operation("sites.delete", target=dn):
        await ad_write(worker, session, sites.delete_site, dn, label="sites.delete")
    return {"dn": dn, "deleted": True}


# ---------------------------------------------------------------------------
# Subnets
# ---------------------------------------------------------------------------


@router.get("/subnets")
async def list_subnets(worker: Worker, session: CurrentSession) -> dict[str, Any]:
    found = await ad_read(worker, session, sites.list_subnets, label="sites.subnets")
    return {"subnets": found}


@router.post("/subnets")
async def create_subnet(
    payload: CreateSubnetRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
) -> dict[str, Any]:
    with audit.operation("sites.create_subnet") as record:
        created = await ad_write(
            worker,
            session,
            sites.create_subnet,
            payload.name,
            site_dn=payload.site_dn,
            description=payload.description,
            location=payload.location,
            label="sites.create_subnet",
        )
        record["target"] = created["dn"]
        record["changes"] = {
            "subnet": {"new": created["name"]},
            "site": {"new": created["site"]},
        }
    return created


@router.patch("/subnets")
async def update_subnet(
    payload: UpdateSubnetRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    with audit.operation("sites.update_subnet", target=dn) as record:
        applied = await ad_write(
            worker,
            session,
            sites.update_subnet,
            dn,
            site_dn=payload.site_dn,
            description=payload.description,
            location=payload.location,
            clear_site=payload.clear_site,
            label="sites.update_subnet",
        )
        record["changes"] = applied
    return {"dn": dn, "applied": applied}


@router.delete("/subnets")
async def delete_subnet(
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    with audit.operation("sites.delete_subnet", target=dn):
        await ad_write(worker, session, sites.delete_subnet, dn, label="sites.delete_subnet")
    return {"dn": dn, "deleted": True}


# ---------------------------------------------------------------------------
# Servers
# ---------------------------------------------------------------------------


@router.get("/servers")
async def list_servers(worker: Worker, session: CurrentSession, dn: DnQuery) -> dict[str, Any]:
    """The domain controllers in one site."""
    found = await ad_read(worker, session, sites.list_servers, dn, label="sites.servers")
    return {"site_dn": dn, "servers": found}


@router.get("/connections")
async def list_connections(worker: Worker, session: CurrentSession, dn: DnQuery) -> dict[str, Any]:
    """Replication connections into a server. Read-only: the KCC owns these."""
    found = await ad_read(worker, session, sites.list_connections, dn, label="sites.connections")
    return {"server_dn": dn, "connections": found}


@router.post("/servers/move")
async def move_server(
    payload: MoveServerRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    """Move a domain controller into another site.

    Clients pick their DC by site, so this changes who they talk to.
    """
    with audit.operation("sites.move_server", target=dn) as record:
        moved = await ad_write(
            worker, session, sites.move_server, dn, payload.site_dn, label="sites.move_server"
        )
        record["changes"] = {"site": {"old": dn, "new": moved["dn"]}}
    return moved


# ---------------------------------------------------------------------------
# Site links
# ---------------------------------------------------------------------------


@router.get("/links")
async def list_links(worker: Worker, session: CurrentSession) -> dict[str, Any]:
    found = await ad_read(worker, session, sites.list_site_links, label="sites.links")
    return {"links": found}


@router.post("/links")
async def create_link(
    payload: CreateSiteLinkRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
) -> dict[str, Any]:
    with audit.operation("sites.create_link") as record:
        created = await ad_write(
            worker,
            session,
            sites.create_site_link,
            payload.name,
            site_dns=payload.site_dns,
            transport=payload.transport,
            cost=payload.cost if payload.cost is not None else 100,
            replication_interval=(
                payload.replication_interval if payload.replication_interval is not None else 180
            ),
            description=payload.description,
            label="sites.create_link",
        )
        record["target"] = created["dn"]
        record["changes"] = {
            "link": {"new": created["name"]},
            "sites": {"new": ", ".join(created["sites"])},
        }
    return created


@router.patch("/links")
async def update_link(
    payload: UpdateSiteLinkRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    with audit.operation("sites.update_link", target=dn) as record:
        applied = await ad_write(
            worker,
            session,
            sites.update_site_link,
            dn,
            site_dns=payload.site_dns,
            cost=payload.cost,
            replication_interval=payload.replication_interval,
            description=payload.description,
            label="sites.update_link",
        )
        record["changes"] = applied
    return {"dn": dn, "applied": applied}


@router.delete("/links")
async def delete_link(
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    with audit.operation("sites.delete_link", target=dn):
        await ad_write(worker, session, sites.delete_site_link, dn, label="sites.delete_link")
    return {"dn": dn, "deleted": True}
