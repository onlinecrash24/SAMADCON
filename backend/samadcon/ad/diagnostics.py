"""Read-only health and policy view of the domain.

What an administrator normally reaches for `samba-tool fsmo show`,
`samba-tool drs showrepl` and `samba-tool domain passwordsettings show` to
find out. Everything here is read through LDAP on the signed-in
administrator's connection — no DRSUAPI, no RPC — so it works through the same
port the rest of SAMADCON uses and shows exactly what that account is allowed to
see.

One consequence of the LDAP route is worth knowing: replication metadata is
read from the ``repsFrom`` attribute of each naming context **on the DC we are
connected to**. It therefore describes that DC's view — which is the useful
one when diagnosing "this DC is behind", and not a forest-wide summary.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from samadcon.ad import sites, uac, values
from samadcon.ad.connection import SCOPE_ONELEVEL, SCOPE_SUBTREE, DirectoryConnection
from samadcon.core.errors import NotFound

logger = logging.getLogger(__name__)

# msDS-Behavior-Version values (MS-ADTS 6.1.4.2/6.1.4.3).
FUNCTIONAL_LEVELS: dict[int, str] = {
    0: "Windows 2000",
    1: "Windows Server 2003 interim",
    2: "Windows Server 2003",
    3: "Windows Server 2008",
    4: "Windows Server 2008 R2",
    5: "Windows Server 2012",
    6: "Windows Server 2012 R2",
    7: "Windows Server 2016",
    8: "Windows Server 2025",
}

# pwdProperties bits (MS-ADTS 2.2.16).
DOMAIN_PASSWORD_COMPLEX = 0x00000001
DOMAIN_PASSWORD_NO_ANON_CHANGE = 0x00000002
DOMAIN_PASSWORD_NO_CLEAR_CHANGE = 0x00000004
DOMAIN_LOCKOUT_ADMINS = 0x00000008
DOMAIN_PASSWORD_STORE_CLEARTEXT = 0x00000010
DOMAIN_REFUSE_PASSWORD_CHANGE = 0x00000020


def level_name(value: int | None) -> str | None:
    if value is None:
        return None
    return FUNCTIONAL_LEVELS.get(value, f"Unknown ({value})")


# ---------------------------------------------------------------------------
# FSMO roles
# ---------------------------------------------------------------------------


def fsmo_roles(conn: DirectoryConnection) -> list[dict[str, Any]]:
    """The five FSMO roles plus the two DNS ones, and who holds them.

    Each is recorded as ``fSMORoleOwner`` on a different object, and the value
    points at an NTDS Settings object rather than at anything an administrator
    would recognise — the server two levels above it is the answer to
    "who holds this role".
    """
    base = conn.info.base_dn
    forest = conn.info.root_domain_dn or base

    definitions = [
        ("schema", "Schema Master", conn.info.schema_dn, "forest"),
        ("domain_naming", "Domain Naming Master", f"CN=Partitions,{conn.info.config_dn}", "forest"),
        ("pdc", "PDC Emulator", base, "domain"),
        ("rid", "RID Master", f"CN=RID Manager$,CN=System,{base}", "domain"),
        ("infrastructure", "Infrastructure Master", f"CN=Infrastructure,{base}", "domain"),
        # The two DNS application partitions have their own infrastructure
        # role. They are missing on domains provisioned without them, which is
        # not a fault — hence the tolerant lookup below.
        (
            "domain_dns",
            "DomainDnsZones Infrastructure",
            f"CN=Infrastructure,DC=DomainDnsZones,{base}",
            "domain",
        ),
        (
            "forest_dns",
            "ForestDnsZones Infrastructure",
            f"CN=Infrastructure,DC=ForestDnsZones,{forest}",
            "forest",
        ),
    ]

    roles = []
    for key, label, dn, scope in definitions:
        owner_dn = _role_owner(conn, dn)
        roles.append(
            {
                "role": key,
                "label": label,
                "scope": scope,
                "object_dn": dn,
                "owner_dn": owner_dn,
                "owner": _server_of_ntds(owner_dn),
                "site": _site_of_ntds(owner_dn),
                "present": owner_dn is not None,
            }
        )
    return roles


def _role_owner(conn: DirectoryConnection, dn: str) -> str | None:
    try:
        entry = conn.get(dn, attrs=["fSMORoleOwner"])
    except NotFound:
        return None
    if entry is None:
        return None
    return values.as_str(entry, "fSMORoleOwner")


def _server_of_ntds(ntds_dn: str | None) -> str | None:
    """``CN=NTDS Settings,CN=DC1,CN=Servers,CN=Site,…`` -> ``DC1``."""
    if not ntds_dn:
        return None
    server = values.parent_dn(ntds_dn)
    return values.name_from_dn(server) if server else None


def _site_of_ntds(ntds_dn: str | None) -> str | None:
    if not ntds_dn:
        return None
    server = values.parent_dn(ntds_dn)
    site = sites.site_of_server(server) if server else None
    return values.name_from_dn(site) if site else None


# ---------------------------------------------------------------------------
# Domain controllers
# ---------------------------------------------------------------------------


def domain_controllers(conn: DirectoryConnection) -> list[dict[str, Any]]:
    """Every DC in the forest, with its site, roles and operating system.

    Built from the server objects under ``CN=Sites`` — the authoritative list —
    and enriched from the matching computer account, which is where the
    operating system version lives.
    """
    role_owner_names: dict[str, list[str]] = {}
    for role in fsmo_roles(conn):
        if role["owner"]:
            role_owner_names.setdefault(role["owner"].lower(), []).append(role["label"])

    controllers = []
    for site in sites.list_sites(conn):
        for server in sites.list_servers(conn, site["dn"]):
            if not server["is_dc"]:
                continue
            controllers.append(
                {
                    **server,
                    "site": site["name"],
                    "site_dn": site["dn"],
                    "roles": role_owner_names.get(server["name"].lower(), []),
                    **_computer_facts(conn, server["computer_dn"]),
                }
            )

    controllers.sort(key=lambda dc: (dc["site"].lower(), dc["name"].lower()))
    return controllers


def _computer_facts(conn: DirectoryConnection, computer_dn: str | None) -> dict[str, Any]:
    if not computer_dn:
        return {"operating_system": None, "last_logon": None}
    entry = conn.get(
        computer_dn,
        attrs=["operatingSystem", "operatingSystemVersion", "lastLogonTimestamp", "whenCreated"],
    )
    if entry is None:
        return {"operating_system": None, "last_logon": None}

    system = values.as_str(entry, "operatingSystem")
    version = values.as_str(entry, "operatingSystemVersion")
    return {
        "operating_system": " ".join(part for part in (system, version) if part) or None,
        "last_logon": values.as_filetime(entry, "lastLogonTimestamp"),
    }


# ---------------------------------------------------------------------------
# Replication
# ---------------------------------------------------------------------------


def replication(conn: DirectoryConnection) -> dict[str, Any]:
    """Inbound replication status of the DC we are connected to.

    ``repsFrom`` holds one blob per source DC and naming context, carrying the
    last attempt, the last success and the result of the last attempt. A DC
    that is failing to replicate shows it here as a non-zero result together
    with a success time that stops advancing.
    """
    partitions = _naming_contexts(conn)
    neighbours: list[dict[str, Any]] = []
    unreadable: list[str] = []

    for label, dn in partitions:
        entry = conn.get(dn, attrs=["repsFrom"])
        if entry is None:
            continue
        raw_values = entry.get("repsFrom")
        if not raw_values:
            continue
        for raw in raw_values:
            decoded = _decode_reps(bytes(raw))
            if decoded is None:
                unreadable.append(label)
                continue
            neighbours.append({"partition": label, "partition_dn": dn, **decoded})

    failing = [item for item in neighbours if item["result"] not in (0, None)]
    return {
        "dc": conn.info.dc_hostname,
        "neighbours": neighbours,
        "failing": len(failing),
        "healthy": not failing,
        "unreadable_partitions": sorted(set(unreadable)),
    }


def _naming_contexts(conn: DirectoryConnection) -> list[tuple[str, str]]:
    base = conn.info.base_dn
    forest = conn.info.root_domain_dn or base
    contexts = [
        ("Domain", base),
        ("Configuration", conn.info.config_dn),
        ("Schema", conn.info.schema_dn),
        ("DomainDnsZones", f"DC=DomainDnsZones,{base}"),
        ("ForestDnsZones", f"DC=ForestDnsZones,{forest}"),
    ]
    return [(label, dn) for label, dn in contexts if conn.exists(dn)]


def _decode_reps(raw: bytes) -> dict[str, Any] | None:
    """Unpack one ``repsFrom`` value.

    The blob is versioned; ``ctr1`` is what every current DC writes. Anything
    else is reported as unreadable rather than guessed at — a wrong reading of
    a replication failure is worse than none.
    """
    try:
        from samba.dcerpc import drsblobs
        from samba.ndr import ndr_unpack

        blob = ndr_unpack(drsblobs.repsFromToBlob, raw)
        # The union is switched on the version, and the binding hands back the
        # selected arm directly rather than a ctr1/ctr2 member.
        ctr = blob.ctr
        return {
            "source_dsa": _source_name(blob),
            "source_guid": str(ctr.source_dsa_obj_guid),
            "last_attempt": _drs_time(getattr(ctr, "last_attempt", None)),
            "last_success": _drs_time(getattr(ctr, "last_success", None)),
            "result": _werror(getattr(ctr, "result_last_attempt", 0)),
            "consecutive_failures": int(getattr(ctr, "consecutive_sync_failures", 0)),
        }
    except Exception:
        logger.warning("cannot decode a repsFrom value", exc_info=True)
        return None


def _source_name(blob: Any) -> str | None:
    """The partner's DNS name, which moved between the two blob versions."""
    other = getattr(blob.ctr, "other_info", None)
    if other is None:
        return None
    if int(blob.version) == 1:
        return getattr(other, "dns_name", None)
    return getattr(other, "dns_name1", None) or getattr(other, "dns_name2", None)


