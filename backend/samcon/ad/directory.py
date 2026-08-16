"""Navigation and generic object access.

The container tree, object lists and the raw attribute editor. Type-specific
behaviour (users, groups, computers, OUs) lives in the sibling modules; this
one deals with whatever an object happens to be.
"""

from __future__ import annotations

from typing import Any

from samcon.ad import uac, values
from samcon.ad.connection import (
    SCOPE_BASE,
    SCOPE_ONELEVEL,
    SCOPE_SUBTREE,
    DirectoryConnection,
)
from samcon.core.errors import InvalidRequest, NotFound

# Attributes every list view needs. Kept small — a container with 2000 objects
# should not drag half the schema across the network.
SUMMARY_ATTRS = [
    "distinguishedName",
    "objectClass",
    "objectGUID",
    "objectSid",
    "name",
    "displayName",
    "description",
    "sAMAccountName",
    "userPrincipalName",
    "userAccountControl",
    "groupType",
    "mail",
    "whenCreated",
    "whenChanged",
    "showInAdvancedViewOnly",
]

# objectClass -> object type, most specific first.
_TYPE_BY_CLASS: list[tuple[str, str]] = [
    ("computer", "computer"),
    ("msDS-GroupManagedServiceAccount", "managed_service_account"),
    ("msDS-ManagedServiceAccount", "managed_service_account"),
    ("user", "user"),
    ("group", "group"),
    ("organizationalUnit", "organizational_unit"),
    ("builtinDomain", "builtin"),
    ("domainDNS", "domain"),
    ("contact", "contact"),
    ("groupPolicyContainer", "gpo"),
    ("printQueue", "printer"),
    ("volume", "shared_folder"),
    ("msDS-PasswordSettings", "password_settings"),
    ("site", "site"),
    ("subnet", "subnet"),
    ("nTDSDSA", "ntds_settings"),
    ("server", "server"),
    ("dnsZone", "dns_zone"),
    ("dnsNode", "dns_node"),
    ("lostAndFound", "container"),
    ("container", "container"),
]

# Object types that can hold children and therefore appear in the tree.
CONTAINER_TYPES = frozenset(
    {"domain", "organizational_unit", "container", "builtin", "site", "server"}
)

# Filter fragments per type, for the list view's type filter.
_FILTER_BY_TYPE: dict[str, str] = {
    "user": "(&(objectCategory=person)(objectClass=user))",
    "computer": "(objectCategory=computer)",
    "group": "(objectCategory=group)",
    "contact": "(objectCategory=contact)",
    "organizational_unit": "(objectCategory=organizationalUnit)",
    "container": "(objectCategory=container)",
    "gpo": "(objectClass=groupPolicyContainer)",
    "printer": "(objectCategory=printQueue)",
    "shared_folder": "(objectCategory=volume)",
    "managed_service_account": "(objectClass=msDS-GroupManagedServiceAccount)",
}


def object_type(entry: Any) -> str:
    classes = {c.lower() for c in values.as_list(entry, "objectClass")}
    for class_name, type_name in _TYPE_BY_CLASS:
        if class_name.lower() in classes:
            return type_name
    return "object"


def summarize(entry: Any) -> dict[str, Any]:
    """Compact representation for lists and trees."""
    dn = values.as_str(entry, "distinguishedName") or str(entry.dn)
    otype = object_type(entry)
    uac_value = values.as_int(entry, "userAccountControl")

    summary: dict[str, Any] = {
        "dn": dn,
        "name": values.as_str(entry, "name") or values.name_from_dn(dn),
        "type": otype,
        "display_name": values.as_str(entry, "displayName"),
        "description": values.as_str(entry, "description"),
        "guid": values.guid_to_str(values.as_bytes(entry, "objectGUID")),
        "when_created": values.as_generalized_time(entry, "whenCreated"),
        "when_changed": values.as_generalized_time(entry, "whenChanged"),
        "is_container": otype in CONTAINER_TYPES,
        "advanced_only": values.as_bool(entry, "showInAdvancedViewOnly", False),
    }

    sid = values.sid_to_str(values.as_bytes(entry, "objectSid"))
    if sid:
        summary["sid"] = sid

    account_name = values.as_str(entry, "sAMAccountName")
    if account_name:
        summary["sam_account_name"] = account_name

    if otype in ("user", "computer", "managed_service_account"):
        summary["upn"] = values.as_str(entry, "userPrincipalName")
        summary["mail"] = values.as_str(entry, "mail")
        summary["disabled"] = uac.is_disabled(uac_value)

    if otype == "group":
        group_type = values.as_int(entry, "groupType")
        summary["group_scope"] = group_scope_name(group_type)
        summary["security_group"] = is_security_group(group_type)

    return summary


