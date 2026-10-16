"""Writing the domain's password and lockout policy.

On a Samba DC this is where the policy for domain accounts lives: attributes
of the domain object, not the Default Domain Policy. A Windows DC copies the
GPO's [System Access] onto the domain object; a Samba DC does not, so a
tester who set the GPO and then created a user was held to the old values.
Reading it is in diagnostics.password_policy; this is the write half.

Everything here follows ``samba-tool domain passwordsettings set`` (Samba
4.22.11): the same ranges, intervals as negative 100-ns ticks, 0 meaning
"never" for the maximum age, the lockout duration and the reset window, and
the maximum age kept above the minimum. Other bits of pwdProperties are left
as they are.
"""

from __future__ import annotations

from typing import Any

from samadcon.ad import values
from samadcon.ad.connection import DirectoryConnection
from samadcon.ad.diagnostics import (
    DOMAIN_PASSWORD_COMPLEX,
    DOMAIN_PASSWORD_STORE_CLEARTEXT,
    password_policy,
)
from samadcon.core.errors import InvalidRequest

TICKS_PER_MINUTE = 60 * 10_000_000
TICKS_PER_DAY = 24 * 60 * TICKS_PER_MINUTE
NEVER = -0x8000000000000000

# field: (attribute, lowest, highest, ticks per unit or None for a plain number,
#         whether 0 means "never")
_NUMBERS: dict[str, tuple[str, int, int, int | None, bool]] = {
    "min_length": ("minPwdLength", 0, 14, None, False),
    "history_length": ("pwdHistoryLength", 0, 24, None, False),
    "min_age_days": ("minPwdAge", 0, 998, TICKS_PER_DAY, False),
    "max_age_days": ("maxPwdAge", 0, 999, TICKS_PER_DAY, True),
    # samba-tool sets no upper bound here; 999 is the limit Windows' own
    # editor puts on it, and a value above that is a typo, not a policy.
    "lockout_threshold": ("lockoutThreshold", 0, 999, None, False),
    "lockout_duration_minutes": ("lockoutDuration", 0, 99999, TICKS_PER_MINUTE, True),
    "lockout_window_minutes": ("lockOutObservationWindow", 0, 99999, TICKS_PER_MINUTE, True),
}

_FLAGS = {
    "complexity": DOMAIN_PASSWORD_COMPLEX,
    "reversible_encryption": DOMAIN_PASSWORD_STORE_CLEARTEXT,
}

FIELDS = (*_FLAGS, *_NUMBERS)


def _days(ticks: int | None) -> int | float:
    """Days in an interval; 0 for none or never, as samba-tool counts it."""
    if not ticks or ticks == NEVER:
        return 0
    days = round(abs(ticks) / TICKS_PER_DAY, 2)
    return int(days) if days == int(days) else days


def policy_changes(current: dict[str, Any], request: dict[str, Any]) -> dict[str, str]:
    """The attributes to replace, from what was asked for and what is there.

    *current* holds pwd_properties, min_age_ticks and max_age_ticks; *request*
    the fields of FIELDS, None for "leave as it is".
    """
    changes: dict[str, str] = {}

    properties = int(current.get("pwd_properties") or 0)
    flags_asked = False
    for field, bit in _FLAGS.items():
        wanted = request.get(field)
        if wanted is None:
            continue
        flags_asked = True
        properties = properties | bit if wanted else properties & ~bit
    if flags_asked:
        changes["pwdProperties"] = str(properties)

    min_age_ticks = current.get("min_age_ticks")
    max_age_ticks = current.get("max_age_ticks")
    for field, (attribute, low, high, unit, zero_is_never) in _NUMBERS.items():
        given = request.get(field)
        if given is None:
            continue
        if not low <= given <= high:
            raise InvalidRequest(
                f"{field} must be between {low} and {high}.",
                code="password_policy_out_of_range",
                context={"reason": field, "min": low, "max": high, "given": given},
            )
        if unit is None:
            changes[attribute] = str(given)
            continue
        ticks = NEVER if given == 0 and zero_is_never else -given * unit
        changes[attribute] = str(ticks)
        if attribute == "minPwdAge":
            min_age_ticks = ticks
        elif attribute == "maxPwdAge":
            max_age_ticks = ticks

    if "minPwdAge" in changes or "maxPwdAge" in changes:
        min_age, max_age = _days(min_age_ticks), _days(max_age_ticks)
        if max_age != 0 and min_age >= max_age:
            raise InvalidRequest(
                "The maximum password age must be greater than the minimum.",
                code="password_age_order",
                context={"min_age": min_age, "max_age": max_age},
            )

    return changes


def set_password_policy(conn: DirectoryConnection, **request: Any) -> dict[str, Any]:
    """Replace the asked-for parts of the policy; return what was written and
    the policy as it now reads."""
    import ldb

    entry = conn.get(conn.info.base_dn, attrs=["pwdProperties", "minPwdAge", "maxPwdAge"])
    current = {
        "pwd_properties": values.as_int(entry, "pwdProperties", 0),
        "min_age_ticks": values.as_int(entry, "minPwdAge"),
        "max_age_ticks": values.as_int(entry, "maxPwdAge"),
    }
    changes = policy_changes(current, request)
    if not changes:
        raise InvalidRequest("Nothing to change.", code="no_changes")

    message = ldb.Message()
    message.dn = ldb.Dn(conn.samdb, conn.info.base_dn)
    for attribute, value in changes.items():
        message[attribute] = ldb.MessageElement(value, ldb.FLAG_MOD_REPLACE, attribute)
    conn.modify(message)

    return {"applied": changes, "policy": password_policy(conn)}
