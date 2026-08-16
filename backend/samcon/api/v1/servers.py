"""Choosing which domain to sign in to.

Both endpoints answer before authentication, because the sign-in form needs
them. The probe therefore opens outbound connections for an unauthenticated
caller — it is rate limited, and the ports it touches are fixed in code so it
cannot be turned into a port scanner.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from samcon.ad import discovery, targets
from samcon.auth.deps import client_ip
from samcon.config import get_settings
from samcon.core.errors import InvalidRequest
from samcon.core.ratelimit import probe_limiter
from samcon.schemas.requests import ProbeRequest

router = APIRouter(prefix="/servers", tags=["servers"])


@router.get("")
def list_servers() -> dict[str, Any]:
    """Configured profiles and the default domain, for the sign-in form."""
    return targets.describe_profiles(get_settings())


@router.post("/probe")
async def probe_server(payload: ProbeRequest, request: Request) -> dict[str, Any]:
    """Identify the domain behind an address.

    Reads the rootDSE without authenticating, which yields the realm, the DC's
    own FQDN and the naming contexts. That is what makes entering a bare IP
    work: Kerberos needs a realm and a service principal, and neither can be
    derived from an address.

    The answer also reports whether LDAPS validates, so the form can tell the
    administrator up front that a self-signed certificate needs the check
    turned off.
    """
    settings = get_settings()
    if not settings.allow_custom_servers and not payload.profile_id:
        raise InvalidRequest(
            "This installation only allows the configured servers.",
            code="custom_servers_disabled",
        )

    probe_limiter.check(client_ip(request) or "unknown")

    host = payload.host
    ca_file = None
    insecure = payload.insecure

    if payload.profile_id:
        profile = targets.find_profile(settings, payload.profile_id)
        ca_file = profile.ca_file
        insecure = insecure or profile.insecure
        if not host:
            if not profile.hosts:
                raise InvalidRequest(
                    "The server profile names no host to probe.",
                    code="incomplete_server_profile",
                )
            host = profile.hosts[0]

    if not host:
        raise InvalidRequest("No server address was given.", code="missing_server")

    identity = await run_in_threadpool(
        discovery.probe, host, settings, ca_file=ca_file, insecure=insecure
    )

    result = identity.describe()
    # The form uses this to decide whether to nudge the user towards the
    # "do not verify the certificate" option.
    result["requires_insecure"] = (
        identity.ldaps_reachable and identity.ldaps_certificate_trusted is False
    )
    return result
