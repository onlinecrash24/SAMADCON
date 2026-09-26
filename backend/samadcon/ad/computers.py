"""Computer accounts.

Includes reading LAPS passwords, which is the one operation here that hands a
live credential to a browser. It is therefore a separate, explicitly audited
call — never part of the normal detail view — and both LAPS generations are
supported: legacy Microsoft LAPS (``ms-Mcs-AdmPwd``) and Windows LAPS
(``msLAPS-Password``). BitLocker recovery passwords follow the same rule.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from samadcon.ad import uac, values
from samadcon.ad.connection import SCOPE_ONELEVEL, SCOPE_SUBTREE, DirectoryConnection
from samadcon.ad.directory import summarize
from samadcon.core.errors import Conflict, InvalidRequest, NotFound, PermissionDenied

COMPUTER_FIELDS: dict[str, str] = {
    "display_name": "displayName",
    "description": "description",
    "location": "location",
    "managed_by": "managedBy",
    "dns_host_name": "dNSHostName",
}

STATUS_ATTRS = [
    "operatingSystem",
    "operatingSystemVersion",
    "operatingSystemServicePack",
    "lastLogon",
    "lastLogonTimestamp",
    "pwdLastSet",
    "servicePrincipalName",
    "primaryGroupID",
]

DETAIL_ATTRS = [
    "distinguishedName",
    "objectClass",
    "objectGUID",
    "objectSid",
    "name",
    "sAMAccountName",
    "userAccountControl",
    "memberOf",
    "whenCreated",
    "whenChanged",
    *COMPUTER_FIELDS.values(),
    *STATUS_ATTRS,
]

# Attribute pairs per LAPS generation: password, expiry.
LAPS_LEGACY = ("ms-Mcs-AdmPwd", "ms-Mcs-AdmPwdExpirationTime")
LAPS_WINDOWS = ("msLAPS-Password", "msLAPS-PasswordExpirationTime")
LAPS_WINDOWS_ENCRYPTED = ("msLAPS-EncryptedPassword", "msLAPS-PasswordExpirationTime")


def get_computer(conn: DirectoryConnection, dn: str) -> dict[str, Any]:
    entry = conn.get(dn, attrs=DETAIL_ATTRS)
    if entry is None:
        raise NotFound("The computer account does not exist.", context={"dn": dn})

    uac_value = values.as_int(entry, "userAccountControl", 0) or 0
    return {
        **summarize(entry),
        "dn": values.as_str(entry, "distinguishedName") or str(entry.dn),
        "type": "computer",
        "sam_account_name": values.as_str(entry, "sAMAccountName"),
        "attributes": {
            field: values.as_str(entry, attribute) for field, attribute in COMPUTER_FIELDS.items()
        },
        "flags": uac.decode(uac_value),
        "user_account_control": uac_value,
        "role": uac.account_type(uac_value),
        "operating_system": {
            "name": values.as_str(entry, "operatingSystem"),
            "version": values.as_str(entry, "operatingSystemVersion"),
            "service_pack": values.as_str(entry, "operatingSystemServicePack"),
        },
        "status": {
            "disabled": uac.is_disabled(uac_value),
            "last_logon": _newest_logon(entry),
            "password_last_set": values.as_filetime(entry, "pwdLastSet"),
        },
        "service_principal_names": sorted(values.as_list(entry, "servicePrincipalName")),
        "member_of": sorted(values.as_list(entry, "memberOf"), key=str.lower),
    }


def _newest_logon(entry: Any):
    candidates = [
        values.as_filetime(entry, "lastLogon"),
        values.as_filetime(entry, "lastLogonTimestamp"),
    ]
    known = [c for c in candidates if c is not None]
    return max(known) if known else None


def create_computer(
    conn: DirectoryConnection,
    *,
    parent_dn: str,
    name: str,
    description: str | None = None,
    location: str | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    import ldb

    computer_name = name.strip().rstrip("$").upper()
    if not computer_name:
        raise InvalidRequest("The computer name is missing.", code="missing_name")
    if len(computer_name) > 15:
        raise InvalidRequest(
            "A computer name must not exceed 15 characters.",
            code="computer_name_too_long",
            hint="This is the NetBIOS limit and applies to the account name.",
        )

    if not conn.exists(parent_dn):
        raise NotFound("The target container does not exist.", context={"dn": parent_dn})

    sam = f"{computer_name}$"
    dn = f"CN={values.escape_rdn_value(computer_name)},{parent_dn}"
    if conn.exists(dn):
        raise Conflict(
            "A computer with this name already exists in the container.",
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
            "This computer account name is already in use.",
            code="sam_account_name_taken",
            context={"sam_account_name": sam},
        )

    account_control = uac.WORKSTATION_TRUST_ACCOUNT
    if not enabled:
        account_control |= uac.ACCOUNTDISABLE

    message = ldb.Message()
    message.dn = ldb.Dn(conn.samdb, dn)
    message["objectClass"] = ldb.MessageElement(
        ["top", "person", "organizationalPerson", "user", "computer"],
        ldb.FLAG_MOD_ADD,
        "objectClass",
    )
    message["sAMAccountName"] = ldb.MessageElement(sam, ldb.FLAG_MOD_ADD, "sAMAccountName")
    message["userAccountControl"] = ldb.MessageElement(
        str(account_control), ldb.FLAG_MOD_ADD, "userAccountControl"
    )
    if description:
        message["description"] = ldb.MessageElement(description, ldb.FLAG_MOD_ADD, "description")
    if location:
        message["location"] = ldb.MessageElement(location, ldb.FLAG_MOD_ADD, "location")

    conn.add(message)
    return get_computer(conn, dn)


def update_computer(
    conn: DirectoryConnection,
    dn: str,
    *,
    attributes: dict[str, Any] | None = None,
    flags: dict[str, bool] | None = None,
) -> dict[str, Any]:
    from samadcon.ad.users import _set_uac

    applied: dict[str, Any] = {}

    if attributes:
        changes = {}
        for field, value in attributes.items():
            attribute = COMPUTER_FIELDS.get(field)
            if attribute is None:
                raise InvalidRequest(f"Unknown field '{field}'.", code="unknown_field")
            changes[attribute] = value
        applied.update(conn.modify_attributes(dn, changes))

    if flags:
        entry = conn.get(dn, attrs=["userAccountControl"])
        if entry is None:
            raise NotFound("The computer account does not exist.", context={"dn": dn})
        current = values.as_int(entry, "userAccountControl", 0) or 0
        updated = uac.apply(current, flags)
        if updated != current:
            _set_uac(conn, dn, updated)
            applied["userAccountControl"] = {"old": current, "new": updated}

    return applied


def reset_computer_account(conn: DirectoryConnection, dn: str) -> None:
    """Reset the machine account password to its initial value.

    The initial password of a domain member is its account name without the
    trailing ``$``, in lower case. Setting it lets the machine rejoin without
    being removed from the domain first — the same thing ADUC's "Reset
    Account" does.
    """
    from samadcon.ad.users import set_password

    entry = conn.get(dn, attrs=["sAMAccountName", "userAccountControl", "objectClass"])
    if entry is None:
        raise NotFound("The computer account does not exist.", context={"dn": dn})

    classes = {c.lower() for c in values.as_list(entry, "objectClass")}
    if "computer" not in classes:
        raise InvalidRequest(
            "This object is not a computer account.",
            code="not_a_computer",
            context={"dn": dn},
        )

    sam = values.as_str(entry, "sAMAccountName") or ""
    initial_password = sam.rstrip("$").lower()
    if not initial_password:
        raise InvalidRequest(
            "The computer account has no logon name.",
            code="missing_sam_account_name",
            context={"reason": "computer_account"},
        )

    set_password(conn, dn, initial_password, must_change=False)


# ---------------------------------------------------------------------------
# LAPS
# ---------------------------------------------------------------------------


def laps_status(conn: DirectoryConnection, dn: str) -> dict[str, Any]:
    """Which LAPS generation, if any, has a password stored for this computer.

    Reads only the expiry timestamps, never the password itself — so this is
    safe to call from a normal detail view.
    """
    attrs = [
        LAPS_LEGACY[1],
        LAPS_WINDOWS[1],
        "msLAPS-EncryptedPassword",
        "ms-Mcs-AdmPwdExpirationTime",
    ]
    try:
        entry = conn.get(dn, attrs=attrs)
    except Exception:  # noqa: BLE001 — schema may not know the attributes at all
        return {"available": False, "generation": None}

    if entry is None:
        raise NotFound("The computer account does not exist.", context={"dn": dn})

    windows_expiry = values.as_filetime(entry, LAPS_WINDOWS[1])
    legacy_expiry = values.as_filetime(entry, LAPS_LEGACY[1])
    encrypted = values.as_bytes(entry, "msLAPS-EncryptedPassword") is not None

    if windows_expiry is not None or encrypted:
        return {
            "available": True,
            "generation": "windows",
            "expires_at": windows_expiry,
            "encrypted": encrypted,
        }
    if legacy_expiry is not None:
        return {"available": True, "generation": "legacy", "expires_at": legacy_expiry}
    return {"available": False, "generation": None}


def read_laps_password(conn: DirectoryConnection, dn: str) -> dict[str, Any]:
    """Read the LAPS password.

    Deliberately separate from :func:`get_computer`: this returns a live local
    administrator credential, the caller audits it as its own action, and the
    directory ACL on the attribute is what actually authorises it.
    """
    import json

    entry = conn.get(
        dn,
        attrs=[
            LAPS_LEGACY[0],
            LAPS_LEGACY[1],
            LAPS_WINDOWS[0],
            LAPS_WINDOWS[1],
            "msLAPS-EncryptedPassword",
            "sAMAccountName",
        ],
    )
    if entry is None:
        raise NotFound("The computer account does not exist.", context={"dn": dn})

    windows_value = values.as_str(entry, LAPS_WINDOWS[0])
    if windows_value:
        # Windows LAPS stores a JSON blob: {"n": account, "t": timestamp, "p": password}
        try:
            parsed = json.loads(windows_value)
            return {
                "generation": "windows",
                "account": parsed.get("n"),
                "password": parsed.get("p"),
                "expires_at": values.as_filetime(entry, LAPS_WINDOWS[1]),
            }
        except (ValueError, AttributeError):
            return {
                "generation": "windows",
                "account": None,
                "password": windows_value,
                "expires_at": values.as_filetime(entry, LAPS_WINDOWS[1]),
            }

    legacy_value = values.as_str(entry, LAPS_LEGACY[0])
    if legacy_value:
        return {
            "generation": "legacy",
            "account": "Administrator",
            "password": legacy_value,
            "expires_at": values.as_filetime(entry, LAPS_LEGACY[1]),
        }

    if values.as_bytes(entry, "msLAPS-EncryptedPassword") is not None:
        raise InvalidRequest(
            "This password is stored encrypted and can only be decrypted by an authorised group.",
            code="laps_encrypted",
            hint="Windows LAPS encryption is not supported by SAMADCON yet.",
        )

    raise PermissionDenied(
        "No LAPS password is readable for this computer.",
        code="laps_unavailable",
        hint=(
            "Either no password is stored, or your account lacks read access to the "
            "LAPS attribute."
        ),
    )


# ---------------------------------------------------------------------------
# BitLocker
# ---------------------------------------------------------------------------

# Windows stores each recovery password as a child of the computer account,
# named "<date>{<recovery GUID>}". The GUID is the key ID that the recovery
# screen shows the first eight characters of. The password is a confidential
# attribute: the directory decides who may read it, not this code.
BITLOCKER_CLASS = "msFVE-RecoveryInformation"
BITLOCKER_PASSWORD = "msFVE-RecoveryPassword"
BITLOCKER_LISTED = ["name", "msFVE-RecoveryGuid", "msFVE-VolumeGuid", "whenCreated"]
BITLOCKER_FIND_LIMIT = 50


def _bitlocker_schema_known(conn: DirectoryConnection) -> bool:
    """Whether the schema has the recovery class at all.

    Without it a search for the class finds nothing, which reads as "no keys
    stored". The two are different answers.
    """
    try:
        found = conn.search(
            conn.info.schema_dn,
            scope=SCOPE_ONELEVEL,
            expression=f"(lDAPDisplayName={BITLOCKER_CLASS})",
            attrs=["lDAPDisplayName"],
            max_results=1,
        )
    except Exception:  # noqa: BLE001 — an unreadable schema is an unknown class
        return False
    return len(found) > 0


def _bitlocker_key_id(entry: Any) -> str | None:
    """The key ID, from the GUID attribute or else from the object's name."""
    guid = values.guid_to_str(values.as_bytes(entry, "msFVE-RecoveryGuid"))
    if guid:
        return guid.strip("{}").upper()
    name = values.as_str(entry, "name") or ""
    start, end = name.find("{"), name.find("}")
    if 0 <= start < end:
        return name[start + 1 : end].upper()
    return None


