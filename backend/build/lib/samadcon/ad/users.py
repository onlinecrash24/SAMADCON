"""User accounts.

Covers what ADUC's user property sheets do: the attribute tabs, account
options, password reset, unlocking, expiry and group membership.

Creating a user is deliberately a three-step sequence — add the object
disabled, set the password, then enable it. Active Directory rejects an
enabled account that has no password, so doing it in one shot fails on exactly
the domains that have a password policy worth having.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import Any

from samadcon.ad import uac, values
from samadcon.ad.connection import SCOPE_SUBTREE, DirectoryConnection
from samadcon.ad.directory import summarize
from samadcon.core.errors import Conflict, InvalidRequest, NotFound

# API field -> LDAP attribute. Used for both reading and writing, so the two
# directions cannot drift apart.
USER_FIELDS: dict[str, str] = {
    # General
    "first_name": "givenName",
    "last_name": "sn",
    "initials": "initials",
    "display_name": "displayName",
    "description": "description",
    "office": "physicalDeliveryOfficeName",
    "mail": "mail",
    "web_page": "wWWHomePage",
    # Address
    "street": "streetAddress",
    "post_office_box": "postOfficeBox",
    "city": "l",
    "state": "st",
    "postal_code": "postalCode",
    "country": "c",
    # Telephones
    "telephone": "telephoneNumber",
    "mobile": "mobile",
    "home_phone": "homePhone",
    "pager": "pager",
    "fax": "facsimileTelephoneNumber",
    "ip_phone": "ipPhone",
    "notes": "info",
    # Profile
    "profile_path": "profilePath",
    "logon_script": "scriptPath",
    "home_directory": "homeDirectory",
    "home_drive": "homeDrive",
    # Organization
    "title": "title",
    "department": "department",
    "company": "company",
    "manager": "manager",
    # Account
    "upn": "userPrincipalName",
    "logon_workstations": "userWorkstations",
}

# Read-only, but shown on the account tab.
STATUS_ATTRS = [
    "lastLogon",
    "lastLogonTimestamp",
    "logonCount",
    "badPwdCount",
    "badPasswordTime",
    "lockoutTime",
    "pwdLastSet",
    "accountExpires",
    "whenCreated",
    "whenChanged",
    "msDS-UserPasswordExpiryTimeComputed",
    "primaryGroupID",
]

DETAIL_ATTRS = [
    "distinguishedName",
    "objectClass",
    "objectGUID",
    "objectSid",
    "cn",
    "name",
    "sAMAccountName",
    "userAccountControl",
    "memberOf",
    "directReports",
    *USER_FIELDS.values(),
    *STATUS_ATTRS,
]

# Attributes the directory owns; letting them through a generic update would
# either fail or corrupt the object.
#
# sAMAccountName is deliberately NOT in here. Changing a logon name is a
# legitimate administrative act, and the directory enforces its uniqueness
# itself — a collision comes back as a constraint violation and is translated
# like any other. The typed property sheet leaves it out because renaming has
# its own action; the raw editor is the escape hatch and may do it.
PROTECTED_ATTRS = frozenset(
    {
        "objectclass",
        "objectguid",
        "objectsid",
        "distinguishedname",
        "samaccounttype",
        "useraccountcontrol",
        "unicodepwd",
        "dbcspwd",
        "primarygroupid",
        "memberof",
        "whencreated",
        "whenchanged",
        "usncreated",
        "usnchanged",
        "cn",
        "name",
    }
)


def get_user(conn: DirectoryConnection, dn: str) -> dict[str, Any]:
    entry = conn.get(dn, attrs=DETAIL_ATTRS)
    if entry is None:
        raise NotFound("The user does not exist.", context={"dn": dn})
    return _render_user(conn, entry)


def _render_user(conn: DirectoryConnection, entry: Any) -> dict[str, Any]:
    dn = values.as_str(entry, "distinguishedName") or str(entry.dn)
    uac_value = values.as_int(entry, "userAccountControl", 0) or 0

    attributes = {
        field: values.as_str(entry, attribute) for field, attribute in USER_FIELDS.items()
    }

    lockout_time = values.as_filetime(entry, "lockoutTime")
    pwd_last_set_raw = values.as_int(entry, "pwdLastSet")

    detail: dict[str, Any] = {
        **summarize(entry),
        "dn": dn,
        "type": "user",
        "sam_account_name": values.as_str(entry, "sAMAccountName"),
        "attributes": attributes,
        "flags": uac.decode(uac_value),
        "user_account_control": uac_value,
        "status": {
            "disabled": uac.is_disabled(uac_value),
            "locked_out": lockout_time is not None,
            "lockout_time": lockout_time,
            "last_logon": _newest_logon(entry),
            "logon_count": values.as_int(entry, "logonCount", 0),
            "bad_password_count": values.as_int(entry, "badPwdCount", 0),
            "bad_password_time": values.as_filetime(entry, "badPasswordTime"),
            # pwdLastSet == 0 is AD's way of saying "must change at next logon".
            "must_change_password": pwd_last_set_raw == 0,
            "password_last_set": values.filetime_to_datetime(pwd_last_set_raw),
            "password_expires": values.as_filetime(
                entry, "msDS-UserPasswordExpiryTimeComputed"
            ),
            "account_expires": values.as_filetime(entry, "accountExpires"),
        },
        "member_of": sorted(values.as_list(entry, "memberOf"), key=str.lower),
        "direct_reports": sorted(values.as_list(entry, "directReports"), key=str.lower),
        "primary_group_id": values.as_int(entry, "primaryGroupID"),
    }
    return detail


def _newest_logon(entry: Any) -> datetime | None:
    """Most recent of lastLogon and lastLogonTimestamp.

    lastLogon is per-DC and not replicated; lastLogonTimestamp is replicated
    but lags by up to two weeks. Neither alone is trustworthy, so we report
    whichever is newer and let the UI label it as approximate.
    """
    candidates = [
        values.as_filetime(entry, "lastLogon"),
        values.as_filetime(entry, "lastLogonTimestamp"),
    ]
    known = [c for c in candidates if c is not None]
    return max(known) if known else None


# ---------------------------------------------------------------------------
# Creating
# ---------------------------------------------------------------------------


def create_user(
    conn: DirectoryConnection,
    *,
    parent_dn: str,
    sam_account_name: str,
    common_name: str | None = None,
    password: str | None = None,
    must_change_password: bool = False,
    enabled: bool = True,
    attributes: dict[str, Any] | None = None,
    flags: dict[str, bool] | None = None,
) -> dict[str, Any]:
    import ldb

    sam = sam_account_name.strip()
    if not sam:
        raise InvalidRequest("The logon name is missing.", code="missing_sam_account_name")
    if len(sam) > 20:
        # Not a hard AD limit, but pre-Windows-2000 logon names longer than
        # this break on older clients and NTLM.
        raise InvalidRequest(
            "The logon name must not exceed 20 characters.",
            code="sam_account_name_too_long",
        )
    if enabled and not password:
        raise InvalidRequest(
            "An enabled account needs a password.",
            code="password_required",
            hint="Either supply a password or create the account disabled.",
        )

    if not conn.exists(parent_dn):
        raise NotFound("The target container does not exist.", context={"dn": parent_dn})

    cn = (common_name or sam).strip()
    dn = f"CN={values.escape_rdn_value(cn)},{parent_dn}"
    if conn.exists(dn):
        raise Conflict(
            "An object with this name already exists in the container.",
            code="already_exists",
            context={"dn": dn},
        )
    _ensure_sam_available(conn, sam)

    field_values = dict(attributes or {})
    upn = field_values.pop("upn", None) or f"{sam}@{conn.info.dns_domain}"

    message = ldb.Message()
    message.dn = ldb.Dn(conn.samdb, dn)
    message["objectClass"] = ldb.MessageElement(
        ["top", "person", "organizationalPerson", "user"], ldb.FLAG_MOD_ADD, "objectClass"
    )
    message["sAMAccountName"] = ldb.MessageElement(sam, ldb.FLAG_MOD_ADD, "sAMAccountName")
    message["userPrincipalName"] = ldb.MessageElement(
        upn, ldb.FLAG_MOD_ADD, "userPrincipalName"
    )
    # Always born disabled: AD refuses an enabled account without a password,
    # and the password can only be set once the object exists.
    message["userAccountControl"] = ldb.MessageElement(
        str(uac.NORMAL_ACCOUNT | uac.ACCOUNTDISABLE), ldb.FLAG_MOD_ADD, "userAccountControl"
    )

    for field, value in field_values.items():
        attribute = USER_FIELDS.get(field)
        if attribute is None:
            raise InvalidRequest(f"Unknown field '{field}'.", code="unknown_field")
        if value in (None, ""):
            continue
        message[attribute] = ldb.MessageElement(str(value), ldb.FLAG_MOD_ADD, attribute)

    conn.add(message)

    try:
        if password:
            set_password(conn, dn, password, must_change=must_change_password)

        target_uac = uac.NORMAL_ACCOUNT
        if flags:
            target_uac = uac.apply(target_uac, flags)
        if not enabled:
            target_uac |= uac.ACCOUNTDISABLE
        else:
            target_uac &= ~uac.ACCOUNTDISABLE

        _set_uac(conn, dn, target_uac)
    except Exception:
        # Leaving a half-built, disabled account behind would be worse than
        # failing outright — the next attempt would hit "already exists".
        # A failing rollback must not mask the original error.
        with contextlib.suppress(Exception):
            conn.delete(dn)
        raise

    return get_user(conn, dn)


def _ensure_sam_available(conn: DirectoryConnection, sam: str) -> None:
    existing = conn.search(
        conn.info.base_dn,
        scope=SCOPE_SUBTREE,
        expression=f"(sAMAccountName={values.escape_filter(sam)})",
        attrs=["distinguishedName"],
        max_results=1,
    )
    if len(existing):
        raise Conflict(
            "This logon name is already in use.",
            code="sam_account_name_taken",
            context={"sam_account_name": sam},
        )


# ---------------------------------------------------------------------------
# Updating
# ---------------------------------------------------------------------------


def update_user(
    conn: DirectoryConnection,
    dn: str,
    *,
    attributes: dict[str, Any] | None = None,
    flags: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Apply attribute and account-option changes. Returns the applied diff."""
    applied: dict[str, Any] = {}

    if attributes:
        changes: dict[str, Any] = {}
        for field, value in attributes.items():
            attribute = USER_FIELDS.get(field)
            if attribute is None:
                raise InvalidRequest(
                    f"Unknown field '{field}'.",
                    code="unknown_field",
                    context={"field": field},
                )
            changes[attribute] = value
        applied.update(conn.modify_attributes(dn, changes))

    if flags:
        entry = conn.get(dn, attrs=["userAccountControl"])
        if entry is None:
            raise NotFound("The user does not exist.", context={"dn": dn})
        current = values.as_int(entry, "userAccountControl", 0) or 0
        updated = uac.apply(current, flags)
        if updated != current:
            _set_uac(conn, dn, updated)
            applied["userAccountControl"] = {"old": current, "new": updated}

    return applied