def _werror(value: Any) -> int | None:
    """A WERROR, as an integer.

    0 means the last attempt succeeded, which is what the healthy/failing
    split turns on — so an unreadable value becomes None rather than 0, to
    avoid reporting a failure as success.
    """
    if isinstance(value, int):
        return value
    for attribute in ("value", "v"):
        inner = getattr(value, attribute, None)
        if isinstance(inner, int):
            return inner
    return None


def _drs_time(ticks: int | None) -> datetime | None:
    """Written as 0 when the event never happened.

    The IDL declares these as ``NTTIME_1sec``, stored with one-second
    resolution — but the binding multiplies them back up on unpacking, so what
    arrives here is an ordinary FILETIME.
    """
    if not ticks:
        return None
    return values.filetime_to_datetime(int(ticks))


# ---------------------------------------------------------------------------
# Password and lockout policy
# ---------------------------------------------------------------------------


def password_policy(conn: DirectoryConnection) -> dict[str, Any]:
    """The domain's password and lockout policy, plus any PSOs."""
    entry = conn.get(
        conn.info.base_dn,
        attrs=[
            "minPwdLength",
            "minPwdAge",
            "maxPwdAge",
            "pwdHistoryLength",
            "pwdProperties",
            "lockoutThreshold",
            "lockoutDuration",
            "lockOutObservationWindow",
            "msDS-Behavior-Version",
        ],
    )
    if entry is None:
        raise NotFound("The domain object could not be read.", code="domain_not_found")

    properties = values.as_int(entry, "pwdProperties", 0) or 0
    return {
        "min_length": values.as_int(entry, "minPwdLength", 0),
        "history_length": values.as_int(entry, "pwdHistoryLength", 0),
        "min_age_days": _days(entry, "minPwdAge"),
        "max_age_days": _days(entry, "maxPwdAge"),
        "complexity": bool(properties & DOMAIN_PASSWORD_COMPLEX),
        "reversible_encryption": bool(properties & DOMAIN_PASSWORD_STORE_CLEARTEXT),
        "lockout_threshold": values.as_int(entry, "lockoutThreshold", 0),
        "lockout_duration_minutes": _minutes(entry, "lockoutDuration"),
        "lockout_window_minutes": _minutes(entry, "lockOutObservationWindow"),
        "password_settings_objects": password_settings_objects(conn),
    }


