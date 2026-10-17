"""The domain and forest functional level: shown, and raised.

A router of its own because diagnostics is read-only by design, and this is
the one write in the console that cannot be undone. The rules and the
readiness checks live in samadcon.ad.functional_level.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from samadcon.ad import functional_level
from samadcon.ad.access import ad_read, ad_write
from samadcon.api.common import Audit
from samadcon.auth.deps import CurrentSession, VerifiedSession, VerifiedWorker, Worker
from samadcon.schemas.requests import FunctionalLevelRequest

router = APIRouter(prefix="/functional-level", tags=["functional-level"])


@router.get("")
async def show(worker: Worker, session: CurrentSession) -> dict[str, Any]:
    """The levels, every DC's, the prep and schema, and what each higher level needs."""
    return await ad_read(worker, session, functional_level.overview, label="functional_level")


@router.put("")
async def raise_levels(
    payload: FunctionalLevelRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
) -> dict[str, Any]:
    """Raise the domain and/or the forest. Cannot be undone."""
    request = payload.model_dump()
    with audit.operation(
        "domain.functional_level",
        domain_level=request["domain_level"],
        forest_level=request["forest_level"],
    ) as record:
        result = await ad_write(
            worker,
            session,
            functional_level.raise_levels,
            label="domain.functional_level",
            **request,
        )
        record["changes"] = result["applied"]
    return result["levels"]
