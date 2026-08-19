"""Findings about the domain's group policies.

The failure these exist for: a policy that reaches nobody looks exactly like
one that works. Every console shows its settings, its versions and its links;
none of them says "and therefore nothing happens".
"""

from __future__ import annotations

from typing import Any

from samadcon.core import findings


def gpo(**overrides: Any) -> dict[str, Any]:
    """A policy nothing is wrong with, so a test changes one thing."""
    base = {
        "guid": "{AAAAAAAA-0000-0000-0000-000000000001}",
        "display_name": "Baseline",
        "machine_enabled": True,
        "user_enabled": True,
        "machine_extensions": "[{35378EAC-683F-11D2-A89A-00C04FBBCFA2}]",
        "user_extensions": None,
    }
    base.update(overrides)
    return base


def link(enabled: bool = True) -> dict[str, Any]:
    return {"container": "Workstations", "kind": "ou", "enabled": enabled, "enforced": False}


def linked(target: dict[str, Any], *links: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return {(target["guid"]).upper(): list(links)}


def ids(found: list[findings.Finding]) -> list[str]:
    return [item.id for item in found]


# ---------------------------------------------------------------------------
# Nothing to say
# ---------------------------------------------------------------------------


def test_a_linked_policy_that_registers_something_raises_nothing():
    one = gpo()
    assert findings.evaluate_policies([one], links=linked(one, link())) == []


def test_a_domain_without_policies_raises_nothing():
    assert findings.evaluate_policies([], links={}) == []


# ---------------------------------------------------------------------------
# Reaching nobody
# ---------------------------------------------------------------------------


def test_a_policy_linked_nowhere_is_reported():
    one = gpo()
    found = findings.evaluate_policies([one], links={})

    assert ids(found) == ["gpo_not_linked"]
    assert found[0].subject == "Baseline"


def test_a_policy_whose_every_link_is_disabled_is_reported():
    one = gpo()
    found = findings.evaluate_policies([one], links=linked(one, link(False), link(False)))

    assert ids(found) == ["gpo_all_links_disabled"]


def test_one_enabled_link_among_disabled_ones_is_enough():
    one = gpo()
    found = findings.evaluate_policies([one], links=linked(one, link(False), link(True)))

    assert found == []


def test_a_policy_with_both_halves_switched_off_is_reported():
    one = gpo(machine_enabled=False, user_enabled=False)
    found = findings.evaluate_policies([one], links=linked(one, link()))

    assert ids(found) == ["gpo_both_halves_disabled"]


def test_a_linked_policy_registering_nothing_ranks_above_the_others():
    """It reads as a working policy in every console and applies nothing —
    worse than an unlinked one, which at least looks unused."""
    one = gpo(machine_extensions=None, user_extensions=None)
    found = findings.evaluate_policies([one], links=linked(one, link()))

    assert ids(found) == ["gpo_linked_but_empty"]
    assert found[0].severity == "medium"


def test_an_unlinked_empty_policy_is_only_reported_as_unlinked():
    """A staged policy nobody has filled in yet is one observation, not two."""
    one = gpo(machine_extensions=None, user_extensions=None)
    found = findings.evaluate_policies([one], links={})

    assert ids(found) == ["gpo_not_linked"]


def test_a_switched_off_policy_is_not_also_reported_as_empty():
    one = gpo(machine_enabled=False, user_enabled=False, machine_extensions=None)
    found = findings.evaluate_policies([one], links=linked(one, link()))

    assert ids(found) == ["gpo_both_halves_disabled"]


# ---------------------------------------------------------------------------
# What only SYSVOL can answer
# ---------------------------------------------------------------------------


def test_the_deep_findings_are_absent_when_the_walk_was_not_asked_for():
    one = gpo()
    assert findings.evaluate_policies([one], links=linked(one, link()), deep=None) == []


def test_content_without_an_extension_is_the_worst_of_them():
    """Settings sitting on SYSVOL that no client will ever read."""
    one = gpo()
    found = findings.evaluate_policies(
        [one],
        links=linked(one, link()),
        deep={one["guid"].upper(): ["machine_content_without_extension"]},
    )

    assert ids(found) == ["gpo_machine_content_without_extension"]
    assert found[0].severity == "high"


def test_other_deep_problems_rank_below_it():
    one = gpo()
    found = findings.evaluate_policies(
        [one],
        links=linked(one, link()),
        deep={one["guid"].upper(): ["version_mismatch"]},
    )

    assert ids(found) == ["gpo_version_mismatch"]
    assert found[0].severity == "medium"


# ---------------------------------------------------------------------------
# Several policies
# ---------------------------------------------------------------------------


def test_findings_name_the_policy_they_are_about():
    """Several policies share an id, so the id alone cannot tell them apart —
    on screen or as a react key."""
    first = gpo(guid="{AAAAAAAA-0000-0000-0000-000000000001}", display_name="Alpha")
    second = gpo(guid="{BBBBBBBB-0000-0000-0000-000000000002}", display_name="Beta")

    found = findings.evaluate_policies([first, second], links={})

    assert [item.subject for item in found] == ["Alpha", "Beta"]
    assert {item.id for item in found} == {"gpo_not_linked"}


def test_the_worst_comes_first_then_the_policies_in_order():
    first = gpo(guid="{AAAAAAAA-0000-0000-0000-000000000001}", display_name="Zulu")
    second = gpo(
        guid="{BBBBBBBB-0000-0000-0000-000000000002}",
        display_name="Alpha",
        machine_extensions=None,
        user_extensions=None,
    )
    links = {second["guid"].upper(): [link()]}

    found = findings.evaluate_policies([first, second], links=links)

    assert [(item.severity, item.subject) for item in found] == [
        ("medium", "Alpha"),
        ("low", "Zulu"),
    ]
