"""DNS zones and records, through LDAP.

Active Directory keeps its DNS data in the directory, so SAMCON reads and
writes it over the same authenticated LDAP connection as everything else. The
alternative — the DCE/RPC dnsserver interface that ``samba-tool dns`` uses —
needs another port open and another set of permissions, and gains nothing here.

The layout:

* a zone is a ``dnsZone`` object under ``CN=MicrosoftDNS`` in one of three
  partitions (domain, forest, or the pre-2003 location under CN=System),
* every name in the zone is one ``dnsNode`` below it, and
* all records for that name live in its multi-valued ``dnsRecord`` attribute.

That last point shapes the whole module: "the A record of www" is one value
among several on a shared object, not an object of its own, and the directory
gives it no identifier. Editing therefore means read-modify-write of the node,
matching the record to change by its content.
"""

from __future__ import annotations

import logging
from typing import Any

from samcon.ad import dnsrecords, values
from samcon.ad.connection import SCOPE_ONELEVEL, SCOPE_SUBTREE, DirectoryConnection
from samcon.core.errors import Conflict, InvalidRequest, NotFound

logger = logging.getLogger(__name__)

# The node that represents the zone itself.
APEX = "@"

# Zones Samba maintains itself; editing them by hand causes more harm than good.
SYSTEM_ZONES = frozenset({"RootDNSServers", "..TrustAnchors"})

ZONE_ATTRS = [
    "distinguishedName",
    "name",
    "objectGUID",
    "dNSProperty",
    "whenCreated",
    "whenChanged",
]

NODE_ATTRS = ["distinguishedName", "name", "dnsRecord", "dNSTombstoned", "whenChanged"]


# ---------------------------------------------------------------------------
# Where zones live
# ---------------------------------------------------------------------------


def zone_containers(conn: DirectoryConnection) -> list[tuple[str, str]]:
    """(partition label, container DN) for every place zones can be stored."""
    base = conn.info.base_dn
    forest = conn.info.root_domain_dn or base
    return [
        ("domain", f"CN=MicrosoftDNS,DC=DomainDnsZones,{base}"),
        ("forest", f"CN=MicrosoftDNS,DC=ForestDnsZones,{forest}"),
        # Where zones lived before application partitions existed. Still in use
        # on domains upgraded from that era.
        ("legacy", f"CN=MicrosoftDNS,CN=System,{base}"),
    ]


def list_zones(conn: DirectoryConnection, *, include_system: bool = False) -> list[dict[str, Any]]:
    """Every DNS zone the directory holds, across all three partitions."""
    zones: list[dict[str, Any]] = []

    for partition, container in zone_containers(conn):
        try:
            result = conn.search(
                container,
                scope=SCOPE_ONELEVEL,
                expression="(objectClass=dnsZone)",
                attrs=ZONE_ATTRS,
            )
        except Exception:
            logger.debug("no DNS zones in %s", container, exc_info=True)
            continue

        for entry in result:
            name = values.as_str(entry, "name") or ""
            if not include_system and name in SYSTEM_ZONES:
                continue
            zones.append(
                {
                    "dn": values.as_str(entry, "distinguishedName") or str(entry.dn),
                    "name": name,
                    "partition": partition,
                    "reverse": name.lower().endswith((".in-addr.arpa", ".ip6.arpa")),
                    "guid": values.guid_to_str(values.as_bytes(entry, "objectGUID")),
                    "when_changed": values.as_generalized_time(entry, "whenChanged"),
                }
            )

    zones.sort(key=lambda zone: (zone["reverse"], zone["name"].lower()))
    return zones


def find_zone(conn: DirectoryConnection, name: str) -> dict[str, Any]:
    """Look up a zone by name."""
    wanted = name.strip().rstrip(".").lower()
    for zone in list_zones(conn, include_system=True):
        if zone["name"].lower() == wanted:
            return zone
    raise NotFound("The DNS zone does not exist.", code="zone_not_found", context={"zone": name})


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------


def relative_name(name: str, zone: str) -> str:
    """Turn a name into the node name used inside *zone*.

    ``www.example.lan`` in zone ``example.lan`` is the node ``www``; the zone
    itself is ``@``.
    """
    text = (name or "").strip().rstrip(".").lower()
    zone_name = zone.strip().rstrip(".").lower()

    if not text or text in (APEX, zone_name):
        return APEX
    if text.endswith(f".{zone_name}"):
        return text[: -len(zone_name) - 1]
    return text


