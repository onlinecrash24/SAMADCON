"""Administrative templates: the central store, the policy tree, and editing.

Reading a policy's definition and reading its state in a GPO are separate
calls on purpose. The definitions are the same for the whole domain and are
cached; the state belongs to one GPO and changes under you.
"""

from __future__ import annotations

import io
import zipfile
from typing import Annotated, Any

from fastapi import APIRouter, File, Query, UploadFile

from samadcon.ad.access import ad_read, ad_write
from samadcon.api.common import Audit, DnQuery, OptionalDnQuery
from samadcon.auth.deps import CurrentSession, VerifiedSession, VerifiedWorker, Worker
from samadcon.core.errors import InvalidRequest, NotFound
from samadcon.gpo.admx import serialise, store, writer
from samadcon.gpo.admx.model import Catalogue, Policy
from samadcon.schemas.requests import ApplyPolicyRequest

router = APIRouter(prefix="/admx", tags=["administrative-templates"])

LanguageQuery = Annotated[str | None, Query(max_length=16, description="e.g. de-DE")]
HalfQuery = Annotated[str | None, Query(pattern="^(Machine|User)$")]

# An upload is a handful of XML files. The ceiling stops a wrong file from
# being read into memory whole.
MAX_UPLOAD_BYTES = 64 * 1024 * 1024


def _find_policy(catalogue: Catalogue, policy_id: str) -> Policy:
    policy = catalogue.policies.get(policy_id)
    if policy is None:
        raise NotFound(
            "This setting is not in the installed templates.",
            code="policy_not_found",
            hint="The template that defines it may not be in the central store.",
            context={"policy": policy_id},
        )
    return policy


# ---------------------------------------------------------------------------
# The central store
# ---------------------------------------------------------------------------


@router.get("/store")
async def describe_store(worker: Worker, session: CurrentSession) -> dict[str, Any]:
    """What templates are installed, without parsing them."""
    return await ad_read(worker, session, store.describe, label="admx.store")


@router.post("/store")
async def upload_templates(
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    files: Annotated[list[UploadFile], File(description=".admx, .adml or a ZIP of both")],
    overwrite: Annotated[bool, Query(description="Replace templates already there")] = False,
) -> dict[str, Any]:
    """Add templates to the central store, creating it if there is none."""
    payload: dict[str, bytes] = {}
    total = 0

    for upload in files:
        data = await upload.read()
        total += len(data)
        if total > MAX_UPLOAD_BYTES:
            raise InvalidRequest(
                "These files are too large.",
                code="upload_too_large",
                context={"limit_bytes": MAX_UPLOAD_BYTES},
            )

        name = upload.filename or ""
        if name.lower().endswith(".zip"):
            payload.update(_unpack(data))
        else:
            payload[name] = data

    with audit.operation("admx.upload") as record:
        result = await ad_write(
            worker, session, store.upload, payload, overwrite=overwrite, label="admx.upload"
        )
        record["target"] = result["path"]
        record["changes"] = {"templates": {"new": ", ".join(result["added"])}}
    return result


