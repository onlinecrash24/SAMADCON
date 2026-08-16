"""Names for the numbers in an access control entry.

An ACE is a bitmask, a SID and two GUIDs. On its own that is unreadable, and an
ACL editor that shows raw values is worse than none — it invites people to
guess. This module turns each part into something an administrator recognises:

* the access mask into named rights,
* the trustee SID into an account name,
* the object-type GUID into an extended right ("Reset Password") or a schema
  class or attribute.

The GUID catalogues are read from the directory itself rather than hard-coded.
Extended rights live under ``CN=Extended-Rights,CN=Configuration`` and schema
GUIDs in the schema partition, so a domain with its own schema extensions gets
correct names too. Both are cached — they change about as often as the schema.
"""

from __future__ import annotations

import logging
from typing import Any

from samadcon.ad import values
from samadcon.ad.connection import SCOPE_ONELEVEL, SCOPE_SUBTREE, DirectoryConnection
from samadcon.core.cache import schema_cache

logger = logging.getLogger(__name__)

# --- access mask bits (MS-ADTS 5.1.3.2, mirrored from samba.dcerpc.security) --

SEC_ADS_CREATE_CHILD = 0x00000001
SEC_ADS_DELETE_CHILD = 0x00000002
SEC_ADS_LIST = 0x00000004
SEC_ADS_SELF_WRITE = 0x00000008
SEC_ADS_READ_PROP = 0x00000010
SEC_ADS_WRITE_PROP = 0x00000020
SEC_ADS_DELETE_TREE = 0x00000040
SEC_ADS_LIST_OBJECT = 0x00000080
SEC_ADS_CONTROL_ACCESS = 0x00000100

SEC_STD_DELETE = 0x00010000
SEC_STD_READ_CONTROL = 0x00020000
SEC_STD_WRITE_DAC = 0x00040000
SEC_STD_WRITE_OWNER = 0x00080000

SEC_GENERIC_ALL = 0x10000000
SEC_GENERIC_EXECUTE = 0x20000000
SEC_GENERIC_WRITE = 0x40000000
SEC_GENERIC_READ = 0x80000000

# What "Full control" expands to on a directory object.
SEC_ADS_FULL_CONTROL = (
    SEC_ADS_CREATE_CHILD
    | SEC_ADS_DELETE_CHILD
    | SEC_ADS_LIST
    | SEC_ADS_SELF_WRITE
    | SEC_ADS_READ_PROP
    | SEC_ADS_WRITE_PROP
    | SEC_ADS_DELETE_TREE
    | SEC_ADS_LIST_OBJECT
    | SEC_ADS_CONTROL_ACCESS
    | SEC_STD_DELETE
    | SEC_STD_READ_CONTROL
    | SEC_STD_WRITE_DAC
    | SEC_STD_WRITE_OWNER
)

# Order matters: the UI lists them like this.
RIGHT_NAMES: tuple[tuple[int, str], ...] = (
    (SEC_ADS_CREATE_CHILD, "create_child"),
    (SEC_ADS_DELETE_CHILD, "delete_child"),
    (SEC_ADS_LIST, "list_contents"),
    (SEC_ADS_SELF_WRITE, "self_write"),
    (SEC_ADS_READ_PROP, "read_property"),
    (SEC_ADS_WRITE_PROP, "write_property"),
    (SEC_ADS_DELETE_TREE, "delete_tree"),
    (SEC_ADS_LIST_OBJECT, "list_object"),
    (SEC_ADS_CONTROL_ACCESS, "control_access"),
    (SEC_STD_DELETE, "delete"),
    (SEC_STD_READ_CONTROL, "read_permissions"),
    (SEC_STD_WRITE_DAC, "write_permissions"),
    (SEC_STD_WRITE_OWNER, "take_ownership"),
    (SEC_GENERIC_ALL, "generic_all"),
    (SEC_GENERIC_EXECUTE, "generic_execute"),
    (SEC_GENERIC_WRITE, "generic_write"),
    (SEC_GENERIC_READ, "generic_read"),
)

# --- ACE types and flags ---------------------------------------------------