def _days(entry: Any, attr: str) -> float | None:
    delta = values.interval_to_timedelta(values.as_int(entry, attr))
    return round(delta.total_seconds() / 86400, 2) if delta else None


def _minutes(entry: Any, attr: str) -> int | None:
    delta = values.interval_to_timedelta(values.as_int(entry, attr))
    return round(delta.total_seconds() / 60) if delta else None


def password_settings_objects(conn: DirectoryConnection) -> list[dict[str, Any]]:
    """Fine-grained password policies, in the order they take effect.

    Precedence decides which one wins for a user in several groups: the lowest
    number applies. Sorting by it here means the list reads the same way the
    DC evaluates it.
    """
    container = f"CN=Password Settings Container,CN=System,{conn.info.base_dn}"
    try:
        result = conn.search(
            container,
            scope=SCOPE_ONELEVEL,
            expression="(objectClass=msDS-PasswordSettings)",
            attrs=[
                "distinguishedName",
                "name",
                "msDS-PasswordSettingsPrecedence",
                "msDS-MinimumPasswordLength",
                "msDS-PasswordHistoryLength",
                "msDS-PasswordComplexityEnabled",
                "msDS-MinimumPasswordAge",
                "msDS-MaximumPasswordAge",
                "msDS-LockoutThreshold",
                "msDS-LockoutDuration",
                "msDS-LockoutObservationWindow",
                "msDS-PSOAppliesTo",
            ],
        )
    except NotFound:
        return []

    policies = []
    for entry in result:
        applies_to = values.as_list(entry, "msDS-PSOAppliesTo")
        policies.append(
            {
                "dn": values.as_str(entry, "distinguishedName") or str(entry.dn),
                "name": values.as_str(entry, "name") or "",
                "precedence": values.as_int(entry, "msDS-PasswordSettingsPrecedence"),
                "min_length": values.as_int(entry, "msDS-MinimumPasswordLength"),
                "history_length": values.as_int(entry, "msDS-PasswordHistoryLength"),
                "complexity": values.as_bool(entry, "msDS-PasswordComplexityEnabled"),
                "min_age_days": _days(entry, "msDS-MinimumPasswordAge"),
                "max_age_days": _days(entry, "msDS-MaximumPasswordAge"),
                "lockout_threshold": values.as_int(entry, "msDS-LockoutThreshold"),
                "lockout_duration_minutes": _minutes(entry, "msDS-LockoutDuration"),
                "lockout_window_minutes": _minutes(entry, "msDS-LockoutObservationWindow"),
                "applies_to": [values.name_from_dn(dn) for dn in applies_to],
                "applies_to_dns": applies_to,
            }
        )

    policies.sort(key=lambda pso: (pso["precedence"] is None, pso["precedence"], pso["name"]))
    return policies


