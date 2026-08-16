"""Groups: scope, type, membership.

Two details drive most of this module:

* ``groupType`` is a signed 32-bit value. The security bit is 0x80000000,
  which must be written as a negative number — a positive 2147483650 is
  rejected by the DC.
* Primary group membership is stored on the *member*, not on the group.
  "Domain Users" therefore looks empty in a naive member listing, which is why
  :func:`list_members` can fold primary members in.
"""

from __future__ import annotations

from typing import Any

from samadcon.ad import values
from samadcon.ad.connection import SCOPE_SUBTREE, DirectoryConnection
from samadcon.ad.directory import (
    GROUP_TYPE_DOMAIN_LOCAL,
    GROUP_TYPE_GLOBAL,
    GROUP_TYPE_SECURITY,
    GROUP_TYPE_UNIVERSAL,
    group_scope_name,
    is_security_group,
    summarize,
)
from samadcon.core.errors import Conflict, InvalidRequest, NotFound

GROUP_FIELDS: dict[str, str] = {
    "display_name": "displayName",
    "description": "description",
    "mail": "mail",
    "notes": "info",
    "managed_by": "managedBy",
}

DETAIL_ATTRS = [
    "distinguishedName",
    "objectClass",
    "objectGUID",
    "objectSid",
    "name",
    "sAMAccountName",
    "groupType",
    "member",
    "memberOf",
    *GROUP_FIELDS.values(),
    "whenCreated",
    "whenChanged",
]

_SCOPE_BITS = {
    "global": GROUP_TYPE_GLOBAL,
    "domain_local": GROUP_TYPE_DOMAIN_LOCAL,
    "universal": GROUP_TYPE_UNIVERSAL,
}

# Guards the recursive membership walk against pathological nesting.
MAX_NESTING_DEPTH = 20


def group_type_value(scope: str, security: bool) -> int:
    """Signed groupType for a scope/type combination."""
    bits = _SCOPE_BITS.get(scope)
    if bits is None:
        raise InvalidRequest(
            f"Unknown group scope '{scope}'.",
            code="unknown_group_scope",
            context={"allowed": list(_SCOPE_BITS)},
        )
    if not security:
        return bits
    # The security bit set, expressed as a signed 32-bit integer: AD rejects
    # the positive form.
    return bits - 0x100000000 + GROUP_TYPE_SECURITY


def get_group(conn: DirectoryConnection, dn: str) -> dict[str, Any]:
    entry = conn.get(dn, attrs=DETAIL_ATTRS)
    if entry is None:
        raise NotFound("The group does not exist.", context={"dn": dn})

    group_type = values.as_int(entry, "groupType")
    detail = {
        **summarize(entry),
        "dn": values.as_str(entry, "distinguishedName") or str(entry.dn),
        "type": "group",
        "sam_account_name": values.as_str(entry, "sAMAccountName"),
        "attributes": {
            field: values.as_str(entry, attribute) for field, attribute in GROUP_FIELDS.items()
        },
        "scope": group_scope_name(group_type),
        "security_group": is_security_group(group_type),
        "group_type": group_type,
        "member_count": len(values.as_list(entry, "member")),
        "member_of": sorted(values.as_list(entry, "memberOf"), key=str.lower),
    }
    return detail


def create_group(
    conn: DirectoryConnection,
    *,
    parent_dn: str,
    name: str,
    sam_account_name: str | None = None,
    scope: str = "global",
    security: bool = True,
    description: str | None = None,
) -> dict[str, Any]:
    import ldb

    group_name = name.strip()
    if not group_name:
        raise InvalidRequest("The group name is missing.", code="missing_name")

    sam = (sam_account_name or group_name).strip()
    if len(sam) > 64:
        raise InvalidRequest(
            "The group's logon name must not exceed 64 characters.",
            code="sam_account_name_too_long",
        )

    if not conn.exists(parent_dn):
        raise NotFound("The target container does not exist.", context={"dn": parent_dn})

    dn = f"CN={values.escape_rdn_value(group_name)},{parent_dn}"
    if conn.exists(dn):
        raise Conflict(
            "An object with this name already exists in the container.",
            code="already_exists",
            context={"dn": dn},
        )

    existing = conn.search(
        conn.info.base_dn,
        scope=SCOPE_SUBTREE,
        expression=f"(sAMAccountName={values.escape_filter(sam)})",
        attrs=["distinguishedName"],
        max_results=1,
    )
    if len(existing):
        raise Conflict(
            "This group name is already in use.",
            code="sam_account_name_taken",
            context={"sam_account_name": sam},
        )

    message = ldb.Message()
    message.dn = ldb.Dn(conn.samdb, dn)
    message["objectClass"] = ldb.MessageElement(["top", "group"], ldb.FLAG_MOD_ADD, "objectClass")
    message["sAMAccountName"] = ldb.MessageElement(sam, ldb.FLAG_MOD_ADD, "sAMAccountName")
    message["groupType"] = ldb.MessageElement(
        str(group_type_value(scope, security)), ldb.FLAG_MOD_ADD, "groupType"
    )
    if description:
        message["description"] = ldb.MessageElement(
            description, ldb.FLAG_MOD_ADD, "description"
        )

    conn.add(message)
    return get_group(conn, dn)


