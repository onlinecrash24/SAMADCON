"""Links, inheritance and security filtering — the management half of GPMC.

Two questions an administrator asks and the directory does not answer
directly: *where is this policy linked* and *what actually applies to this
OU*. Both need walking the tree, because a link on a parent reaches every
child unless something stops it.
"""

from __future__ import annotations

import logging
from typing import Any

from samadcon.ad import directory, sacl, values
from samadcon.ad.connection import SCOPE_SUBTREE, DirectoryConnection
from samadcon.core.errors import Conflict, InvalidRequest, NotFound
from samadcon.gpo import container, links

logger = logging.getLogger(__name__)

# Containers that can carry a gPLink.
LINKABLE_CLASSES = ("domainDNS", "organizationalUnit", "site")

# The same statement in the two other vocabularies it has to be made in, both
# derived rather than written out again. A list of classes here and a list of
# types in the browser drift apart silently: nothing fails, a container simply
# stops being offered, or starts being offered where a link would do nothing.
LINKABLE_TYPES = frozenset(directory.type_for_class(name) for name in LINKABLE_CLASSES)

# What the management tree searches for one level down. Wider than
# LINKABLE_CLASSES on purpose: a container that already carries a link is part
# of the answer to "what applies where", whether or not a link belongs there.
# This tree is the only view that reports links by location, so a row dropped
# here is a live link nothing else would mention — the same reason a link whose
# policy is gone keeps its row. (gPLink=*) is the filter link_map already uses.
LINK_TREE_FILTER = (
    "(|" + "".join(f"(objectClass={name})" for name in LINKABLE_CLASSES) + "(gPLink=*))"
)

# Applying a GPO needs both of these on the object; GPMC calls the pair
# "security filtering".
RIGHT_READ = 0x00000010  # RIGHT_DS_READ_PROPERTY
RIGHT_APPLY_GROUP_POLICY = "edacfd8f-ffb3-11d1-b41d-00a0c968f939"


# ---------------------------------------------------------------------------
# Links on one container
# ---------------------------------------------------------------------------


def get_links(conn: DirectoryConnection, dn: str) -> dict[str, Any]:
    """The policies linked to one container, in the order they take effect."""
    entry = conn.get(dn, attrs=["distinguishedName", "name", "objectClass", "gPLink", "gPOptions"])
    if entry is None:
        raise NotFound("The container does not exist.", context={"dn": dn})

    parsed = links.parse(values.as_str(entry, "gPLink"))
    known = {gpo["dn"].lower(): gpo for gpo in container.list_gpos(conn)}

    resolved = []
    for link in parsed:
        gpo = known.get(link["dn"].lower())
        resolved.append(
            {
                **link,
                # A link whose target is gone still occupies its place in the
                # order; showing it as unresolved is the only way an
                # administrator finds out it is there.
                "display_name": gpo["display_name"] if gpo else None,
                "guid": gpo["name"] if gpo else values.name_from_dn(link["dn"]),
                "missing": gpo is None,
            }
        )

    options = values.as_int(entry, "gPOptions", 0) or 0
    return {
        "dn": values.as_str(entry, "distinguishedName") or dn,
        "name": values.as_str(entry, "name") or values.name_from_dn(dn),
        "links": resolved,
        "block_inheritance": bool(options & links.BLOCK_INHERITANCE),
    }


def _write_links(conn: DirectoryConnection, dn: str, updated: list[dict[str, Any]]) -> None:
    encoded = links.format(updated)
    # An empty attribute is not the same as an absent one to some clients, so
    # the attribute is removed rather than set to "".
    conn.modify_attributes(dn, {"gPLink": encoded or None})