# ---------------------------------------------------------------------------
# Accounts that need attention
# ---------------------------------------------------------------------------

ACCOUNT_ATTRS = [
    "distinguishedName",
    "sAMAccountName",
    "displayName",
    "userAccountControl",
    "lockoutTime",
    "accountExpires",
    "pwdLastSet",
    "lastLogonTimestamp",
]


def account_problems(conn: DirectoryConnection, *, limit: int = 200) -> dict[str, Any]:
    """Locked out, disabled and expired user accounts.

    Deliberately one search rather than three: the filter is wide enough to
    catch all of them at once, and the classification then happens here, where
    the lockout duration is available to tell a still-locked account from one
    whose lockout has already run out.
    """
    policy_entry = conn.get(conn.info.base_dn, attrs=["lockoutDuration"])
    lockout = values.interval_to_timedelta(values.as_int(policy_entry, "lockoutDuration"))
    now = datetime.now(UTC)

    expression = (
        "(&(objectClass=user)(objectCategory=person)"
        "(|(lockoutTime>=1)"
        f"(userAccountControl:1.2.840.113556.1.4.803:={uac.ACCOUNTDISABLE})"
        "(&(accountExpires>=1)(!(accountExpires=9223372036854775807)))))"
    )

    result = conn.search(
        conn.info.base_dn,
        scope=SCOPE_SUBTREE,
        expression=expression,
        attrs=ACCOUNT_ATTRS,
        max_results=limit,
    )

    locked: list[dict[str, Any]] = []
    disabled: list[dict[str, Any]] = []
    expired: list[dict[str, Any]] = []

    for entry in result:
        account = _account_summary(entry)
        flags = values.as_int(entry, "userAccountControl", 0) or 0

        if account["lockout_time"] is not None and _still_locked(
            account["lockout_time"], lockout, now
        ):
            locked.append(account)
        if flags & uac.ACCOUNTDISABLE:
            disabled.append(account)
        if account["expires"] is not None and account["expires"] < now:
            expired.append(account)

    return {
        "locked": locked,
        "disabled": disabled,
        "expired": expired,
        "truncated": result.truncated,
        "lockout_duration_minutes": round(lockout.total_seconds() / 60) if lockout else None,
    }