# ---------------------------------------------------------------------------
# Group type helpers (needed here because lists show them)
# ---------------------------------------------------------------------------

GROUP_TYPE_SYSTEM = 0x00000001
GROUP_TYPE_GLOBAL = 0x00000002
GROUP_TYPE_DOMAIN_LOCAL = 0x00000004
GROUP_TYPE_UNIVERSAL = 0x00000008
GROUP_TYPE_SECURITY = 0x80000000


def group_scope_name(group_type: int | None) -> str | None:
    if group_type is None:
        return None
    if group_type & GROUP_TYPE_UNIVERSAL:
        return "universal"
    if group_type & GROUP_TYPE_DOMAIN_LOCAL:
        return "domain_local"
    if group_type & GROUP_TYPE_GLOBAL:
        return "global"
    return None


def is_security_group(group_type: int | None) -> bool:
    # AD stores groupType as a signed 32-bit integer, so a security group
    # arrives as a negative number. Python's arbitrary-precision & handles the
    # two's-complement form correctly, so this works for both encodings.
    if group_type is None:
        return False
    return bool(group_type & GROUP_TYPE_SECURITY)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def list_children(
    conn: DirectoryConnection,
    dn: str,
    *,
    types: list[str] | None = None,
    query: str | None = None,
    include_advanced: bool = False,
    max_results: int = 2000,
) -> dict[str, Any]:
    """One level below *dn*, the way ADUC's right-hand pane shows it."""
    expression = build_filter(types=types, query=query, include_advanced=include_advanced)
    result = conn.search(
        dn,
        scope=SCOPE_ONELEVEL,
        expression=expression,
        attrs=SUMMARY_ATTRS,
        max_results=max_results,
    )
    entries = [summarize(entry) for entry in result]
    # Containers first, then alphabetically — same ordering as the MMC.
    entries.sort(key=lambda item: (not item["is_container"], (item["name"] or "").lower()))
    return {"parent": dn, "entries": entries, "truncated": result.truncated}


# Object classes that make a node a branch of the navigation tree.
CONTAINER_FILTER = (
    "(|(objectClass=organizationalUnit)(objectClass=container)"
    "(objectClass=builtinDomain)(objectClass=domainDNS)(objectClass=lostAndFound))"
)

# Above this many siblings, the per-node "can this be expanded?" probe is
# skipped: one cheap search each is fine for a dozen nodes and wasteful for a
# hundred. The tree then falls back to showing an expander until proven empty.
MAX_EXPANDER_PROBES = 60


def _tree_filter(include_advanced: bool) -> str:
    if include_advanced:
        return CONTAINER_FILTER
    return f"(&{CONTAINER_FILTER}(!(showInAdvancedViewOnly=TRUE)))"


def has_container_children(
    conn: DirectoryConnection, dn: str, *, include_advanced: bool = False
) -> bool:
    """Whether *dn* holds anything the tree would show below it."""
    result = conn.search(
        dn,
        scope=SCOPE_ONELEVEL,
        expression=_tree_filter(include_advanced),
        attrs=["1.1"],
        max_results=1,
    )
    return len(result) > 0


def list_tree_children(
    conn: DirectoryConnection, dn: str, *, include_advanced: bool = False
) -> list[dict[str, Any]]:
    """Container objects below *dn*, for the navigation tree.

    Each node reports whether it can be expanded, so the tree only draws an
    expander where there is something to expand. ``None`` means "not
    determined" — the caller should assume it might have children.
    """
    result = conn.search(
        dn,
        scope=SCOPE_ONELEVEL,
        expression=_tree_filter(include_advanced),
        attrs=["distinguishedName", "objectClass", "name", "description", "objectGUID",
               "showInAdvancedViewOnly"],
    )
    nodes = [summarize(entry) for entry in result]
    nodes.sort(key=lambda item: (item["name"] or "").lower())

    if len(nodes) <= MAX_EXPANDER_PROBES:
        for node in nodes:
            node["has_children"] = has_container_children(
                conn, node["dn"], include_advanced=include_advanced
            )
    else:
        for node in nodes:
            node["has_children"] = None

    return nodes


def search_objects(
    conn: DirectoryConnection,
    *,
    base: str | None = None,
    query: str | None = None,
    types: list[str] | None = None,
    scope: int = SCOPE_SUBTREE,
    include_advanced: bool = True,
    max_results: int = 2000,
) -> dict[str, Any]:
    """Directory-wide search.

    Free text goes through ANR, the same ambiguous-name resolution ADUC uses:
    one term matches name, display name, sAMAccountName, UPN, first/last name
    and more, without the caller having to know which.
    """
    expression = build_filter(types=types, query=query, include_advanced=include_advanced)
    result = conn.search(
        base or conn.info.base_dn,
        scope=scope,
        expression=expression,
        attrs=SUMMARY_ATTRS,
        max_results=max_results,
    )
    entries = [summarize(entry) for entry in result]
    entries.sort(key=lambda item: (item["name"] or "").lower())
    return {"entries": entries, "truncated": result.truncated, "base": base or conn.info.base_dn}


