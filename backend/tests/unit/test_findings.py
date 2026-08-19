"""The binding half of the security report.

Every rule is tested on its own, and so are the two that were deliberately not
written: a rule that does not exist is a decision, and a decision nobody
recorded gets reintroduced by the next person who thinks it was an oversight.
"""

from __future__ import annotations

from typing import Any

from samadcon.core import findings


def policy(**overrides: Any) -> dict[str, Any]:
    """A domain policy that raises nothing, so a test changes one thing."""
    base = {
        "min_length": 12,
        "history_length": 24,
        "min_age_days": 1,
        "max_age_days": 0,
        "complexity": True,
        "reversible_encryption": False,
        "lockout_threshold": 5,
        "lockout_duration_minutes": 30,
        "lockout_window_minutes": 30,
        "password_settings_objects": [],
    }
    base.update(overrides)
    return base


def ids(found: list[findings.Finding]) -> list[str]:
    return [item.id for item in found]


# ---------------------------------------------------------------------------
# Nothing to say
# ---------------------------------------------------------------------------


def test_a_sound_policy_raises_nothing():
    assert findings.evaluate(policy=policy()) == []


def test_a_part_that_was_not_read_is_not_guessed_at():
    """A caller that could not reach one section still gets the others."""
    found = findings.evaluate(policy=policy(reversible_encryption=True))
    assert ids(found) == ["password_reversible_encryption"]


# ---------------------------------------------------------------------------
# Consequences, not conventions
# ---------------------------------------------------------------------------


def test_reversible_storage_is_the_worst_of_them():
    found = findings.evaluate(policy=policy(reversible_encryption=True))
    assert found[0].severity == "high"


def test_no_lockout_threshold_is_reported():
    """Zero does not mean "no limit configured" but "guess as long as you like"."""
    found = findings.evaluate(policy=policy(lockout_threshold=0))
    assert ids(found) == ["password_no_lockout"]


def test_replication_failures_are_reported_with_the_partner_count():
    found = findings.evaluate(
        replication={"dc": "dc1.example.lan", "failing": 2, "neighbours": [{}, {}, {}]}
    )
    assert ids(found) == ["replication_failing"]
    assert found[0].evidence == {"failing": 2, "partners": 3, "dc": "dc1.example.lan"}


def test_replication_without_partners_is_not_a_failure():
    """A single-DC domain has none, which is a state and not a fault."""
    assert findings.evaluate(replication={"dc": "dc1", "failing": 0, "neighbours": []}) == []


# ---------------------------------------------------------------------------
# Conventions, carrying the number they rest on
# ---------------------------------------------------------------------------


def test_a_short_minimum_carries_the_threshold_it_was_judged_against():
    """So a reader can disagree with the number rather than with the finding."""
    found = findings.evaluate(policy=policy(min_length=6))
    assert ids(found) == ["password_short_minimum"]
    assert found[0].evidence == {"min_length": 6, "convention": findings.MIN_PASSWORD_LENGTH}


def test_the_minimum_itself_is_not_reported():
    assert findings.evaluate(policy=policy(min_length=findings.MIN_PASSWORD_LENGTH)) == []


def test_complexity_switched_off_ranks_below_the_others():
    found = findings.evaluate(policy=policy(complexity=False, lockout_threshold=0))
    assert ids(found) == ["password_no_lockout", "password_no_complexity"]


# ---------------------------------------------------------------------------
# Rules deliberately not written
# ---------------------------------------------------------------------------


def test_passwords_that_never_expire_are_not_reported():
    """Forced rotation was standard advice for decades and is not any more —
    NIST withdrew it, on the grounds that it pushes people towards predictable
    variations. Reporting it would spread advice its own authors dropped."""
    assert findings.evaluate(policy=policy(max_age_days=0)) == []


def test_a_long_maximum_age_is_not_reported_either():
    assert findings.evaluate(policy=policy(max_age_days=3650)) == []


# ---------------------------------------------------------------------------
# The connection
# ---------------------------------------------------------------------------


def test_an_unverified_certificate_is_reported():
    found = findings.evaluate(
        connection={
            "transport": "ldaps",
            "url": "ldaps://dc1.example.lan",
            "certificate_verified": False,
        }
    )
    assert ids(found) == ["connection_certificate_unverified"]


def test_kerberos_without_a_certificate_is_not_a_missing_check():
    """certificate_verified is None there, and None is not False: under GSSAPI
    the DC proves itself by decrypting the ticket, so there is nothing that
    could have been skipped."""
    found = findings.evaluate(
        connection={
            "transport": "ldap",
            "url": "ldap://dc1.example.lan",
            "certificate_verified": None,
        }
    )
    assert found == []


def test_a_verified_certificate_says_nothing():
    found = findings.evaluate(
        connection={"transport": "ldaps", "url": "x", "certificate_verified": True}
    )
    assert found == []


# ---------------------------------------------------------------------------
# Password settings objects
# ---------------------------------------------------------------------------


def test_password_settings_objects_are_noted_rather_than_faulted():
    """A PSO overrides the domain policy for whoever it applies to, so the
    findings above may not describe everyone. Saying so stops a reader taking
    the domain policy for the whole answer."""
    found = findings.evaluate(policy=policy(password_settings_objects=[{"name": "Admins"}]))

    assert ids(found) == ["password_settings_objects_present"]
    assert found[0].severity == "info"


# ---------------------------------------------------------------------------
# Order
# ---------------------------------------------------------------------------


def test_the_worst_comes_first_and_the_note_last():
    found = findings.evaluate(
        policy=policy(
            reversible_encryption=True,
            complexity=False,
            lockout_threshold=0,
            password_settings_objects=[{"name": "x"}],
        )
    )
    assert [item.severity for item in found] == ["high", "medium", "low", "info"]


def test_every_finding_can_be_handed_to_the_interface():
    found = findings.evaluate(policy=policy(reversible_encryption=True))
    assert found[0].describe() == {
        "id": "password_reversible_encryption",
        "severity": "high",
        "area": "password_policy",
        # Empty: a finding about the domain is one of a kind. A policy
        # finding names the policy, because several share an id.
        "subject": "",
        "evidence": {"reversible_encryption": True},
    }
