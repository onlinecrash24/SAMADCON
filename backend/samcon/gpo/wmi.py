"""WMI filters.

A WMI filter is a WQL query that decides at apply time whether a policy is
used on a machine — "only on laptops", "only on Windows 11". It is a separate
directory object; a policy points at one through ``gPCWQLFilter``.

Samba does not evaluate these itself: they are applied by Windows clients.
Reading and assigning them is still worth having, because a filter assigned to
a policy explains why it does not apply somewhere, and that is invisible
otherwise.

Creating filters is not offered. The query language is WQL, a wrong query
silently matches nothing, and a filter that matches nothing looks exactly like
a policy that is broken.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from samcon.ad import values
from samcon.ad.connection import SCOPE_ONELEVEL, DirectoryConnection
from samcon.core.errors import InvalidRequest, NotFound
from samcon.gpo import container

logger = logging.getLogger(__name__)

FILTER_ATTRS = [
    "distinguishedName",
    "msWMI-Name",
    "msWMI-Parm1",
    "msWMI-Parm2",
    "msWMI-ID",
    "msWMI-Author",
    "whenCreated",
    "whenChanged",
]

# gPCWQLFilter holds "[<domain>;<{GUID}>;0]".
_ASSIGNMENT_RE = re.compile(r"^\[(?P<domain>[^;]*);(?P<id>\{[^}]+\});(?P<flags>\d+)\]$")

# msWMI-Parm2 packs each query as
#   <n>;<namespace length>;<query length>;WQL;<namespace>;<query>;
# The lengths are what makes it unambiguous, and they are there for a reason:
# a WQL query may contain semicolons.
_QUERY_RE = re.compile(r"(?P<namespace_length>\d+);(?P<query_length>\d+);WQL;", re.IGNORECASE)


def filters_dn(conn: DirectoryConnection) -> str:
    return f"CN=SOM,CN=WMIPolicy,CN=System,{conn.info.base_dn}"


def list_filters(conn: DirectoryConnection) -> list[dict[str, Any]]:
    """Every WMI filter in the domain."""
    try:
        result = conn.search(
            filters_dn(conn),
            scope=SCOPE_ONELEVEL,
            expression="(objectClass=msWMI-Som)",
            attrs=FILTER_ATTRS,
        )
    except NotFound:
        # The container is created with the first filter; its absence means
        # the domain has none, not that anything is wrong.
        return []

    filters = [_describe(entry) for entry in result]
    filters.sort(key=lambda item: (item["name"] or "").lower())
    return filters


def _describe(entry: Any) -> dict[str, Any]:
    dn = values.as_str(entry, "distinguishedName") or str(entry.dn)
    return {
        "dn": dn,
        "id": values.as_str(entry, "msWMI-ID") or values.name_from_dn(dn),
        "name": values.as_str(entry, "msWMI-Name"),
        "description": values.as_str(entry, "msWMI-Parm1"),
        "queries": parse_queries(values.as_str(entry, "msWMI-Parm2")),
        "author": values.as_str(entry, "msWMI-Author"),
        "created": values.as_generalized_time(entry, "whenCreated"),
        "changed": values.as_generalized_time(entry, "whenChanged"),
    }


def parse_queries(parm2: str | None) -> list[dict[str, str]]:
    """Pull the namespace and query pairs out of ``msWMI-Parm2``.

    The lengths are used rather than the separators: a query may contain a
    semicolon, and splitting on those would cut it in half at exactly the
    filters that are most worth reading.
    """
    if not parm2:
        return []

    found: list[dict[str, str]] = []
    for match in _QUERY_RE.finditer(parm2):
        namespace_length = int(match.group("namespace_length"))
        query_length = int(match.group("query_length"))

        start = match.end()
        end_of_namespace = start + namespace_length
        start_of_query = end_of_namespace + 1  # the separator after the namespace
        end_of_query = start_of_query + query_length
        if end_of_query > len(parm2):
            # The lengths do not describe this string; fall through to
            # reporting the attribute whole rather than slicing it wrongly.
            found = []
            break

        found.append(
            {
                "namespace": parm2[start:end_of_namespace],
                "query": parm2[start_of_query:end_of_query],
            }
        )

    if found:
        return found
    # Unreadable: show it whole rather than claim the filter is empty.
    return [{"namespace": "", "query": parm2.strip()}]


def parse_assignment(value: str | None) -> dict[str, str] | None:
    """Read a policy's ``gPCWQLFilter``."""
    if not value:
        return None
    match = _ASSIGNMENT_RE.match(value.strip())
    if match is None:
        return {"domain": "", "id": value.strip(), "flags": "0"}
    return {
        "domain": match.group("domain"),
        "id": match.group("id"),
        "flags": match.group("flags"),
    }


def format_assignment(domain: str, filter_id: str) -> str:
    return f"[{domain};{filter_id};0]"


def get_filter(conn: DirectoryConnection, dn: str) -> dict[str, Any]:
    entry = conn.get(dn, attrs=FILTER_ATTRS)
    if entry is None:
        raise NotFound(
            "The WMI filter does not exist.", code="wmi_filter_not_found", context={"dn": dn}
        )
    return _describe(entry)


def describe_for_gpo(conn: DirectoryConnection, gpo: dict[str, Any]) -> dict[str, Any] | None:
    """The filter a policy uses, resolved to its name and query.

    A policy can point at a filter that has been deleted; that is reported as
    a missing filter rather than as no filter, because the effect is the
    opposite — a policy pointing at a filter that is gone applies nowhere.
    """
    assignment = parse_assignment(gpo.get("wmi_filter"))
    if assignment is None:
        return None

    for item in list_filters(conn):
        if item["id"].lower() == assignment["id"].lower():
            return {**item, "missing": False}

    return {
        "dn": None,
        "id": assignment["id"],
        "name": None,
        "queries": [],
        "missing": True,
    }


def assign(conn: DirectoryConnection, gpo_dn: str, filter_dn: str | None) -> dict[str, Any]:
    """Point a policy at a WMI filter, or clear the assignment."""
    gpo = container.get_gpo(conn, gpo_dn)

    if filter_dn is None:
        conn.modify_attributes(gpo_dn, {"gPCWQLFilter": None})
        return container.get_gpo(conn, gpo_dn)

    wmi_filter = get_filter(conn, filter_dn)
    if not wmi_filter["id"]:
        raise InvalidRequest(
            "This WMI filter has no identifier to point at.",
            code="invalid_wmi_filter",
            context={"dn": filter_dn},
        )

    value = format_assignment(conn.info.dns_domain, wmi_filter["id"])
    conn.modify_attributes(gpo_dn, {"gPCWQLFilter": value})
    logger.info("assigned WMI filter %s to %s", wmi_filter["name"], gpo["guid"])
    return container.get_gpo(conn, gpo_dn)