def build_filter(
    *,
    types: list[str] | None = None,
    query: str | None = None,
    include_advanced: bool = True,
    extra: str | None = None,
) -> str:
    parts: list[str] = []

    if types:
        unknown = [t for t in types if t not in _FILTER_BY_TYPE]
        if unknown:
            raise InvalidRequest(
                f"Unknown object type: {', '.join(unknown)}",
                code="unknown_object_type",
                context={"types": unknown},
            )
        type_filters = "".join(_FILTER_BY_TYPE[t] for t in types)
        parts.append(type_filters if len(types) == 1 else f"(|{type_filters})")

    if query:
        text = query.strip()
        if text:
            escaped = values.escape_filter(text)
            # Trailing wildcard mirrors what users expect from a search box;
            # ANR itself already does prefix matching on most attributes.
            parts.append(f"(anr={escaped})")

    if not include_advanced:
        parts.append("(!(showInAdvancedViewOnly=TRUE))")

    if extra:
        parts.append(extra)

    if not parts:
        return "(objectClass=*)"
    if len(parts) == 1:
        return parts[0]
    return f"(&{''.join(parts)})"


def get_object(
    conn: DirectoryConnection, dn: str, attrs: list[str] | None = None
) -> dict[str, Any]:
    entry = conn.get(dn, attrs=attrs or SUMMARY_ATTRS)
    if entry is None:
        raise NotFound("The directory object does not exist.", context={"dn": dn})
    return summarize(entry)


def get_attributes(conn: DirectoryConnection, dn: str) -> dict[str, Any]:
    """All attributes of an object, for the raw attribute editor.

    Binary values are reported as base64 with their length so the editor can
    show something meaningful instead of mojibake. Each attribute also carries
    whether it may be written, so the editor does not have to keep its own copy
    of the protected list — and cannot drift from the one that is enforced.
    """
    import base64

    from samcon.ad.users import PROTECTED_ATTRS

    entry = conn.get(dn, attrs=["*", "nTSecurityDescriptor", "msDS-KeyCredentialLink"])
    if entry is None:
        raise NotFound("The directory object does not exist.", context={"dn": dn})

    attributes: dict[str, Any] = {}
    # .keys() is required here: an ldb.Message iterates over its elements, not
    # over attribute names, so `for name in entry` would yield the wrong thing.
    for name in entry.keys():  # noqa: SIM118
        # "dn" is part of every message but is not an attribute: its value is
        # an ldb.Dn, not a list of values, and iterating it raises. The DN is
        # returned separately below.
        if name.lower() == "dn":
            continue

        raw_values = []
        has_binary = False
        for raw in entry[name]:
            data = bytes(raw) if not isinstance(raw, bytes) else raw
            try:
                text = data.decode("utf-8")
                if text.isprintable() or "\n" in text:
                    raw_values.append({"text": text})
                    continue
            except UnicodeDecodeError:
                pass
            has_binary = True
            raw_values.append(
                {"binary": base64.b64encode(data).decode("ascii"), "size": len(data)}
            )

        attributes[name] = {
            "values": raw_values,
            # Binary values are excluded as well: a base64 blob typed back in
            # by hand is a corrupted object waiting to happen.
            "editable": name.lower() not in PROTECTED_ATTRS and not has_binary,
        }

    return {
        "dn": values.as_str(entry, "distinguishedName") or str(entry.dn),
        "attributes": attributes,
    }


def get_ancestors(conn: DirectoryConnection, dn: str) -> list[dict[str, Any]]:
    """Path from the domain root down to *dn*, for breadcrumbs."""
    base_dn = conn.info.base_dn
    if not dn.lower().endswith(base_dn.lower()):
        raise InvalidRequest(
            "The object is outside this domain's naming context.",
            code="outside_naming_context",
            context={"dn": dn, "base_dn": base_dn},
        )

    chain: list[str] = []
    current: str | None = dn
    while current and len(current) >= len(base_dn):
        chain.append(current)
        if current.lower() == base_dn.lower():
            break
        current = values.parent_dn(current)

    chain.reverse()
    nodes: list[dict[str, Any]] = []
    for node_dn in chain:
        entry = conn.get(node_dn, attrs=["distinguishedName", "objectClass", "name", "objectGUID"])
        if entry is not None:
            nodes.append(summarize(entry))
    return nodes


