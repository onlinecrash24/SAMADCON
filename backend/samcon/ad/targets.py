"""Turning what the sign-in form sends into a connection target.

Three sources, in this order:

1. an explicit server address — the realm is discovered from its rootDSE,
2. a configured profile,
3. the container's default realm.

Resolution touches the network (the probe), so it belongs on a worker thread
like every other Samba call.
"""

from __future__ import annotations

import logging
from typing import Any

from samcon.ad import discovery
from samcon.ad.target import ConnectionTarget
from samcon.config import ServerProfile, Settings
from samcon.core.errors import InvalidRequest, NotFound

logger = logging.getLogger(__name__)


def list_profiles(settings: Settings) -> list[ServerProfile]:
    return settings.load_profiles()


def find_profile(settings: Settings, profile_id: str) -> ServerProfile:
    for profile in list_profiles(settings):
        if profile.id == profile_id:
            return profile
    raise NotFound(
        "The selected server profile does not exist.",
        code="unknown_server_profile",
        context={"profile_id": profile_id},
    )


def describe_profiles(settings: Settings) -> dict[str, Any]:
    """Server list for the sign-in form.

    Deliberately omits CA file paths: this endpoint answers before anyone has
    authenticated, and a container's file layout is nobody else's business.
    """
    profiles = [
        {
            "id": profile.id,
            "label": profile.label or profile.hosts[0] if profile.hosts else profile.id,
            "hosts": profile.hosts,
            "realm": profile.realm,
            "insecure": profile.insecure,
        }
        for profile in list_profiles(settings)
    ]

    default = settings.default_target
    return {
        "profiles": profiles,
        "default": (
            {
                "realm": default.realm,
                "hosts": list(default.hosts),
                "discovery": "dns" if not default.hosts else "static",
            }
            if default is not None
            else None
        ),
        "allow_custom_servers": settings.allow_custom_servers,
    }


def resolve_target(
    settings: Settings,
    *,
    server: str | None = None,
    realm: str | None = None,
    profile_id: str | None = None,
    insecure: bool = False,
) -> ConnectionTarget:
    """Build the target to sign in against. Runs in a worker thread."""
    if profile_id:
        return _from_profile(settings, profile_id, insecure=insecure)
    if server:
        return _from_address(settings, server, realm=realm, insecure=insecure)
    return _from_default(settings, realm=realm, insecure=insecure)


def _from_profile(settings: Settings, profile_id: str, *, insecure: bool) -> ConnectionTarget:
    profile = find_profile(settings, profile_id)
    if not profile.hosts and not profile.realm:
        raise InvalidRequest(
            "The server profile names neither a host nor a realm.",
            code="incomplete_server_profile",
            context={"profile_id": profile_id},
        )

    target = ConnectionTarget(
        # A profile without a realm gets one from the probe below.
        realm=profile.realm or _realm_placeholder(profile.hosts[0]),
        hosts=tuple(profile.hosts),
        label=profile.label,
        ca_file=profile.ca_file,
        insecure=profile.insecure or insecure,
        profile_id=profile.id,
    )

    if profile.realm:
        # Still worth probing for the DC's FQDN, but a failure here must not
        # block a sign-in: the realm is already known.
        first_host = profile.hosts[0] if profile.hosts else None
        return _enrich(settings, target, host=first_host, required=False)
    return _enrich(settings, target, host=profile.hosts[0], required=True)


def _from_address(
    settings: Settings, server: str, *, realm: str | None, insecure: bool
) -> ConnectionTarget:
    if not settings.allow_custom_servers:
        raise InvalidRequest(
            "This installation only allows the configured servers.",
            code="custom_servers_disabled",
            hint="Pick one of the offered domains.",
        )

    host = discovery.normalise_host(server)
    target = ConnectionTarget(
        realm=(realm or _realm_placeholder(host)),
        hosts=(host,),
        insecure=insecure,
    )
    # Without an explicit realm the probe is the only way to learn it, so a
    # failure there is fatal.
    return _enrich(settings, target, host=host, required=realm is None)


def _from_default(settings: Settings, *, realm: str | None, insecure: bool) -> ConnectionTarget:
    default = settings.default_target
    if default is None:
        raise InvalidRequest(
            "No domain was given and this installation has no default.",
            code="no_target",
            hint="Enter the address of a domain controller.",
        )
    if realm:
        default = default.with_discovery(realm=realm)
    if insecure:
        default = ConnectionTarget(
            realm=default.realm,
            hosts=default.hosts,
            label=default.label,
            ca_file=default.ca_file,
            insecure=True,
            profile_id=default.profile_id,
            dns_domain=default.dns_domain,
            dc_hostname=default.dc_hostname,
        )

    # The configured domain gets probed like any other, and for the reason
    # that matters most: the probe is where the DC's own name comes from.
    # Kerberos issues tickets for ldap/<hostname>@REALM and there is no such
    # principal for a bare address, so a container configured with an IP —
    # which is the documented way to set it up — could authenticate through
    # the typed-address path and nowhere else. Not required: the realm is
    # already known, and a probe that fails is not a reason to refuse a
    # sign-in that might still work.
    if default.hosts:
        default = _enrich(settings, default, host=default.hosts[0], required=False)
    return default


def _enrich(
    settings: Settings, target: ConnectionTarget, *, host: str | None, required: bool
) -> ConnectionTarget:
    """Fill in realm, DNS domain and DC FQDN from the server itself."""
    if host is None:
        return target

    try:
        identity = discovery.probe(
            host, settings, ca_file=target.ca_file, insecure=target.insecure
        )
    except Exception as exc:
        if required:
            raise
        # With the reason. Without it this line reads as a network hiccup, and
        # the catch is wide enough to swallow a mistake in our own code and
        # report it the same way — which is exactly how a sign-in ends up
        # failing later, at the bind, over a name that was never fetched.
        logger.warning(
            "probe of %s failed (%s: %s); continuing with the configured realm",
            host,
            type(exc).__name__,
            exc,
        )
        return target

    return target.with_discovery(
        realm=identity.realm,
        dns_domain=identity.dns_domain,
        dc_hostname=identity.dc_hostname,
    )


def _realm_placeholder(host: str) -> str:
    """A stand-in realm for the moment before the probe answers.

    A host name usually carries the domain, which makes error messages
    readable if the probe fails; a bare IP falls back to a marker that the
    validation in ConnectionTarget accepts.
    """
    if "." in host and not host.replace(".", "").isdigit():
        return host.split(".", 1)[1].upper()
    return "UNKNOWN"
