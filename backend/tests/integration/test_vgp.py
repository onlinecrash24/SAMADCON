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


# ---------------------------------------------------------------------------
# Unix/Files
#
# The one kind whose entries name a file instead of carrying their content.
# What needs a domain controller: the file landing beside the manifest where
# vgp_files_ext looks for it, an entry naming a file nobody uploaded being
# refused, and the file going away with the entry that referred to it — which
# is what cmd_remove_files does.
# ---------------------------------------------------------------------------


def payloads(api, gpo):
    listed = api.get(f"/api/v1/gpos/vgp/payloads?dn={quoted(gpo['dn'])}&policy=files")
    assert listed.status_code == 200, listed.text
    return {item["name"]: item["size"] for item in listed.json()["payloads"]}


def upload(api, gpo, name, content):
    return api.post(
        f"/api/v1/gpos/vgp/payloads?dn={quoted(gpo['dn'])}&policy=files",
        files={"file": (name, content, "application/octet-stream")},
    )


def entry(source, target="/etc/samadcon-test.conf", mode="0644"):
    return {
        "source": source,
        "target": target,
        "user": "root",
        "group": "root",
        "mode": mode,
    }


def test_a_policy_starts_with_no_files_beside_its_manifest(api, gpo):
    assert payloads(api, gpo) == {}


def test_an_uploaded_file_lands_beside_the_manifest(api, gpo):
    response = upload(api, gpo, "motd.txt", b"hello from samadcon")
    assert response.status_code == 200, response.text

    assert payloads(api, gpo) == {"motd.txt": 19}


def test_uploading_does_not_put_the_file_into_force(api, gpo):
    """A file on the share and an entry naming it are separate decisions —
    the same rule the script files follow."""
    upload(api, gpo, "motd.txt", b"hello")

    assert read(api, gpo, "files")["entries"] == []


def test_an_entry_naming_a_file_nobody_uploaded_is_refused(api, gpo):
    """Otherwise the console shows it as configured while every member logs
    "Source file does not exist" and applies nothing."""
    response = write(api, gpo, "files", [entry("nowhere.txt")])

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "vgp_payload_missing"


def test_a_refused_entry_leaves_the_manifest_alone(api, gpo):
    upload(api, gpo, "first.txt", b"first")
    assert write(api, gpo, "files", [entry("first.txt")]).status_code == 200

    write(api, gpo, "files", [entry("first.txt"), entry("missing.txt", target="/etc/other")])

    assert [item["source"] for item in read(api, gpo, "files")["entries"]] == ["first.txt"]


def test_an_entry_round_trips_with_its_mode(api, gpo):
    upload(api, gpo, "motd.txt", b"hello")

    assert write(api, gpo, "files", [entry("motd.txt", mode="0640")]).status_code == 200

    entries = read(api, gpo, "files")["entries"]
    assert entries == [entry("motd.txt", mode="0640")]


def test_dropping_an_entry_takes_its_file_with_it(api, gpo):
    """cmd_remove_files unlinks the source when the entry goes, so a replaced
    list has to take the files it dropped with it."""
    upload(api, gpo, "keep.txt", b"keep")
    upload(api, gpo, "drop.txt", b"drop")
    write(
        api,
        gpo,
        "files",
        [entry("keep.txt"), entry("drop.txt", target="/etc/samadcon-test-2.conf")],
    )
    assert set(payloads(api, gpo)) == {"keep.txt", "drop.txt"}

    write(api, gpo, "files", [entry("keep.txt")])

    assert set(payloads(api, gpo)) == {"keep.txt"}


def test_the_manifest_stays_when_the_last_entry_goes(api, gpo):
    """samba-tool leaves it behind — cmd_remove_files removes the element and
    writes the file back, it never unlinks the manifest."""
    upload(api, gpo, "motd.txt", b"hello")
    write(api, gpo, "files", [entry("motd.txt")])

    write(api, gpo, "files", [])

    listed = read(api, gpo, "files")
    assert listed["present"] is True
    assert listed["entries"] == []


def test_a_file_name_with_a_path_in_it_is_refused(api, gpo):
    """This writes onto a share every domain member reads."""
    response = upload(api, gpo, "../escape.txt", b"nope")

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "vgp_invalid_payload_name"


def test_only_the_computer_half_of_the_version_moves(api, gpo):
    upload(api, gpo, "motd.txt", b"hello")
    before = api.get(f"/api/v1/gpos/gpo?dn={quoted(gpo['dn'])}").json()

    write(api, gpo, "files", [entry("motd.txt")])

    after = api.get(f"/api/v1/gpos/gpo?dn={quoted(gpo['dn'])}").json()
    assert after["machine_version"] > before["machine_version"]
    assert after["user_version"] == before["user_version"]