def absolute_name(node: str, zone: str) -> str:
    """The fully qualified name of a node."""
    zone_name = zone.strip().rstrip(".").lower()
    if node == APEX:
        return zone_name
    return f"{node.lower()}.{zone_name}"


def node_dn(zone_dn: str, node: str) -> str:
    return f"DC={values.escape_rdn_value(node)},{zone_dn}"


# ---------------------------------------------------------------------------
# Reading records
# ---------------------------------------------------------------------------


def list_records(
    conn: DirectoryConnection,
    zone_dn: str,
    *,
    zone_name: str | None = None,
    include_tombstones: bool = False,
) -> dict[str, Any]:
    """Every record in a zone, flattened to one entry per record.

    The directory groups them by name; a table of records is what an
    administrator wants to see.
    """
    zone = zone_name or values.name_from_dn(zone_dn)

    result = conn.search(
        zone_dn,
        scope=SCOPE_SUBTREE,
        expression="(objectClass=dnsNode)",
        attrs=NODE_ATTRS,
        max_results=10000,
    )

    records: list[dict[str, Any]] = []
    for entry in result:
        node = values.as_str(entry, "name") or APEX
        dn = values.as_str(entry, "distinguishedName") or str(entry.dn)
        tombstoned_node = values.as_bool(entry, "dNSTombstoned", False)

        raw_values = entry.get("dnsRecord")
        for index, raw in enumerate(raw_values or []):
            try:
                decoded = dnsrecords.decode(bytes(raw))
            except Exception:
                logger.warning("undecodable dnsRecord on %s", dn, exc_info=True)
                continue

            if decoded["tombstone"] and not include_tombstones:
                continue

            records.append(
                {
                    **decoded,
                    # The index identifies the value within its node, which is
                    # the closest thing to a record identifier that exists.
                    "index": index,
                    "node": node,
                    "name": absolute_name(node, zone),
                    "dn": dn,
                    "node_tombstoned": tombstoned_node,
                    "editable": decoded["type"] in dnsrecords.EDITABLE_TYPES,
                }
            )

    # The zone's own records first, then by name; an empty string sorts ahead
    # of everything else.
    records.sort(
        key=lambda record: ("" if record["node"] == APEX else record["node"], record["type"])
    )
    return {"zone": zone, "zone_dn": zone_dn, "records": records}


# ---------------------------------------------------------------------------
# Writing records
# ---------------------------------------------------------------------------


def _read_node(conn: DirectoryConnection, dn: str) -> tuple[Any, list[bytes]]:
    entry = conn.get(dn, attrs=NODE_ATTRS)
    if entry is None:
        return None, []
    return entry, [bytes(raw) for raw in (entry.get("dnsRecord") or [])]


def _readable(packed: list[bytes], dn: str) -> list[dict[str, Any]]:
    """The records of a node that we can decode, skipping the ones we cannot."""
    decoded: list[dict[str, Any]] = []
    for raw in packed:
        try:
            decoded.append(dnsrecords.decode(raw))
        except Exception:
            logger.warning("undecodable dnsRecord on %s", dn, exc_info=True)
    return decoded


def _write_node_records(conn: DirectoryConnection, dn: str, packed: list[bytes]) -> None:
    import ldb

    message = ldb.Message()
    message.dn = ldb.Dn(conn.samdb, dn)
    message["dnsRecord"] = ldb.MessageElement(packed, ldb.FLAG_MOD_REPLACE, "dnsRecord")
    conn.modify(message)


def advance_zone_serial(conn: DirectoryConnection, zone_dn: str) -> int:
    """Raise the zone's SOA serial by one and return the new value.

    Every change to a zone has to advance it: the serial is how a secondary
    server decides whether there is anything to fetch, and it is what
    ``samba-tool dns query`` reports. Samba does this in
    ``dnsserver_update_soa()`` before each write and stamps the record it
    writes with the serial it got back — SAMCON follows suit, so that records
    from both tools carry the same kind of value.

    A zone without an SOA is not something to fail a record write over. It
    cannot be served either way, and refusing the write would leave the
    administrator with a zone that can only be repaired elsewhere.
    """
    apex_dn = node_dn(zone_dn, APEX)
    entry, existing = _read_node(conn, apex_dn)
    if entry is None:
        logger.warning("zone %s has no apex node; leaving the serial alone", zone_dn)
        return 1

    updated: list[bytes] = []
    serial = 1
    bumped = False
    for raw in existing:
        if not bumped:
            try:
                replacement, serial = dnsrecords.bump_soa_serial(raw)
            except Exception:  # noqa: BLE001 — anything that is not a readable SOA
                updated.append(raw)
                continue
            updated.append(replacement)
            bumped = True
        else:
            updated.append(raw)

    if not bumped:
        logger.warning("zone %s has no SOA record; leaving the serial alone", zone_dn)
        return 1

    _write_node_records(conn, apex_dn, updated)
    return serial