def update_group(
    conn: DirectoryConnection,
    dn: str,
    *,
    attributes: dict[str, Any] | None = None,
    scope: str | None = None,
    security: bool | None = None,
) -> dict[str, Any]:
    import ldb

    applied: dict[str, Any] = {}

    if attributes:
        changes = {}
        for field, value in attributes.items():
            attribute = GROUP_FIELDS.get(field)
            if attribute is None:
                raise InvalidRequest(f"Unknown field '{field}'.", code="unknown_field")
            changes[attribute] = value
        applied.update(conn.modify_attributes(dn, changes))

    if scope is not None or security is not None:
        entry = conn.get(dn, attrs=["groupType"])
        if entry is None:
            raise NotFound("The group does not exist.", context={"dn": dn})
        current = values.as_int(entry, "groupType", 0) or 0
        new_scope = scope or group_scope_name(current) or "global"
        new_security = is_security_group(current) if security is None else security
        new_value = group_type_value(new_scope, new_security)

        if new_value != current:
            # AD only permits certain transitions (global <-> universal,
            # domain local <-> universal, and only when membership allows it).
            # Rather than reimplementing that matrix, let the DC decide and
            # translate its refusal.
            message = ldb.Message()
            message.dn = ldb.Dn(conn.samdb, dn)
            message["groupType"] = ldb.MessageElement(
                str(new_value), ldb.FLAG_MOD_REPLACE, "groupType"
            )
            conn.modify(message)
            applied["groupType"] = {"old": current, "new": new_value}

    return applied


# ---------------------------------------------------------------------------
# Membership
# ---------------------------------------------------------------------------


def add_members(conn: DirectoryConnection, dn: str, member_dns: list[str]) -> dict[str, Any]:
    """Add members, skipping the ones already present.

    Adding an existing member would fail the whole modify with
    "attribute or value exists", taking the other additions down with it.
    """
    import ldb

    entry = conn.get(dn, attrs=["member"])
    if entry is None:
        raise NotFound("The group does not exist.", context={"dn": dn})

    current = {m.lower() for m in values.as_list(entry, "member")}
    to_add = [m for m in member_dns if m.lower() not in current]
    missing = [m for m in to_add if not conn.exists(m)]
    if missing:
        raise NotFound(
            "Some of the objects to add do not exist.",
            code="member_not_found",
            context={"missing": missing},
        )

    if to_add:
        message = ldb.Message()
        message.dn = ldb.Dn(conn.samdb, dn)
        message["member"] = ldb.MessageElement(to_add, ldb.FLAG_MOD_ADD, "member")
        conn.modify(message)

    return {"added": to_add, "already_members": [m for m in member_dns if m not in to_add]}


def remove_members(conn: DirectoryConnection, dn: str, member_dns: list[str]) -> dict[str, Any]:
    import ldb

    entry = conn.get(dn, attrs=["member"])
    if entry is None:
        raise NotFound("The group does not exist.", context={"dn": dn})

    current = {m.lower(): m for m in values.as_list(entry, "member")}
    to_remove = [current[m.lower()] for m in member_dns if m.lower() in current]
    not_members = [m for m in member_dns if m.lower() not in current]

    if to_remove:
        message = ldb.Message()
        message.dn = ldb.Dn(conn.samdb, dn)
        message["member"] = ldb.MessageElement(to_remove, ldb.FLAG_MOD_DELETE, "member")
        conn.modify(message)

    return {"removed": to_remove, "not_members": not_members}


def list_members(
    conn: DirectoryConnection,
    dn: str,
    *,
    recursive: bool = False,
    include_primary: bool = True,
) -> dict[str, Any]:
    """Members of a group.

    *include_primary* folds in accounts whose primaryGroupID points here —
    without it, "Domain Users" and "Domain Computers" appear empty.
    """
    entry = conn.get(dn, attrs=["member", "objectSid", "objectClass", "name"])
    if entry is None:
        raise NotFound("The group does not exist.", context={"dn": dn})

    direct = values.as_list(entry, "member")
    member_dns: list[str] = list(direct)
    primary_members: list[str] = []

    if include_primary:
        rid = values.rid_of(values.sid_to_str(values.as_bytes(entry, "objectSid")))
        if rid is not None:
            result = conn.search(
                conn.info.base_dn,
                scope=SCOPE_SUBTREE,
                expression=f"(primaryGroupID={rid})",
                attrs=["distinguishedName"],
            )
            primary_members = [
                values.as_str(item, "distinguishedName") or str(item.dn) for item in result
            ]
            known = {m.lower() for m in member_dns}
            member_dns.extend(m for m in primary_members if m.lower() not in known)

    if recursive:
        member_dns = _expand_nested(conn, member_dns)

    entries = _resolve_members(conn, member_dns)
    primary_set = {m.lower() for m in primary_members}
    for item in entries:
        item["primary_group_member"] = item["dn"].lower() in primary_set

    entries.sort(key=lambda item: (item["type"], (item["name"] or "").lower()))
    return {"dn": dn, "members": entries, "recursive": recursive}


