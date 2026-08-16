"""Diagnosis logic that does not need a directory."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from samadcon.ad import diagnostics

# ---------------------------------------------------------------------------
# Functional levels
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, "Windows 2000"), (3, "Windows Server 2008"), (7, "Windows Server 2016")],
)
def test_a_known_functional_level_gets_its_name(value, expected):
    assert diagnostics.level_name(value) == expected


def test_an_unknown_functional_level_still_says_something():
    """A newer Windows must not turn the field blank."""
    assert diagnostics.level_name(99) == "Unknown (99)"


def test_a_missing_functional_level_stays_missing():
    assert diagnostics.level_name(None) is None


# ---------------------------------------------------------------------------
# FSMO owners
# ---------------------------------------------------------------------------

NTDS = "CN=NTDS Settings,CN=DC1,CN=Servers,CN=Berlin,CN=Sites,CN=Configuration,DC=example,DC=lan"


def test_the_role_owner_is_named_after_its_server():
    """fSMORoleOwner points at NTDS Settings, which no administrator asked for."""
    assert diagnostics._server_of_ntds(NTDS) == "DC1"


def test_the_role_owner_reports_its_site():
    assert diagnostics._site_of_ntds(NTDS) == "Berlin"


def test_a_role_without_an_owner_reports_nothing():
    """A domain provisioned without the DNS partitions has no owner for those."""
    assert diagnostics._server_of_ntds(None) is None
    assert diagnostics._site_of_ntds(None) is None


# ---------------------------------------------------------------------------
# Replication results
# ---------------------------------------------------------------------------


def test_a_werror_that_is_already_a_number_is_taken_as_is():
    assert diagnostics._werror(0) == 0
    assert diagnostics._werror(1722) == 1722


def test_a_wrapped_werror_is_unwrapped():
    class Wrapped:
        value = 1722

    assert diagnostics._werror(Wrapped()) == 1722


def test_an_unreadable_werror_does_not_pass_as_success():
    """0 means the last replication attempt worked — never guess it."""
    assert diagnostics._werror(object()) is None
    assert diagnostics._werror(None) is None


def test_a_replication_time_of_zero_means_it_never_happened():
    assert diagnostics._drs_time(0) is None
    assert diagnostics._drs_time(None) is None


def test_a_replication_time_is_read_as_a_filetime():
    """The binding scales NTTIME_1sec back up on unpacking."""
    # 2024-01-01 00:00:00 UTC in FILETIME ticks. Read as seconds instead, this
    # would land in 1601 — which is the mistake the test exists to catch.
    ticks = 133485408000000000
    moment = diagnostics._drs_time(ticks)
    assert moment == datetime(2024, 1, 1, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Lockouts
# ---------------------------------------------------------------------------

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def test_a_recent_lockout_is_still_in_force():
    locked_at = NOW - timedelta(minutes=5)
    assert diagnostics._still_locked(locked_at, timedelta(minutes=30), NOW) is True


def test_a_lockout_that_has_run_out_is_not_reported():
    """lockoutTime is not cleared when the lockout expires — it stays until the
    next successful logon, so the timestamp alone means little."""
    locked_at = NOW - timedelta(hours=5)
    assert diagnostics._still_locked(locked_at, timedelta(minutes=30), NOW) is False


def test_a_lockout_without_a_duration_lasts_until_an_admin_clears_it():
    locked_at = NOW - timedelta(days=400)
    assert diagnostics._still_locked(locked_at, None, NOW) is True


def test_the_boundary_belongs_to_the_expired_side():
    locked_at = NOW - timedelta(minutes=30)
    assert diagnostics._still_locked(locked_at, timedelta(minutes=30), NOW) is False