def create_record(
    conn: DirectoryConnection,
    zone_dn: str,
    *,
    zone_name: str,
    name: str,
    record_type: str,
    data: dict[str, Any],
    ttl: int | None = None,
) -> dict[str, Any]:
    """Add a record, creating the node if this is the first one for that name."""
    import ldb

    kind = record_type.strip().upper()
    clean = dnsrecords.validate_data(kind, data)
    seconds = dnsrecords.validate_ttl(ttl)

    node = relative_name(name, zone_name)
    dn = node_dn(zone_dn, node)

    # Read first: a rejected duplicate must not have moved the zone's serial.
    entry, existing = _read_node(conn, dn)
    for decoded in _readable(existing, dn):
        if dnsrecords.matches(decoded, kind, clean):
            raise Conflict(
                "This record already exists.",
                code="record_exists",
                context={"name": absolute_name(node, zone_name), "type": kind},
            )

    serial = advance_zone_serial(conn, zone_dn)
    packed = dnsrecords.encode(kind, clean, ttl=seconds, serial=serial)
    # Re-read: a record on the zone's own name shares its node with the SOA
    # that was just rewritten, and the copy above no longer has it.
    entry, existing = _read_node(conn, dn)

    if entry is None:
        message = ldb.Message()
        message.dn = ldb.Dn(conn.samdb, dn)
        message["objectClass"] = ldb.MessageElement(
            ["top", "dnsNode"], ldb.FLAG_MOD_ADD, "objectClass"
        )
        message["dnsRecord"] = ldb.MessageElement([packed], ldb.FLAG_MOD_ADD, "dnsRecord")
        conn.add(message)
    else:
        _write_node_records(conn, dn, [*existing, packed])

    return {
        "name": absolute_name(node, zone_name),
        "node": node,
        "type": kind,
        "ttl": seconds,
        "data": clean,
        "display": dnsrecords.format_data(kind, clean),
        "dn": dn,
    }


def update_record(
    conn: DirectoryConnection,
    zone_dn: str,
    *,
    zone_name: str,
    name: str,
    record_type: str,
    old_data: dict[str, Any],
    data: dict[str, Any],
    ttl: int | None = None,
) -> dict[str, Any]:
    """Replace one record on a node, leaving the others untouched."""
    kind = record_type.strip().upper()
    clean = dnsrecords.validate_data(kind, data)
    seconds = dnsrecords.validate_ttl(ttl)

    node = relative_name(name, zone_name)
    dn = node_dn(zone_dn, node)

    # Read first: an edit that finds nothing to change must not have moved the
    # zone's serial.
    entry, existing = _read_node(conn, dn)
    if entry is None:
        raise NotFound("The DNS name does not exist.", code="record_not_found", context={"dn": dn})
    if not any(dnsrecords.matches(decoded, kind, old_data) for decoded in _readable(existing, dn)):
        raise NotFound(
            "The record no longer exists in this form.",
            code="record_not_found",
            hint="It may have been changed by someone else in the meantime.",
        )

    serial = advance_zone_serial(conn, zone_dn)
    entry, existing = _read_node(conn, dn)

    replaced = False
    updated: list[bytes] = []
    for raw in existing:
        try:
            decoded = dnsrecords.decode(raw)
        except Exception:  # noqa: BLE001 — keep values we cannot read
            updated.append(raw)
            continue

        if not replaced and dnsrecords.matches(decoded, kind, old_data):
            updated.append(dnsrecords.encode(kind, clean, ttl=seconds, serial=serial))
            replaced = True
        else:
            updated.append(raw)

    if not replaced:
        # Only reachable if the record went away between the two reads.
        raise NotFound(
            "The record no longer exists in this form.",
            code="record_not_found",
            hint="It may have been changed by someone else in the meantime.",
        )

    _write_node_records(conn, dn, updated)
    return {
        "name": absolute_name(node, zone_name),
        "node": node,
        "type": kind,
        "ttl": seconds,
        "data": clean,
        "display": dnsrecords.format_data(kind, clean),
        "dn": dn,
    }