def _expand_nested(conn: DirectoryConnection, member_dns: list[str]) -> list[str]:
    """Walk nested groups depth-first.

    Done in the client rather than with LDAP_MATCHING_RULE_IN_CHAIN
    (1.2.840.113556.1.4.1941): Samba's support for that rule has been uneven
    across releases, and a wrong membership list is worse than a slower one.
    Cycles are possible in AD, hence the seen-set.
    """
    seen: set[str] = set()
    collected: list[str] = []
    stack = [(dn, 0) for dn in reversed(member_dns)]

    while stack:
        dn, depth = stack.pop()
        key = dn.lower()
        if key in seen:
            continue
        seen.add(key)
        collected.append(dn)

        if depth >= MAX_NESTING_DEPTH:
            continue

        entry = conn.get(dn, attrs=["member", "objectClass"])
        if entry is None:
            continue
        classes = {c.lower() for c in values.as_list(entry, "objectClass")}
        if "group" not in classes:
            continue
        for nested in reversed(values.as_list(entry, "member")):
            if nested.lower() not in seen:
                stack.append((nested, depth + 1))

    return collected


def _resolve_members(conn: DirectoryConnection, member_dns: list[str]) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for member_dn in member_dns:
        entry = conn.get(
            member_dn,
            attrs=["distinguishedName", "objectClass", "name", "displayName", "objectGUID",
                   "sAMAccountName", "userAccountControl", "groupType", "description", "objectSid"],
        )
        if entry is None:
            # A stale member reference — worth showing rather than hiding.
            resolved.append(
                {
                    "dn": member_dn,
                    "name": values.name_from_dn(member_dn),
                    "type": "unresolved",
                    "is_container": False,
                    "display_name": None,
                    "description": None,
                }
            )
            continue
        resolved.append(summarize(entry))
    return resolved


def list_member_of(
    conn: DirectoryConnection, dn: str, *, recursive: bool = False
) -> list[dict[str, Any]]:
    """Groups an object belongs to, including its primary group."""
    entry = conn.get(dn, attrs=["memberOf", "primaryGroupID", "objectSid"])
    if entry is None:
        raise NotFound("The object does not exist.", context={"dn": dn})

    group_dns = list(values.as_list(entry, "memberOf"))

    primary_dn: str | None = None
    primary_rid = values.as_int(entry, "primaryGroupID")
    object_sid = values.sid_to_str(values.as_bytes(entry, "objectSid"))
    if primary_rid is not None and object_sid:
        domain_sid = object_sid.rsplit("-", 1)[0]
        result = conn.search(
            conn.info.base_dn,
            scope=SCOPE_SUBTREE,
            expression=f"(objectSid={values.escape_filter(f'{domain_sid}-{primary_rid}')})",
            attrs=["distinguishedName"],
            max_results=1,
        )
        if len(result):
            primary_dn = values.as_str(result.entries[0], "distinguishedName")
            if primary_dn and primary_dn.lower() not in {g.lower() for g in group_dns}:
                group_dns.append(primary_dn)

    if recursive:
        group_dns = _expand_parents(conn, group_dns)

    groups = _resolve_members(conn, group_dns)
    primary_key = primary_dn.lower() if primary_dn else None
    for group in groups:
        group["primary_group"] = group["dn"].lower() == primary_key
    groups.sort(key=lambda item: (item["name"] or "").lower())
    return groups


def _expand_parents(conn: DirectoryConnection, group_dns: list[str]) -> list[str]:
    seen: set[str] = set()
    collected: list[str] = []
    stack = list(reversed(group_dns))
    depth = 0

    while stack and depth < MAX_NESTING_DEPTH * len(group_dns) + MAX_NESTING_DEPTH:
        depth += 1
        dn = stack.pop()
        key = dn.lower()
        if key in seen:
            continue
        seen.add(key)
        collected.append(dn)

        entry = conn.get(dn, attrs=["memberOf"])
        if entry is None:
            continue
        for parent in reversed(values.as_list(entry, "memberOf")):
            if parent.lower() not in seen:
                stack.append(parent)

    return collected