def _set_uac(conn: DirectoryConnection, dn: str, value: int) -> None:
    import ldb

    message = ldb.Message()
    message.dn = ldb.Dn(conn.samdb, dn)
    message["userAccountControl"] = ldb.MessageElement(
        str(value), ldb.FLAG_MOD_REPLACE, "userAccountControl"
    )
    conn.modify(message)


def set_enabled(conn: DirectoryConnection, dn: str, enabled: bool) -> dict[str, Any]:
    return update_user(conn, dn, flags={"account_disabled": not enabled})


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------


def set_password(
    conn: DirectoryConnection,
    dn: str,
    password: str,
    *,
    must_change: bool = False,
) -> None:
    """Administrative password reset.

    Uses the same LDIF form samba-tool does. It requires an encrypted
    connection, which is guaranteed here because SAMADCON only ever connects
    over LDAPS.
    """
    import base64

    if not password:
        raise InvalidRequest("The password is empty.", code="empty_password")

    # unicodePwd is UTF-16LE and must be wrapped in double quotes.
    encoded = base64.b64encode(f'"{password}"'.encode("utf-16-le")).decode("ascii")
    ldif = (
        f"dn: {dn}\n"
        "changetype: modify\n"
        "replace: unicodePwd\n"
        f"unicodePwd:: {encoded}\n"
    )

    try:
        conn.samdb.modify_ldif(ldif)
    except Exception as exc:
        from samadcon.core.errors import translate

        raise translate(exc) from exc

    set_must_change_password(conn, dn, must_change)


