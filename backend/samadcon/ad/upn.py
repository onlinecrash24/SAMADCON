"""User principal name suffixes: what the forest offers, and the ones that
were added by hand.

Two sources, and only one of them is editable. Every domain in the forest is
a suffix by nature — its DNS name, read from the crossRef that carries a
nETBIOSName. Anything else lives in ``uPNSuffixes`` on the Partitions
container, where RSAT's Domains and Trusts writes it. That attribute is the
whole of what this module changes.

A suffix is a DNS name and is checked as one: labels of letters, digits and
hyphens, joined by dots. Not because the directory would refuse anything
else — it takes any string — but because a suffix with a space or an @ in it
is a logon name nobody can type, and the place to learn that is here rather
than at the next sign-in.
"""

from __future__ import annotations

import re
from typing import Any

from samadcon.ad import values
from samadcon.ad.connection import SCOPE_ONELEVEL, DirectoryConnection
from samadcon.core.errors import InvalidRequest

_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_SUFFIX_RE = re.compile(rf"^{_LABEL}(?:\.{_LABEL})*$", re.IGNORECASE)
MAX_SUFFIX_LENGTH = 255


def partitions_dn(conn: DirectoryConnection) -> str:
    return f"CN=Partitions,{conn.info.config_dn}"


def forest_domains(conn: DirectoryConnection) -> list[str]:
    """The DNS root of every domain in the forest, this one first.

    Domains are the crossRefs with a nETBIOSName; the other crossRefs are the
    configuration and schema partitions and application partitions such as
    DomainDnsZones, none of which is a UPN suffix.
    """
    found = [conn.info.dns_domain]
    for ref in conn.search(
        partitions_dn(conn),
        scope=SCOPE_ONELEVEL,
        expression="(&(objectClass=crossRef)(nETBIOSName=*))",
        attrs=["dnsRoot"],
    ):
        root = values.as_str(ref, "dnsRoot")
        if root and root.lower() not in {d.lower() for d in found}:
            found.append(root)
    return found


def added_suffixes(conn: DirectoryConnection) -> list[str]:
    """What was added by hand: ``uPNSuffixes`` on the Partitions container."""
    container = conn.get(partitions_dn(conn), attrs=["uPNSuffixes"])
    if container is None:
        return []
    return values.as_list(container, "uPNSuffixes")


def describe(conn: DirectoryConnection) -> dict[str, Any]:
    """Both lists, kept apart: one can be edited, the other only read."""
    return {"added": added_suffixes(conn), "domains": forest_domains(conn)}


def normalise(suffixes: list[str], domains: list[str]) -> list[str]:
    """The list as it will be written, or an error naming the first bad entry.

    Whitespace trimmed, duplicates dropped without regard to case (DNS has
    none) keeping the first spelling, and a domain's own name refused: it is
    a suffix already, and listing it twice would let it be "removed" from a
    list it was never in.
    """
    lowered_domains = {d.lower() for d in domains}
    seen: list[str] = []
    for raw in suffixes:
        suffix = raw.strip()
        if not suffix:
            continue
        if len(suffix) > MAX_SUFFIX_LENGTH or not _SUFFIX_RE.match(suffix):
            raise InvalidRequest(
                f"'{suffix}' is not a valid UPN suffix.",
                code="invalid_upn_suffix",
                context={"suffix": suffix},
            )
        if suffix.lower() in lowered_domains:
            raise InvalidRequest(
                f"'{suffix}' is a domain of this forest and a suffix already.",
                code="suffix_is_a_domain",
                context={"suffix": suffix},
            )
        if suffix.lower() not in {s.lower() for s in seen}:
            seen.append(suffix)
    return seen


def set_suffixes(conn: DirectoryConnection, suffixes: list[str]) -> dict[str, Any]:
    """Replace the hand-added suffixes with *suffixes*; an empty list clears them."""
    cleaned = normalise(suffixes, forest_domains(conn))
    return conn.modify_attributes(partitions_dn(conn), {"uPNSuffixes": cleaned})
