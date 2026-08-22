"""The domain report: what it joins, and what it refuses to leave out.

No directory here. What is worth testing is the composition — a document is
trusted differently from a screen, and the ways it can lie are its own.
"""

from __future__ import annotations

from typing import Any

import pytest

from samadcon.core import document


class Info:
    dns_domain = "example.test"
    netbios_name = "EXAMPLE"
    base_dn = "DC=example,DC=test"
    root_domain_dn = "DC=example,DC=test"
    domain_sid = "S-1-5-21-1-2-3"
    dc_hostname = "dc1.example.test"
    domain_functional_level = 7
    forest_functional_level = 7


class Conn:
    info = Info()
    transport = None


def collected(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "findings": [],
        "unreadable": [],
        "policy": {"min_length": 7},
        "replication": {"failing": 0},
        "connection": {"transport": "ldap", "encrypted": True},
        "members": {"members": [], "count": 0, "truncated": False},
        "gpos": [],
        "links": {},
        "status": {},
    }
    base.update(overrides)
    return base


@pytest.fixture
def collect(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, bool]]:
    """Records every collection, so a test can count the readings."""
    calls: list[tuple[str, bool]] = []

    def fake(conn: Any, area: str, *, deep: bool = False) -> dict[str, Any]:
        calls.append((area, deep))
        return collected()

    monkeypatch.setattr(document.findings_source, "collect", fake)
    monkeypatch.setattr(document.diagnostics, "fsmo_roles", lambda conn: [])
    monkeypatch.setattr(document.diagnostics, "domain_controllers", lambda conn: [])
    return calls


def test_each_area_is_read_exactly_once(collect: list[tuple[str, bool]]) -> None:
    """The timestamp at the top has to be true of everything under it. Two
    readings of a section would make it true of neither."""
    document.build(Conn(), deep=True)

    assert collect == [("security", False), ("policies", True)]


def test_a_section_that_cannot_be_read_is_named_rather_than_dropped(
    monkeypatch: pytest.MonkeyPatch, collect: list[tuple[str, bool]]
) -> None:
    """Silently omitting replication because the read failed is worse than no
    report at all: what comes out reads as a clean bill of health."""

    def boom(conn: Any) -> Any:
        raise RuntimeError("no")

    monkeypatch.setattr(document.diagnostics, "fsmo_roles", boom)

    built = document.build(Conn())

    assert "roles" in built["security"]["unreadable"]
    assert built["domain"]["dns_domain"] == "example.test"


def test_a_policy_carries_the_links_that_point_at_it(
    monkeypatch: pytest.MonkeyPatch, collect: list[tuple[str, bool]]
) -> None:
    """The join happens once, here. A policy printed without its links reads
    as a policy nobody linked — which is a finding, and must not be produced
    by a rendering mistake."""
    guid = "{AAAAAAAA-0000-0000-0000-000000000001}"
    link = {"container": "Workstations", "kind": "organizational_unit", "enabled": True}

    def fake(conn: Any, area: str, *, deep: bool = False) -> dict[str, Any]:
        if area != "policies":
            return collected()
        return collected(
            gpos=[{"guid": guid, "display_name": "Baseline"}],
            links={guid.upper(): [link]},
        )

    monkeypatch.setattr(document.findings_source, "collect", fake)

    entries = document.build(Conn())["policies"]["gpos"]

    assert [entry["links"] for entry in entries] == [[link]]


def test_a_policy_nobody_linked_carries_an_empty_list_not_a_missing_key(
    collect: list[tuple[str, bool]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """So that "no links" is stated by the document rather than inferred from
    an absence by whoever renders it."""

    def fake(conn: Any, area: str, *, deep: bool = False) -> dict[str, Any]:
        if area != "policies":
            return collected()
        return collected(gpos=[{"guid": "{B}", "display_name": "Staged"}])

    monkeypatch.setattr(document.findings_source, "collect", fake)

    entry = document.build(Conn())["policies"]["gpos"][0]

    assert entry["links"] == []
    assert entry["status"] is None


def test_the_timestamp_carries_its_offset(collect: list[tuple[str, bool]]) -> None:
    """A report is read in a timezone nobody can know from inside a container."""
    stamped = document.build(Conn())["generated_at"]

    assert stamped.endswith("+00:00")
