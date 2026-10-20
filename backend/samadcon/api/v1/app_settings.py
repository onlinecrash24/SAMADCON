"""SAMADCON's own settings, kept in the domain (samadcon.ad.app_settings)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from samadcon.ad import app_settings
from samadcon.ad.access import ad_read, ad_write
from samadcon.api.common import Audit
from samadcon.auth.deps import CurrentSession, VerifiedSession, VerifiedWorker, Worker
from samadcon.schemas.requests import AppSettingsRequest

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
async def read_settings(worker: Worker, session: CurrentSession) -> dict[str, Any]:
    """The settings, where they live, and whether this account may change them."""
    return await ad_read(worker, session, app_settings.read, label="settings.read")


@router.put("")
async def write_settings(
    payload: AppSettingsRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
) -> dict[str, Any]:
    """Save, refused if someone else saved since *expected* was read."""
    with audit.operation(
        "settings.write", required_user_fields=payload.required_user_fields
    ) as record:
        result = await ad_write(
            worker,
            session,
            app_settings.write,
            required_fields=payload.required_user_fields,
            expected=payload.expected,
            label="settings.write",
        )
        record["changes"] = {"users.required_fields": payload.required_user_fields}
    return result
