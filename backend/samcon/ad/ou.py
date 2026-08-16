"""Organizational units and containers."""

from __future__ import annotations

from typing import Any

from samcon.ad import sacl, values
from samcon.ad.connection import SCOPE_ONELEVEL, DirectoryConnection
from samcon.ad.directory import summarize
from samcon.core.errors import Conflict, InvalidRequest, NotFound

OU_FIELDS: dict[str, str] = {
    "description": "description",
    "street": "street",
    "city": "l",
    "state": "st",
    "postal_code": "postalCode",
    "country": "c",
    "managed_by": "managedBy",
}

DETAIL_ATTRS = [
    "distinguishedName",
    "objectClass",
    "objectGUID",
    "name",
    "ou",
    "gPLink",
    "gPOptions",
    "whenCreated",
    "whenChanged",
    *OU_FIELDS.values(),
]


def get_ou(conn: DirectoryConnection, dn: str) -> dict[str, Any]:
    entry = conn.get(dn, attrs=DETAIL_ATTRS)
    if entry is None:
        raise NotFound("The organizational unit does not exist.", context={"dn": dn})

    detail = {
        **summarize(entry),
        "dn": values.as_str(entry, "distinguishedName") or str(entry.dn),
        "type": "organizational_unit",
        "attributes": {
            field: values.as_str(entry, attribute) for field, attribute in OU_FIELDS.items()
        },
        # Raw values; the GPMC module turns them into linked GPO objects.
        "gp_link": values.as_str(entry, "gPLink"),
        "block_inheritance": bool((values.as_int(entry, "gPOptions", 0) or 0) & 1),
        "child_count": _child_count(conn, dn),
    }

    try:
        detail["delete_protected"] = sacl.is_delete_protected(sacl.read_sddl(conn, dn))
    except Exception:  # noqa: BLE001 — no READ_CONTROL is not a reason to fail the view
        detail["delete_protected"] = None

    return detail


def _child_count(conn: DirectoryConnection, dn: str) -> int:
    result = conn.search(dn, scope=SCOPE_ONELEVEL, expression="(objectClass=*)", attrs=["1.1"])
    return len(result)


def create_ou(
    conn: DirectoryConnection,
    *,
    parent_dn: str,
    name: str,
    description: str | None = None,
    protect_from_deletion: bool = True,
) -> dict[str, Any]:
    """Create an OU.

    Deletion protection defaults to on — the same default ADUC has used since
    Windows Server 2008, and the reason most accidental mass deletions do not
    happen.
    """
    import ldb

    ou_name = name.strip()
    if not ou_name:
        raise InvalidRequest("The name is missing.", code="missing_name")

    if not conn.exists(parent_dn):
        raise NotFound("The target container does not exist.", context={"dn": parent_dn})

    dn = f"OU={values.escape_rdn_value(ou_name)},{parent_dn}"
    if conn.exists(dn):
        raise Conflict(
            "An organizational unit with this name already exists here.",
            code="already_exists",
            context={"dn": dn},
        )

    message = ldb.Message()
    message.dn = ldb.Dn(conn.samdb, dn)
    message["objectClass"] = ldb.MessageElement(
        ["top", "organizationalUnit"], ldb.FLAG_MOD_ADD, "objectClass"
    )
    if description:
        message["description"] = ldb.MessageElement(description, ldb.FLAG_MOD_ADD, "description")

    conn.add(message)

    if protect_from_deletion:
        try:
            sacl.set_delete_protection(conn, dn, True)
        except Exception:  # noqa: BLE001 — the OU exists; protection is a follow-up
            # Reported through the returned object so the UI can offer a retry
            # instead of leaving the administrator with a silent half-success.
            detail = get_ou(conn, dn)
            detail["delete_protection_failed"] = True
            return detail

    return get_ou(conn, dn)


def update_ou(
    conn: DirectoryConnection,
    dn: str,
    *,
    attributes: dict[str, Any] | None = None,
    protect_from_deletion: bool | None = None,
) -> dict[str, Any]:
    applied: dict[str, Any] = {}

    if attributes:
        changes = {}
        for field, value in attributes.items():
            attribute = OU_FIELDS.get(field)
            if attribute is None:
                raise InvalidRequest(f"Unknown field '{field}'.", code="unknown_field")
            changes[attribute] = value
        applied.update(conn.modify_attributes(dn, changes))

    if protect_from_deletion is not None:
        changed = sacl.set_delete_protection(conn, dn, protect_from_deletion)
        if changed:
            applied["delete_protected"] = {"new": protect_from_deletion}

    return applied


def delete_ou(conn: DirectoryConnection, dn: str, *, recursive: bool = False) -> None:
    """Delete an OU.

    Deletion protection is not silently lifted: an administrator who set it
    has to clear it deliberately. What we do is explain that, instead of
    letting the DC return a bare "insufficient access rights".
    """
    from samcon.ad.directory import delete_object

    try:
        protected = sacl.is_delete_protected(sacl.read_sddl(conn, dn))
    except Exception:  # noqa: BLE001
        protected = False

    if protected:
        raise InvalidRequest(
            "The organizational unit is protected against accidental deletion.",
            code="delete_protected",
            hint="Clear the protection in the OU's properties first.",
            context={"dn": dn},
        )

    if not recursive and _child_count(conn, dn) > 0:
        raise Conflict(
            "The organizational unit is not empty.",
            code="not_empty",
            hint="Move the objects out first, or delete recursively.",
            context={"dn": dn},
        )

    delete_object(conn, dn, recursive=recursive)
