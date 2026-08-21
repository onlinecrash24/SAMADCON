"""What it takes to reach one domain.

SAMADCON used to be configured for a single domain at container start. It now
connects to whichever domain an administrator picks at sign-in, so realm, DC
list and TLS settings travel with the session instead of living in the
process-wide settings.

A target comes from one of three places, in this order of precedence:

1. a server the user typed into the sign-in form (realm discovered from the
   rootDSE — see :mod:`samadcon.ad.discovery`),
2. a profile from the server configuration file,
3. the container's default realm, if one is configured at all.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from samadcon.core.errors import InvalidRequest


@dataclass(frozen=True)
class ConnectionTarget:
    """One domain, reachable over a specific set of DCs."""

    realm: str
    # Explicit DC host names or IPs. Empty means: discover them via DNS SRV.
    hosts: tuple[str, ...] = ()
    label: str | None = None
    ca_file: Path | None = None
    # Skips LDAPS certificate validation. Encryption stays on; only the
    # server's identity goes unverified.
    insecure: bool = False
    profile_id: str | None = None
    # Resolved during discovery, kept for display and for Kerberos.
    dns_domain: str | None = None
    dc_hostname: str | None = None

    def __post_init__(self) -> None:
        if not self.realm:
            raise InvalidRequest(
                "No domain was given.",
                code="missing_realm",
                hint="Enter a server address, or configure SAMADCON_REALM.",
            )
        object.__setattr__(self, "realm", self.realm.strip().upper())

    @property
    def netbios_name(self) -> str:
        return self.realm.split(".")[0]

    @property
    def display_name(self) -> str:
        return self.label or self.dns_domain or self.realm.lower()

    @property
    def kdcs(self) -> tuple[str, ...]:
        """Hosts to use as key distribution centres.

        The DC we discovered comes first: when the user typed an IP, that is
        the only address we know actually answers.
        """
        ordered: list[str] = []
        for host in (*self.hosts, self.dc_hostname):
            if host and host not in ordered:
                ordered.append(host)
        return tuple(ordered)

    def with_discovery(
        self,
        *,
        realm: str | None = None,
        dns_domain: str | None = None,
        dc_hostname: str | None = None,
    ) -> ConnectionTarget:
        """Return a copy enriched with what the rootDSE told us."""
        return replace(
            self,
            realm=(realm or self.realm).upper(),
            dns_domain=dns_domain or self.dns_domain,
            dc_hostname=dc_hostname or self.dc_hostname,
        )

    def describe(self) -> dict[str, object]:
        """Safe to hand to the front end and the audit log."""
        return {
            "realm": self.realm,
            "label": self.label,
            "hosts": list(self.hosts),
            "dns_domain": self.dns_domain,
            "dc_hostname": self.dc_hostname,
            "profile_id": self.profile_id,
            "insecure": self.insecure,
            "ca_file": str(self.ca_file) if self.ca_file else None,
        }
