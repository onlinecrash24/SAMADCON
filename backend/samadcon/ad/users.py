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
import re
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

# The "Other…" lists beside the single-valued ones: ADUC keeps a second
# telephone number, a second web page and so on in these, and shows them in a
# small list dialog. Multi-valued in the directory, so they are read as lists
# and written as lists — a string sent to one of these is one value, and a list
# sent to a single-valued field above is refused.
USER_MULTI_FIELDS: dict[str, str] = {
    "other_telephone": "otherTelephone",
    "other_home_phone": "otherHomePhone",
    "other_pager": "otherPager",
    "other_mobile": "otherMobile",
    "other_fax": "otherFacsimileTelephoneNumber",
    "other_ip_phone": "otherIpPhone",
    "other_web_page": "url",
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
    "otherTelephone",
    "otherHomePhone",
    "otherPager",
    "otherMobile",
    "otherFacsimileTelephoneNumber",
    "otherIpPhone",
    "url",
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


def primary_group_dn(conn: DirectoryConnection, entry: Any) -> str | None:
    """The primary group as a DN, from the RID in primaryGroupID.

    The RID is only meaningful together with the account's own domain SID —
    the group is the object whose SID is that domain with this RID on the end.
    One indexed search; None when either half is missing or nothing matches,
    which the sheet shows as a dash rather than as a number nobody can read.
    """
    return group_dn_by_rid(conn, entry, values.as_int(entry, "primaryGroupID"))


def group_dn_by_rid(conn: DirectoryConnection, entry: Any, rid: int | None) -> str | None:
    """The group in *entry*'s own domain whose RID is *rid*, as a DN.

    By SID and not by name: Domain Users is "Domänen-Benutzer" on a German
    domain, and any group can be renamed.
    """
    account_sid = values.sid_to_str(values.as_bytes(entry, "objectSid"))
    if rid is None or not account_sid:
        return None
    domain_sid = account_sid.rsplit("-", 1)[0]
    result = conn.search(
        conn.info.base_dn,
        scope=SCOPE_SUBTREE,
        expression=f"(objectSid={values.escape_filter(f'{domain_sid}-{rid}')})",
        attrs=["distinguishedName"],
        max_results=1,
    )
    if not len(result):
        return None
    return values.as_str(result.entries[0], "distinguishedName")


def _render_user(conn: DirectoryConnection, entry: Any) -> dict[str, Any]:
    dn = values.as_str(entry, "distinguishedName") or str(entry.dn)
    uac_value = values.as_int(entry, "userAccountControl", 0) or 0

    attributes: dict[str, Any] = {
        field: values.as_str(entry, attribute) for field, attribute in USER_FIELDS.items()
    }
    for field, attribute in USER_MULTI_FIELDS.items():
        attributes[field] = values.as_list(entry, attribute)

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
            # Present is not the same as in force: the DC keeps the stamp after
            # the window has passed. Only read the policy when there is a stamp.
            "locked_out": lockout_time is not None
            and is_locked_out(entry, lockout_duration_seconds(conn)),
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
        "primary_group_dn": primary_group_dn(conn, entry),
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
    raw_attributes: dict[str, bytes | str] | None = None,
) -> dict[str, Any]:
    """Create a user account.

    *raw_attributes* are written as given, at creation — for values a copy
    carries over that have no field of their own, such as logon hours.
    """
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
            context={"limit": 20},
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
    for attribute, raw in (raw_attributes or {}).items():
        message[attribute] = ldb.MessageElement(raw, ldb.FLAG_MOD_ADD, attribute)

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
# Copying from a template account
# ---------------------------------------------------------------------------

# What "Copy…" carries over, as ADUC does: where the person sits and what they
# are given, not who they are. Description, office, telephone, mail, title and
# street stay behind.
COPIED_FIELDS = (
    "post_office_box",
    "city",
    "state",
    "postal_code",
    "country",
    "profile_path",
    "logon_script",
    "home_directory",
    "home_drive",
    "department",
    "company",
    "manager",
    "logon_workstations",
)
#: Paths that usually end in the account's own name, and follow the new one.
PER_ACCOUNT_PATHS = ("profile_path", "home_directory")
DOMAIN_USERS_RID = 513
#: accountExpires values that both mean "never".
NEVER_EXPIRES = (0, 0x7FFFFFFFFFFFFFFF)


