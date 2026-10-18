"""Rules ADUC and GPMC enforce that SAMADCON let through.

Found by comparing with Microsoft's documentation after a tester saved an
account with "must change password" and "password never expires" together:

1. Account lockout. With a threshold above 0, "Reset account lockout counter
   after" must be less than or equal to "Account lockout duration"
   (Microsoft's reference for both settings). Neither the domain password
   policy dialog nor the GPO editor checked it.
2. Group scope. Global and domain local do not convert into each other
   directly; global to universal needs the group to be in no other global
   group; domain local to universal needs no domain local group among its
   members; universal to global needs no universal group among them
   (Microsoft, "Group scope" / "Change Group Scope"). ADUC greys out what
   cannot be done; SAMADCON offered every scope and left the refusal to the
   DC.
"""

from __future__ import annotations

import pytest

from samadcon.ad import groups
from samadcon.ad import password_policy as pp
from samadcon.core.errors import InvalidRequest
from samadcon.gpo import security

MINUTE = 60 * 10_000_000
NEVER = -0x8000000000000000

# ---------------------------------------------------------------------------
# 1a. Lockout in the domain password policy
# ---------------------------------------------------------------------------

LOCKOUT = {
    "pwd_properties": 1,
    "min_age_ticks": None,
    "max_age_ticks": None,
    "lockout_threshold": 5,
    "lockout_duration_ticks": -30 * MINUTE,
    "lockout_window_ticks": -30 * MINUTE,
}


def test_a_reset_longer_than_the_lockout_is_refused():
    with pytest.raises(InvalidRequest) as caught:
        pp.policy_changes(LOCKOUT, {"lockout_window_minutes": 45})
    assert caught.value.code == "lockout_reset_exceeds_duration"
    assert caught.value.context == {"reset": 45, "duration": 30}


def test_a_shorter_lockout_than_the_reset_is_refused():
    with pytest.raises(InvalidRequest) as caught:
        pp.policy_changes(LOCKOUT, {"lockout_duration_minutes": 10})
    assert caught.value.code == "lockout_reset_exceeds_duration"


def test_reset_and_lockout_set_together_are_checked_together():
    changes = pp.policy_changes(
        LOCKOUT, {"lockout_duration_minutes": 10, "lockout_window_minutes": 10}
    )
    assert changes["lockoutDuration"] == str(-10 * MINUTE)


def test_without_a_threshold_the_two_are_free():
    current = {**LOCKOUT, "lockout_threshold": 0}
    assert pp.policy_changes(current, {"lockout_window_minutes": 45})


def test_switching_the_lockout_on_checks_what_is_already_there():
    current = {**LOCKOUT, "lockout_threshold": 0, "lockout_window_ticks": -60 * MINUTE}
    with pytest.raises(InvalidRequest):
        pp.policy_changes(current, {"lockout_threshold": 3})


def test_until_an_administrator_unlocks_has_no_upper_bound():
    # Duration 0 = "until an administrator unlocks it"; any reset time fits.
    current = {**LOCKOUT, "lockout_duration_ticks": NEVER}
    assert pp.policy_changes(current, {"lockout_window_minutes": 600})


def test_an_unrelated_change_is_not_held_up_by_an_old_mismatch():
    current = {**LOCKOUT, "lockout_window_ticks": -60 * MINUTE}
    assert pp.policy_changes(current, {"min_length": 10}) == {"minPwdLength": "10"}


# ---------------------------------------------------------------------------
# 1b. Lockout in a GPO's security settings
# ---------------------------------------------------------------------------


def _access(**keys: str) -> dict[str, dict[str, str]]:
    return {"System Access": dict(keys)}


def test_the_gpo_check_refuses_a_reset_longer_than_the_lockout():
    with pytest.raises(InvalidRequest) as caught:
        security.check_lockout(
            _access(LockoutBadCount="5", LockoutDuration="15", ResetLockoutCount="30")
        )
    assert caught.value.code == "lockout_reset_exceeds_duration"
    assert caught.value.context == {"reset": 30, "duration": 15}


@pytest.mark.parametrize(
    "keys",
    [
        {"LockoutBadCount": "5", "LockoutDuration": "30", "ResetLockoutCount": "30"},
        {"LockoutBadCount": "0", "LockoutDuration": "15", "ResetLockoutCount": "30"},
        # Not defined: GPMC leaves the other two alone, and so does this.
        {"LockoutBadCount": "5", "ResetLockoutCount": "30"},
        {"LockoutBadCount": "5", "LockoutDuration": "15"},
        # Until an administrator unlocks it.
        {"LockoutBadCount": "5", "LockoutDuration": "-1", "ResetLockoutCount": "30"},
        {"LockoutBadCount": "5", "LockoutDuration": "0", "ResetLockoutCount": "30"},
        {},
    ],
)
def test_the_gpo_check_lets_the_rest_through(keys):
    security.check_lockout(_access(**keys))


# ---------------------------------------------------------------------------
# 2. Group scope
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("current", "target", "members", "parents", "problem"),
    [
        ("global", "universal", set(), set(), None),
        ("global", "universal", set(), {"global"}, "member_of_global"),
        ("global", "domain_local", set(), set(), "via_universal"),
        ("domain_local", "global", set(), set(), "via_universal"),
        ("domain_local", "universal", set(), set(), None),
        ("domain_local", "universal", {"domain_local"}, set(), "has_domain_local_members"),
        ("universal", "global", set(), set(), None),
        ("universal", "global", {"universal"}, set(), "has_universal_members"),
        ("universal", "domain_local", {"universal", "global"}, {"universal"}, None),
        ("global", "global", set(), {"global"}, None),
    ],
)
def test_the_scope_changes_microsoft_allows(current, target, members, parents, problem):
    assert groups.scope_change_problem(current, target, members, parents) == problem


def test_a_builtin_group_keeps_its_scope():
    assert (
        groups.scope_change_problem("domain_local", "universal", set(), set(), builtin=True)
        == "builtin"
    )
