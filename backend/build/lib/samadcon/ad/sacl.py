"""Security descriptors: reading and editing an object's permissions.

SDDL is manipulated as text rather than through the binary structure: it is the
form Samba, Windows and every piece of documentation agree on, and it round
trips losslessly through ``security.descriptor``. Building an ACE by hand as
SDDL is also far less error-prone than assembling the NDR structure, and the
numeric access mask (``0x00000010`` instead of ``RP``) leaves no room for
mis-transcribed right abbreviations.

Concurrent edits are caught rather than merged: a caller passes back the DACL
it saw, and a write is refused if the object has changed since. ACLs are
exactly where a silent last-writer-wins would be most damaging.
"""

from __future__ import annotations

import re
from typing import Any

from samadcon.ad import rights, values
from samadcon.ad.connection import DirectoryConnection
from samadcon.core.errors import Conflict, InvalidRequest, NotFound, SamadconError

# Deny Delete + Delete Tree for Everyone — exactly what ADUC writes for
# "Protect object from accidental deletion".
DELETE_PROTECTION_ACE = "(D;;SDDT;;;WD)"

# Matches that ACE regardless of right ordering or extra whitespace.
_PROTECTION_RE = re.compile(r"\(D;[^;]*;([A-Z]*);;;WD\)")


def read_descriptor(conn: DirectoryConnection, dn: str) -> Any:
    """Return the object's nTSecurityDescriptor as a samba structure."""
    from samba.dcerpc import security
    from samba.ndr import ndr_unpack

    entry = conn.get(dn, attrs=["nTSecurityDescriptor"])
    if entry is None:
        raise NotFound("The directory object does not exist.", context={"dn": dn})

    raw = values.as_bytes(entry, "nTSecurityDescriptor")
    if raw is None:
        raise SamadconError(
            "The object has no security descriptor, or it is not readable for you.",
            code="no_security_descriptor",
            status_code=403,
            hint="Reading an ACL requires READ_CONTROL on the object.",
        )
    return ndr_unpack(security.descriptor, raw)


def read_sddl(conn: DirectoryConnection, dn: str) -> str:
    descriptor = read_descriptor(conn, dn)
    return descriptor.as_sddl(_domain_sid(conn))


def write_sddl(conn: DirectoryConnection, dn: str, sddl: str) -> None:
    """Replace the object's security descriptor.

    Only the DACL portion is written: touching the owner or the SACL requires
    privileges most delegated admins do not have, and the control bits AD
    maintains itself must not be overwritten wholesale.
    """
    import ldb
    from samba.dcerpc import security
    from samba.ndr import ndr_pack

    descriptor = security.descriptor.from_sddl(sddl, _domain_sid(conn))

    message = ldb.Message()
    message.dn = ldb.Dn(conn.samdb, dn)
    message["nTSecurityDescriptor"] = ldb.MessageElement(
        ndr_pack(descriptor), ldb.FLAG_MOD_REPLACE, "nTSecurityDescriptor"
    )
    # SECINFO_DACL only.
    conn.samdb.modify(message, controls=["sd_flags:1:4"])


def _domain_sid(conn: DirectoryConnection) -> Any:
    from samba.dcerpc import security

    sid = conn.info.domain_sid
    if sid is None:
        return conn.samdb.get_domain_sid()
    return security.dom_sid(sid)


# ---------------------------------------------------------------------------
# Accidental deletion protection
# ---------------------------------------------------------------------------


def is_delete_protected(sddl: str) -> bool:
    """Whether an Everyone-deny ACE covers delete and delete-tree."""
    for match in _PROTECTION_RE.finditer(sddl):
        rights = match.group(1)
        if "SD" in rights and "DT" in rights:
            return True
    return False


def set_delete_protection(conn: DirectoryConnection, dn: str, protect: bool) -> bool:
    """Add or remove the deletion-protection ACE. Returns True if changed."""
    sddl = read_sddl(conn, dn)
    protected = is_delete_protected(sddl)
    if protected == protect:
        return False

    if protect:
        # Deny ACEs must precede allow ACEs to be evaluated first; AD reorders
        # canonically on write, but inserting at the front of the DACL keeps
        # the intent obvious for anyone reading the raw SDDL.
        updated = _insert_ace(sddl, DELETE_PROTECTION_ACE)
    else:
        updated = _PROTECTION_RE.sub(
            lambda m: "" if ("SD" in m.group(1) and "DT" in m.group(1)) else m.group(0),
            sddl,
        )

    write_sddl(conn, dn, updated)
    return True


