"""Identifying a domain controller from nothing but an address.

An administrator types ``192.168.1.10`` and expects it to work. Kerberos does
not: a ticket is issued for ``ldap/dc1.example.lan@EXAMPLE.LAN``, and neither
the service principal nor the realm can be guessed from an IP.

The way out is the rootDSE. It is readable without authentication and tells us
the DC's own FQDN, the naming contexts and — via ``ldapServiceName`` — the
realm. With those in hand we can build a Kerberos configuration that names the
IP as the KDC, and connect over LDAPS to the FQDN the certificate was issued
for. This is what `net ads info` does.
"""

from __future__ import annotations

import logging
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from samadcon.ad import values
from samadcon.config import Settings
from samadcon.core.cache import TTLCache
from samadcon.core.errors import InvalidRequest, UpstreamUnavailable, translate

logger = logging.getLogger(__name__)

LDAP_PORT = 389
LDAPS_PORT = 636

# A probe hits an unauthenticated endpoint; keep it short so a wrong address
# fails fast instead of making the sign-in form hang.
CONNECT_TIMEOUT_SECONDS = 5.0

ROOTDSE_ATTRS = [
    "dnsHostName",
    "ldapServiceName",
    "defaultNamingContext",
    "configurationNamingContext",
    "schemaNamingContext",
    "rootDomainNamingContext",
    "serverName",
    "dsServiceName",
    "supportedSASLMechanisms",
    "supportedCapabilities",
    "domainFunctionality",
    "forestFunctionality",
    "isSynchronized",
    "currentTime",
]

# Probing is cheap but not free, and the sign-in form may ask repeatedly while
# the user is still typing their password.
_probe_cache: TTLCache[Any] = TTLCache(ttl_seconds=120.0, max_entries=32)


@dataclass(frozen=True)
class ServerIdentity:
    """What a domain controller tells us about itself before we authenticate."""

    host: str
    dc_hostname: str | None
    realm: str
    dns_domain: str
    base_dn: str
    config_dn: str | None
    transport: str
    supports_gssapi: bool
    is_domain_controller: bool
    ldaps_reachable: bool
    # None when LDAPS was not reachable at all.
    ldaps_certificate_trusted: bool | None
    # Whether this container can resolve the DC's own name. Kerberos issues
    # tickets for ldap/<hostname>@REALM, so a name that does not resolve here
    # breaks the sign-in even though the probe itself worked over the IP.
    dc_hostname_resolves: bool | None
    # Whether the container's resolver serves this domain. Samba locates a
    # domain controller with a netlogon ping over these records, and a
    # container given only an /etc/hosts entry has none — which is why a
    # server that answers on both ports can still fail the sign-in with
    # NT_STATUS_NO_LOGON_SERVERS. Reported, never required: a deployment
    # that names its DC explicitly does not need them.
    srv_lookups: list[dict[str, Any]]
    domain_functional_level: int | None
    forest_functional_level: int | None

    def describe(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "dc_hostname": self.dc_hostname,
            "realm": self.realm,
            "dns_domain": self.dns_domain,
            "base_dn": self.base_dn,
            "transport": self.transport,
            "supports_gssapi": self.supports_gssapi,
            "is_domain_controller": self.is_domain_controller,
            "ldaps_reachable": self.ldaps_reachable,
            "ldaps_certificate_trusted": self.ldaps_certificate_trusted,
            "dc_hostname_resolves": self.dc_hostname_resolves,
            "srv_lookups": self.srv_lookups,
            "domain_functional_level": self.domain_functional_level,
            "forest_functional_level": self.forest_functional_level,
        }


# ---------------------------------------------------------------------------
# Address handling
# ---------------------------------------------------------------------------


# The two the sign-in depends on. The first is what Samba's netlogon ping
# uses to find a domain controller; the second is where Kerberos looks for
# a KDC when the configuration does not name one.
SRV_QUERIES = (
    "_ldap._tcp.dc._msdcs.{realm}",
    "_kerberos._udp.{realm}",
)


def srv_lookups(realm: str) -> list[dict[str, Any]]:
    """How many records the container's resolver returns for each query.

    Never raises. This runs inside a probe whose job is to describe a
    server, and a resolver that answers nothing is a fact worth reporting
    rather than a reason to report nothing at all.
    """
    if not realm:
        return []

    results: list[dict[str, Any]] = []
    for template in SRV_QUERIES:
        query = template.format(realm=realm.lower())
        try:
            import dns.resolver

            answers = dns.resolver.resolve(query, "SRV")
            results.append({"query": query, "found": len(answers)})
        except Exception:
            # Every failure means the same thing here — the resolver did
            # not answer with records — and the distinctions between them
            # (NXDOMAIN, timeout, no nameserver) do not change what to do.
            logger.info("SRV lookup of %s found nothing", query, exc_info=True)
            results.append({"query": query, "found": 0})
    return results


