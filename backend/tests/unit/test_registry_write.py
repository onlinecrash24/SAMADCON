"""Administrative templates are written through SAMADCON's own SYSVOL writer.

They went through samba.policies.RegistryGroupPolicies, which writes with a
plain savefile. SMB refuses that with ACCESS_DENIED on a hidden or read-only
file. A tester met it in October 2026: Registry.pol was written, GPT.INI was
refused, the version never moved — and saving again "worked" because nothing
was left to write, while every client kept the old setting. SAMADCON's own
writer has handled hidden files since GPMC's scripts.ini; this holds the
template path to it.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from samadcon.gpo import registry_pol
from samadcon.gpo.admx import resolver, writer

# ---------------------------------------------------------------------------
# Merging
# ---------------------------------------------------------------------------

KEY = "Software\\Policies\\Google\\Chrome"


def entry(key: str, value: str, data: Any, kind: str = "REG_SZ") -> dict[str, Any]:
    return {"key": key, "value": value, "type": kind, "data": data}


def test_a_value_already_there_is_replaced_where_it_stands():
    current = [entry(KEY, "A", "1"), entry(KEY, "ManagedBookmarks", "old"), entry(KEY, "Z", "9")]
    merged = registry_pol.merge(current, [entry(KEY, "ManagedBookmarks", "new")], [])
    assert [(item["value"], item["data"]) for item in merged] == [
        ("A", "1"),
        ("ManagedBookmarks", "new"),
        ("Z", "9"),
    ]


def test_key_and_value_name_compare_without_case():
    """The registry does not care, and GPMC and Samba spell keys differently."""
    current = [entry(KEY.upper(), "managedbookmarks", "old")]
    merged = registry_pol.merge(current, [entry(KEY, "ManagedBookmarks", "new")], [])
    assert len(merged) == 1 and merged[0]["data"] == "new"


def test_a_new_value_is_appended():
    merged = registry_pol.merge([entry(KEY, "A", "1")], [entry(KEY, "B", "2")], [])
    assert [item["value"] for item in merged] == ["A", "B"]


def test_a_removed_value_goes_and_the_others_stay():
    current = [entry(KEY, "A", "1"), entry(KEY, "**del.B", " "), entry(KEY, "C", "3")]
    merged = registry_pol.merge(current, [], [(KEY, "a")])
    assert [item["value"] for item in merged] == ["**del.B", "C"]


def test_removing_and_setting_the_same_value_sets_it():
    merged = registry_pol.merge([entry(KEY, "A", "1")], [entry(KEY, "A", "2")], [(KEY, "A")])
    assert merged == [entry(KEY, "A", "2")]


# ---------------------------------------------------------------------------
# Writing into a GPO
# ---------------------------------------------------------------------------

GPO = {
    "path": "\\\\example.lan\\sysvol\\example.lan\\Policies\\{X}",
    "version": 65537,
    "display_name": "Test",
}


class Share:
    def __init__(self, existing: bool) -> None:
        self.existing = existing
        self.written: list[tuple[str, bytes]] = []
        self.made: list[str] = []

    def resolve(self, base: str, relative: str) -> str | None:
        return f"{base}\\MACHINE\\Registry.pol" if self.existing else None

    def makedirs(self, path: str) -> None:
        self.made.append(path)

    def write(self, path: str, data: bytes) -> None:
        self.written.append((path, data))


@pytest.fixture
def written(monkeypatch):
    calls: dict[str, Any] = {"bumped": []}
    share = Share(existing=True)
    monkeypatch.setattr(writer.sysvol, "sysvol_for", lambda conn: share)
    # preg needs Samba; the packing itself is tested in the image. Here only
    # what reaches the writer matters.
    monkeypatch.setattr(
        writer.registry_pol, "build", lambda entries: json.dumps(entries).encode()
    )
    monkeypatch.setattr(
        writer.container, "bump_version", lambda conn, dn, **kw: calls["bumped"].append(kw)
    )
    calls["share"] = share
    return calls


def plan(set_entries=(), remove=()) -> resolver.Plan:
    return resolver.Plan(set=list(set_entries), remove=list(remove))


def test_the_file_goes_through_the_hidden_aware_writer(written):
    """share.write, which retries a refused overwrite in place — not savefile."""
    current = [entry(KEY, "A", "1")]
    new = resolver.Entry(KEY, "ManagedBookmarks", registry_pol.REG_SZ, "[{}]")

    remaining = writer.write_entries(object(), "CN={X}", GPO, "Machine", current, plan([new]))

    path, data = written["share"].written[0]
    assert path.endswith("\\MACHINE\\Registry.pol")
    assert [item["value"] for item in json.loads(data)] == ["A", "ManagedBookmarks"]
    assert [item["value"] for item in remaining] == ["A", "ManagedBookmarks"]


def test_the_version_advances_once_in_the_half_that_changed(written):
    new = resolver.Entry(KEY, "A", registry_pol.REG_DWORD, 1)
    writer.write_entries(object(), "CN={X}", GPO, "User", [], plan([new]))
    assert written["bumped"] == [{"machine_changed": False, "user_changed": True}]


def test_a_half_without_a_file_gets_one(written):
    written["share"].existing = False
    new = resolver.Entry(KEY, "A", registry_pol.REG_DWORD, 1)
    writer.write_entries(object(), "CN={X}", GPO, "Machine", [], plan([new]))

    path, _ = written["share"].written[0]
    assert path.endswith("\\Machine\\Registry.pol")
    assert written["share"].made == [path.rsplit("\\", 1)[0]]


def test_samba_s_own_writer_is_not_used():
    """Its savefile is the call that failed on a hidden GPT.INI."""
    import inspect

    assert "RegistryGroupPolicies" not in inspect.getsource(writer).split('"""', 2)[2]
