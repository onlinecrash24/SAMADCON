"""LDAP connection handling.

Every call in this module runs inside a session's worker thread (see
:mod:`samcon.core.executor`) — an ldb handle must not be shared between
threads. Nothing here may be awaited directly from a router; go through
:func:`samcon.ad.session_directory.directory_for` instead.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from samcon.ad import values
from samcon.ad.target import ConnectionTarget
from samcon.config import Settings
from samcon.core.errors import (
    InvalidRequest,
    SamconError,
    UpstreamUnavailable,
    translate,
)

logger = logging.getLogger(__name__)

# ldb scopes, mirrored so callers do not need to import ldb themselves.
SCOPE_BASE = 0
SCOPE_ONELEVEL = 1
SCOPE_SUBTREE = 2

# ADUC shows at most 2000 objects per container by default; the same ceiling
# keeps a mis-scoped search from pulling an entire large domain into memory.
DEFAULT_MAX_RESULTS = 2000


@dataclass(frozen=True)
class DomainInfo:
    """Naming contexts and identity of the domain, read from the rootDSE."""

    dc_hostname: str
    base_dn: str
    config_dn: str
    schema_dn: str
    root_domain_dn: str
    domain_sid: str | None
    dns_domain: str
    netbios_name: str
    domain_functional_level: int | None
    forest_functional_level: int | None

    @property
    def policies_dn(self) -> str:
        return f"CN=Policies,CN=System,{self.base_dn}"

    @property
    def sysvol_share(self) -> str:
        return f"\\\\{self.dns_domain}\\SYSVOL"


@dataclass
class SearchResult:
    entries: list[Any]
    truncated: bool = False

    def __iter__(self):
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)


class DirectoryConnection:
    """A SamDB bound to one DC on behalf of one signed-in administrator."""

    def __init__(
        self,
        samdb: Any,
        host: str,
        info: DomainInfo,
        settings: Settings,
        lp: Any = None,
        creds: Any = None,
        target: ConnectionTarget | None = None,
        ccache: Path | None = None,
    ) -> None:
        self.samdb = samdb
        self.host = host
        self.info = info
        self.settings = settings
        self.lp = lp
        self.creds = creds
        # Kept for SYSVOL: group policy lives half in the directory and half on
        # an SMB share, and the share is opened as the same person — from the
        # ticket, not from the credentials object above. That one is configured
        # for an LDAP transport and has already been through a bind.
        self.target = target
        self.ccache = ccache
        # Filled in lazily by samcon.gpo.sysvol; one SMB session per directory
        # connection, torn down with it.
        self.sysvol: Any = None

    # -- reading -----------------------------------------------------------

    def search(
        self,
        base: str | None = None,
        *,
        scope: int = SCOPE_SUBTREE,
        expression: str = "(objectClass=*)",
        attrs: list[str] | None = None,
        controls: list[str] | None = None,
        max_results: int = DEFAULT_MAX_RESULTS,
    ) -> SearchResult:
        page_size = self.settings.ldap_page_size
        all_controls = list(controls or [])
        if not any(c.startswith("paged_results") for c in all_controls):
            all_controls.append(f"paged_results:1:{page_size}")

        try:
            raw = self.samdb.search(
                base=base if base is not None else self.info.base_dn,
                scope=scope,
                expression=expression,
                attrs=attrs,
                controls=all_controls,
            )
        except Exception as exc:
            raise translate(exc) from exc

        entries = list(raw)
        if len(entries) > max_results:
            logger.info(
                "search truncated at %d entries (base=%s filter=%s)",
                max_results,
                base,
                expression,
            )
            return SearchResult(entries[:max_results], truncated=True)
        return SearchResult(entries)

    def get(self, dn: str, attrs: list[str] | None = None) -> Any | None:
        """Read one object, or None when it does not exist."""
        from samcon.core.errors import NotFound

        try:
            result = self.search(dn, scope=SCOPE_BASE, attrs=attrs, max_results=1)
        except NotFound:
            return None
        return result.entries[0] if result.entries else None

    def exists(self, dn: str) -> bool:
        return self.get(dn, attrs=["1.1"]) is not None

    # -- writing -----------------------------------------------------------

    def add(self, message: Any) -> None:
        try:
            self.samdb.add(message)
        except Exception as exc:
            raise translate(exc) from exc

    def modify(self, message: Any) -> None:
        try:
            self.samdb.modify(message)
        except Exception as exc:
            raise translate(exc) from exc

    def delete(self, dn: str, *, recursive: bool = False) -> None:
        controls = ["tree_delete:1"] if recursive else None
        try:
            self.samdb.delete(dn, controls)
        except Exception as exc:
            raise translate(exc) from exc

    def rename(self, old_dn: str, new_dn: str) -> None:
        try:
            self.samdb.rename(old_dn, new_dn)
        except Exception as exc:
            raise translate(exc) from exc

    def modify_attributes(self, dn: str, changes: dict[str, Any]) -> dict[str, Any]:
        """Replace attributes on *dn*.

        ``None`` or an empty value deletes the attribute. Returns the applied
        changes with their previous values, ready for the audit log.
        """
        import ldb

        current = self.get(dn, attrs=list(changes.keys()))
        if current is None:
            from samcon.core.errors import NotFound

            raise NotFound("The directory object does not exist.", context={"dn": dn})

        message = ldb.Message()
        message.dn = ldb.Dn(self.samdb, dn)
        applied: dict[str, Any] = {}

        for attr, new_value in changes.items():
            old_values = values.as_list(current, attr)
            old = old_values[0] if len(old_values) == 1 else (old_values or None)

            if new_value is None or new_value == "" or new_value == []:
                if not old_values:
                    continue  # nothing to delete
                message[attr] = ldb.MessageElement([], ldb.FLAG_MOD_DELETE, attr)
                applied[attr] = {"old": old, "new": None}
                continue

            wire = new_value if isinstance(new_value, list) else [new_value]
            wire = [str(v) for v in wire]
            if wire == old_values:
                continue  # unchanged — do not bump whenChanged for nothing
            message[attr] = ldb.MessageElement(wire, ldb.FLAG_MOD_REPLACE, attr)
            applied[attr] = {"old": old, "new": new_value}

        if not applied:
            return {}

        self.modify(message)
        return applied

    # -- housekeeping ------------------------------------------------------

    def is_alive(self) -> bool:
        try:
            self.samdb.search(base="", scope=SCOPE_BASE, attrs=["currentTime"])
        except Exception:  # noqa: BLE001 — any failure means reconnect
            return False
        return True

    def close(self) -> None:
        # ldb has no explicit close; dropping the reference is what releases
        # the socket. Named for the executor's teardown protocol.
        #
        # SYSVOL is different and has to be closed deliberately: an SMB
        # session left behind keeps the server's handles on whatever it
        # touched, and the next write to the same file fails with a sharing
        # violation — from a session that ended hours ago.
        if self.sysvol is not None:
            try:
                self.sysvol.close()
            except Exception:  # teardown must not raise
                logger.debug("closing the SYSVOL connection failed", exc_info=True)
            self.sysvol = None

        self.samdb = None


# ---------------------------------------------------------------------------
# DC discovery
# ---------------------------------------------------------------------------


def discover_dcs(target: ConnectionTarget) -> list[str]:
    """Return DC host names for *target*, most preferred first.

    Explicit hosts win — including the address an administrator typed into the
    sign-in form. Otherwise the domain's SRV records are queried, which is also
    what gives us automatic failover.
    """
    if target.hosts:
        # The discovered FQDN goes first, even when the user typed an IP:
        # Kerberos issues tickets for ldap/<hostname>@REALM, and no such
        # principal exists for a bare address. The typed address follows as a
        # fallback for when the container cannot resolve that name.
        hosts: list[str] = []
        if target.dc_hostname:
            hosts.append(target.dc_hostname)
        hosts.extend(host for host in target.hosts if host not in hosts)
        return hosts

    query = f"_ldap._tcp.dc._msdcs.{target.realm.lower()}"
    try:
        import dns.resolver

        answers = dns.resolver.resolve(query, "SRV")
    except Exception as exc:
        raise UpstreamUnavailable(
            "No domain controller could be discovered.",
            code="dc_discovery_failed",
            hint=(
                f"DNS lookup of {query} failed. Enter the server address directly "
                "at sign-in, or point the container at a DNS server that serves "
                "the domain."
            ),
            detail=str(exc),
        ) from exc

    # Lower priority first, higher weight first within a priority.
    records = sorted(answers, key=lambda r: (r.priority, -r.weight))
    hosts = [str(record.target).rstrip(".") for record in records]
    if not hosts:
        raise UpstreamUnavailable(
            "The domain published no domain controllers.",
            code="dc_discovery_empty",
            hint=f"{query} returned no SRV records.",
        )
    return hosts


# ---------------------------------------------------------------------------
# Connecting
# ---------------------------------------------------------------------------


# How SAMCON tries to reach a DC, in order.
#
# LDAP with GSSAPI sign-and-seal comes first: the Kerberos session key encrypts
# the traffic, no certificate is involved, and it is the path samba-tool and
# the Windows tools use — the best-supported one through Samba's client stack.
# LDAPS follows for environments where port 389 is closed.
TRANSPORTS: tuple[tuple[str, str], ...] = (
    ("ldap", "GSSAPI seal"),
    ("ldaps", "TLS"),
)


def _build_loadparm(settings: Settings, target: ConnectionTarget, transport: str) -> Any:
    # Transport protection is configured through loadparm, not through the
    # SamDB constructor — see samcon.auth.kerberos.apply_transport_settings.
    from samcon.auth.kerberos import load_loadparm

    return load_loadparm(settings, target, transport=transport)


def _credentials_from_ccache(ccache: Path, settings: Settings, lp: Any) -> Any:
    from samba.credentials import MUST_USE_KERBEROS, Credentials

    from samcon.auth.kerberos import CRED_SPECIFIED, ccache_url

    creds = Credentials()
    creds.guess(lp)
    creds.set_kerberos_state(MUST_USE_KERBEROS)

    # Two details that are easy to get wrong and fail identically — with an
    # NT_STATUS_INVALID_PARAMETER at bind time, long after the ticket was
    # obtained without complaint:
    #
    #   * the cache name needs its "FILE:" type prefix,
    #   * "obtained" must be CRED_SPECIFIED. It is 6, not 3 — 3 is
    #     CRED_GUESS_ENV, which leaves the cache at guess priority and lets
    #     other sources win.
    name = ccache_url(ccache)

    # The binding's signature has changed across Samba releases; try the
    # documented forms in order instead of pinning one.
    errors = []
    for attempt in (
        lambda: creds.set_named_ccache(name, CRED_SPECIFIED, lp),
        lambda: creds.set_named_ccache(name, lp),
        lambda: creds.set_named_ccache(name),
    ):
        try:
            attempt()
            return creds
        except TypeError as exc:
            errors.append(str(exc))
            continue
        except Exception as exc:
            raise translate(exc) from exc

    raise SamconError(
        "The Kerberos credential cache could not be attached to the LDAP connection.",
        code="ccache_unsupported",
        detail="; ".join(errors),
        hint="Samba's Credentials.set_named_ccache has an unexpected signature in this build.",
    )


def _read_domain_info(samdb: Any, host: str, target: ConnectionTarget) -> DomainInfo:
    result = samdb.search(
        base="",
        scope=SCOPE_BASE,
        attrs=[
            "defaultNamingContext",
            "configurationNamingContext",
            "schemaNamingContext",
            "rootDomainNamingContext",
            "dnsHostName",
            "domainFunctionality",
            "forestFunctionality",
        ],
    )
    if not len(result):
        raise UpstreamUnavailable(
            "The domain controller returned an empty rootDSE.",
            code="rootdse_empty",
        )
    root = result[0]

    base_dn = values.as_str(root, "defaultNamingContext") or ""
    try:
        domain_sid = str(samdb.get_domain_sid())
    except Exception:  # noqa: BLE001 — not fatal, only used for display
        domain_sid = None

    dns_domain = ".".join(
        part[3:] for part in base_dn.split(",") if part.upper().startswith("DC=")
    )

    return DomainInfo(
        dc_hostname=values.as_str(root, "dnsHostName") or host,
        base_dn=base_dn,
        config_dn=values.as_str(root, "configurationNamingContext")
        or f"CN=Configuration,{base_dn}",
        schema_dn=values.as_str(root, "schemaNamingContext")
        or f"CN=Schema,CN=Configuration,{base_dn}",
        root_domain_dn=values.as_str(root, "rootDomainNamingContext") or base_dn,
        domain_sid=domain_sid,
        dns_domain=dns_domain or target.dns_domain or target.realm.lower(),
        netbios_name=target.netbios_name,
        domain_functional_level=values.as_int(root, "domainFunctionality"),
        forest_functional_level=values.as_int(root, "forestFunctionality"),
    )


def connect(target: ConnectionTarget, settings: Settings, ccache: Path) -> DirectoryConnection:
    """Open an authenticated connection to *target*.

    Every candidate DC is tried with LDAP + GSSAPI seal first and LDAPS second;
    both are encrypted, so the fallback never weakens the connection.

    Runs in a worker thread. The returned object stays bound to that thread.
    """
    try:
        from samba.samdb import SamDB
    except ImportError as exc:  # pragma: no cover
        raise SamconError(
            "The Samba python bindings are not available.",
            code="samba_missing",
            hint="The container image must provide python3-samba.",
        ) from exc

    if target.insecure or settings.ldap_insecure:
        logger.warning(
            "LDAPS certificate validation is disabled for %s — an LDAPS fallback "
            "would be encrypted but the server's identity unverified",
            target.display_name,
        )

    candidates = discover_dcs(target)
    if not candidates:
        # Nothing was tried, so "unreachable" would be the wrong word and the
        # advice that follows it — check ports, check the clock — sends the
        # reader looking in the wrong place entirely. A configured realm with
        # no configured hosts lands here whenever the container's resolver
        # does not serve the domain, which is the normal case for Docker.
        raise UpstreamUnavailable(
            "No domain controller could be found for this domain.",
            code="no_dc_candidates",
            hint=(
                "No server address is configured for this domain and the DNS "
                "lookup for its _ldap._tcp SRV records found none. Give the "
                "container a DC address, or a resolver that serves the domain."
            ),
            context={"realm": target.realm},
        )

    failures: list[str] = []
    for host in candidates:
        for transport, protection in TRANSPORTS:
            url = f"{transport}://{host}"
            try:
                # A fresh LoadParm per transport: the SASL wrapping and TLS
                # settings differ, and Samba reads them at connect time.
                lp = _build_loadparm(settings, target, transport)
                creds = _credentials_from_ccache(ccache, settings, lp)
                samdb = SamDB(url=url, lp=lp, credentials=creds)
                info = _read_domain_info(samdb, host, target)
            except Exception as exc:
                error = translate(exc)
                # The raw server text, not our summary: when a bind fails, the
                # actual reason is in Samba's message and nowhere else.
                failures.append(f"{url}: {error.detail or error.message}")
                logger.info(
                    "connection to %s (%s) failed: %s",
                    url,
                    protection,
                    error.detail or error.message,
                )
                # Bad credentials fail the same way on every DC and transport.
                if error.status_code in (401, 403):
                    raise error from exc
                continue

            logger.info(
                "connected to %s over %s (%s, base=%s)",
                info.dc_hostname,
                transport,
                protection,
                info.base_dn,
            )
            return DirectoryConnection(
                samdb, host, info, settings, lp=lp, creds=creds, target=target, ccache=ccache
            )

    if all(_is_address(host) for host in candidates):
        # Every candidate was a bare address, so this was never going to work
        # and the usual advice would send the reader to check ports and clocks
        # that are fine. Kerberos needs the DC's name.
        raise UpstreamUnavailable(
            "No domain controller could be reached.",
            code="dc_name_unknown",
            detail="; ".join(failures),
            hint=(
                "Only the address was available, and Kerberos issues tickets "
                "for ldap/<hostname> — no such principal exists for a bare "
                "address. SAMCON reads the name from the DC itself, so this "
                "usually means that probe failed: check that the container can "
                "resolve the DC's name and reach it on port 389 or 636."
            ),
            context={"realm": target.realm, "hosts": list(target.hosts)},
        )

    raise UpstreamUnavailable(
        "No domain controller could be reached.",
        code="dc_unreachable",
        detail="; ".join(failures),
        hint=(
            "SAMCON tried LDAP with Kerberos encryption (port 389) and LDAPS "
            "(port 636). Check that one of them is reachable, that the clock "
            "difference to the DC is under five minutes, and that the account "
            "exists in this domain."
        ),
        context={"realm": target.realm, "hosts": list(target.hosts)},
    )


def _is_address(host: str) -> bool:
    """Whether *host* is a literal address rather than a name."""
    import ipaddress

    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


def require_dn(dn: str | None, what: str = "Distinguished name") -> str:
    if not dn or "=" not in dn:
        raise InvalidRequest(f"{what} is missing or malformed.", code="invalid_dn")
    return dn
