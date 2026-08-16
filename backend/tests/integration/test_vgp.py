"""Samba policies in a real GPO.

The manifest format is covered without a domain in tests/unit/test_vgp.py.
What needs a domain controller is the rest: the file landing under
MACHINE/VGP/VTLA where samba-gpupdate looks for it, only the computer half of
the version moving, and — the one that is easy to get wrong by being helpful —
that **no** client-side extension is registered.
"""

from __future__ import annotations

import uuid
from urllib.parse import quote

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.gpo]


def quoted(value: str) -> str:
    return quote(value, safe="")


@pytest.fixture
def gpo(api):
    response = api.post("/api/v1/gpos", json={"display_name": f"SAMADCON vgp {uuid.uuid4().hex[:8]}"})
    if response.status_code != 200:
        pytest.skip(f"cannot create a group policy: {response.text}")

    created = response.json()
    yield created
    api.delete(f"/api/v1/gpos?dn={quoted(created['dn'])}&force=true")


def read(api, gpo, policy):
    return api.get(
        f"/api/v1/gpos/vgp/policy?dn={quoted(gpo['dn'])}&policy={policy}"
    ).json()


def write(api, gpo, policy, entries, **extra):
    return api.post(
        f"/api/v1/gpos/vgp?dn={quoted(gpo['dn'])}",
        json={"policy": policy, "entries": entries, **extra},
    )


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def test_the_kinds_are_listed_with_their_paths(api):
    kinds = api.get("/api/v1/gpos/vgp/kinds").json()["kinds"]
    paths = {item["id"]: item["path"] for item in kinds}

    assert paths["sudoers"] == "MACHINE\\VGP\\VTLA\\Sudo\\SudoersConfiguration\\manifest.xml"
    assert paths["symlink"] == "MACHINE\\VGP\\VTLA\\Unix\\Symlink\\manifest.xml"


def test_a_fresh_policy_has_none_of_them(api, gpo):
    listed = api.get(f"/api/v1/gpos/vgp?dn={quoted(gpo['dn'])}").json()

    assert listed["version_number"] == 0
    assert all(item["present"] is False for item in listed["policies"].values())


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def test_a_symlink_survives_the_round_trip(api, gpo):
    response = write(api, gpo, "symlink", [{"source": "/etc/motd", "target": "/tmp/motd"}])
    assert response.status_code == 200, response.text
    assert response.json()["changed"] is True

    listed = read(api, gpo, "symlink")
    assert listed["present"] is True
    assert listed["entries"] == [{"source": "/etc/motd", "target": "/tmp/motd"}]


def test_a_sudo_rule_survives_the_round_trip(api, gpo):
    entries = [
        {"command": "ALL", "user": "ALL", "principals": ["alice"], "password": False}
    ]

    write(api, gpo, "sudoers", entries)

    assert read(api, gpo, "sudoers")["entries"] == entries


def test_a_banner_survives_the_round_trip(api, gpo):
    write(api, gpo, "motd", [{"text": "Zutritt nur für Befugte\n"}])

    entries = read(api, gpo, "motd")["entries"]
    assert entries[0]["text"] == "Zutritt nur für Befugte\n"


def test_no_client_side_extension_is_registered(api, gpo):
    """The one that is easy to get wrong by being helpful.

    samba-tool gpo manage writes the manifest and bumps the version, nothing
    else, and samba-gpupdate runs every extension against every applicable
    policy regardless. A GUID here would be shown to every Windows client in
    the domain, which knows none of these, for no gain at all.
    """
    write(api, gpo, "symlink", [{"source": "/etc/motd", "target": "/tmp/motd"}])

    entry = api.get(f"/api/v1/gpos/gpo?dn={quoted(gpo['dn'])}").json()
    assert not (entry["machine_extensions"] or "")
    assert not (entry["user_extensions"] or "")


def test_only_the_computer_half_moves(api, gpo):
    """Every one of these lives under MACHINE."""
    before = api.get(f"/api/v1/gpos/gpo?dn={quoted(gpo['dn'])}").json()

    write(api, gpo, "symlink", [{"source": "/etc/motd", "target": "/tmp/motd"}])

    after = api.get(f"/api/v1/gpos/gpo?dn={quoted(gpo['dn'])}").json()
    assert after["machine_version"] > before["machine_version"]
    assert after["user_version"] == before["user_version"]


def test_writing_the_same_thing_twice_changes_nothing(api, gpo):
    entries = [{"source": "/etc/motd", "target": "/tmp/motd"}]
    write(api, gpo, "symlink", entries)

    assert write(api, gpo, "symlink", entries).json()["changed"] is False


def test_the_policies_do_not_overwrite_each_other(api, gpo):
    """Each lives in its own manifest, several directories apart."""
    write(api, gpo, "symlink", [{"source": "/a", "target": "/b"}])
    write(api, gpo, "motd", [{"text": "hello"}])

    listed = api.get(f"/api/v1/gpos/vgp?dn={quoted(gpo['dn'])}").json()["policies"]
    assert listed["symlink"]["present"] is True
    assert listed["motd"]["present"] is True


def test_the_list_is_replaced_whole(api, gpo):
    write(api, gpo, "symlink", [{"source": "/a", "target": "/b"}])
    write(api, gpo, "symlink", [{"source": "/c", "target": "/d"}])

    assert read(api, gpo, "symlink")["entries"] == [{"source": "/c", "target": "/d"}]


def test_clearing_leaves_an_empty_manifest(api, gpo):
    """Not a deleted file: samba-tool leaves the manifest in place, and an
    empty one applies nothing."""
    write(api, gpo, "symlink", [{"source": "/a", "target": "/b"}])
    write(api, gpo, "symlink", [])

    listed = read(api, gpo, "symlink")
    assert listed["present"] is True
    assert listed["entries"] == []


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_an_unknown_policy_is_refused(api, gpo):
    response = write(api, gpo, "firewall", [])

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unknown_vgp_policy"


def test_a_second_banner_is_refused(api, gpo):
    """The manifest holds one block of text; writing two would keep the first
    and lose the other without a word."""
    response = write(api, gpo, "motd", [{"text": "one"}, {"text": "two"}])

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "vgp_single_entry"


def test_a_concurrent_change_is_refused(api, gpo):
    stale = read(api, gpo, "symlink")["version_number"]
    write(api, gpo, "symlink", [{"source": "/a", "target": "/b"}])

    response = write(
        api, gpo, "symlink", [{"source": "/c", "target": "/d"}], expected_version=stale
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "gpo_version_conflict"