def set_must_change_password(conn: DirectoryConnection, dn: str, must_change: bool) -> None:
    """Toggle "user must change password at next logon".

    ``pwdLastSet = 0`` forces a change; ``-1`` tells the DC to stamp the
    current time. Any other value is rejected by AD.
    """
    import ldb

    message = ldb.Message()
    message.dn = ldb.Dn(conn.samdb, dn)
    message["pwdLastSet"] = ldb.MessageElement(
        "0" if must_change else "-1", ldb.FLAG_MOD_REPLACE, "pwdLastSet"
    )
    conn.modify(message)


def unlock_account(conn: DirectoryConnection, dn: str) -> None:
    """Clear a lockout.

    ``lockoutTime = 0`` is the documented way; the LOCKOUT bit in
    userAccountControl is not writable and clears itself.
    """
    import ldb

    message = ldb.Message()
    message.dn = ldb.Dn(conn.samdb, dn)
    message["lockoutTime"] = ldb.MessageElement("0", ldb.FLAG_MOD_REPLACE, "lockoutTime")
    conn.modify(message)


def set_account_expiry(
    conn: DirectoryConnection, dn: str, expires_at: datetime | None
) -> dict[str, Any]:
    """Set or clear the account expiry date.

    ``None`` means "never", which AD stores as 0 rather than the usual
    0x7FFFFFFFFFFFFFFF sentinel — both work on read, only 0 is idiomatic here.
    """
    import ldb

    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)

    raw = "0" if expires_at is None else str(values.datetime_to_filetime(expires_at))

    message = ldb.Message()
    message.dn = ldb.Dn(conn.samdb, dn)
    message["accountExpires"] = ldb.MessageElement(raw, ldb.FLAG_MOD_REPLACE, "accountExpires")
    conn.modify(message)
    return {"accountExpires": {"new": expires_at.isoformat() if expires_at else None}}


