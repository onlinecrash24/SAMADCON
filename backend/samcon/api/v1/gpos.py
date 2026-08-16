"""Group policy objects, their links and what they apply to."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import HTMLResponse, Response

from samcon.ad.access import ad_read, ad_write
from samcon.api.common import Audit, DnQuery
from samcon.auth.deps import CurrentSession, VerifiedSession, VerifiedWorker, Worker
from samcon.core.errors import InvalidRequest
from samcon.gpo import container, gpmc, report, transfer, wmi
from samcon.schemas.requests import (
    AddGpoLinkRequest,
    AssignWmiFilterRequest,
    BlockInheritanceRequest,
    CopyGpoRequest,
    CreateGpoRequest,
    RemoveGpoLinkRequest,
    UpdateGpoLinkRequest,
    UpdateGpoRequest,
)

router = APIRouter(prefix="/gpos", tags=["group-policy"])


# ---------------------------------------------------------------------------
# The policies themselves
# ---------------------------------------------------------------------------


@router.get("")
async def list_gpos(worker: Worker, session: CurrentSession) -> dict[str, Any]:
    found = await ad_read(worker, session, container.list_gpos, label="gpo.list")
    return {"gpos": found}


@router.get("/gpo")
async def get_gpo(worker: Worker, session: CurrentSession, dn: DnQuery) -> dict[str, Any]:
    return await ad_read(worker, session, container.get_gpo, dn, label="gpo.get")


@router.get("/status")
async def gpo_status(worker: Worker, session: CurrentSession, dn: DnQuery) -> dict[str, Any]:
    """Whether the directory half and the SYSVOL half of a policy agree.

    Separate from the policy itself because it opens an SMB session, which a
    plain listing has no reason to do.
    """

    def _run(conn: Any) -> dict[str, Any]:
        return container.status(conn, container.get_gpo(conn, dn))

    return await ad_read(worker, session, _run, label="gpo.status")


@router.post("")
async def create_gpo(
    payload: CreateGpoRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
) -> dict[str, Any]:
    """Create a policy in the directory and on SYSVOL, with its permissions."""
    with audit.operation("gpo.create") as record:
        created = await ad_write(
            worker,
            session,
            container.create_gpo,
            payload.display_name,
            label="gpo.create",
        )
        record["target"] = created["dn"]
        record["changes"] = {
            "displayName": {"new": payload.display_name},
            "gPCFileSysPath": {"new": created["path"]},
        }
    return created


@router.patch("")
async def update_gpo(
    payload: UpdateGpoRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    with audit.operation("gpo.update", target=dn) as record:

        def _run(conn: Any) -> dict[str, Any]:
            result = container.get_gpo(conn, dn)
            if payload.display_name is not None:
                result = container.rename_gpo(conn, dn, payload.display_name)
            if payload.machine_enabled is not None or payload.user_enabled is not None:
                result = container.set_status(
                    conn,
                    dn,
                    machine_enabled=payload.machine_enabled,
                    user_enabled=payload.user_enabled,
                )
            return result

        updated = await ad_write(worker, session, _run, label="gpo.update")
        record["changes"] = {
            key: {"new": value}
            for key, value in (
                ("displayName", payload.display_name),
                ("machine_enabled", payload.machine_enabled),
                ("user_enabled", payload.user_enabled),
            )
            if value is not None
        }
    return updated


@router.delete("")
async def delete_gpo(
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
    force: Annotated[bool, Query(description="Delete even while links point at it")] = False,
) -> dict[str, Any]:
    """Delete a policy in both halves. Refused while it is still linked."""
    with audit.operation("gpo.delete", target=dn, force=force) as record:
        result = await ad_write(
            worker, session, container.delete_gpo, dn, force=force, label="gpo.delete"
        )
        record["changes"] = {"gpo": {"removed": result["name"]}}
    return result


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------


@router.get("/links")
async def get_links(worker: Worker, session: CurrentSession, dn: DnQuery) -> dict[str, Any]:
    """The policies linked to one container, in the order they take effect."""
    return await ad_read(worker, session, gpmc.get_links, dn, label="gpo.links")


@router.post("/links")
async def add_link(
    payload: AddGpoLinkRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    with audit.operation("gpo.link", target=dn) as record:
        result = await ad_write(
            worker,
            session,
            gpmc.add_link,
            dn,
            payload.gpo_dn,
            enabled=payload.enabled,
            enforced=payload.enforced,
            label="gpo.link",
        )
        record["changes"] = {
            "gPLink": {"new": f"{payload.gpo_dn} (enforced={payload.enforced})"}
        }
    return result


@router.patch("/links")
async def update_link(
    payload: UpdateGpoLinkRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    """Enable, enforce or reorder one link."""
    with audit.operation("gpo.update_link", target=dn) as record:
        result = await ad_write(
            worker,
            session,
            gpmc.update_link,
            dn,
            payload.gpo_dn,
            enabled=payload.enabled,
            enforced=payload.enforced,
            order=payload.order,
            label="gpo.update_link",
        )
        record["changes"] = {
            "gPLink": {
                "new": ", ".join(
                    f"{key}={value}"
                    for key, value in (
                        ("enabled", payload.enabled),
                        ("enforced", payload.enforced),
                        ("order", payload.order),
                    )
                    if value is not None
                )
            }
        }
    return result


@router.delete("/links")
async def remove_link(
    payload: RemoveGpoLinkRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    with audit.operation("gpo.unlink", target=dn) as record:
        result = await ad_write(
            worker, session, gpmc.remove_link, dn, payload.gpo_dn, label="gpo.unlink"
        )
        record["changes"] = {"gPLink": {"removed": payload.gpo_dn}}
    return result


@router.get("/linked")
async def find_links(
    worker: Worker,
    session: CurrentSession,
    guid: Annotated[str, Query(min_length=1, description="The policy's identifier")],
) -> dict[str, Any]:
    """Every container that links a policy — the question before deleting one."""
    found = await ad_read(worker, session, gpmc.find_links, guid, label="gpo.linked")
    return {"guid": guid, "links": found}


# ---------------------------------------------------------------------------
# Inheritance and filtering
# ---------------------------------------------------------------------------


@router.get("/inheritance")
async def inheritance(worker: Worker, session: CurrentSession, dn: DnQuery) -> dict[str, Any]:
    """Which policies reach a container, and which are stopped on the way."""
    return await ad_read(worker, session, gpmc.inheritance, dn, label="gpo.inheritance")


@router.post("/inheritance")
async def set_inheritance(
    payload: BlockInheritanceRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    with audit.operation("gpo.block_inheritance", target=dn, block=payload.block):
        return await ad_write(
            worker,
            session,
            gpmc.set_inheritance_block,
            dn,
            payload.block,
            label="gpo.block_inheritance",
        )


@router.get("/filtering")
async def filtering(worker: Worker, session: CurrentSession, dn: DnQuery) -> dict[str, Any]:
    """Who a policy applies to, and who has only half the rights it needs."""
    return await ad_read(worker, session, gpmc.get_filtering, dn, label="gpo.filtering")


# ---------------------------------------------------------------------------
# What a policy contains
# ---------------------------------------------------------------------------


@router.get("/report")
async def settings_report(
    worker: Worker, session: CurrentSession, dn: DnQuery
) -> dict[str, Any]:
    """Every setting the policy holds, read off SYSVOL."""
    return await ad_read(worker, session, report.build_report, dn, label="gpo.report")


@router.get("/report.html", response_class=HTMLResponse)
async def settings_report_html(
    worker: Worker, session: CurrentSession, dn: DnQuery
) -> HTMLResponse:
    """The same report as a standalone file, for a ticket or a change record."""
    data = await ad_read(worker, session, report.build_report, dn, label="gpo.report")
    name = data["gpo"]["display_name"] or data["gpo"]["guid"]
    return HTMLResponse(
        content=report.to_html(data),
        headers={"Content-Disposition": f'inline; filename="{_ascii_filename(name)}.html"'},
    )


# ---------------------------------------------------------------------------
# Copying and moving between domains
# ---------------------------------------------------------------------------


@router.post("/copy")
async def copy_gpo(
    payload: CopyGpoRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    """Duplicate a policy. Links are not copied — where it applies is a decision."""
    with audit.operation("gpo.copy", target=dn) as record:
        created = await ad_write(
            worker, session, transfer.copy_gpo, dn, payload.display_name, label="gpo.copy"
        )
        record["changes"] = {"copy": {"new": created["dn"]}}
    return created


@router.get("/backup")
async def backup_gpo(
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> Response:
    """Download a policy as a ZIP that ``samba-tool gpo restore`` also accepts."""
    with audit.operation("gpo.backup", target=dn):
        name, data = await ad_read(worker, session, transfer.backup_gpo, dn, label="gpo.backup")
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{_ascii_filename(name)}"'},
    )


@router.post("/restore")
async def restore_gpo(
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    archive: Annotated[UploadFile, File(description="A backup archive")],
    display_name: Annotated[str | None, Query(max_length=255)] = None,
) -> dict[str, Any]:
    """Create a policy from a backup — always a new one, never an overwrite."""
    data = await archive.read()
    if len(data) > transfer.MAX_BACKUP_BYTES:
        raise InvalidRequest(
            "This backup is too large.",
            code="backup_too_large",
            context={"limit_bytes": transfer.MAX_BACKUP_BYTES},
        )

    with audit.operation("gpo.restore") as record:
        created = await ad_write(
            worker,
            session,
            transfer.restore_gpo,
            data,
            display_name=display_name,
            label="gpo.restore",
        )
        record["target"] = created["dn"]
        record["changes"] = {"restored": {"new": created["display_name"]}}
    return created


# ---------------------------------------------------------------------------
# WMI filters
# ---------------------------------------------------------------------------


@router.get("/wmi-filters")
async def list_wmi_filters(worker: Worker, session: CurrentSession) -> dict[str, Any]:
    found = await ad_read(worker, session, wmi.list_filters, label="gpo.wmi_filters")
    return {"filters": found}


@router.get("/wmi-filter")
async def gpo_wmi_filter(
    worker: Worker, session: CurrentSession, dn: DnQuery
) -> dict[str, Any]:
    """The filter a policy uses, if any, resolved to its name and query."""

    def _run(conn: Any) -> dict[str, Any]:
        return {"filter": wmi.describe_for_gpo(conn, container.get_gpo(conn, dn))}

    return await ad_read(worker, session, _run, label="gpo.wmi_filter")


@router.post("/wmi-filter")
async def assign_wmi_filter(
    payload: AssignWmiFilterRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    with audit.operation("gpo.assign_wmi_filter", target=dn) as record:
        updated = await ad_write(
            worker, session, wmi.assign, dn, payload.filter_dn, label="gpo.assign_wmi_filter"
        )
        record["changes"] = {"gPCWQLFilter": {"new": payload.filter_dn}}
    return updated


def _ascii_filename(name: str) -> str:
    """A file name safe for a Content-Disposition header.

    The header is latin-1 only, and policy names carry umlauts often enough
    that a raw name breaks the download rather than merely looking odd.
    """
    cleaned = "".join(char if char.isalnum() or char in "-_. " else "_" for char in name)
    return cleaned.strip() or "policy"
