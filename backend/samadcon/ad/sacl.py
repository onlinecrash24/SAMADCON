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
from samadcon.ad.connection import SCOPE_BASE, DirectoryConnection
from samadcon.core.errors import Conflict, InvalidRequest, NotFound, SamadconError

# Deny Delete + Delete Tree for Everyone — exactly what ADUC writes for
# "Protect object from accidental deletion".
DELETE_PROTECTION_ACE = "(D;;SDDT;;;WD)"

# Matches that ACE regardless of right ordering or extra whitespace.
_PROTECTION_RE = re.compile(r"\(D;[^;]*;([A-Z]*);;;WD\)")


# Owner, group and DACL — SECINFO_OWNER | SECINFO_GROUP | SECINFO_DACL. Asked
# for by name: without the control, which parts came back was the server's
# choice and depended on the account. The SACL is left out; reading it needs
# a privilege most delegated admins do not have, and nothing here edits it.
READ_SD_CONTROLS = ["sd_flags:1:7"]


def _raw_descriptor(conn: DirectoryConnection, dn: str) -> bytes | None:
    """The packed nTSecurityDescriptor, or None when it is not readable."""
    try:
        result = conn.search(
            dn,
            scope=SCOPE_BASE,
            attrs=["nTSecurityDescriptor"],
            controls=READ_SD_CONTROLS,
            max_results=1,
        )
    except NotFound:
        result = None
    if result is None or not result.entries:
        raise NotFound("The directory object does not exist.", context={"dn": dn})
    return values.as_bytes(result.entries[0], "nTSecurityDescriptor")


def read_descriptor(conn: DirectoryConnection, dn: str) -> Any:
    """Return the object's nTSecurityDescriptor as a samba structure."""
    from samba.dcerpc import security
    from samba.ndr import ndr_unpack

    raw = _raw_descriptor(conn, dn)
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
    domain = _domain_sid_text(conn)
    if any(same_ace(ace, existing, domain) for existing in aces):
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


def change_acl(
    conn: DirectoryConnection,
    dn: str,
    *,
    remove: list[int],
    add: list[str],
    expected_sddl: str,
) -> dict[str, Any]:
    """Apply what the property sheet queued: one read, one check, one write.

    *remove* holds positions in the list as :func:`read_acl` reported it, so
    they are resolved against the ACL as read, before anything is added. A
    refusal of any part writes nothing. The check against *expected_sddl* is
    not optional here: the positions only mean something in the list the
    sheet saw.
    """
    if not expected_sddl:
        raise InvalidRequest(
            "The permissions the changes were made against are missing.",
            code="acl_expected_missing",
        )
    if not remove and not add:
        raise InvalidRequest("Nothing to change.", code="no_changes")

    current = read_sddl(conn, dn)
    _ensure_unchanged(current, expected_sddl)
    prefix, aces, suffix = _split_dacl(current)

    for index in remove:
        if index < 0 or index >= len(aces):
            raise NotFound(
                "This permission no longer exists on the object.",
                code="ace_not_found",
                context={"index": index},
            )
        if is_inherited_ace(aces[index]):
            raise InvalidRequest(
                "Inherited permissions cannot be removed here.",
                code="ace_inherited",
                hint="Change them on the container they come from, or block inheritance.",
            )
    removed = set(remove)
    removed_aces = [ace for index, ace in enumerate(aces) if index in removed]
    kept = [ace for index, ace in enumerate(aces) if index not in removed]

    domain = _domain_sid_text(conn)
    for ace in add:
        if any(same_ace(ace, existing, domain) for existing in kept):
            raise Conflict("This permission already exists on the object.", code="ace_exists")
        if ace.startswith(("(D;", "(OD;")):
            # Deny before allow, the order the directory evaluates them in.
            first_allow = next(
                (i for i, existing in enumerate(kept) if existing.startswith(("(A;", "(OA;"))),
                len(kept),
            )
            kept.insert(first_allow, ace)
        else:
            kept.append(ace)

    write_sddl(conn, dn, prefix + "".join(kept) + suffix)
    return {"dn": dn, "removed": removed_aces, "added": list(add)}


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


# ---------------------------------------------------------------------------
# Comparing ACEs
#
# SAMADCON writes an ACE with a hex mask and the trustee's full SID; Samba
# reads the ACL back with right letters and SID aliases. Compared as text,
# (A;;0x00000010;;;S-1-5-21-…-512) and (A;;RP;;;DA) were two entries, and
# the same permission could be added twice. These are compared as what they
# mean: type, flags as a set, the mask as a number, GUIDs without braces or
# case, and the trustee as a SID.
# ---------------------------------------------------------------------------