def _render_bitlocker_key(entry: Any) -> dict[str, Any] | None:
    key_id = _bitlocker_key_id(entry)
    if key_id is None:
        return None
    volume = values.guid_to_str(values.as_bytes(entry, "msFVE-VolumeGuid"))
    return {
        "dn": str(entry.dn) if hasattr(entry, "dn") else values.as_str(entry, "distinguishedName"),
        "key_id": key_id,
        "key_id_short": key_id[:8],
        "volume_id": volume.strip("{}").upper() if volume else None,
        "created": values.as_generalized_time(entry, "whenCreated"),
    }


def _bitlocker_children(conn: DirectoryConnection, dn: str) -> list[dict[str, Any]]:
    result = conn.search(
        dn,
        scope=SCOPE_ONELEVEL,
        expression=f"(objectClass={BITLOCKER_CLASS})",
        attrs=BITLOCKER_LISTED,
    )
    keys = [key for key in (_render_bitlocker_key(entry) for entry in result) if key]
    keys.sort(key=lambda key: key["created"] or datetime.min.replace(tzinfo=UTC), reverse=True)
    return keys


def bitlocker_keys(conn: DirectoryConnection, dn: str) -> dict[str, Any]:
    """The recovery keys stored for this computer — IDs and dates, never a password."""
    if not conn.exists(dn):
        raise NotFound("The computer account does not exist.", context={"dn": dn})
    if not _bitlocker_schema_known(conn):
        return {"available": False, "keys": []}
    return {"available": True, "keys": _bitlocker_children(conn, dn)}


