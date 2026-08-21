"""Group policy preferences — the "Einstellungen" branch of the editor.

One file per type per half on SYSVOL, each with its own client-side extension.
Wave one covers drive maps, registry values and files; the ``/types`` endpoint
says which are available rather than the editor assuming, so adding one is a
change in the catalogue and nowhere else.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from samadcon.ad.access import ad_read, ad_write
from samadcon.api.common import Audit, DnQuery
from samadcon.auth.deps import CurrentSession, VerifiedSession, VerifiedWorker, Worker
from samadcon.gpo import preferences
from samadcon.schemas.requests import SetPreferenceItemsRequest

router = APIRouter(prefix="/gpos/preferences", tags=["group-policy"])

TypeQuery = Annotated[str, Query(min_length=1, max_length=32, pattern=r"^[a-z_]+$")]
HalfQuery = Annotated[str, Query(pattern=r"^(Machine|User)$")]


@router.get("/types")
async def types() -> dict[str, Any]:
    """Which preference types the editor offers, and what each one holds."""
    return {
        "actions": list(preferences.ACTIONS),
        "types": [
            {
                "id": preference.id,
                "halves": list(preference.halves),
                # Several kinds only for printers, where a shared, a port and
                # a local printer share one file and do not share a half.
                "kinds": [
                    {
                        "id": kind.id,
                        "halves": list(kind.halves),
                        # A kind without an action has none to offer; one that
                        # cannot be created is read and edited but never added.
                        "has_action": kind.has_action,
                        "creatable": kind.creatable,
                        "fields": [
                            {
                                "name": field.name,
                                "kind": field.kind,
                                "default": field.default,
                                "choices": list(field.choices),
                            }
                            for field in kind.fields
                            # The action has its own control in the editor's
                            # heading, and a secret is never offered at all.
                            if field.kind not in ("action", "secret")
                        ],
                    }
                    for kind in preference.kinds
                ],
            }
            for preference in preferences.TYPES.values()
        ],
    }


@router.get("")
async def read_all(worker: Worker, session: CurrentSession, dn: DnQuery) -> dict[str, Any]:
    """Every preference type of one GPO, both halves."""

    def _run(conn: Any) -> dict[str, Any]:
        return preferences.read_all(conn, dn)

    return await ad_read(worker, session, _run, label="preferences.read")


@router.get("/type")
async def read_one(
    worker: Worker,
    session: CurrentSession,
    dn: DnQuery,
    type: TypeQuery,
    half: HalfQuery,
) -> dict[str, Any]:
    """One preference type, with the version to write back against."""

    def _run(conn: Any) -> dict[str, Any]:
        return preferences.read(conn, dn, type, half)

    return await ad_read(worker, session, _run, label="preferences.read_one")


@router.post("")
async def set_items(
    payload: SetPreferenceItemsRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    """Replace one preference type's items."""
    with audit.operation("preferences.set", target=dn) as record:

        def _run(conn: Any) -> dict[str, Any]:
            return preferences.write(
                conn,
                dn,
                payload.type,
                payload.half,
                payload.items,
                expected_version=payload.expected_version,
            )

        result = await ad_write(worker, session, _run, label="preferences.set")
        record["changes"] = {
            f"{payload.half}/{payload.type}": {"new": f"{len(payload.items)} items"}
        }
    return result
