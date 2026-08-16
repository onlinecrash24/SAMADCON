"""Sign-in, sign-out and session state."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Request, Response

from samadcon.ad import targets
from samadcon.ad.access import ad_read
from samadcon.auth import kerberos
from samadcon.auth.deps import CurrentSession, client_ip
from samadcon.auth.session import get_store, get_throttle
from samadcon.config import get_settings
from samadcon.core.audit import get_audit
from samadcon.core.errors import AuthenticationError, SamadconError
from samadcon.core.executor import get_registry
from samadcon.schemas.requests import LoginRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
    """Obtain a Kerberos ticket for the chosen domain and open a session.

    The domain comes from the request, not from the container's configuration:
    an address, a configured profile, or the default. Resolving it may involve
    an unauthenticated rootDSE read to learn the realm — that is what lets an
    administrator type a bare IP address.

    The password is used here and nowhere else: it goes into the KDC exchange
    and is then out of scope. Everything the session does afterwards runs off
    the resulting ticket.
    """
    settings = get_settings()
    store = get_store()
    throttle = get_throttle()
    audit = get_audit()
    address = client_ip(request)

    session_id = store.new_id()
    ccache = kerberos.ccache_path_for(settings, session_id)
    registry = get_registry()
    worker = registry.get(session_id)

    def _fail(exc: SamadconError, principal_name: str | None, target: Any = None) -> None:
        registry.drop(session_id)
        kerberos.destroy_ticket(ccache)
        if principal_name:
            throttle.record_failure(principal_name, address)
        audit.record(
            action="auth.login",
            actor=principal_name,
            result="error",
            error=exc.message,
            error_code=exc.code,
            client_ip=address,
            extra={"domain": target.display_name} if target is not None else None,
        )

    # Resolving the target probes the network, so it runs on the worker thread.
    try:
        target = await worker.run(
            targets.resolve_target,
            settings,
            server=payload.server,
            realm=payload.realm,
            profile_id=payload.profile_id,
            insecure=payload.insecure,
            label="server.resolve",
            timeout=30,
        )
    except SamadconError as exc:
        _fail(exc, None)
        raise

    principal = kerberos.parse_principal(payload.username, target.realm)
    try:
        throttle.check(principal.username, address)
    except SamadconError as exc:
        registry.drop(session_id)
        raise exc

    try:
        # Ticket acquisition blocks on the network, so it belongs on the
        # session's worker thread like every other Samba call.
        await worker.run(
            kerberos.acquire_ticket,
            principal,
            payload.password,
            ccache,
            settings,
            target,
            label="kerberos.kinit",
            timeout=45,
        )
    except SamadconError as exc:
        _fail(exc, principal.username, target)
        raise

    expires_at = kerberos.ticket_expiry(ccache) or kerberos.default_expiry()
    session = store.create(
        session_id=session_id,
        principal=principal,
        target=target,
        ccache=ccache,
        ticket_expires_at=expires_at,
        client_ip=address,
        user_agent=request.headers.get("user-agent"),
    )

    # Connect straight away: a ticket the DC will not accept should surface
    # here, not on the user's first click.
    try:
        domain = await ad_read(
            worker, session, lambda conn: asdict(conn.info), label="ldap.connect"
        )
    except SamadconError as exc:
        store.drop(session_id, reason="connect_failed")
        throttle.record_failure(principal.username, address)
        audit.record(
            action="auth.login",
            actor=principal.full,
            result="error",
            error=exc.message,
            error_code=exc.code,
            client_ip=address,
            extra={"domain": target.display_name},
        )
        raise

    throttle.record_success(principal.username, address)
    audit.record(
        action="auth.login",
        actor=principal.full,
        result="ok",
        session_id=session_id,
        client_ip=address,
        # Which domain and which DC — the question every audit trail gets
        # asked once more than one domain is in play.
        extra={
            "domain": target.display_name,
            "realm": target.realm,
            "dc": domain.get("dc_hostname"),
            "tls_verified": not (target.insecure or settings.ldap_insecure),
        },
    )

    _set_session_cookie(response, session_id)
    return {
        "principal": principal.full,
        "username": principal.username,
        "realm": principal.realm,
        "csrf_token": session.csrf_token,
        "expires_at": session.expires_at,
        "domain": domain,
        "target": target.describe(),
    }


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict[str, Any]:
    """End the session and destroy its Kerberos ticket."""
    settings = get_settings()
    session_id = request.cookies.get(settings.cookie_name)

    if session_id:
        store = get_store()
        try:
            session = store.get(session_id)
            actor = session.principal.full
        except SamadconError:
            actor = None
        store.drop(session_id, reason="logout")
        get_audit().record(
            action="auth.logout",
            actor=actor,
            session_id=session_id,
            client_ip=client_ip(request),
        )

    response.delete_cookie(
        settings.cookie_name,
        path="/",
        httponly=True,
        secure=_cookie_secure(),
        samesite="strict",
    )
    return {"status": "signed_out"}


@router.get("/session")
async def session_info(session: CurrentSession) -> dict[str, Any]:
    """Current session, for restoring state after a page reload."""
    worker = get_registry().get(session.id)
    domain = await ad_read(worker, session, lambda conn: asdict(conn.info), label="ldap.info")
    return {
        "principal": session.principal.full,
        "username": session.principal.username,
        "realm": session.principal.realm,
        "csrf_token": session.csrf_token,
        "expires_at": session.expires_at,
        "ticket_expires_at": session.ticket_expires_at,
        "created_at": session.created_at,
        "domain": domain,
        "target": session.target.describe(),
    }


@router.get("/whoami")
async def whoami(session: CurrentSession) -> dict[str, Any]:
    """Who the directory thinks we are, and what that account may do.

    Useful when a delegated administrator wonders why an action is refused:
    this shows the account and its group memberships as the DC sees them.
    """
    from samadcon.ad import groups as groups_module
    from samadcon.ad.connection import SCOPE_SUBTREE
    from samadcon.ad.directory import summarize
    from samadcon.ad.values import escape_filter

    worker = get_registry().get(session.id)

    def _lookup(conn: Any) -> dict[str, Any]:
        result = conn.search(
            conn.info.base_dn,
            scope=SCOPE_SUBTREE,
            expression=f"(sAMAccountName={escape_filter(session.principal.username)})",
            attrs=[
                "distinguishedName", "objectClass", "name", "displayName", "objectGUID",
                "objectSid", "sAMAccountName", "userAccountControl", "description",
            ],
            max_results=1,
        )
        if not len(result):
            raise AuthenticationError(
                "The signed-in account was not found in the directory.",
                code="account_not_found",
            )
        account = summarize(result.entries[0])
        account["member_of"] = groups_module.list_member_of(conn, account["dn"], recursive=True)
        return account

    return await ad_read(worker, session, _lookup, label="auth.whoami")


def _cookie_secure() -> bool:
    settings = get_settings()
    # dev_mode exists so the container can be reached over plain http on
    # localhost; a Secure cookie would never be sent back in that case.
    return settings.cookie_secure and not settings.dev_mode


def _set_session_cookie(response: Response, session_id: str) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.cookie_name,
        session_id,
        httponly=True,
        secure=_cookie_secure(),
        samesite="strict",
        path="/",
        # No max-age: a session cookie disappears when the browser closes,
        # and the server-side expiry is authoritative anyway.
    )