def add_link(
    conn: DirectoryConnection,
    dn: str,
    gpo_dn: str,
    *,
    enabled: bool = True,
    enforced: bool = False,
) -> dict[str, Any]:
    """Link a policy to a container, at the top of the order.

    New links go first because that is what GPMC does and what people expect:
    the policy you just linked wins over the ones that were already there.
    """
    if not conn.exists(dn):
        raise NotFound("The container does not exist.", context={"dn": dn})
    target = container.get_gpo(conn, gpo_dn)

    current = get_links(conn, dn)
    if links.find(current["links"], target["dn"]) is not None:
        raise Conflict(
            "This policy is already linked here.",
            code="gpo_link_exists",
            context={"gpo": target["display_name"], "dn": dn},
        )

    updated = [
        {
            "dn": target["dn"],
            "options": links.options_for(enabled=enabled, enforced=enforced),
        },
        *current["links"],
    ]
    _write_links(conn, dn, updated)
    return get_links(conn, dn)


def remove_link(conn: DirectoryConnection, dn: str, gpo_dn: str) -> dict[str, Any]:
    current = get_links(conn, dn)
    index = links.find(current["links"], gpo_dn)
    if index is None:
        raise NotFound(
            "This policy is not linked here.", code="gpo_link_not_found", context={"dn": dn}
        )

    updated = [link for position, link in enumerate(current["links"]) if position != index]
    _write_links(conn, dn, updated)
    return get_links(conn, dn)


def update_link(
    conn: DirectoryConnection,
    dn: str,
    gpo_dn: str,
    *,
    enabled: bool | None = None,
    enforced: bool | None = None,
    order: int | None = None,
) -> dict[str, Any]:
    """Change one link: enable it, enforce it, or move it in the order."""
    current = get_links(conn, dn)
    index = links.find(current["links"], gpo_dn)
    if index is None:
        raise NotFound(
            "This policy is not linked here.", code="gpo_link_not_found", context={"dn": dn}
        )

    updated = list(current["links"])
    link = dict(updated[index])
    if enabled is not None:
        link["enabled"] = enabled
    if enforced is not None:
        link["enforced"] = enforced
    link["options"] = links.options_for(
        enabled=link.get("enabled", True), enforced=link.get("enforced", False)
    )
    updated[index] = link

    if order is not None:
        if order < 1 or order > len(updated):
            raise InvalidRequest(
                "That position does not exist.",
                code="invalid_link_order",
                context={"given": order, "count": len(updated)},
            )
        updated = links.move(updated, index, order - 1)

    _write_links(conn, dn, updated)
    return get_links(conn, dn)


def set_inheritance_block(conn: DirectoryConnection, dn: str, block: bool) -> dict[str, Any]:
    """Block or unblock inherited policies on a container.

    Enforced links from above ignore this — that is the whole point of
    enforcing them — so a blocked OU is not necessarily an unaffected one.
    """
    entry = conn.get(dn, attrs=["gPOptions"])
    if entry is None:
        raise NotFound("The container does not exist.", context={"dn": dn})

    options = values.as_int(entry, "gPOptions", 0) or 0
    updated = options | links.BLOCK_INHERITANCE if block else options & ~links.BLOCK_INHERITANCE
    if updated != options:
        conn.modify_attributes(dn, {"gPOptions": str(updated)})
    return get_links(conn, dn)


# ---------------------------------------------------------------------------
# Where a policy is linked
# ---------------------------------------------------------------------------


def link_map(conn: DirectoryConnection) -> dict[str, list[dict[str, Any]]]:
    """Every link in the domain and the configuration, by policy GUID.

    Two searches for the whole domain rather than two per policy.
    :func:`find_links` is right for one policy on its own page and wrong
    for a report that asks about all of them: twenty policies would cost
    forty searches, and every answer sits in the same attribute anyway.
    """
    found: dict[str, list[dict[str, Any]]] = {}
    for base in (conn.info.base_dn, conn.info.config_dn):
        try:
            result = conn.search(
                base,
                scope=SCOPE_SUBTREE,
                expression="(gPLink=*)",
                attrs=["distinguishedName", "name", "objectClass", "gPLink"],
            )
        except Exception:
            logger.debug("cannot search %s for links", base, exc_info=True)
            continue

        for entry in result:
            dn = values.as_str(entry, "distinguishedName") or str(entry.dn)
            for link in links.parse(values.as_str(entry, "gPLink")):
                guid = values.name_from_dn(link["dn"]).upper()
                found.setdefault(guid, []).append(
                    {
                        "container": values.as_str(entry, "name")
                        or values.name_from_dn(dn),
                        "container_dn": dn,
                        "kind": _container_kind(entry),
                        "order": link["order"],
                        "enabled": link["enabled"],
                        "enforced": link["enforced"],
                    }
                )
    return found


