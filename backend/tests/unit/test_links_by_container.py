"""Every link in the domain, turned around for a tree.

link_map answers "where does this policy apply". A management tree asks the
other question — "what applies here" — and the inversion belongs on this side
so the shape does not depend on which screen is asking.

No directory here: link_map and the policy list are stood in for, because what
is worth testing is the turning around and the ordering.
"""

from __future__ import annotations

from typing import Any

import pytest

from samadcon.gpo import gpmc

WORKSTATIONS = "OU=Workstations,DC=example,DC=test"
SERVERS = "OU=Server,DC=example,DC=test"

BASELINE = "{AAAA0000-0000-0000-0000-000000000001}"
UPDATES = "{BBBB0000-0000-0000-0000-000000000002}"
GHOST = "{CCCC0000-0000-0000-0000-000000000003}"


def place(dn: str, name: str, order: int, **overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "container": name,
        "container_dn": dn,
        "kind": "organizational_unit",
        "order": order,
        "enabled": True,
        "enforced": False,
    }
    entry.update(overrides)
    return entry


@pytest.fixture
def domain(monkeypatch: pytest.MonkeyPatch) -> None:
    """One policy on two OUs, one on one, and one linked policy that is gone."""
    monkeypatch.setattr(
        gpmc,
        "link_map",
        lambda conn: {
            BASELINE: [
                place(WORKSTATIONS, "Workstations", 2),
                place(SERVERS, "Server", 1),
            ],
            UPDATES: [place(WORKSTATIONS, "Workstations", 1)],
            GHOST: [place(SERVERS, "Server", 2)],
        },
    )
    monkeypatch.setattr(
        gpmc.container,
        "list_gpos",
        lambda conn: [
            {"guid": BASELINE, "display_name": "Baseline"},
            {"guid": UPDATES, "display_name": "Windows Updates"},
        ],
    )


def containers(found: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {node["dn"]: node for node in found["containers"]}


def test_the_map_is_turned_around_onto_the_containers(domain: None) -> None:
    found = containers(gpmc.links_by_container(object()))

    assert set(found) == {WORKSTATIONS, SERVERS}
    assert {link["guid"] for link in found[WORKSTATIONS]["links"]} == {BASELINE, UPDATES}


def test_links_come_back_in_precedence_order(domain: None) -> None:
    """Order 1 wins. Listing them in whatever order the attribute parsed in
    would show something that looks like precedence and is not."""
    found = containers(gpmc.links_by_container(object()))

    assert [link["order"] for link in found[WORKSTATIONS]["links"]] == [1, 2]
    assert found[WORKSTATIONS]["links"][0]["guid"] == UPDATES


def test_a_policy_name_is_joined_in(domain: None) -> None:
    """The label is the whole point of a node, and joining it here keeps the
    tree from having to hold the policy list to draw one."""
    found = containers(gpmc.links_by_container(object()))
    names = {link["guid"]: link["display_name"] for link in found[WORKSTATIONS]["links"]}

    assert names[BASELINE] == "Baseline"
    assert names[UPDATES] == "Windows Updates"


def test_a_link_to_a_policy_that_is_gone_is_kept_and_unnamed(domain: None) -> None:
    """Dropping it would hide a real state. A link pointing at nothing still
    costs every client in scope a lookup on each refresh, and nothing else
    reports it."""
    found = containers(gpmc.links_by_container(object()))
    ghost = [link for link in found[SERVERS]["links"] if link["guid"] == GHOST]

    assert len(ghost) == 1
    assert ghost[0]["display_name"] is None


def test_a_container_that_links_nothing_does_not_appear(domain: None) -> None:
    """This is the link map turned around, not the directory. An OU with no
    links has nothing to say here, and the tree gets its shape elsewhere."""
    found = containers(gpmc.links_by_container(object()))

    assert "OU=Benutzer,DC=example,DC=test" not in found