def _still_locked(
    lockout_time: datetime, duration: Any, now: datetime
) -> bool:
    """Whether a lockout is still in force.

    ``lockoutTime`` is not cleared when the lockout expires — it stays until
    the next successful logon. Listing every account that was ever locked as
    "locked" would make the view useless within a week.
    """
    if duration is None:
        # A lockout that never expires by itself: only an administrator clears it.
        return True
    return now < lockout_time + duration


def _account_summary(entry: Any) -> dict[str, Any]:
    return {
        "dn": values.as_str(entry, "distinguishedName") or str(entry.dn),
        "name": values.as_str(entry, "sAMAccountName") or "",
        "display_name": values.as_str(entry, "displayName"),
        "lockout_time": values.as_filetime(entry, "lockoutTime"),
        "expires": values.as_filetime(entry, "accountExpires"),
        "password_last_set": values.as_filetime(entry, "pwdLastSet"),
        "last_logon": values.as_filetime(entry, "lastLogonTimestamp"),
        "must_change_password": values.as_int(entry, "pwdLastSet", -1) == 0,
    }


# ---------------------------------------------------------------------------
# Everything at once
# ---------------------------------------------------------------------------


def overview(conn: DirectoryConnection) -> dict[str, Any]:
    """The diagnosis page in one call."""
    return {
        "domain": {
            "dns_domain": conn.info.dns_domain,
            "netbios_name": conn.info.netbios_name,
            "base_dn": conn.info.base_dn,
            "domain_sid": conn.info.domain_sid,
            "connected_dc": conn.info.dc_hostname,
            "domain_level": conn.info.domain_functional_level,
            "domain_level_name": level_name(conn.info.domain_functional_level),
            "forest_level": conn.info.forest_functional_level,
            "forest_level_name": level_name(conn.info.forest_functional_level),
            "is_forest_root": (conn.info.root_domain_dn or conn.info.base_dn).lower()
            == conn.info.base_dn.lower(),
        },
        "roles": fsmo_roles(conn),
        "controllers": domain_controllers(conn),
        "replication": replication(conn),
        "policy": password_policy(conn),
    }
