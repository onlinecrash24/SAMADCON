"""Sign-in, sign-out and session state."""

from __future__ import annotations

import logging
import threading
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Request, Response

from samadcon.ad import targets
from samadcon.ad.access import ad_read
from samadcon.auth import kerberos
from samadcon.auth.deps import CurrentSession, client_ip, idp_user
from samadcon.auth.session import get_store, get_throttle
from samadcon.config import get_settings
from samadcon.core.audit import get_audit
from samadcon.core.errors import AuthenticationError, PermissionDenied, SamadconError
from samadcon.core.executor import get_registry
from samadcon.core.ratelimit import probe_limiter
from samadcon.schemas.requests import LoginRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

# Sign-ins that may wait at the same time. Each holds a worker thread while
# its target is resolved and its ticket fetched; the registry allows 64 in
# all, sessions included, so this leaves most of them to people signed in.
MAX_PENDING_SIGN_INS = 16


class SignInSlots:
    """A count of sign-ins in progress, refusing beyond its limit at once."""

    class _Slot:
        def __init__(self, owner: SignInSlots) -> None:
            self._owner: SignInSlots | None = owner

        def release(self) -> None:
            if self._owner is not None:
                self._owner._release()
                self._owner = None

    def __init__(self, limit: int = MAX_PENDING_SIGN_INS) -> None:
        self.limit = limit
        self._taken = 0
        self._lock = threading.Lock()

    def take(self) -> SignInSlots._Slot:
        with self._lock:
            if self._taken >= self.limit:
                raise SamadconError(
                    "Too many sign-ins at the same time.",
                    code="too_many_sign_ins",
                    status_code=503,
                    hint="Try again in a moment.",
                )
            self._taken += 1
        return SignInSlots._Slot(self)

    def _release(self) -> None:
        with self._lock:
            self._taken -= 1


sign_in_slots = SignInSlots()


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

    # The identity provider in front, when one is configured. Without the
    # setting nginx drops the header, and should one arrive anyway it is not
    # believed. When it is required and missing, the request did not come
    # through the proxy — someone went straight to the port — and that is
    # refused before anything else: no target, no ticket, no failed attempt
    # counted against an account nobody tried.
    idp = idp_user(request) if settings.proxy_user_header else None
    if settings.proxy_user_required and not idp:
        audit.record(
            action="auth.login",
            actor=None,
            result="error",
            error="No user from the identity provider in front.",
            error_code="idp_user_missing",
            client_ip=address,
        )
        raise PermissionDenied(
            "Sign-in is only possible through the identity provider in front of SAMADCON.",
            code="idp_user_missing",
        )

    # A typed-in server address makes resolve_target open outbound connections
    # to whatever was named, on 389 and 636, before anyone is signed in — the
    # same reach /servers/probe rate-limits for exactly this reason. Without a
    # limit here, login is a second, unthrottled way to use the container as a
    # port scanner: a failed resolve records nothing (no principal yet) and can
    # be repeated as fast as the network answers. A configured profile or the
    # default is not throttled — those hosts are set by the operator, not the
    # caller.
    if payload.server:
        probe_limiter.check(address or "unknown")

    # The address before anything else: a throttled one gets no worker thread
    # and no target resolved. Then a slot: resolving the target may wait 30
    # seconds on a slow DC, and without a cap 64 such attempts filled the
    # registry and real administrators got too_many_sessions (Rowie).
    throttle.check_address(address)
    slot = sign_in_slots.take()
    try:
        return await _sign_in(
            payload, request, response, settings, store, throttle, audit, address, idp
        )
    finally:
        slot.release()


async def _sign_in(
    payload: LoginRequest,
    request: Request,
    response: Response,
    settings: Any,
    store: Any,
    throttle: Any,
    audit: Any,
    address: str | None,
    idp: str | None,
) -> dict[str, Any]:
    """Everything of a sign-in that holds a worker thread."""
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
            idp_user=idp,
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
        raise _public(exc) from None

    expires_at = kerberos.ticket_expiry(ccache) or kerberos.default_expiry()
    session = store.create(
        session_id=session_id,
        principal=principal,
        target=target,
        ccache=ccache,
        ticket_expires_at=expires_at,
        client_ip=address,
        user_agent=request.headers.get("user-agent"),
        idp_user=idp,
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
            idp_user=idp,
        )
        raise _public(exc) from None

    throttle.record_success(principal.username, address)
    audit.record(
        action="auth.login",
        actor=principal.full,
        result="ok",
        session_id=session_id,
        client_ip=address,
        idp_user=idp,
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
        "idp_user": session.idp_user,
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
            actor, idp = session.principal.full, session.idp_user
        except SamadconError:
            actor, idp = None, None
        store.drop(session_id, reason="logout")
        get_audit().record(
            action="auth.logout",
            actor=actor,
            session_id=session_id,
            client_ip=client_ip(request),
            idp_user=idp,
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
    # Both in one hop: the connection state lives on the same object as the
    # domain facts, and a second round trip through the worker to read an
    # attribute already in hand would be waste.
    facts = await ad_read(
        worker,
        session,
        lambda conn: {
            "domain": asdict(conn.info),
            "connection": conn.transport.describe() if conn.transport else None,
        },
        label="ldap.info",
    )
    return {
        "principal": session.principal.full,
        "username": session.principal.username,
        "realm": session.principal.realm,
        "csrf_token": session.csrf_token,
        "expires_at": session.expires_at,
        "ticket_expires_at": session.ticket_expires_at,
        "created_at": session.created_at,
        "domain": facts["domain"],
        "connection": facts["connection"],
        "target": session.target.describe(),
        "idp_user": session.idp_user,
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


def _public(exc: SamadconError) -> SamadconError:
    """A failed sign-in as the caller sees it.

    Kerberos tells an unknown account from a wrong password, and the KDC's
    own text named the principal: the form told a stranger which accounts
    exist (reported by Rowie). Both now get the same answer, without the
    KDC's text; the audit log and the server log keep what happened.
    """
    logger.info("sign-in failed: %s (%s): %s", exc.message, exc.code, exc.detail)
    if exc.code in ("user_not_found", "invalid_credentials"):
        return AuthenticationError("Wrong user name or password.", code="invalid_credentials")
    exc.detail = None
    return exc


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
