"""Writing the domain's password policy, as samba-tool writes it.

On a Samba DC the policy for domain accounts lives on the domain object
(minPwdLength, pwdProperties, ...). A tester set it in the Default Domain
Policy, created a user, and was held to the domain object's values instead:
a Samba DC does not copy the GPO there as a Windows DC does. The ranges, the
conversions and the age check here are the ones of
``samba-tool domain passwordsettings set`` (Samba 4.22.11).
"""

from __future__ import annotations

import pytest

from samadcon.ad import password_policy as pp
from samadcon.core.errors import InvalidRequest

DAY = 24 * 60 * 60 * 10_000_000
MINUTE = 60 * 10_000_000
NEVER = -0x8000000000000000

# What a freshly provisioned domain carries: complexity on, 1 and 42 days.
CURRENT = {"pwd_properties": 1, "min_age_ticks": -1 * DAY, "max_age_ticks": -42 * DAY}


def changes(**request):
    return pp.policy_changes(CURRENT, request)


def test_complexity_off_clears_only_its_own_bit():
    current = {**CURRENT, "pwd_properties": 0x1 | 0x10 | 0x4}
    assert pp.policy_changes(current, {"complexity": False}) == {"pwdProperties": str(0x10 | 0x4)}


def test_reversible_encryption_sets_its_own_bit():
    assert changes(reversible_encryption=True) == {"pwdProperties": str(0x1 | 0x10)}


def test_lengths_and_counts_are_written_as_numbers():
    assert changes(min_length=6, history_length=10, lockout_threshold=5) == {
        "minPwdLength": "6",
        "pwdHistoryLength": "10",
        "lockoutThreshold": "5",
    }


def test_days_and_minutes_become_negative_intervals():
    assert changes(min_age_days=2, max_age_days=90) == {
        "minPwdAge": str(-2 * DAY),
        "maxPwdAge": str(-90 * DAY),
    }
    assert changes(lockout_duration_minutes=30, lockout_window_minutes=15) == {
        "lockoutDuration": str(-30 * MINUTE),
        "lockOutObservationWindow": str(-15 * MINUTE),
    }


def test_zero_means_never_where_samba_tool_says_so():
    assert changes(max_age_days=0) == {"maxPwdAge": str(NEVER)}
    assert changes(lockout_duration_minutes=0)["lockoutDuration"] == str(NEVER)
    assert changes(lockout_window_minutes=0)["lockOutObservationWindow"] == str(NEVER)
    # The minimum age has no "never": 0 is simply no minimum.
    assert changes(min_age_days=0) == {"minPwdAge": "0"}


def test_unchanged_fields_are_not_written():
    assert changes(complexity=None, min_length=None, max_age_days=None) == {}


@pytest.mark.parametrize(
    ("field", "value", "low", "high"),
    [
        ("min_length", 15, 0, 14),
        ("history_length", 25, 0, 24),
        ("min_age_days", 999, 0, 998),
        ("max_age_days", 1000, 0, 999),
        ("lockout_duration_minutes", 100000, 0, 99999),
        ("lockout_window_minutes", -1, 0, 99999),
        ("lockout_threshold", 1000, 0, 999),
    ],
)
def test_values_outside_samba_tools_ranges_are_refused(field, value, low, high):
    with pytest.raises(InvalidRequest) as caught:
        changes(**{field: value})
    assert caught.value.code == "password_policy_out_of_range"
    assert caught.value.context == {"reason": field, "min": low, "max": high, "given": value}


def test_the_maximum_age_must_exceed_the_minimum():
    with pytest.raises(InvalidRequest) as caught:
        changes(min_age_days=50)  # against the current maximum of 42
    assert caught.value.code == "password_age_order"
    assert caught.value.context == {"min_age": 50, "max_age": 42}


def test_no_maximum_age_allows_any_minimum():
    assert changes(max_age_days=0, min_age_days=500) == {
        "maxPwdAge": str(NEVER),
        "minPwdAge": str(-500 * DAY),
    }


def test_a_current_never_maximum_counts_as_none():
    current = {**CURRENT, "max_age_ticks": NEVER}
    assert pp.policy_changes(current, {"min_age_days": 100}) == {"minPwdAge": str(-100 * DAY)}