def _insert_ace(sddl: str, ace: str) -> str:
    """Insert *ace* at the start of the DACL section of an SDDL string."""
    marker = "D:"
    index = sddl.find(marker)
    if index < 0:
        return sddl + f"D:{ace}"

    # Skip the DACL flags (AI, P, AR, ...) that sit between "D:" and the first
    # "(" of an ACE.
    cursor = index + len(marker)
    while cursor < len(sddl) and sddl[cursor] not in "(S":
        cursor += 1
    return sddl[:cursor] + ace + sddl[cursor:]


def describe_protection(conn: DirectoryConnection, dn: str) -> dict[str, Any]:
    sddl = read_sddl(conn, dn)
    return {"dn": dn, "delete_protected": is_delete_protected(sddl), "sddl": sddl}


# ---------------------------------------------------------------------------
# Reading the ACL
# ---------------------------------------------------------------------------


def read_acl(conn: DirectoryConnection, dn: str) -> dict[str, Any]:
    """The object's permissions, with SIDs and GUIDs resolved to names."""
    descriptor = read_descriptor(conn, dn)
    domain_sid = _domain_sid(conn)

    aces: list[dict[str, Any]] = []
    dacl = getattr(descriptor, "dacl", None)
    for index, ace in enumerate(getattr(dacl, "aces", []) or []):
        described = _describe_ace(conn, ace, index)
        if described is not None:
            aces.append(described)

    owner_sid = getattr(descriptor, "owner_sid", None)

    return {
        "dn": dn,
        "owner": rights.resolve_sid(conn, str(owner_sid)) if owner_sid else None,
        "aces": aces,
        # Passed back on write to detect a concurrent change.
        "sddl": descriptor.as_sddl(domain_sid),
        "inheritance_blocked": _inheritance_blocked(descriptor),
    }


def _inheritance_blocked(descriptor: Any) -> bool:
    """Whether the object stops inheriting permissions from its parent."""
    # SEC_DESC_DACL_PROTECTED
    return bool(getattr(descriptor, "type", 0) & 0x1000)


def _describe_ace(conn: DirectoryConnection, ace: Any, index: int) -> dict[str, Any] | None:
    ace_type = int(getattr(ace, "type", 0))
    if ace_type not in (
        rights.ACE_TYPE_ALLOWED,
        rights.ACE_TYPE_DENIED,
        rights.ACE_TYPE_ALLOWED_OBJECT,
        rights.ACE_TYPE_DENIED_OBJECT,
    ):
        # Audit and alarm ACEs belong to the SACL; they are not permissions and
        # showing them here would only confuse.
        return None

    flags = int(getattr(ace, "flags", 0))
    mask = int(getattr(ace, "access_mask", 0))

    described: dict[str, Any] = {
        "index": index,
        "type": "deny" if ace_type in rights.DENY_ACE_TYPES else "allow",
        "inherited": bool(flags & rights.ACE_FLAG_INHERITED),
        "applies_to_children": bool(flags & rights.ACE_FLAG_CONTAINER_INHERIT),
        "inherit_only": bool(flags & rights.ACE_FLAG_INHERIT_ONLY),
        "trustee": rights.resolve_sid(conn, str(ace.trustee)),
        "mask": mask,
        "rights": rights.decode_mask(mask),
        "full_control": rights.is_full_control(mask),
    }

    if ace_type in rights.OBJECT_ACE_TYPES:
        obj = getattr(ace, "object", None)
        present = int(getattr(obj, "flags", 0)) if obj is not None else 0
        if present & rights.ACE_OBJECT_TYPE_PRESENT:
            described["object"] = rights.describe_object_guid(conn, str(obj.type))
        if present & rights.ACE_INHERITED_TYPE_PRESENT:
            described["applies_to"] = rights.describe_object_guid(conn, str(obj.inherited_type))

    return described


# ---------------------------------------------------------------------------
# Editing the ACL
# ---------------------------------------------------------------------------

# Matches one ACE in an SDDL string, including nested-free parentheses.
_ACE_RE = re.compile(r"\([^)]*\)")


def _split_dacl(sddl: str) -> tuple[str, list[str], str]:
    """Split an SDDL string into (prefix, ace strings, suffix).

    The prefix carries owner, group and the DACL flags; the suffix is the SACL
    section, if any. Both are preserved verbatim — rewriting them would mean
    re-deciding things the directory already decided.
    """
    marker = sddl.find("D:")
    if marker < 0:
        raise InvalidRequest(
            "The security descriptor has no DACL.",
            code="no_dacl",
            hint="Permissions cannot be edited on this object.",
        )

    cursor = marker + 2
    while cursor < len(sddl) and sddl[cursor] not in "(S":
        cursor += 1

    prefix = sddl[:cursor]
    rest = sddl[cursor:]

    sacl = rest.find("S:")
    body = rest if sacl < 0 else rest[:sacl]
    suffix = "" if sacl < 0 else rest[sacl:]

    return prefix, _ACE_RE.findall(body), suffix


