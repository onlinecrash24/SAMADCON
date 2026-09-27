"""Which security settings the editor offers, and what shape each one has.

The file itself carries no types: everything in ``GptTmpl.inf`` is text, and
whether ``LockoutDuration`` counts minutes or ``PasswordComplexity`` is a
switch is knowledge that lives here.

**On provenance.** Seven of these keys are read off a file GPMC wrote —
``MinimumPasswordLength``, ``LockoutBadCount``, ``ResetLockoutCount``,
``LockoutDuration``, ``AllowAdministratorLockout``, ``AuditLogonEvents`` and
``SeSystemtimePrivilege``. The rest come from Microsoft's documentation of the
format. That difference matters more than it looks: a wrong key name does not
fail, it produces a setting that is written, displayed, and **applied by
nobody** — the same silent failure as a wrong CSE GUID. The ``gpresult`` check
covers one setting per section for exactly this reason.
"""

from __future__ import annotations

from typing import Any

SYSTEM_ACCESS = "System Access"
KERBEROS = "Kerberos Policy"
EVENT_AUDIT = "Event Audit"
PRIVILEGE_RIGHTS = "Privilege Rights"
GROUP_MEMBERSHIP = "Group Membership"
REGISTRY_VALUES = "Registry Values"
SYSTEM_LOG = "System Log"
SECURITY_LOG = "Security Log"
APPLICATION_LOG = "Application Log"

# How the editor draws a setting.
NUMBER = "number"
SWITCH = "switch"  # 0 or 1
AUDIT = "audit"  # 0 none, 1 success, 2 failure, 3 both
TRUSTEES = "trustees"
# An event log's retention method: 0 overwrite as needed, 1 by days (with
# RetentionDays), 2 do not overwrite. Measured: GPMC wrote 0 for "overwrite
# events as needed"; 1 and 2 follow the same key's documented values.
RETENTION = "retention"
# A REG_DWORD in [Registry Values], written as "4,<value>" — type 4 is
# REG_DWORD. Measured: "force audit policy subcategory settings" enabled is
# SCENoApplyLegacyAuditPolicy=4,1.
REGISTRY_SWITCH = "registry_switch"

#: Measured in the audit reference GPO: this switch makes Windows apply the
#: advanced audit policy and ignore the nine categories of [Event Audit].
FORCE_SUBCATEGORIES = (
    "MACHINE\\System\\CurrentControlSet\\Control\\Lsa\\SCENoApplyLegacyAuditPolicy"
)

# Groups as the Windows editor arranges them, which is not the same as the
# file's sections: password and lockout policy share [System Access].
GROUPS: list[dict[str, Any]] = [
    {"id": "password", "section": SYSTEM_ACCESS},
    {"id": "lockout", "section": SYSTEM_ACCESS},
    {"id": "kerberos", "section": KERBEROS},
    {"id": "audit", "section": EVENT_AUDIT},
    {"id": "rights", "section": PRIVILEGE_RIGHTS},
    {"id": "event_log", "section": SECURITY_LOG},
    {"id": "restricted_groups", "section": GROUP_MEMBERSHIP},
    # Its subcategories live in audit.csv, not here; the one setting of this
    # group that GptTmpl.inf carries is the switch that makes them count.
    {"id": "audit_advanced", "section": REGISTRY_VALUES},
]


def _setting(
    group: str,
    section: str,
    key: str,
    kind: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
    unit: str | None = None,
    setting_id: str | None = None,
) -> dict[str, Any]:
    return {
        # Unique across the catalogue. The key alone is not: the three event
        # logs share theirs, one section each.
        "id": setting_id or key,
        "group": group,
        "section": section,
        "key": key,
        "kind": kind,
        "min": minimum,
        "max": maximum,
        "unit": unit,
    }