def move_object(conn: DirectoryConnection, dn: str, new_parent_dn: str) -> str:
    """Move an object into another container. Returns the new DN."""
    if not conn.exists(new_parent_dn):
        raise NotFound("The target container does not exist.", context={"dn": new_parent_dn})

    rdn = values.rdn_of(dn)
    new_dn = f"{rdn},{new_parent_dn}"
    if new_dn.lower() == dn.lower():
        return dn
    conn.rename(dn, new_dn)
    return new_dn


def rename_object(conn: DirectoryConnection, dn: str, new_name: str) -> str:
    """Change an object's RDN value. Returns the new DN."""
    new_name = new_name.strip()
    if not new_name:
        raise InvalidRequest("The new name is empty.", code="empty_name")

    rdn = values.rdn_of(dn)
    attribute, _, _ = rdn.partition("=")
    parent = values.parent_dn(dn)
    if parent is None:
        raise InvalidRequest("A naming context cannot be renamed.", code="cannot_rename_root")

    new_dn = f"{attribute}={values.escape_rdn_value(new_name)},{parent}"
    if new_dn.lower() == dn.lower():
        return dn
    conn.rename(dn, new_dn)

    # For most object classes the `name` attribute follows the RDN
    # automatically; `displayName` does not and stays as it was on purpose.
    return new_dn


def delete_object(conn: DirectoryConnection, dn: str, *, recursive: bool = False) -> None:
    entry = conn.get(dn, attrs=["objectClass", "isCriticalSystemObject", "systemFlags"])
    if entry is None:
        raise NotFound("The directory object does not exist.", context={"dn": dn})

    if values.as_bool(entry, "isCriticalSystemObject", False):
        raise InvalidRequest(
            "This object is required by the domain and cannot be deleted.",
            code="critical_system_object",
            context={"dn": dn},
        )

    # systemFlags bit 0x80000000 marks objects the DC refuses to delete;
    # catching it here gives a clearer message than the LDAP error would.
    system_flags = values.as_int(entry, "systemFlags", 0) or 0
    if system_flags & 0x80000000:
        raise InvalidRequest(
            "This object is protected against deletion.",
            code="delete_protected",
            context={"dn": dn},
        )

    conn.delete(dn, recursive=recursive)


def object_children_count(conn: DirectoryConnection, dn: str) -> int:
    result = conn.search(dn, scope=SCOPE_ONELEVEL, expression="(objectClass=*)", attrs=["1.1"])
    return len(result)


def resolve_name(conn: DirectoryConnection, identifier: str) -> str:
    """Resolve a DN, GUID, SID or sAMAccountName to a DN."""
    text = identifier.strip()
    if not text:
        raise InvalidRequest("No object was given.", code="missing_identifier")

    if "=" in text and "," in text:
        return text

    if text.startswith("S-1-"):
        expression = f"(objectSid={values.escape_filter(text)})"
    elif text.startswith("{") and text.endswith("}"):
        expression = f"(objectGUID={values.escape_filter(text.strip('{}'))})"
    else:
        expression = f"(sAMAccountName={values.escape_filter(text)})"

    result = conn.search(
        conn.info.base_dn, scope=SCOPE_SUBTREE, expression=expression,
        attrs=["distinguishedName"], max_results=2,
    )
    if not len(result):
        raise NotFound("No object matches this name.", context={"identifier": identifier})
    if len(result) > 1:
        raise InvalidRequest(
            "The name is ambiguous.",
            code="ambiguous_identifier",
            context={"identifier": identifier},
        )
    return values.as_str(result.entries[0], "distinguishedName") or str(result.entries[0].dn)


def naming_contexts(conn: DirectoryConnection) -> list[dict[str, Any]]:
    """Roots the tree can start from."""
    info = conn.info
    roots = [
        {"dn": info.base_dn, "label": info.dns_domain, "kind": "domain"},
        {"dn": info.config_dn, "label": "Configuration", "kind": "configuration"},
        {"dn": info.schema_dn, "label": "Schema", "kind": "schema"},
    ]
    for root in roots:
        entry = conn.get(root["dn"], attrs=["objectClass", "name", "objectGUID"])
        root["exists"] = entry is not None
        if entry is not None:
            root["guid"] = values.guid_to_str(values.as_bytes(entry, "objectGUID"))
    return roots


def base_scope(name: str) -> int:
    mapping = {"base": SCOPE_BASE, "one": SCOPE_ONELEVEL, "subtree": SCOPE_SUBTREE}
    if name not in mapping:
        raise InvalidRequest(
            f"Unknown search scope '{name}'.",
            code="unknown_scope",
            context={"allowed": list(mapping)},
        )
    return mapping[name]