def _unpack(data: bytes) -> dict[str, bytes]:
    """The files inside a template package.

    Packages are shipped as ZIPs with the language directories inside, which
    is the shape the store wants anyway. Which members are acceptable is
    decided by the store, not here.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise InvalidRequest(
            "This file is not a template package.", code="invalid_package"
        ) from exc

    unpacked: dict[str, bytes] = {}
    for info in archive.infolist():
        if info.is_dir() or info.file_size > MAX_UPLOAD_BYTES:
            continue
        unpacked[info.filename] = archive.read(info)
    return unpacked


@router.post("/refresh")
async def refresh(worker: Worker, session: CurrentSession) -> dict[str, Any]:
    """Re-read the templates.

    The cache notices a changed directory on its own; this is for the case it
    cannot see — a file replaced by one of the same size and timestamp.
    """

    def _run(conn: Any) -> dict[str, Any]:
        store.forget(conn.info.dns_domain)
        return store.catalogue_for(conn, refresh=True).summary()

    return await ad_read(worker, session, _run, label="admx.refresh")


# ---------------------------------------------------------------------------
# The policy tree
# ---------------------------------------------------------------------------


@router.get("/tree")
async def tree(
    worker: Worker,
    session: CurrentSession,
    category: Annotated[str | None, Query(max_length=512)] = None,
    half: HalfQuery = None,
    language: LanguageQuery = None,
    dn: OptionalDnQuery = None,
    configured: bool = False,
) -> dict[str, Any]:
    """One level of the tree: the categories below a node, and its settings.

    With a GPO named in *dn* each setting also carries what that GPO says
    about it — the status column of the listing. It rides along here rather
    than in a call of its own because the whole level is answered by a single
    read of the ``Registry.pol``.

    With *configured* the level is cut down to what this GPO actually sets.
    That cannot be decided in the browser: it holds one level of the tree,
    and a branch worth showing may have its settings three levels further
    down. Answering it here costs one extra pass over the catalogue in
    memory — the ``Registry.pol`` is read once either way.
    """

    def _run(conn: Any) -> dict[str, Any]:
        catalogue = store.catalogue_for(conn, language=language)
        states = None
        chosen: set[str] | None = None

        if dn and half and configured:
            everything = [
                policy for policy in catalogue.policies.values() if half in policy.halves
            ]
            states = writer.states_for(conn, dn, everything, half)
            chosen = {
                policy_id
                for policy_id, state in states.items()
                if state != "not_configured"
            }
        elif dn and half and category:
            states = writer.states_for(
                conn, dn, catalogue.policies_in(category, policy_class=half), half
            )

        return {
            **serialise.tree_json(
                catalogue, category, half=half, states=states, configured=chosen
            ),
            "language": catalogue.language,
        }

    return await ad_read(worker, session, _run, label="admx.tree")


@router.get("/policy")
async def policy(
    worker: Worker,
    session: CurrentSession,
    id: Annotated[str, Query(min_length=1, max_length=512)],
    language: LanguageQuery = None,
) -> dict[str, Any]:
    """One setting's definition, with everything its form needs."""

    def _run(conn: Any) -> dict[str, Any]:
        catalogue = store.catalogue_for(conn, language=language)
        return serialise.policy_json(_find_policy(catalogue, id), catalogue, full=True)

    return await ad_read(worker, session, _run, label="admx.policy")


@router.get("/search")
async def search(
    worker: Worker,
    session: CurrentSession,
    q: Annotated[str, Query(min_length=2, max_length=200)],
    half: HalfQuery = None,
    language: LanguageQuery = None,
    dn: OptionalDnQuery = None,
) -> dict[str, Any]:
    """Settings whose name or explanation mentions the term."""

    def _run(conn: Any) -> dict[str, Any]:
        catalogue = store.catalogue_for(conn, language=language)
        found = [
            item
            for item in catalogue.search(q)
            if half is None or half in item.halves
        ]
        states = writer.states_for(conn, dn, found, half) if dn and half else None
        return {
            "query": q,
            "policies": [
                serialise.policy_json(item, state=states.get(item.id) if states else None)
                for item in found
            ],
        }

    return await ad_read(worker, session, _run, label="admx.search")


# ---------------------------------------------------------------------------
# A setting in one GPO
# ---------------------------------------------------------------------------


@router.get("/state")
async def read_state(
    worker: Worker,
    session: CurrentSession,
    dn: DnQuery,
    id: Annotated[str, Query(min_length=1, max_length=512)],
    half: Annotated[str, Query(pattern="^(Machine|User)$")],
    language: LanguageQuery = None,
) -> dict[str, Any]:
    """What a GPO currently says about one setting.

    The version number comes with it and is passed back when saving, so two
    administrators editing the same policy do not overwrite each other
    silently.
    """

    def _run(conn: Any) -> dict[str, Any]:
        catalogue = store.catalogue_for(conn, language=language)
        return writer.read_state(conn, dn, _find_policy(catalogue, id), half)

    return await ad_read(worker, session, _run, label="admx.state")


@router.post("/state")
async def apply_state(
    payload: ApplyPolicyRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    """Set a policy in a GPO, and register the extension that applies it."""
    with audit.operation("admx.apply", target=dn) as record:

        def _run(conn: Any) -> dict[str, Any]:
            catalogue = store.catalogue_for(conn)
            policy = _find_policy(catalogue, payload.policy)
            return writer.apply_state(
                conn,
                dn,
                policy,
                payload.half,
                payload.state,
                payload.values,
                expected_version=payload.expected_version,
            )

        result = await ad_write(worker, session, _run, label="admx.apply")
        record["changes"] = {
            payload.policy: {"new": f"{payload.state} ({payload.half.lower()} half)"}
        }
    return result