# The right letters of SDDL for directory objects (MS-DTYP 2.5.1.1), and the
# generic ones. File and registry letters are left out: they never appear on
# a directory object, and an unknown letter keeps the mask as text.
_SDDL_RIGHTS = {
    "CC": 0x00000001,
    "DC": 0x00000002,
    "LC": 0x00000004,
    "SW": 0x00000008,
    "RP": 0x00000010,
    "WP": 0x00000020,
    "DT": 0x00000040,
    "LO": 0x00000080,
    "CR": 0x00000100,
    "SD": 0x00010000,
    "RC": 0x00020000,
    "WD": 0x00040000,
    "WO": 0x00080000,
    "GA": 0x10000000,
    "GX": 0x20000000,
    "GW": 0x40000000,
    "GR": 0x80000000,
}

# SID aliases that need no domain (MS-DTYP 2.5.1.1).
_WELL_KNOWN_ALIASES = {
    "WD": "S-1-1-0",
    "CO": "S-1-3-0",
    "CG": "S-1-3-1",
    "OW": "S-1-3-4",
    "NU": "S-1-5-2",
    "IU": "S-1-5-4",
    "SU": "S-1-5-6",
    "AN": "S-1-5-7",
    "ED": "S-1-5-9",
    "PS": "S-1-5-10",
    "AU": "S-1-5-11",
    "RC": "S-1-5-12",
    "SY": "S-1-5-18",
    "LS": "S-1-5-19",
    "NS": "S-1-5-20",
    "WR": "S-1-5-33",
    "BA": "S-1-5-32-544",
    "BU": "S-1-5-32-545",
    "BG": "S-1-5-32-546",
    "PU": "S-1-5-32-547",
    "AO": "S-1-5-32-548",
    "SO": "S-1-5-32-549",
    "PO": "S-1-5-32-550",
    "BO": "S-1-5-32-551",
    "RE": "S-1-5-32-552",
    "RU": "S-1-5-32-554",
    "RD": "S-1-5-32-555",
    "NO": "S-1-5-32-556",
    "MU": "S-1-5-32-558",
    "LU": "S-1-5-32-559",
    "IS": "S-1-5-32-568",
    "CY": "S-1-5-32-569",
    "ER": "S-1-5-32-573",
    "RM": "S-1-5-32-580",
}

# SID aliases relative to the domain, by RID. Schema and Enterprise Admins
# belong to the forest root; in a single-domain forest that is this domain.
_DOMAIN_ALIASES = {
    "RO": 498,
    "DA": 512,
    "DU": 513,
    "DG": 514,
    "DC": 515,
    "DD": 516,
    "CA": 517,
    "SA": 518,
    "EA": 519,
    "PA": 520,
    "CN": 522,
    "AP": 525,
    "KA": 526,
    "EK": 527,
    "RS": 553,
}


def _domain_sid_text(conn: Any) -> str | None:
    try:
        sid = conn.info.domain_sid
    except AttributeError:
        return None
    return str(sid) if sid else None


def _normal_mask(rights_field: str) -> int | str:
    text = rights_field.strip()
    if not text:
        return 0
    if text[:2].lower() == "0x" or text.isdigit():
        try:
            return int(text, 0)
        except ValueError:
            return text
    if len(text) % 2:
        return text
    mask = 0
    for index in range(0, len(text), 2):
        bit = _SDDL_RIGHTS.get(text[index : index + 2].upper())
        if bit is None:
            return text
        mask |= bit
    return mask


def _normal_sid(trustee: str, domain_sid: str | None) -> str:
    text = trustee.strip()
    if text.upper().startswith("S-"):
        return text.upper()
    alias = text.upper()
    if alias in _WELL_KNOWN_ALIASES:
        return _WELL_KNOWN_ALIASES[alias]
    if alias in _DOMAIN_ALIASES and domain_sid:
        return f"{domain_sid.upper()}-{_DOMAIN_ALIASES[alias]}"
    # Without the domain, an alias only ever matches itself.
    return alias


def _normal_guid(value: str) -> str:
    return value.strip().strip("{}").lower()


def normal_ace(ace: str, domain_sid: str | None) -> tuple[Any, ...]:
    """What an ACE means, as something two spellings of it compare equal on."""
    fields = parse_ace(ace)
    return (
        fields["type"].strip().upper(),
        frozenset(ace_flags(ace)),
        _normal_mask(fields["rights"]),
        _normal_guid(fields["object_guid"]),
        _normal_guid(fields["applies_to_guid"]),
        _normal_sid(fields["trustee"], domain_sid),
    )


def same_ace(a: str, b: str, domain_sid: str | None) -> bool:
    """Whether two ACEs grant the same thing to the same trustee.

    An entry this cannot take apart — a conditional ACE, say — is compared as
    text, as everything was before: a missed duplicate is better than a
    refused write over an entry nobody is touching.
    """
    try:
        return normal_ace(a, domain_sid) == normal_ace(b, domain_sid)
    except InvalidRequest:
        return a == b


def _ensure_unchanged(current: str, expected: str | None) -> None:
    """Refuse the write if someone else edited the ACL in the meantime."""
    if expected is None or current == expected:
        return
    raise Conflict(
        "The permissions were changed by someone else while you were editing.",
        code="acl_changed",
        hint="Reload the permissions and apply your change again.",
    )