def read_bitlocker_key(conn: DirectoryConnection, dn: str, key_id: str) -> dict[str, Any]:
    """Read one recovery password.

    Separate from the listing for the same reason as LAPS: it hands out a
    secret, the caller audits it as its own action, and the attribute's ACL
    is what authorises it. Only the one password asked for is read.
    """
    wanted = key_id.strip("{}").upper()
    match = next((key for key in _bitlocker_children(conn, dn) if key["key_id"] == wanted), None)
    if match is None:
        raise NotFound(
            "This computer has no recovery key with that ID.",
            code="bitlocker_key_not_found",
            context={"dn": dn, "key_id": wanted},
        )

    entry = conn.get(match["dn"], attrs=[BITLOCKER_PASSWORD])
    password = values.as_str(entry, BITLOCKER_PASSWORD) if entry is not None else None
    if not password:
        raise PermissionDenied(
            "The recovery password is not readable.",
            code="bitlocker_unreadable",
            hint=(
                "The recovery password is a confidential attribute. Your account can see "
                "that the key exists but lacks the right to read it."
            ),
        )
    return {"key_id": match["key_id"], "created": match["created"], "recovery_password": password}


def find_bitlocker_key(conn: DirectoryConnection, key_id_prefix: str) -> dict[str, Any]:
    """Every stored key whose ID starts with *key_id_prefix*, domain-wide.

    What the recovery screen shows is the first eight characters of the key
    ID; this finds the computer it belongs to. No password is read here.
    """
    prefix = key_id_prefix.strip("{}").upper()
    result = conn.search(
        conn.info.base_dn,
        scope=SCOPE_SUBTREE,
        expression=(
            f"(&(objectClass={BITLOCKER_CLASS})(name=*{{{values.escape_filter(prefix)}*))"
        ),
        attrs=BITLOCKER_LISTED,
        max_results=BITLOCKER_FIND_LIMIT,
    )
    found = []
    for entry in result:
        key = _render_bitlocker_key(entry)
        if key is None or not key["key_id"].startswith(prefix):
            continue
        computer_dn = values.parent_dn(key["dn"]) or ""
        found.append(
            {**key, "computer_dn": computer_dn, "computer": values.name_from_dn(computer_dn)}
        )
    return {"keys": found, "truncated": getattr(result, "truncated", False)}


def list_stale_computers(conn: DirectoryConnection, days: int = 90) -> list[dict[str, Any]]:
    """Computers that have not authenticated for *days*.

    Based on lastLogonTimestamp, which replicates but lags by up to 14 days —
    good enough for a cleanup list, not for an audit.
    """
    from datetime import timedelta

    cutoff = datetime.now(UTC) - timedelta(days=days)
    threshold = values.datetime_to_filetime(cutoff)

    result = conn.search(
        conn.info.base_dn,
        scope=SCOPE_SUBTREE,
        expression=(
            f"(&(objectCategory=computer)(lastLogonTimestamp<={threshold})"
            "(!(lastLogonTimestamp=0)))"
        ),
        attrs=["distinguishedName", "objectClass", "name", "objectGUID", "sAMAccountName",
               "lastLogonTimestamp", "operatingSystem", "userAccountControl", "description"],
    )

    stale = []
    for entry in result:
        item = summarize(entry)
        item["last_logon"] = values.as_filetime(entry, "lastLogonTimestamp")
        item["operating_system"] = values.as_str(entry, "operatingSystem")
        stale.append(item)
    stale.sort(key=lambda item: item["last_logon"] or cutoff)
    return stale