def follow_name(path: str, template_sam: str | None, new_sam: str) -> str:
    r"""*path* with every segment that is the template's logon name replaced by
    the new one: ``\\srv\home\_Vorlage_Vertrieb`` becomes ``\\srv\home\mmuster``.

    Whole segments only, compared without regard to case, so a template named
    "vt" does not rewrite ``\\srv\vthome``.
    """
    if not template_sam:
        return path
    wanted = template_sam.lower()
    return re.sub(
        r"[^\\/]+",
        lambda segment: new_sam if segment.group(0).lower() == wanted else segment.group(0),
        path,
    )


def _template_groups(conn: DirectoryConnection, template: Any) -> list[dict[str, Any]]:
    """The groups a copy of *template* is offered.

    Its memberships, and its primary group when that is not Domain Users —
    less Domain Users itself. Every new account starts with Domain Users as
    its primary group, and the directory refuses it as a member of that
    group a second time. When the copy's primary group is then switched to
    the template's, the DC turns Domain Users into an ordinary membership on
    its own, as it did for the template. Offering it anyway made a copy report
    a failure for a group it ended up in (found on a Samba 4.22 DC).
    """
    domain_users = (group_dn_by_rid(conn, template, DOMAIN_USERS_RID) or "").lower()
    groups = [
        {"dn": dn, "primary": False}
        for dn in values.as_list(template, "memberOf")
        if dn.lower() != domain_users
    ]
    if values.as_int(template, "primaryGroupID") not in (None, DOMAIN_USERS_RID):
        primary = primary_group_dn(conn, template)
        if primary and primary.lower() != domain_users:
            groups.append({"dn": primary, "primary": True})
    return groups


def copy_template_groups(conn: DirectoryConnection, template_dn: str) -> list[dict[str, Any]]:
    """What the copy dialog lists: the groups :func:`copy_user` would give."""
    template = conn.get(
        template_dn, attrs=["objectClass", "objectSid", "memberOf", "primaryGroupID"]
    )
    if template is None:
        raise NotFound("The template account does not exist.", context={"dn": template_dn})
    _require_user_template(template)
    return _template_groups(conn, template)


def _require_user_template(template: Any) -> None:
    classes = {c.lower() for c in values.as_list(template, "objectClass")}
    if "user" not in classes or "computer" in classes:
        raise InvalidRequest("Only a user account can be copied.", code="not_a_user_template")


def copy_user(
    conn: DirectoryConnection,
    template_dn: str,
    *,
    sam_account_name: str,
    common_name: str | None = None,
    parent_dn: str | None = None,
    attributes: dict[str, Any] | None = None,
    password: str | None = None,
    generate_password: bool = False,
    must_change_password: bool = True,
    enabled: bool = True,
    groups: list[str] | None = None,
) -> dict[str, Any]:
    """Create an account from a template account — ADUC's "Copy…".

    The account is created first, with everything that can be written at
    creation, and rolled back if that fails. Group memberships follow one
    group at a time: the account exists by then and is usable, so a group the
    caller may not write to is reported in ``failed_groups`` rather than
    undoing the account.

    *groups* narrows the template's groups; ``None`` takes all of them. A
    generated password is returned once, here, and nowhere else.
    """
    from samadcon.ad import groups as group_ops
    from samadcon.ad import passwords
    from samadcon.core.errors import SamadconError

    if password and generate_password:
        raise InvalidRequest(
            "Give a password or have one generated, not both.", code="password_conflict"
        )

    template = conn.get(
        template_dn,
        attrs=[
            *(USER_FIELDS[field] for field in COPIED_FIELDS),
            "objectClass",
            "objectSid",
            "sAMAccountName",
            "userAccountControl",
            "memberOf",
            "primaryGroupID",
            "logonHours",
            "accountExpires",
        ],
    )
    if template is None:
        raise NotFound("The template account does not exist.", context={"dn": template_dn})
    _require_user_template(template)

    sam = sam_account_name.strip()
    template_sam = values.as_str(template, "sAMAccountName")

    fields: dict[str, Any] = {}
    for field in COPIED_FIELDS:
        value = values.as_str(template, USER_FIELDS[field])
        if not value:
            continue
        fields[field] = (
            follow_name(value, template_sam, sam) if field in PER_ACCOUNT_PATHS else value
        )
    fields.update(attributes or {})

    template_uac = values.as_int(template, "userAccountControl", 0) or 0
    flags = {
        name: True
        for name, bit in uac.EDITABLE_FLAGS.items()
        if name != "account_disabled" and template_uac & bit
    }

    raw: dict[str, bytes | str] = {}
    logon_hours = values.as_bytes(template, "logonHours")
    if logon_hours:
        raw["logonHours"] = logon_hours
    expires = values.as_int(template, "accountExpires")
    if expires is not None and expires not in NEVER_EXPIRES:
        raw["accountExpires"] = str(expires)

    template_groups = _template_groups(conn, template)
    offered = [group["dn"] for group in template_groups]
    primary = next((group["dn"] for group in template_groups if group["primary"]), None)
    by_name = {group.lower(): group for group in offered}
    if groups is None:
        chosen = offered
    else:
        strangers = [group for group in groups if group.lower() not in by_name]
        if strangers:
            raise InvalidRequest(
                "Only the template's own groups can be chosen.",
                code="group_not_in_template",
                context={"groups": strangers},
            )
        chosen = [by_name[group.lower()] for group in groups]

    new_password = password
    if generate_password:
        names = [
            sam,
            common_name,
            *(fields.get(key) for key in ("first_name", "last_name", "display_name")),
        ]
        new_password = passwords.for_domain(conn, avoid=names)

    created = create_user(
        conn,
        parent_dn=parent_dn or values.parent_dn(template_dn) or "",
        sam_account_name=sam,
        common_name=common_name,
        password=new_password,
        must_change_password=must_change_password,
        enabled=enabled,
        attributes=fields,
        flags=flags,
        raw_attributes=raw,
    )
    new_dn = created["dn"]

    added: list[str] = []
    failed: list[dict[str, Any]] = []
    for group in chosen:
        try:
            group_ops.add_members(conn, group, [new_dn])
            added.append(group)
        except SamadconError as exc:
            failed.append({"dn": group, "code": exc.code, "message": str(exc)})

    if primary and primary in added:
        try:
            set_primary_group(conn, new_dn, primary)
        except SamadconError as exc:
            failed.append({"dn": primary, "code": exc.code, "message": str(exc), "primary": True})

    return {
        "user": get_user(conn, new_dn),
        "template": template_dn,
        "groups_added": added,
        "failed_groups": failed,
        "generated_password": new_password if generate_password else None,
    }