def normalise_host(raw: str) -> str:
    """Strip what users paste in: schemes, ports, trailing dots, whitespace."""
    host = raw.strip()
    if not host:
        raise InvalidRequest("No server address was given.", code="missing_server")

    for scheme in ("ldaps://", "ldap://", "https://", "http://"):
        if host.lower().startswith(scheme):
            host = host[len(scheme) :]
            break

    host = host.split("/", 1)[0]

    # Strip a port, but leave bracketed IPv6 literals intact.
    if host.startswith("["):
        closing = host.find("]")
        if closing > 0:
            host = host[1:closing]
    elif host.count(":") == 1:
        host = host.split(":", 1)[0]

    host = host.rstrip(".")
    if not host:
        raise InvalidRequest("The server address is empty.", code="missing_server")
    if any(char in host for char in " \t\n\r"):
        raise InvalidRequest(
            "The server address contains spaces.", code="invalid_server_address"
        )
    return host


def check_port(host: str, port: int, timeout: float = CONNECT_TIMEOUT_SECONDS) -> bool:
    """Plain TCP reachability.

    Done before the LDAP call so an unreachable host produces "no route" rather
    than an opaque LDAP timeout.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Probing
# ---------------------------------------------------------------------------


def _probe_loadparm(settings: Settings, *, ca_file: Path | None, insecure: bool) -> Any:
    from samba.param import LoadParm

    from samadcon.auth.kerberos import apply_transport_settings

    lp = LoadParm()
    if settings.smb_conf.exists():
        lp.load(str(settings.smb_conf))
    else:
        lp.load_default()

    # The probe reads the rootDSE anonymously, so the LDAPS rules are what
    # matter here — and they must match what a real connection would use, or
    # the reported trust decision would not survive the sign-in.
    apply_transport_settings(
        lp,
        transport="ldaps",
        ca_file=ca_file or settings.ldap_ca_file,
        insecure=insecure,
    )

    # Keep a dead address from stalling the sign-in form.
    _try_set(lp, "ldap connection timeout", str(int(CONNECT_TIMEOUT_SECONDS)))
    _try_set(lp, "ldap timeout", str(int(CONNECT_TIMEOUT_SECONDS * 2)))
    return lp


def _try_set(lp: Any, option: str, value: str) -> None:
    """Set a loadparm option, ignoring ones this Samba build does not know."""
    try:
        lp.set(option, value)
    except Exception:  # noqa: BLE001 — an unknown tuning option is not fatal
        logger.debug("loadparm does not accept %r", option)


def _read_rootdse(url: str, lp: Any) -> Any:
    """Anonymous rootDSE read."""
    from samba.samdb import SamDB

    # No credentials: an unauthenticated search of the rootDSE is what every
    # AD-compatible server allows, and it is all we need here.
    db = SamDB(url=url, lp=lp)
    result = db.search(base="", scope=0, attrs=ROOTDSE_ATTRS)
    if not len(result):
        raise UpstreamUnavailable(
            "The server returned an empty rootDSE.",
            code="rootdse_empty",
            hint="It answers on the LDAP port but does not look like a domain controller.",
        )
    return result[0]


def _realm_from_rootdse(entry: Any, base_dn: str) -> str:
    """Derive the Kerberos realm.

    ``ldapServiceName`` looks like ``example.lan:dc1$@EXAMPLE.LAN`` and is the
    authoritative source. Domains whose DN does not mirror their realm exist,
    so the base DN is only the fallback.
    """
    service_name = values.as_str(entry, "ldapServiceName")
    if service_name and "@" in service_name:
        realm = service_name.rsplit("@", 1)[1].strip()
        if realm:
            return realm.upper()

    if base_dn:
        labels = [
            part.split("=", 1)[1]
            for part in base_dn.split(",")
            if part.strip().upper().startswith("DC=")
        ]
        if labels:
            return ".".join(labels).upper()

    raise UpstreamUnavailable(
        "The server did not reveal its Kerberos realm.",
        code="realm_undetermined",
        hint="Enter the realm manually, e.g. EXAMPLE.LAN.",
    )


def probe(
    host: str,
    settings: Settings,
    *,
    ca_file: Path | None = None,
    insecure: bool = False,
    use_cache: bool = True,
) -> ServerIdentity:
    """Ask a server who it is. Runs in a worker thread — it does network I/O."""
    target_host = normalise_host(host)
    cache_key = f"{target_host}|{insecure}|{ca_file or ''}"

    if use_cache:
        cached = _probe_cache.get(cache_key)
        if cached is not None:
            return cached

    ldap_open = check_port(target_host, LDAP_PORT)
    ldaps_open = check_port(target_host, LDAPS_PORT)

    if not ldap_open and not ldaps_open:
        raise UpstreamUnavailable(
            "The server cannot be reached.",
            code="server_unreachable",
            hint=f"Neither port {LDAP_PORT} nor {LDAPS_PORT} answers on {target_host}.",
            context={"host": target_host},
        )

    lp = _probe_loadparm(settings, ca_file=ca_file, insecure=insecure)

    # Plain LDAP first: the rootDSE is public, and this step must work even
    # when the certificate is untrusted — which is precisely the case we are
    # trying to diagnose.
    attempts: list[tuple[str, str]] = []
    if ldap_open:
        attempts.append(("ldap", f"ldap://{target_host}"))
    if ldaps_open:
        attempts.append(("ldaps", f"ldaps://{target_host}"))

    entry = None
    transport = ""
    failures: list[str] = []
    for name, url in attempts:
        try:
            entry = _read_rootdse(url, lp)
            transport = name
            break
        except Exception as exc:  # noqa: BLE001 — try the next transport
            error = translate(exc)
            failures.append(f"{name}: {error.message}")
            logger.info("rootDSE probe via %s failed: %s", url, error.detail or error.message)

    if entry is None:
        raise UpstreamUnavailable(
            "The server did not answer an anonymous directory query.",
            code="probe_failed",
            detail="; ".join(failures),
            hint=(
                "It may not be a domain controller, or it refuses unauthenticated "
                "rootDSE reads. Enter the realm manually in that case."
            ),
            context={"host": target_host},
        )

    base_dn = values.as_str(entry, "defaultNamingContext") or ""
    realm = _realm_from_rootdse(entry, base_dn)
    dns_domain = ".".join(
        part.split("=", 1)[1]
        for part in base_dn.split(",")
        if part.strip().upper().startswith("DC=")
    ) or realm.lower()

    mechanisms = {m.upper() for m in values.as_list(entry, "supportedSASLMechanisms")}

    trusted: bool | None = None
    if ldaps_open:
        trusted = _ldaps_certificate_trusted(target_host, settings, ca_file)

    dc_hostname = values.as_str(entry, "dnsHostName")
    resolves = _resolves(dc_hostname) if dc_hostname else None

    identity = ServerIdentity(
        host=target_host,
        dc_hostname=dc_hostname,
        dc_hostname_resolves=resolves,
        srv_lookups=srv_lookups(realm),
        realm=realm,
        dns_domain=dns_domain,
        base_dn=base_dn,
        config_dn=values.as_str(entry, "configurationNamingContext"),
        transport=transport,
        supports_gssapi="GSSAPI" in mechanisms,
        # A DC always publishes dsServiceName; an LDAP server that is not one
        # does not.
        is_domain_controller=bool(values.as_str(entry, "dsServiceName")),
        ldaps_reachable=ldaps_open,
        ldaps_certificate_trusted=trusted,
        domain_functional_level=values.as_int(entry, "domainFunctionality"),
        forest_functional_level=values.as_int(entry, "forestFunctionality"),
    )

    _probe_cache.set(cache_key, identity)
    return identity


def _resolves(hostname: str) -> bool:
    """Whether this container can turn *hostname* into an address.

    A DC reached by IP will still name itself by FQDN, and Kerberos needs that
    name. If it does not resolve here, the sign-in fails later with an opaque
    handshake error — better to say so while the form is still open.
    """
    try:
        socket.getaddrinfo(hostname, None)
    except OSError:
        return False
    return True


def _ldaps_certificate_trusted(
    host: str, settings: Settings, ca_file: Path | None
) -> bool | None:
    """Whether LDAPS validates against the configured CA.

    Answering this before sign-in lets the form say "the certificate cannot be
    verified — tick the box or supply a CA" instead of failing later with a TLS
    error nobody can act on.
    """
    strict = _probe_loadparm(settings, ca_file=ca_file, insecure=False)
    try:
        _read_rootdse(f"ldaps://{host}", strict)
        return True
    except Exception:  # noqa: BLE001 — expected for self-signed certificates
        logger.debug("LDAPS certificate for %s does not validate", host)
        return False


def invalidate_probe_cache(host: str | None = None) -> None:
    if host is None:
        _probe_cache.clear()
    else:
        _probe_cache.invalidate_prefix(f"{normalise_host(host)}|")
