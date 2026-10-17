"""The domain and forest functional level, and what a raise needs.

Read-only. A Samba DC does not let msDS-Behavior-Version be written over
LDAP; the raise is samba-tool on the DC, and this shows the command once the
domain is ready for it. See samadcon.ad.functional_level.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from samadcon.ad import functional_level
from samadcon.ad.access import ad_read
from samadcon.auth.deps import CurrentSession, Worker

router = APIRouter(prefix="/functional-level", tags=["functional-level"])


@router.get("")
async def show(worker: Worker, session: CurrentSession) -> dict[str, Any]:
    """The levels, every DC's, the prep and schema, and what each higher level needs."""
    return await ad_read(worker, session, functional_level.overview, label="functional_level")