ACE_TYPE_ALLOWED = 0
ACE_TYPE_DENIED = 1
ACE_TYPE_ALLOWED_OBJECT = 5
ACE_TYPE_DENIED_OBJECT = 6

OBJECT_ACE_TYPES = frozenset({ACE_TYPE_ALLOWED_OBJECT, ACE_TYPE_DENIED_OBJECT})
DENY_ACE_TYPES = frozenset({ACE_TYPE_DENIED, ACE_TYPE_DENIED_OBJECT})

ACE_FLAG_OBJECT_INHERIT = 0x01
ACE_FLAG_CONTAINER_INHERIT = 0x02
ACE_FLAG_NO_PROPAGATE_INHERIT = 0x04
ACE_FLAG_INHERIT_ONLY = 0x08
ACE_FLAG_INHERITED = 0x10

# Which GUID field of an object ACE is present.
ACE_OBJECT_TYPE_PRESENT = 0x00000001
ACE_INHERITED_TYPE_PRESENT = 0x00000002

# --- well-known SIDs -------------------------------------------------------
#
# Resolving these through LDAP fails or is slow, and they appear in nearly
# every ACL.
WELL_KNOWN_SIDS: dict[str, str] = {
    "S-1-0-0": "Null SID",
    "S-1-1-0": "Everyone",
    "S-1-2-0": "Local",
    "S-1-3-0": "Creator Owner",
    "S-1-3-1": "Creator Group",
    "S-1-5-2": "Network",
    "S-1-5-4": "Interactive",
    "S-1-5-6": "Service",
    "S-1-5-7": "Anonymous",
    "S-1-5-9": "Enterprise Domain Controllers",
    "S-1-5-10": "Self",
    "S-1-5-11": "Authenticated Users",
    "S-1-5-12": "Restricted Code",
    "S-1-5-17": "IIS_USRS",
    "S-1-5-18": "System",
    "S-1-5-19": "Local Service",
    "S-1-5-20": "Network Service",
    "S-1-5-32-544": "Administrators",
    "S-1-5-32-545": "Users",
    "S-1-5-32-546": "Guests",
    "S-1-5-32-547": "Power Users",
    "S-1-5-32-548": "Account Operators",
    "S-1-5-32-549": "Server Operators",
    "S-1-5-32-550": "Print Operators",
    "S-1-5-32-551": "Backup Operators",
    "S-1-5-32-552": "Replicator",
    "S-1-5-32-554": "Pre-Windows 2000 Compatible Access",
    "S-1-5-32-555": "Remote Desktop Users",
    "S-1-5-32-556": "Network Configuration Operators",
    "S-1-5-32-557": "Incoming Forest Trust Builders",
    "S-1-5-32-558": "Performance Monitor Users",
    "S-1-5-32-559": "Performance Log Users",
    "S-1-5-32-560": "Windows Authorization Access Group",
    "S-1-5-32-561": "Terminal Server License Servers",
    "S-1-5-32-562": "Distributed COM Users",
    "S-1-5-32-568": "IIS_IUSRS",
    "S-1-5-32-569": "Cryptographic Operators",
    "S-1-5-32-573": "Event Log Readers",
    "S-1-5-32-574": "Certificate Service DCOM Access",
}


def decode_mask(mask: int) -> list[str]:
    """Named rights contained in *mask*."""
    return [name for bit, name in RIGHT_NAMES if mask & bit]


def is_full_control(mask: int) -> bool:
    return (mask & SEC_ADS_FULL_CONTROL) == SEC_ADS_FULL_CONTROL or bool(mask & SEC_GENERIC_ALL)


# ---------------------------------------------------------------------------
# GUID catalogues
# ---------------------------------------------------------------------------


