"""User accounts."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from samadcon.ad import certificates, users
from samadcon.ad.access import ad_read, ad_write
from samadcon.api.common import Audit, DnQuery, note_confirmation
from samadcon.auth.deps import CurrentSession, VerifiedSession, VerifiedWorker, Worker
from samadcon.schemas.requests import (
    AccountExpiryRequest,
    CertificateRemoveRequest,
    CertificateUploadRequest,
    CreateUserRequest,
    EnabledRequest,
    MustChangePasswordRequest,
    PrimaryGroupRequest,
    SetPasswordRequest,
    UpdateUserRequest,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.get("")
async def get_user(worker: Worker, session: CurrentSession, dn: DnQuery) -> dict[str, Any]:
    return await ad_read(worker, session, users.get_user, dn, label="user.get")


@router.get("/administrative-role")
async def administrative_role(
    worker: Worker, session: CurrentSession, dn: DnQuery
) -> dict[str, Any]:
    """Whether deleting or disabling this object takes an administrator away.

    Lets a dialog ask before the first click rather than after the server has
    refused it. The refusal stays: this is for the question, not the rule.
    """
    role = await ad_read(
        worker, session, users.account_administrative_role, dn, label="user.admin_role"
    )
    return {"dn": dn, "role": role}


@router.post("")
async def create_user(
    payload: CreateUserRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
) -> dict[str, Any]:
    """Create a user.

    Runs as add-disabled → set password → enable; see
    :func:`samadcon.ad.users.create_user` for why.
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
            confirm_admin=payload.confirm_admin,
            label="user.update",
        )
        record["changes"] = applied
        if payload.confirm_admin:
            note_confirmation(record, "disabling an administrator")
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
            worker,
            session,
            users.set_enabled,
            dn,
            payload.enabled,
            confirm_admin=payload.confirm_admin,
            label=action,
        )
        record["changes"] = applied
        if payload.confirm_admin:
            note_confirmation(record, "disabling an administrator")
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


@router.post("/primary-group")
async def set_primary_group(
    payload: PrimaryGroupRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    """Make a group the account's primary group. It must already be a member."""
    with audit.operation("user.set_primary_group", target=dn, group=payload.group_dn) as record:
        applied = await ad_write(
            worker,
            session,
            users.set_primary_group,
            dn,
            payload.group_dn,
            label="user.set_primary_group",
        )
        record["changes"] = applied
    return {"dn": dn, "primary_group": payload.group_dn, "applied": applied}


# ---------------------------------------------------------------------------
# Published certificates
# ---------------------------------------------------------------------------


@router.get("/certificates")
async def list_certificates(
    worker: Worker, session: CurrentSession, dn: DnQuery
) -> dict[str, Any]:
    """The X.509 certificates published on the account, as the tab shows them."""
    found = await ad_read(
        worker, session, certificates.list_certificates, dn, label="user.certificates",
    )
    return {"dn": dn, "certificates": found}


@router.get("/certificate")
async def get_certificate(
    worker: Worker,
    session: CurrentSession,
    dn: DnQuery,
    fingerprint: Annotated[str, Query(pattern="^[0-9a-fA-F]{64}$", description="SHA-256")],
) -> dict[str, Any]:
    """One published certificate with its content, for viewing or saving it."""
    return await ad_read(
        worker, session, certificates.get_certificate, dn, fingerprint,
        label="user.certificate",
    )


@router.post("/certificates/inspect")
async def inspect_certificate(
    payload: CertificateUploadRequest, session: CurrentSession
) -> dict[str, Any]:
    """What an uploaded file would look like on the tab. Parses; writes nothing."""
    return certificates.inspect(payload.data)


@router.post("/certificates")
async def add_certificate(
    payload: CertificateUploadRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    with audit.operation("user.add_certificate", target=dn) as record:
        applied = await ad_write(
            worker,
            session,
            certificates.add_certificate,
            dn,
            payload.data,
            label="user.add_certificate",
        )
        record["changes"] = applied
    return {"dn": dn, **applied}


@router.delete("/certificates")
async def remove_certificate(
    payload: CertificateRemoveRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    dn: DnQuery,
) -> dict[str, Any]:
    with audit.operation(
        "user.remove_certificate", target=dn, fingerprint=payload.fingerprint,
    ) as record:
        applied = await ad_write(
            worker,
            session,
            certificates.remove_certificate,
            dn,
            payload.fingerprint,
            label="user.remove_certificate",
        )
        record["changes"] = applied
    return {"dn": dn, **applied}


@router.get("/locked")
async def locked_accounts(worker: Worker, session: CurrentSession) -> dict[str, Any]:
    """Accounts currently carrying a lockout timestamp."""
    accounts = await ad_read(worker, session, users.list_locked_accounts, label="user.locked")
    return {"accounts": accounts, "count": len(accounts)}
