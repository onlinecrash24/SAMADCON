"""Folder redirection in a real GPO.

The file format is covered without a domain in tests/unit/test_folders.py,
including a byte-for-byte comparison against the fdeploy1.ini GPMC produced.
What needs a domain controller is the rest: the file landing where Windows
looks for it, the extension being registered so a client acts on it, and only
the user half of the version moving.
"""

from __future__ import annotations

import uuid
from urllib.parse import quote

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.gpo]

# Read off gPCUserExtensionNames of a GPO created in GPMC.
REDIRECTION_CSE = "{25537BA6-77A8-11D2-9B6C-0000F8080861}"
REDIRECTION_TOOL = "{88E729D6-BDC1-11D1-BD2A-00C04FB9603F}"

# "Saved Games" — the folder the reference GPO redirects. Harmless to point
# somewhere else in a policy that is linked nowhere.
SAVED_GAMES = "{4C5C32FF-BB9D-43B0-B5B4-2D72E54EAAA4}"
DESKTOP = "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}"
EVERYONE = "S-1-1-0"


def quoted(value: str) -> str:
    return quote(value, safe="")


@pytest.fixture
def gpo(api):
    response = api.post(
        "/api/v1/gpos", json={"display_name": f"SAMCON redirect {uuid.uuid4().hex[:8]}"}
    )
    if response.status_code != 200:
        pytest.skip(f"cannot create a group policy: {response.text}")

    created = response.json()
    yield created
    api.delete(f"/api/v1/gpos?dn={quoted(created['dn'])}&force=true")


def read(api, gpo):
    return api.get(f"/api/v1/gpos/redirection?dn={quoted(gpo['dn'])}").json()


def write(api, gpo, **payload):
    payload.setdefault("folder", SAVED_GAMES)
    payload.setdefault("sid", EVERYONE)
    return api.post(f"/api/v1/gpos/redirection?dn={quoted(gpo['dn'])}", json=payload)


def user_extensions(api, gpo):
    entry = api.get(f"/api/v1/gpos/gpo?dn={quoted(gpo['dn'])}").json()
    return (entry["user_extensions"] or "").upper()


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def test_a_fresh_policy_redirects_nothing(api, gpo):
    listed = read(api, gpo)

    assert listed["present"] is False
    assert listed["folders"] == []


def test_the_empty_answer_still_carries_the_version(api, gpo):
    """It is what a later write is checked against. Leaving it out took the
    conflict protection away from exactly the policy most likely to be edited
    by two people at once — a fresh one."""
    listed = read(api, gpo)

    assert listed["version_number"] == 0
    assert listed["registered"] is False


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def test_a_redirection_survives_the_round_trip(api, gpo):
    path = "\\\\dom.lan\\home\\%USERNAME%\\Saved Games"
    response = write(api, gpo, path=path)
    assert response.status_code == 200, response.text
    assert response.json()["changed"] is True

    listed = read(api, gpo)
    assert listed["present"] is True
    assert [item["guid"] for item in listed["folders"]] == [SAVED_GAMES]
    target = listed["folders"][0]["targets"][0]
    assert target["path"] == path
    # Carried from what Windows itself writes, not computed.
    assert target["options"]["Flags"] == "1211"


def test_writing_registers_the_extension_that_applies_it(api, gpo):
    write(api, gpo, path="\\\\dom.lan\\home\\%USERNAME%")

    assert read(api, gpo)["registered"] is True

    value = user_extensions(api, gpo)
    assert REDIRECTION_CSE in value
    assert REDIRECTION_TOOL in value


def test_only_the_user_half_moves(api, gpo):
    """Folder redirection is user configuration; a computer version that moved
    would make every machine re-read a policy that says nothing to it."""
    before = api.get(f"/api/v1/gpos/gpo?dn={quoted(gpo['dn'])}").json()

    write(api, gpo, path="\\\\dom.lan\\home\\%USERNAME%")

    after = api.get(f"/api/v1/gpos/gpo?dn={quoted(gpo['dn'])}").json()
    assert after["user_version"] > before["user_version"]
    assert after["machine_version"] == before["machine_version"]


def test_writing_the_same_thing_twice_changes_nothing(api, gpo):
    write(api, gpo, path="\\\\dom.lan\\home\\%USERNAME%")
    again = write(api, gpo, path="\\\\dom.lan\\home\\%USERNAME%")

    assert again.json()["changed"] is False


def test_two_folders_live_side_by_side(api, gpo):
    write(api, gpo, folder=SAVED_GAMES, path="\\\\dom.lan\\home\\%USERNAME%\\Saved Games")
    write(api, gpo, folder=DESKTOP, path="\\\\dom.lan\\home\\%USERNAME%\\Desktop")

    listed = read(api, gpo)
    assert sorted(item["guid"] for item in listed["folders"]) == sorted([SAVED_GAMES, DESKTOP])


def test_editing_keeps_the_flags(api, gpo):
    write(api, gpo, path="\\\\dom.lan\\one")
    write(api, gpo, path="\\\\dom.lan\\two")

    target = read(api, gpo)["folders"][0]["targets"][0]
    assert target["path"] == "\\\\dom.lan\\two"
    assert target["options"]["Flags"] == "1211"


# ---------------------------------------------------------------------------
# Taking it away
# ---------------------------------------------------------------------------


def test_removing_the_last_redirection_unregisters_the_extension(api, gpo):
    write(api, gpo, path="\\\\dom.lan\\home\\%USERNAME%")
    assert read(api, gpo)["registered"] is True

    write(api, gpo, path=None)

    listed = read(api, gpo)
    assert listed["folders"] == []
    assert listed["registered"] is False
    assert REDIRECTION_CSE not in user_extensions(api, gpo)


def test_the_extension_stays_while_another_folder_is_redirected(api, gpo):
    write(api, gpo, folder=SAVED_GAMES, path="\\\\dom.lan\\a")
    write(api, gpo, folder=DESKTOP, path="\\\\dom.lan\\b")

    write(api, gpo, folder=SAVED_GAMES, path=None)

    assert read(api, gpo)["registered"] is True


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_something_that_is_not_a_folder_guid_is_refused(api, gpo):
    response = write(api, gpo, folder="Saved Games", path="\\\\dom.lan\\x")

    assert response.status_code == 422


def test_a_concurrent_change_is_refused(api, gpo):
    stale = read(api, gpo)["version_number"]
    write(api, gpo, path="\\\\dom.lan\\one")

    response = write(api, gpo, path="\\\\dom.lan\\two", expected_version=stale)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "gpo_version_conflict"