def links_by_container(conn: DirectoryConnection) -> dict[str, Any]:
    """Every container that links something, with what it links, in order.

    The inverse of :func:`link_map`, and the shape the management tree needs:
    a container with its policies under it, exactly as GPMC draws it.

    Link order is what decides precedence — 1 wins — so the entries are sorted
    by it. A tree that listed them in whatever order the attribute happened to
    parse in would be showing something that looks like precedence and is not.
    """
    by_guid = link_map(conn)
    names = {
        (gpo.get("guid") or "").upper(): gpo.get("display_name") or gpo.get("name")
        for gpo in container.list_gpos(conn)
    }

    containers: dict[str, dict[str, Any]] = {}
    for guid, places in by_guid.items():
        for place in places:
            node = containers.setdefault(
                place["container_dn"],
                {
                    "dn": place["container_dn"],
                    "name": place["container"],
                    "kind": place["kind"],
                    "links": [],
                },
            )
            node["links"].append(
                {
                    "guid": guid,
                    # None when the policy is linked but no longer exists — a
                    # real state, and one the tree should show rather than
                    # silently drop: a link to nothing still costs every client
                    # in scope a lookup on each refresh.
                    "display_name": names.get(guid),
                    "order": place["order"],
                    "enabled": place["enabled"],
                    "enforced": place["enforced"],
                }
            )

    for node in containers.values():
        node["links"].sort(key=lambda link: link["order"])

    return {"containers": sorted(containers.values(), key=lambda node: node["dn"].lower())}


def find_links(conn: DirectoryConnection, guid: str) -> list[dict[str, Any]]:
    """Every container in the domain and the configuration that links *guid*.

    One subtree search per partition with a filter on the GUID text, rather
    than reading every container and parsing its links: the attribute is
    indexed as a string and the GUID is distinctive enough that a substring
    match has no false positives worth worrying about.
    """
    needle = container.normalise_guid(guid)
    escaped = values.escape_filter(needle)
    expression = f"(gPLink=*{escaped}*)"

    found: list[dict[str, Any]] = []
    for base in (conn.info.base_dn, conn.info.config_dn):
        try:
            result = conn.search(
                base,
                scope=SCOPE_SUBTREE,
                expression=expression,
                attrs=["distinguishedName", "name", "objectClass", "gPLink", "gPOptions"],
            )
        except Exception:
            logger.debug("cannot search %s for links", base, exc_info=True)
            continue

        for entry in result:
            dn = values.as_str(entry, "distinguishedName") or str(entry.dn)
            parsed = links.parse(values.as_str(entry, "gPLink"))
            for link in parsed:
                if values.name_from_dn(link["dn"]).upper() != needle:
                    continue
                found.append(
                    {
                        "container": values.as_str(entry, "name") or values.name_from_dn(dn),
                        "container_dn": dn,
                        "kind": _container_kind(entry),
                        "order": link["order"],
                        "enabled": link["enabled"],
                        "enforced": link["enforced"],
                    }
                )

    found.sort(key=lambda item: (item["kind"], item["container"].lower()))
    return found


def _container_kind(entry: Any) -> str:
    classes = {value.lower() for value in values.as_list(entry, "objectClass")}
    if "domaindns" in classes:
        return "domain"
    if "site" in classes:
        return "site"
    if "organizationalunit" in classes:
        return "organizational_unit"
    return "container"


# ---------------------------------------------------------------------------
# What applies where
# ---------------------------------------------------------------------------