def extended_rights(conn: DirectoryConnection) -> dict[str, str]:
    """GUID -> display name for every extended right in the forest.

    Read from CN=Extended-Rights rather than hard-coded, so rights added by
    schema extensions get proper names as well.
    """
    cache_key = f"extended-rights:{conn.info.config_dn}"
    cached = schema_cache.get(cache_key)
    if cached is not None:
        return cached

    catalogue: dict[str, str] = {}
    try:
        result = conn.search(
            f"CN=Extended-Rights,{conn.info.config_dn}",
            scope=SCOPE_ONELEVEL,
            expression="(objectClass=controlAccessRight)",
            attrs=["rightsGuid", "displayName", "cn"],
            max_results=10000,
        )
        for entry in result:
            guid = values.as_str(entry, "rightsGuid")
            if not guid:
                continue
            name = values.as_str(entry, "displayName") or values.as_str(entry, "cn") or guid
            catalogue[guid.lower()] = name
    except Exception:
        logger.warning("could not read the extended rights catalogue", exc_info=True)

    schema_cache.set(cache_key, catalogue)
    return catalogue


def schema_guids(conn: DirectoryConnection) -> dict[str, str]:
    """GUID -> name for schema classes and attributes.

    Object ACEs point at a class ("applies to computer objects") or a single
    attribute ("may write telephoneNumber"), and both are identified by their
    schemaIDGUID.
    """
    cache_key = f"schema-guids:{conn.info.schema_dn}"
    cached = schema_cache.get(cache_key)
    if cached is not None:
        return cached

    catalogue: dict[str, str] = {}
    try:
        result = conn.search(
            conn.info.schema_dn,
            scope=SCOPE_ONELEVEL,
            expression="(|(objectClass=classSchema)(objectClass=attributeSchema))",
            attrs=["schemaIDGUID", "lDAPDisplayName"],
            max_results=20000,
        )
        for entry in result:
            raw = values.as_bytes(entry, "schemaIDGUID")
            name = values.as_str(entry, "lDAPDisplayName")
            guid = values.guid_to_str(raw)
            if guid and name:
                catalogue[guid.lower()] = name
    except Exception:
        logger.warning("could not read the schema GUID catalogue", exc_info=True)

    schema_cache.set(cache_key, catalogue)
    return catalogue


def describe_object_guid(conn: DirectoryConnection, guid: str | None) -> dict[str, str] | None:
    """Resolve an ACE's object GUID to a right, class or attribute."""
    if not guid:
        return None

    key = guid.lower().strip("{}")
    right = extended_rights(conn).get(key)
    if right is not None:
        return {"guid": key, "kind": "extended_right", "name": right}

    schema = schema_guids(conn).get(key)
    if schema is not None:
        return {"guid": key, "kind": "schema", "name": schema}

    return {"guid": key, "kind": "unknown", "name": key}


# ---------------------------------------------------------------------------
# Trustees
# ---------------------------------------------------------------------------


def resolve_sid(conn: DirectoryConnection, sid: str) -> dict[str, Any]:
    """Turn a SID into something with a name.

    Well-known SIDs are answered from the table; everything else is looked up
    once and cached for the lifetime of the schema cache, because an ACL of
    thirty entries would otherwise mean thirty searches.
    """
    text = str(sid)
    well_known = WELL_KNOWN_SIDS.get(text)
    if well_known is not None:
        return {"sid": text, "name": well_known, "kind": "well_known"}

    cache_key = f"sid:{conn.info.base_dn}:{text}"
    cached = schema_cache.get(cache_key)
    if cached is not None:
        return cached

    resolved: dict[str, Any] = {"sid": text, "name": text, "kind": "unresolved"}
    try:
        result = conn.search(
            conn.info.base_dn,
            scope=SCOPE_SUBTREE,
            expression=f"(objectSid={values.escape_filter(text)})",
            attrs=["sAMAccountName", "distinguishedName", "objectClass", "displayName"],
            max_results=1,
        )
        if len(result):
            entry = result.entries[0]
            from samadcon.ad.directory import object_type

            resolved = {
                "sid": text,
                "name": values.as_str(entry, "sAMAccountName")
                or values.as_str(entry, "displayName")
                or text,
                "dn": values.as_str(entry, "distinguishedName"),
                "kind": object_type(entry),
            }
    except Exception:
        logger.debug("could not resolve %s", text, exc_info=True)

    schema_cache.set(cache_key, resolved, ttl=300)
    return resolved
