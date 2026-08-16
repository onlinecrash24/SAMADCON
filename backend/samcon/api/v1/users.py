"""User accounts."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from samcon.ad import users
from samcon.ad.access import ad_read, ad_write
from samcon.api.common import Audit, DnQuery
from samcon.auth.deps import CurrentSession, VerifiedSession, VerifiedWorker, Worker
from samcon.schemas.requests import (
    AccountExpiryRequest,
    CreateUserRequest,
    EnabledRequest,
    MustChangePasswordRequest,
    SetPasswordRequest,
    UpdateUserRequest,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.get("")
async def get_user(worker: Worker, session: CurrentSession, dn: DnQuery) -> dict[str, Any]:
    return await ad_read(worker, session, users.get_user, dn, label="user.get")


@router.post("")
async def create_user(
    payload: CreateUserRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
) -> dict[str, Any]:
    """Create a user.

    Runs as add-disabled → set password → enable; see
    :func:`samcon.ad.users.create_user` for why.
    """
    with audit.operation("user.create", target=payload.parent_dn) as record:
        created = await ad_write(
            worker,
            session,
            users.create_user,
            parent_dn=payload.parent_dn,
            sam_account_name=payload.sam_account_name,
            common_name=payload.common_name,
            password=payload.password,
            must_change_password=payload.must_change_password,
            enabled=payload.enabled,
            attributes=payload.attributes,
            flags=payload.flags,
            label="user.create",
        )
        record["target"] = created["dn"]
        record["changes"] = {
            "sAMAccountName": {"new": payload.sam_account_name},
            "enabled": {"new": payload.enabled},
            **{k: {"new": v} for k, v in payload.attributes.items()},
        }
    return created


@router.patch("")
async def update_user(
    payload: UpdateUserRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    with audit.operation("user.update", target=dn) as record:
        applied = await ad_write(
            worker,
            session,
            users.update_user,
            dn,
            attributes=payload.attributes,
            flags=payload.flags,
            label="user.update",
        )
        record["changes"] = applied
    return {"dn": dn, "applied": applied}


@router.post("/password")
async def set_password(
    payload: SetPasswordRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    """Administrative password reset.

    The password itself never reaches the audit log — only the fact that it
    was reset.
    """
    with audit.operation("user.set_password", target=dn, must_change=payload.must_change):
        await ad_write(
            worker,
            session,
            users.set_password,
            dn,
            payload.password,
            must_change=payload.must_change,
            label="user.set_password",
        )
    return {"dn": dn, "password_set": True, "must_change": payload.must_change}


@router.post("/must-change-password")
async def must_change_password(
    payload: MustChangePasswordRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    with audit.operation("user.must_change_password", target=dn, value=payload.must_change):
        await ad_write(
            worker,
            session,
            users.set_must_change_password,
            dn,
            payload.must_change,
            label="user.must_change_password",
        )
    return {"dn": dn, "must_change_password": payload.must_change}


@router.post("/unlock")
async def unlock(
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    with audit.operation("user.unlock", target=dn):
        await ad_write(worker, session, users.unlock_account, dn, label="user.unlock")
    return {"dn": dn, "unlocked": True}


@router.post("/enabled")
async def set_enabled(
    payload: EnabledRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    action = "user.enable" if payload.enabled else "user.disable"
    with audit.operation(action, target=dn) as record:
        applied = await ad_write(
            worker, session, users.set_enabled, dn, payload.enabled, label=action
        )
        record["changes"] = applied
    return {"dn": dn, "enabled": payload.enabled}


@router.post("/expiry")
async def set_expiry(
    payload: AccountExpiryRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    with audit.operation("user.set_expiry", target=dn) as record:
        applied = await ad_write(
            worker,
            session,
            users.set_account_expiry,
            dn,
            payload.expires_at,
            label="user.set_expiry",
        )
        record["changes"] = applied
    return {"dn": dn, "expires_at": payload.expires_at}


@router.get("/locked")
async def locked_accounts(worker: Worker, session: CurrentSession) -> dict[str, Any]:
    """Accounts currently carrying a lockout timestamp."""
    accounts = await ad_read(worker, session, users.list_locked_accounts, label="user.locked")
    return {"accounts": accounts, "count": len(accounts)}