def inheritance(conn: DirectoryConnection, dn: str) -> dict[str, Any]:
    """The policies that reach a container, in the order they are applied.

    Walks from the container up to the domain root, then reverses: the domain
    applies first and the OU last, so the closest link wins — except where an
    enforced link from above overrides it, and except where a block on the way
    down stops the ones above.

    Sites are not walked here. A client's site is decided at boot from its IP
    address, so "which site is this OU in" has no answer.
    """
    chain: list[dict[str, Any]] = []
    current: str | None = dn

    while current:
        try:
            node = get_links(conn, current)
        except NotFound:
            break
        chain.append(node)
        if current.lower() == conn.info.base_dn.lower():
            break
        current = values.parent_dn(current)

    # From the domain downwards, which is the order they are applied in.
    chain.reverse()

    applied: list[dict[str, Any]] = []
    blocked_below: list[dict[str, Any]] = []
    blocking = False

    for depth, node in enumerate(chain):
        # A block on this container stops everything inherited from above,
        # but not the links on the container itself.
        if node["block_inheritance"] and depth > 0:
            blocking = True

        for link in node["links"]:
            item = {
                **link,
                "source": node["name"],
                "source_dn": node["dn"],
                "depth": depth,
            }
            if not link["enabled"] or link["missing"]:
                reason = "disabled" if not link["enabled"] else "missing"
                blocked_below.append({**item, "reason": reason})
                continue
            applied.append(item)

    if blocking:
        # Everything from above the blocking container drops out unless it is
        # enforced. Enforced links are exactly the ones a block cannot stop.
        block_depth = next(
            depth for depth, node in enumerate(chain) if node["block_inheritance"] and depth > 0
        )
        kept, dropped = [], []
        for item in applied:
            if item["depth"] < block_depth and not item["enforced"]:
                dropped.append({**item, "reason": "blocked"})
            else:
                kept.append(item)
        applied, blocked_below = kept, blocked_below + dropped

    # Enforced links win over everything closer to the object, so they are
    # applied last.
    applied.sort(key=lambda item: (item["enforced"], item["depth"]))
    for position, item in enumerate(applied, start=1):
        item["precedence"] = len(applied) - position + 1

    return {
        "dn": dn,
        "chain": [
            {"name": node["name"], "dn": node["dn"], "blocked": node["block_inheritance"]}
            for node in chain
        ],
        "applied": applied,
        "excluded": blocked_below,
    }


# ---------------------------------------------------------------------------
# Security filtering
# ---------------------------------------------------------------------------


def get_filtering(conn: DirectoryConnection, dn: str) -> dict[str, Any]:
    """Who the policy applies to.

    A GPO applies to an account only if that account has both *read* and
    *apply group policy* on the object. GPMC hides that behind one list; this
    reports the same list, plus anyone who has only one of the two — a state
    GPMC cannot show and that is invariably a mistake.
    """
    acl = sacl.read_acl(conn, dn)

    # The two rights usually sit in separate ACEs for the same trustee, so
    # they are collected per SID and only then judged together.
    by_sid: dict[str, dict[str, Any]] = {}
    for ace in acl["aces"]:
        if ace["type"] != "allow":
            continue

        object_guid = (ace.get("object") or {}).get("guid", "").lower()
        grants_apply = object_guid == RIGHT_APPLY_GROUP_POLICY
        # A read right limited to one attribute is not the read a policy
        # needs, so an object-typed ACE only counts for "apply".
        grants_read = not ace.get("object") and bool(ace["mask"] & RIGHT_READ)
        if not (grants_apply or grants_read):
            continue

        sid = ace["trustee"]["sid"]
        entry = by_sid.setdefault(
            sid,
            {
                "trustee": ace["trustee"],
                "inherited": ace["inherited"],
                "read": False,
                "apply": False,
            },
        )
        entry["read"] = entry["read"] or grants_read
        entry["apply"] = entry["apply"] or grants_apply
        entry["inherited"] = entry["inherited"] and ace["inherited"]

    entries = sorted(by_sid.values(), key=lambda item: item["trustee"]["name"].lower())
    return {
        "dn": dn,
        "applies_to": [item for item in entries if item["read"] and item["apply"]],
        # Half a filter: visible to the account but not applied, or the other
        # way round. GPMC cannot show this state, and it is always a mistake.
        "incomplete": [item for item in entries if not (item["read"] and item["apply"])],
        "sddl": acl["sddl"],
    }