# ---------------------------------------------------------------------------
# Lockout evaluation
# ---------------------------------------------------------------------------


def is_locked_out(entry: Any, lockout_duration_seconds: float | None) -> bool:
    """Whether an account is currently locked.

    ``lockoutTime`` alone is not enough: the DC leaves the timestamp in place
    after the lockout window passes and simply stops enforcing it.
    """
    locked_at = values.as_filetime(entry, "lockoutTime")
    if locked_at is None:
        return False
    if lockout_duration_seconds is None:
        # Duration 0 in the policy means "until an administrator unlocks".
        return True
    elapsed = (datetime.now(UTC) - locked_at).total_seconds()
    return elapsed < lockout_duration_seconds


def list_locked_accounts(conn: DirectoryConnection) -> list[dict[str, Any]]:
    result = conn.search(
        conn.info.base_dn,
        scope=SCOPE_SUBTREE,
        expression="(&(objectCategory=person)(objectClass=user)(lockoutTime>=1))",
        attrs=["distinguishedName", "sAMAccountName", "displayName", "name", "objectClass",
               "lockoutTime", "objectGUID"],
    )
    accounts = []
    for entry in result:
        item = summarize(entry)
        item["locked_since"] = values.as_filetime(entry, "lockoutTime")
        accounts.append(item)
    return accounts