# ---------------------------------------------------------------------------
# Updating
# ---------------------------------------------------------------------------


def update_user(
    conn: DirectoryConnection,
    dn: str,
    *,
    attributes: dict[str, Any] | None = None,
    flags: dict[str, bool] | None = None,
    confirm_admin: bool = False,
) -> dict[str, Any]:
    """Apply attribute and account-option changes. Returns the applied diff.

    Disabling an account that administers the domain needs ``confirm_admin``;
    see :func:`administrative_role`. The check comes before anything is
    written, so a refusal does not leave the other fields of the same request
    already saved.
    """
    if flags and flags.get("account_disabled") and not confirm_admin:
        _refuse_to_disable_an_administrator(conn, dn)

    applied: dict[str, Any] = {}

    if attributes:
        changes: dict[str, Any] = {}
        for field, value in attributes.items():
            attribute = USER_FIELDS.get(field) or USER_MULTI_FIELDS.get(field)
            if attribute is None:
                raise InvalidRequest(
                    f"Unknown field '{field}'.",
                    code="unknown_field",
                    context={"field": field},
                )
            if field in USER_MULTI_FIELDS:
                if value is None:
                    value = []
                elif isinstance(value, str):
                    value = [value]
                if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                    raise InvalidRequest(
                        f"'{field}' takes a list of strings.",
                        code="field_takes_a_list",
                        context={"field": field},
                    )
                value = [v.strip() for v in value if v.strip()]
            elif isinstance(value, list):
                raise InvalidRequest(
                    f"'{field}' takes a single value.",
                    code="field_takes_one_value",
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


def set_enabled(
    conn: DirectoryConnection, dn: str, enabled: bool, *, confirm_admin: bool = False
) -> dict[str, Any]:
    return update_user(
        conn, dn, flags={"account_disabled": not enabled}, confirm_admin=confirm_admin
    )


# ---------------------------------------------------------------------------
# Accounts the domain is administered with
# ---------------------------------------------------------------------------

#: The built-in Administrator, recognised by its RID and not its name: the
#: account can be renamed, and hardening guides tell people to.
BUILTIN_ADMINISTRATOR_RID = 500

#: Groups whose members administer the domain or the forest. RIDs below 1000
#: are reserved for well-known accounts, so a match is one of these — in this
#: domain or, for 518 and 519, in the forest root.
ADMIN_GROUP_RIDS: dict[int, str] = {
    512: "Domain Admins",
    518: "Schema Admins",
    519: "Enterprise Admins",
}

#: The built-in Administrators group. Not domain-relative, so matched by its
#: whole SID: its members hold the domain's administrative rights on every DC
#: without being in Domain Admins, which is exactly the case nothing else here
#: would catch.
BUILTIN_ADMINISTRATORS_SID = "S-1-5-32-544"

#: Which name the question uses when an account is in several — the one an
#: administrator recognises first. Members of Domain Admins are in
#: Administrators too, through nesting; "Domain Admins" is the useful answer.
_ROLE_ORDER = ("Domain Admins", "Enterprise Admins", "Schema Admins", "Administrators")


def administrative_role(conn: DirectoryConnection, dn: str) -> str | None:
    """Why disabling this account would take an administrator from the domain.

    ``"Administrator"`` for the built-in account, the name of an admin group
    the account belongs to — Domain, Enterprise or Schema Admins, or the
    built-in Administrators — or None. Membership is read from ``tokenGroups``,
    which the DC computes with nesting resolved: an account in a group that
    is itself in Domain Admins counts here exactly as it does at sign-in.

    Disabling one is allowed — it is sometimes what hardening asks for — but
    not by a single click. The one account left that could sign in may be
    this one, and SAMADCON signs in with the administrator's own account.
    """
    entry = conn.get(dn, attrs=["objectSid", "tokenGroups"])
    if entry is None:
        return None
    sid = values.sid_to_str(values.as_bytes(entry, "objectSid"))
    if values.rid_of(sid) == BUILTIN_ADMINISTRATOR_RID:
        return "Administrator"
    roles = set()
    for raw in _binary_values(entry, "tokenGroups"):
        group = values.sid_to_str(raw)
        if group == BUILTIN_ADMINISTRATORS_SID:
            roles.add("Administrators")
        elif group and group.startswith("S-1-5-21-"):
            # Domain-relative only: a builtin SID such as S-1-5-32-545 ends in a
            # number too, and must not be read as a domain RID.
            role = ADMIN_GROUP_RIDS.get(values.rid_of(group) or 0)
            if role:
                roles.add(role)
    return next((role for role in _ROLE_ORDER if role in roles), None)


def account_administrative_role(conn: DirectoryConnection, dn: str) -> str | None:
    """:func:`administrative_role`, for any object — None for what is no account.

    Asked before a dialog opens, where the object can be anything: an OU, a
    group, a contact. tokenGroups is read only for accounts, as delete_object
    does, so nothing else is held up by it.
    """
    entry = conn.get(dn, attrs=["objectClass"])
    if entry is None:
        return None
    classes = {name.lower() for name in values.as_list(entry, "objectClass")}
    return administrative_role(conn, dn) if "user" in classes else None


def _binary_values(message: Any, attr: str) -> list[bytes]:
    """Every value of a binary attribute, by index as :func:`values.first` reads one."""
    try:
        element = message.get(attr)
    except (KeyError, TypeError):
        return []
    if element is None:
        return []
    found = []
    for index in range(len(element)):
        value = element[index]
        found.append(value if isinstance(value, bytes) else bytes(value))
    return found


def _refuse_to_disable_an_administrator(conn: DirectoryConnection, dn: str) -> None:
    entry = conn.get(dn, attrs=["userAccountControl", "sAMAccountName"])
    if entry is None:
        # update_user reports that itself, with the message it always had.
        return
    if uac.is_disabled(values.as_int(entry, "userAccountControl", 0) or 0):
        # Already disabled: nothing is being taken away.
        return
    role = administrative_role(conn, dn)
    if role is None:
        return
    raise Conflict(
        "Disabling this account takes an administrator away from the domain.",
        code="confirm_disable_admin",
        hint=(
            "Confirm it explicitly. If it was the last account that could sign in, "
            "`samba-tool user enable` on a domain controller undoes it."
        ),
        # The logon name, because that is what samba-tool takes; the CN the
        # console shows can differ from it.
        context={"dn": dn, "role": role, "account": values.as_str(entry, "sAMAccountName")},
    )


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

    Written as a message, like every other change in this module. It used to be
    a string of LDIF with the DN interpolated into it, and a DN carrying a line
    break became further LDIF records — the audit log said one thing and the
    directory did another. A message has one DN, whatever that DN contains.

    The DC only accepts ``unicodePwd`` over an encrypted connection. Every
    connection here is one: LDAP with the Kerberos session key and sign-and-seal
    required, or LDAPS.
    """
    import ldb

    if not password:
        raise InvalidRequest("The password is empty.", code="empty_password")

    message = ldb.Message()
    message.dn = ldb.Dn(conn.samdb, dn)
    # unicodePwd is UTF-16LE and wrapped in double quotes; the quotes are part
    # of the value, not LDIF syntax.
    message["unicodePwd"] = ldb.MessageElement(
        f'"{password}"'.encode("utf-16-le"), ldb.FLAG_MOD_REPLACE, "unicodePwd"
    )
    conn.modify(message)

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


def set_primary_group(conn: DirectoryConnection, dn: str, group_dn: str) -> dict[str, Any]:
    """Make *group_dn* the account's primary group.

    The primary group is not a membership entry; it is the group's RID in the
    account's ``primaryGroupID``. The directory insists the account already be
    a member of the group — a rule ADUC surfaces as a greyed-out "Set Primary
    Group" button — so that is checked here and refused with a reason, rather
    than left to the directory's less helpful "constraint violation".

    Only the domain's own groups can be primary: the RID is looked up in the
    account's SID, so a group from another domain has no RID here to write.
    """
    import ldb

    entry = conn.get(dn, attrs=["memberOf", "primaryGroupID", "objectSid"])
    if entry is None:
        raise NotFound("The object does not exist.", context={"dn": dn})
    group = conn.get(group_dn, attrs=["objectSid", "objectClass", "groupType"])
    if group is None:
        raise NotFound("The group does not exist.", context={"dn": group_dn})
    if "group" not in {c.lower() for c in values.as_list(group, "objectClass")}:
        raise InvalidRequest("The primary group must be a group.", code="not_a_group")

    account_sid = values.sid_to_str(values.as_bytes(entry, "objectSid")) or ""
    group_sid = values.sid_to_str(values.as_bytes(group, "objectSid")) or ""
    if account_sid.rsplit("-", 1)[0] != group_sid.rsplit("-", 1)[0]:
        raise InvalidRequest(
            "The primary group must belong to the account's own domain.",
            code="primary_group_foreign_domain",
        )
    rid = values.rid_of(group_sid)
    if rid is None:
        raise InvalidRequest("The group has no usable SID.", code="primary_group_no_rid")

    current = values.as_int(entry, "primaryGroupID")
    if current == rid:
        return {}

    member_of = {g.lower() for g in values.as_list(entry, "memberOf")}
    if group_dn.lower() not in member_of:
        raise InvalidRequest(
            "The account must be a member of the group before it can be its primary group.",
            code="primary_group_not_a_member",
        )

    message = ldb.Message()
    message.dn = ldb.Dn(conn.samdb, dn)
    message["primaryGroupID"] = ldb.MessageElement(str(rid), ldb.FLAG_MOD_REPLACE, "primaryGroupID")
    conn.modify(message)
    return {"primaryGroupID": {"old": current, "new": rid}}


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


def lockout_duration_seconds(conn: DirectoryConnection) -> float | None:
    """How long the domain keeps an account locked; None for "until unlocked".

    The domain's own policy, which is what applies unless a fine-grained
    password policy (a PSO) sets a different duration for the account — that
    is not read here, so under a PSO the state can be off by the difference.
    An unreadable policy counts as "until unlocked": it errs towards showing a
    lock, which is what the console did before it read the policy at all.
    """
    entry = conn.get(conn.info.base_dn, attrs=["lockoutDuration"])
    span = values.interval_to_timedelta(values.as_int(entry, "lockoutDuration"))
    return span.total_seconds() if span else None


def list_locked_accounts(conn: DirectoryConnection) -> list[dict[str, Any]]:
    result = conn.search(
        conn.info.base_dn,
        scope=SCOPE_SUBTREE,
        expression="(&(objectCategory=person)(objectClass=user)(lockoutTime>=1))",
        attrs=["distinguishedName", "sAMAccountName", "displayName", "name", "objectClass",
               "lockoutTime", "objectGUID"],
    )
    # lockoutTime>=1 finds every account that was ever locked and not unlocked
    # since; whether the lock is still in force depends on the policy.
    duration = lockout_duration_seconds(conn)
    accounts = []
    for entry in result:
        if not is_locked_out(entry, duration):
            continue
        item = summarize(entry)
        item["locked_since"] = values.as_filetime(entry, "lockoutTime")
        accounts.append(item)
    return accounts