def delete_record(
    conn: DirectoryConnection,
    zone_dn: str,
    *,
    zone_name: str,
    name: str,
    record_type: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Remove one record. The node goes too once its last record is gone."""
    kind = record_type.strip().upper()
    node = relative_name(name, zone_name)
    dn = node_dn(zone_dn, node)

    # Read first: a deletion that finds nothing must not have moved the zone's
    # serial.
    entry, existing = _read_node(conn, dn)
    if entry is None:
        raise NotFound("The DNS name does not exist.", code="record_not_found", context={"dn": dn})
    if not any(dnsrecords.matches(decoded, kind, data) for decoded in _readable(existing, dn)):
        raise NotFound(
            "The record does not exist.",
            code="record_not_found",
            context={"name": absolute_name(node, zone_name), "type": kind},
        )

    advance_zone_serial(conn, zone_dn)
    entry, existing = _read_node(conn, dn)

    kept: list[bytes] = []
    removed = False
    for raw in existing:
        try:
            decoded = dnsrecords.decode(raw)
        except Exception:  # noqa: BLE001
            kept.append(raw)
            continue

        if not removed and dnsrecords.matches(decoded, kind, data):
            removed = True
            continue
        kept.append(raw)

    if not removed:
        raise NotFound(
            "The record does not exist.",
            code="record_not_found",
            context={"name": absolute_name(node, zone_name), "type": kind},
        )

    if kept:
        _write_node_records(conn, dn, kept)
        node_deleted = False
    else:
        # An empty dnsNode would be served as an existing name with no data,
        # which is not the same as a name that does not exist.
        conn.delete(dn)
        node_deleted = True

    return {"name": absolute_name(node, zone_name), "type": kind, "node_deleted": node_deleted}


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------


def create_zone(
    conn: DirectoryConnection,
    name: str,
    *,
    partition: str = "domain",
    forest_wide: bool = False,
) -> dict[str, Any]:
    """Create a zone with the SOA and NS records it needs to be answerable.

    A zone object without those two is loaded by the server but answers
    nothing, which looks like a broken zone rather than a new one.
    """
    import ldb

    zone_name = dnsrecords.normalise_name(name, what="Zone name")

    containers = dict(zone_containers(conn))
    label = "forest" if forest_wide else partition
    container = containers.get(label)
    if container is None:
        raise InvalidRequest(
            f"Unknown DNS partition '{partition}'.",
            code="unknown_dns_partition",
            context={"supported": list(containers)},
        )

    zone_dn = f"DC={values.escape_rdn_value(zone_name)},{container}"
    if conn.exists(zone_dn):
        raise Conflict(
            "A zone with this name already exists.",
            code="zone_exists",
            context={"zone": zone_name},
        )

    message = ldb.Message()
    message.dn = ldb.Dn(conn.samdb, zone_dn)
    message["objectClass"] = ldb.MessageElement(
        ["top", "dnsZone"], ldb.FLAG_MOD_ADD, "objectClass"
    )
    conn.add(message)

    primary = conn.info.dc_hostname or conn.info.dns_domain
    apex_dn = node_dn(zone_dn, APEX)

    apex = ldb.Message()
    apex.dn = ldb.Dn(conn.samdb, apex_dn)
    apex["objectClass"] = ldb.MessageElement(["top", "dnsNode"], ldb.FLAG_MOD_ADD, "objectClass")
    apex["dnsRecord"] = ldb.MessageElement(
        [
            dnsrecords.encode_soa(
                mname=primary,
                rname=f"hostmaster.{zone_name}",
                zone_ttl=dnsrecords.DEFAULT_TTL,
            ),
            dnsrecords.encode("NS", {"target": primary}, ttl=dnsrecords.DEFAULT_TTL),
        ],
        ldb.FLAG_MOD_ADD,
        "dnsRecord",
    )
    conn.add(apex)

    return {"dn": zone_dn, "name": zone_name, "partition": label}


def delete_zone(conn: DirectoryConnection, zone_dn: str) -> None:
    """Delete a zone and everything in it."""
    name = values.name_from_dn(zone_dn)
    if name in SYSTEM_ZONES:
        raise InvalidRequest(
            "This zone is maintained by the directory and cannot be deleted.",
            code="system_zone",
            context={"zone": name},
        )
    conn.delete(zone_dn, recursive=True)