def build_ace(
    *,
    trustee_sid: str,
    mask: int,
    deny: bool = False,
    object_guid: str | None = None,
    applies_to_guid: str | None = None,
    inherit_to_children: bool = False,
) -> str:
    """Assemble one ACE in SDDL form.

    The access mask is written numerically rather than as right abbreviations:
    the abbreviations are easy to mis-transcribe and silently mean something
    else, while a hex mask cannot be misread.
    """
    if mask <= 0:
        raise InvalidRequest("No permissions were selected.", code="empty_access_mask")
    if not trustee_sid:
        raise InvalidRequest("No account was selected.", code="missing_trustee")

    object_ace = bool(object_guid or applies_to_guid)
    if object_ace:
        ace_type = "OD" if deny else "OA"
    else:
        ace_type = "D" if deny else "A"

    flags = "CI" if inherit_to_children else ""

    return (
        f"({ace_type};{flags};0x{mask:08x};"
        f"{(object_guid or '').strip('{}')};{(applies_to_guid or '').strip('{}')};"
        f"{trustee_sid})"
    )


def add_ace(
    conn: DirectoryConnection,
    dn: str,
    *,
    ace: str,
    expected_sddl: str | None = None,
) -> dict[str, Any]:
    """Append an ACE. Deny entries are placed ahead of allow entries."""
    current = read_sddl(conn, dn)
    _ensure_unchanged(current, expected_sddl)

    prefix, aces, suffix = _split_dacl(current)
    if ace in aces:
        raise Conflict(
            "This permission already exists on the object.",
            code="ace_exists",
        )

    if ace.startswith(("(D;", "(OD;")):
        # Deny before allow, the order the directory evaluates them in.
        first_allow = next(
            (index for index, existing in enumerate(aces) if existing.startswith(("(A;", "(OA;"))),
            len(aces),
        )
        aces.insert(first_allow, ace)
    else:
        aces.append(ace)

    write_sddl(conn, dn, prefix + "".join(aces) + suffix)
    return {"dn": dn, "added": ace}


def remove_ace(
    conn: DirectoryConnection,
    dn: str,
    *,
    index: int,
    expected_sddl: str | None = None,
) -> dict[str, Any]:
    """Remove the ACE at *index* as reported by :func:`read_acl`."""
    current = read_sddl(conn, dn)
    _ensure_unchanged(current, expected_sddl)

    prefix, aces, suffix = _split_dacl(current)
    if index < 0 or index >= len(aces):
        raise NotFound(
            "This permission no longer exists on the object.",
            code="ace_not_found",
            context={"index": index},
        )

    target = aces[index]
    if is_inherited_ace(target):
        # Removing an inherited entry here would be undone by the next
        # inheritance pass — the change belongs on the container it comes from.
        raise InvalidRequest(
            "Inherited permissions cannot be removed here.",
            code="ace_inherited",
            hint="Change them on the container they come from, or block inheritance.",
        )

    aces.pop(index)
    write_sddl(conn, dn, prefix + "".join(aces) + suffix)
    return {"dn": dn, "removed": target}


# SDDL ACE fields: (type;flags;rights;object_guid;inherited_object_guid;sid)
_ACE_FIELDS = ("type", "flags", "rights", "object_guid", "applies_to_guid", "trustee")


def parse_ace(ace: str) -> dict[str, str]:
    """Split an SDDL ACE into its six fields."""
    fields = ace.strip().strip("()").split(";")
    if len(fields) < len(_ACE_FIELDS):
        raise InvalidRequest(
            "Malformed access control entry.", code="malformed_ace", context={"ace": ace}
        )
    return dict(zip(_ACE_FIELDS, fields, strict=False))


def ace_flags(ace: str) -> set[str]:
    """The ACE's flags as a set.

    Flags are two-character codes written without a separator ("OICIID"), so
    they have to be split pairwise — a substring search would match "ID"
    inside an unrelated combination.
    """
    raw = parse_ace(ace)["flags"]
    return {raw[index : index + 2] for index in range(0, len(raw) - 1, 2)}


def is_inherited_ace(ace: str) -> bool:
    return "ID" in ace_flags(ace)


def _ensure_unchanged(current: str, expected: str | None) -> None:
    """Refuse the write if someone else edited the ACL in the meantime."""
    if expected is None or current == expected:
        return
    raise Conflict(
        "The permissions were changed by someone else while you were editing.",
        code="acl_changed",
        hint="Reload the permissions and apply your change again.",
    )