SETTINGS: list[dict[str, Any]] = [
    # -- password policy ----------------------------------------------------
    _setting("password", SYSTEM_ACCESS, "PasswordHistorySize", NUMBER, minimum=0, maximum=24),
    _setting("password", SYSTEM_ACCESS, "MaximumPasswordAge", NUMBER, minimum=0, maximum=999,
             unit="days"),
    _setting("password", SYSTEM_ACCESS, "MinimumPasswordAge", NUMBER, minimum=0, maximum=998,
             unit="days"),
    _setting("password", SYSTEM_ACCESS, "MinimumPasswordLength", NUMBER, minimum=0, maximum=256),
    _setting("password", SYSTEM_ACCESS, "PasswordComplexity", SWITCH),
    _setting("password", SYSTEM_ACCESS, "ClearTextPassword", SWITCH),
    # -- account lockout ----------------------------------------------------
    _setting("lockout", SYSTEM_ACCESS, "LockoutBadCount", NUMBER, minimum=0, maximum=999),
    _setting("lockout", SYSTEM_ACCESS, "LockoutDuration", NUMBER, minimum=0, maximum=99999,
             unit="minutes"),
    _setting("lockout", SYSTEM_ACCESS, "ResetLockoutCount", NUMBER, minimum=1, maximum=99999,
             unit="minutes"),
    _setting("lockout", SYSTEM_ACCESS, "AllowAdministratorLockout", SWITCH),
    # -- kerberos -----------------------------------------------------------
    _setting("kerberos", KERBEROS, "MaxTicketAge", NUMBER, minimum=0, maximum=99999,
             unit="hours"),
    _setting("kerberos", KERBEROS, "MaxRenewAge", NUMBER, minimum=0, maximum=99999, unit="days"),
    _setting("kerberos", KERBEROS, "MaxServiceAge", NUMBER, minimum=0, maximum=99999,
             unit="minutes"),
    _setting("kerberos", KERBEROS, "MaxClockSkew", NUMBER, minimum=0, maximum=99999,
             unit="minutes"),
    _setting("kerberos", KERBEROS, "TicketValidateClient", SWITCH),
    # -- audit policy -------------------------------------------------------
    *(
        _setting("audit", EVENT_AUDIT, key, AUDIT)
        for key in (
            "AuditAccountLogon",
            "AuditAccountManage",
            "AuditDSAccess",
            "AuditLogonEvents",
            "AuditObjectAccess",
            "AuditPolicyChange",
            "AuditPrivilegeUse",
            "AuditProcessTracking",
            "AuditSystemEvents",
        )
    ),
    # -- event logs ---------------------------------------------------------
    *(
        setting
        for prefix, section in (
            ("SystemLog", SYSTEM_LOG),
            ("SecurityLog", SECURITY_LOG),
            ("ApplicationLog", APPLICATION_LOG),
        )
        for setting in (
            _setting("event_log", section, "MaximumLogSize", NUMBER, minimum=64,
                     maximum=4194240, unit="kilobytes", setting_id=f"{prefix}.MaximumLogSize"),
            _setting("event_log", section, "AuditLogRetentionPeriod", RETENTION,
                     setting_id=f"{prefix}.AuditLogRetentionPeriod"),
            _setting("event_log", section, "RetentionDays", NUMBER, minimum=1, maximum=365,
                     unit="days", setting_id=f"{prefix}.RetentionDays"),
            _setting("event_log", section, "RestrictGuestAccess", SWITCH,
                     setting_id=f"{prefix}.RestrictGuestAccess"),
        )
    ),
    # -- advanced audit policy ------------------------------------------------
    _setting("audit_advanced", REGISTRY_VALUES, FORCE_SUBCATEGORIES, REGISTRY_SWITCH,
             setting_id="SCENoApplyLegacyAuditPolicy"),
    # -- user rights --------------------------------------------------------
    # The ones an administrator reaches for. Any other Se… name can still be
    # written; this list is what the editor offers, not what it accepts.
    *(
        _setting("rights", PRIVILEGE_RIGHTS, key, TRUSTEES)
        for key in (
            "SeInteractiveLogonRight",
            "SeRemoteInteractiveLogonRight",
            "SeNetworkLogonRight",
            "SeBatchLogonRight",
            "SeServiceLogonRight",
            "SeDenyInteractiveLogonRight",
            "SeDenyRemoteInteractiveLogonRight",
            "SeDenyNetworkLogonRight",
            "SeDenyBatchLogonRight",
            "SeDenyServiceLogonRight",
            "SeBackupPrivilege",
            "SeRestorePrivilege",
            "SeShutdownPrivilege",
            "SeRemoteShutdownPrivilege",
            "SeSystemtimePrivilege",
            "SeTimeZonePrivilege",
            "SeTakeOwnershipPrivilege",
            "SeDebugPrivilege",
            "SeSecurityPrivilege",
            "SeLoadDriverPrivilege",
            "SeManageVolumePrivilege",
            "SeEnableDelegationPrivilege",
            "SeMachineAccountPrivilege",
            "SeIncreaseQuotaPrivilege",
            "SeChangeNotifyPrivilege",
        )
    ),
]

# Restricted groups are not a fixed list: the administrator names the group,
# and each one gets two keys.
MEMBERS_SUFFIX = "__Members"
MEMBEROF_SUFFIX = "__Memberof"


def describe() -> dict[str, Any]:
    """The catalogue, for the editor to draw itself from."""
    return {
        "groups": GROUPS,
        "settings": SETTINGS,
        "restricted_groups": {
            "section": GROUP_MEMBERSHIP,
            "members_suffix": MEMBERS_SUFFIX,
            "memberof_suffix": MEMBEROF_SUFFIX,
        },
    }


def split_group_key(key: str) -> tuple[str, str] | None:
    """A ``[Group Membership]`` key into (group, "members" | "memberof")."""
    for suffix, kind in ((MEMBERS_SUFFIX, "members"), (MEMBEROF_SUFFIX, "memberof")):
        if key.endswith(suffix):
            return key[: -len(suffix)], kind
    return None


def group_key(group: str, kind: str) -> str:
    suffix = MEMBERS_SUFFIX if kind == "members" else MEMBEROF_SUFFIX
    return f"{group}{suffix}"
