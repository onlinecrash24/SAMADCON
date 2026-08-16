"""Preferences in a real GPO.

The file format is covered without a domain in tests/unit/test_preferences.py,
byte for byte against files GPMC wrote. What needs a domain controller is
everything around it: the file landing in the right half, both extension
groups appearing on the right attribute, the right half of the version moving,
and — the one that would be found late and blamed on something else — that an
item's item-level targeting is still there after the item is edited.
"""

from __future__ import annotations

import uuid
from urllib.parse import quote

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.gpo]

NULL_CSE = "{00000000-0000-0000-0000-000000000000}"
DRIVES_CSE = "{5794DAFD-BE60-433F-88A2-1A31939AC01F}"
DRIVES_TOOL = "{2EA1A81B-48E5-45E9-8BB7-A6E3AC170006}"
REGISTRY_CSE = "{B087BE9D-ED37-454F-AF9C-04291E351182}"
REGISTRY_TOOL = "{BEE07A6A-EC9F-4659-B8C9-0B1937907C83}"
FILES_CSE = "{7150F9BF-48AD-4DA4-A49C-29EF4A8369BA}"
FILES_TOOL = "{3BAE7E51-E3F4-41D0-853D-9BB9FD47605F}"


def quoted(value: str) -> str:
    return quote(value, safe="")


@pytest.fixture
def gpo(api):
    response = api.post(
        "/api/v1/gpos", json={"display_name": f"SAMADCON pref {uuid.uuid4().hex[:8]}"}
    )
    if response.status_code != 200:
        pytest.skip(f"cannot create a group policy: {response.text}")

    created = response.json()
    yield created
    api.delete(f"/api/v1/gpos?dn={quoted(created['dn'])}&force=true")


def read(api, gpo, type_id, half):
    return api.get(
        f"/api/v1/gpos/preferences/type?dn={quoted(gpo['dn'])}&type={type_id}&half={half}"
    ).json()


def write(api, gpo, type_id, half, items, **extra):
    return api.post(
        f"/api/v1/gpos/preferences?dn={quoted(gpo['dn'])}",
        json={"type": type_id, "half": half, "items": items, **extra},
    )


def extensions(api, gpo, half="Machine"):
    entry = api.get(f"/api/v1/gpos/gpo?dn={quoted(gpo['dn'])}").json()
    return entry["machine_extensions" if half == "Machine" else "user_extensions"] or ""


REGISTRY_ITEM = {
    "action": "U",
    "properties": {
        "hive": "HKEY_LOCAL_MACHINE",
        "key": "SOFTWARE\\SAMADCON",
        "name": "Probe",
        "type": "REG_SZ",
        "value": "hallo",
    },
}

DRIVE_ITEM = {
    "action": "C",
    "properties": {"path": "\\\\server\\share", "letter": "K", "label": "Test"},
}


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def test_the_types_are_listed_with_their_fields(api):
    catalogue = api.get("/api/v1/gpos/preferences/types").json()
    types = {item["id"]: item for item in catalogue["types"]}

    assert catalogue["actions"] == ["C", "R", "U", "D"]
    assert types["drives"]["halves"] == ["User"]
    assert types["registry"]["halves"] == ["Machine", "User"]

    files = types["files"]["kinds"][0]
    assert [field["name"] for field in files["fields"]][:2] == ["fromPath", "targetPath"]
    # The action is not among the fields: the editor shows it in the item's
    # own heading, and only the catalogue needs to know where it sits on the
    # wire.
    assert all(field["kind"] != "action" for field in files["fields"])


def test_printers_carry_three_kinds_split_over_the_halves(api):
    catalogue = api.get("/api/v1/gpos/preferences/types").json()
    printers = next(item for item in catalogue["types"] if item["id"] == "printers")
    kinds = {kind["id"]: kind["halves"] for kind in printers["kinds"]}

    assert kinds == {"shared": ["User"], "port": ["Machine"], "local": ["Machine"]}


def test_a_fresh_policy_has_none_of_them(api, gpo):
    listed = api.get(f"/api/v1/gpos/preferences?dn={quoted(gpo['dn'])}").json()

    assert listed["version_number"] == 0
    for entry in listed["types"].values():
        assert all(half["present"] is False for half in entry["halves"].values())


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def test_a_registry_value_survives_the_round_trip(api, gpo):
    response = write(api, gpo, "registry", "Machine", [REGISTRY_ITEM])
    assert response.status_code == 200, response.text
    assert response.json()["changed"] is True

    listed = read(api, gpo, "registry", "Machine")
    assert listed["present"] is True
    item = listed["items"][0]
    assert item["properties"]["value"] == "hallo"
    # Derived here, not sent: the console shows the value name.
    assert item["name"] == "Probe"
    assert item["uid"].startswith("{")


def test_a_multi_sz_keeps_its_lines(api, gpo):
    write(
        api,
        gpo,
        "registry",
        "Machine",
        [
            {
                "action": "U",
                "properties": {"key": "SOFTWARE\\SAMADCON", "name": "Liste", "type": "REG_MULTI_SZ"},
                "values": ["eins", "zwei", "drei"],
            }
        ],
    )

    item = read(api, gpo, "registry", "Machine")["items"][0]
    assert item["values"] == ["eins", "zwei", "drei"]
    assert item["properties"]["value"] == "eins zwei drei"


def test_a_dword_is_stored_as_eight_hex_digits(api, gpo):
    write(
        api,
        gpo,
        "registry",
        "Machine",
        [
            {
                "action": "U",
                "properties": {"key": "SOFTWARE\\SAMADCON", "name": "Zahl", "type": "REG_DWORD",
                               "value": "255"},
            }
        ],
    )

    item = read(api, gpo, "registry", "Machine")["items"][0]
    assert item["properties"]["value"] == "000000FF"


def test_a_drive_map_lands_in_the_user_half(api, gpo):
    write(api, gpo, "drives", "User", [DRIVE_ITEM])

    listed = read(api, gpo, "drives", "User")
    assert listed["items"][0]["name"] == "K:"
    assert DRIVES_CSE in extensions(api, gpo, "User")
    assert not extensions(api, gpo, "Machine")


def test_both_extension_groups_are_registered(api, gpo):
    """A preference registers its own pair and one in the shared null group.

    Every GPO GPMC wrote has both. Only the second is obvious; the null group
    is what a hand-written implementation leaves out.
    """
    write(api, gpo, "registry", "Machine", [REGISTRY_ITEM])

    value = extensions(api, gpo, "Machine")
    assert value == f"[{NULL_CSE}{REGISTRY_TOOL}][{REGISTRY_CSE}{REGISTRY_TOOL}]"


def test_two_types_share_the_null_group(api, gpo):
    write(api, gpo, "registry", "Machine", [REGISTRY_ITEM])
    write(
        api,
        gpo,
        "files",
        "Machine",
        [{"action": "C", "properties": {"fromPath": "\\\\a\\b.txt",
                                        "targetPath": "C:\\Temp\\b.txt"}}],
    )

    value = extensions(api, gpo, "Machine")
    assert value == (
        f"[{NULL_CSE}{FILES_TOOL}{REGISTRY_TOOL}]"
        f"[{FILES_CSE}{FILES_TOOL}]"
        f"[{REGISTRY_CSE}{REGISTRY_TOOL}]"
    )


def test_dropping_one_type_leaves_the_others_registration(api, gpo):
    write(api, gpo, "registry", "Machine", [REGISTRY_ITEM])
    write(
        api,
        gpo,
        "files",
        "Machine",
        [{"action": "C", "properties": {"fromPath": "\\\\a\\b.txt",
                                        "targetPath": "C:\\Temp\\b.txt"}}],
    )
    write(api, gpo, "files", "Machine", [])

    value = extensions(api, gpo, "Machine")
    assert value == f"[{NULL_CSE}{REGISTRY_TOOL}][{REGISTRY_CSE}{REGISTRY_TOOL}]"
    assert read(api, gpo, "files", "Machine")["present"] is False


def test_only_the_written_half_moves(api, gpo):
    before = api.get(f"/api/v1/gpos/gpo?dn={quoted(gpo['dn'])}").json()

    write(api, gpo, "drives", "User", [DRIVE_ITEM])

    after = api.get(f"/api/v1/gpos/gpo?dn={quoted(gpo['dn'])}").json()
    assert after["user_version"] > before["user_version"]
    assert after["machine_version"] == before["machine_version"]


def test_writing_the_same_thing_twice_changes_nothing(api, gpo):
    """Including the version: the item's own timestamp only moves when the
    item does, so a save with nothing changed leaves the GPO alone."""
    assert write(api, gpo, "registry", "Machine", [REGISTRY_ITEM]).json()["changed"] is True
    stored = read(api, gpo, "registry", "Machine")["items"][0]
    before = api.get(f"/api/v1/gpos/gpo?dn={quoted(gpo['dn'])}").json()["machine_version"]

    # The same item, with the uid it came back with: only then is it the same
    # item rather than a second one.
    again = write(
        api,
        gpo,
        "registry",
        "Machine",
        [{"uid": stored["uid"], "action": stored["action"], "properties": stored["properties"]}],
    ).json()

    assert again["changed"] is False
    after = api.get(f"/api/v1/gpos/gpo?dn={quoted(gpo['dn'])}").json()["machine_version"]
    assert after == before


def test_an_edit_keeps_the_item_and_its_uid(api, gpo):
    write(api, gpo, "registry", "Machine", [REGISTRY_ITEM])
    stored = read(api, gpo, "registry", "Machine")["items"][0]

    write(
        api,
        gpo,
        "registry",
        "Machine",
        [{"uid": stored["uid"], "action": "U", "properties": {"value": "anders"}}],
    )

    after = read(api, gpo, "registry", "Machine")["items"][0]
    assert after["uid"] == stored["uid"]
    assert after["properties"]["value"] == "anders"
    # Everything not sent came from the file rather than from a default.
    assert after["properties"]["key"] == "SOFTWARE\\SAMADCON"


def test_the_halves_do_not_overwrite_each_other(api, gpo):
    write(api, gpo, "registry", "Machine", [REGISTRY_ITEM])
    write(
        api,
        gpo,
        "registry",
        "User",
        [{"action": "U", "properties": {"hive": "HKEY_CURRENT_USER", "key": "SOFTWARE\\SAMADCON",
                                        "name": "Benutzer", "type": "REG_SZ", "value": "du"}}],
    )

    listed = api.get(f"/api/v1/gpos/preferences?dn={quoted(gpo['dn'])}").json()["types"]
    assert listed["registry"]["halves"]["Machine"]["items"][0]["name"] == "Probe"
    assert listed["registry"]["halves"]["User"]["items"][0]["name"] == "Benutzer"


def test_clearing_removes_the_file_and_the_registration(api, gpo):
    """Not an empty file left behind: an extension registered with nothing to
    apply makes every client in scope fetch the policy on every refresh."""
    write(api, gpo, "registry", "Machine", [REGISTRY_ITEM])
    response = write(api, gpo, "registry", "Machine", [])

    assert response.json()["changed"] is True
    assert read(api, gpo, "registry", "Machine")["present"] is False
    assert not extensions(api, gpo, "Machine")


def test_a_password_cannot_be_planted(api, gpo):
    """cpassword is decryptable by anyone who can read the policy."""
    write(
        api,
        gpo,
        "drives",
        "User",
        [{"action": "C", "properties": {**DRIVE_ITEM["properties"], "cpassword": "AAAA"}}],
    )

    item = read(api, gpo, "drives", "User")["items"][0]
    assert "cpassword" not in item["properties"]
    assert item["has_password"] is False


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_an_unknown_type_is_refused(api, gpo):
    # Deliberately not a type that might exist later. This test named
    # "printers" until wave two added them, at which point it started
    # asserting that a working feature was broken.
    response = write(api, gpo, "nonesuch", "Machine", [])

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unknown_preference_type"


def test_a_drive_map_in_the_computer_half_is_refused(api, gpo):
    """GPMC offers the branch in the user half only."""
    response = write(api, gpo, "drives", "Machine", [DRIVE_ITEM])

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "preference_wrong_half"


def test_an_unknown_action_is_refused(api, gpo):
    response = write(
        api, gpo, "registry", "Machine", [{"action": "X", "properties": {"name": "a"}}]
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unknown_preference_action"


def test_a_dword_that_is_not_a_number_is_refused(api, gpo):
    response = write(
        api,
        gpo,
        "registry",
        "Machine",
        [{"action": "U", "properties": {"name": "a", "type": "REG_DWORD", "value": "viele"}}],
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "preference_dword_value"


def test_two_printer_kinds_share_one_file(api, gpo):
    """The only file that holds more than one kind of element."""
    response = write(
        api,
        gpo,
        "printers",
        "Machine",
        [
            {
                "kind": "port",
                "action": "C",
                "properties": {"ipAddress": "192.168.1.50", "localName": "SAMADCON-IP",
                               "path": "\\\\dc1\\Probe"},
            },
            {
                "kind": "local",
                "action": "C",
                "properties": {"name": "SAMADCON-Lokal", "port": "LPT1:", "location": "Buero"},
            },
        ],
    )
    assert response.status_code == 200, response.text

    items = read(api, gpo, "printers", "Machine")["items"]
    assert [item["kind"] for item in items] == ["port", "local"]
    assert items[0]["name"] == "192.168.1.50"
    # A local printer puts its location in the status line, not its name.
    assert items[1]["status"] == "Buero"


def test_an_environment_variable_states_its_value_in_the_status(api, gpo):
    write(
        api,
        gpo,
        "environment",
        "Machine",
        [{"action": "U", "properties": {"name": "SAMADCON_PROBE", "value": "eins"}}],
    )

    item = read(api, gpo, "environment", "Machine")["items"][0]
    assert item["name"] == "SAMADCON_PROBE"
    assert item["status"] == "SAMADCON_PROBE = eins"


def test_a_shared_printer_in_the_computer_half_is_refused(api, gpo):
    """GPMC offers the branch in the user half only — and the other two kinds
    of printer only in the computer half, in the same file."""
    response = write(
        api,
        gpo,
        "printers",
        "Machine",
        [{"kind": "shared", "action": "C", "properties": {"path": "\\\\dc1\\Probe"}}],
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "preference_wrong_half"


def test_an_unknown_kind_is_refused(api, gpo):
    response = write(
        api, gpo, "printers", "Machine", [{"kind": "nonesuch", "action": "C", "properties": {}}]
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unknown_preference_kind"


def test_a_group_keeps_its_members(api, gpo):
    response = write(
        api,
        gpo,
        "groups",
        "Machine",
        [
            {
                "kind": "group",
                "action": "C",
                "properties": {"groupName": "SAMADCON-Probe", "description": "Probe"},
                "members": [
                    {"name": "EXAMPLE\\Domain Admins", "action": "ADD"},
                    {"name": "EXAMPLE\\Domain Users", "action": "REMOVE"},
                ],
            }
        ],
    )
    assert response.status_code == 200, response.text

    item = read(api, gpo, "groups", "Machine")["items"][0]
    assert item["name"] == "SAMADCON-Probe"
    assert [(member["name"], member["action"]) for member in item["members"]] == [
        ("EXAMPLE\\Domain Admins", "ADD"),
        ("EXAMPLE\\Domain Users", "REMOVE"),
    ]
    # Wave three writes no `status` attribute at all.
    assert item["status"] == ""


def test_a_local_user_gets_no_password(api, gpo):
    """GPMC itself warns that cpassword is a known security risk. SAMADCON
    writes it empty and refuses anything sent for it."""
    write(
        api,
        gpo,
        "groups",
        "Machine",
        [
            {
                "kind": "user",
                "action": "U",
                "properties": {"userName": "samadcon-probe", "cpassword": "AAAA"},
            }
        ],
    )

    item = read(api, gpo, "groups", "Machine")["items"][0]
    assert item["properties"]["cpassword"] == ""
    assert item["has_password"] is False


def test_a_service_needs_no_action(api, gpo):
    response = write(
        api,
        gpo,
        "services",
        "Machine",
        [{"kind": "service", "properties": {"serviceName": "Spooler"}}],
    )
    assert response.status_code == 200, response.text

    item = read(api, gpo, "services", "Machine")["items"][0]
    assert item["action"] == ""
    assert item["properties"]["startupType"] == "AUTOMATIC"
    assert item["image"] == 2


def test_a_member_without_a_direction_is_refused(api, gpo):
    response = write(
        api,
        gpo,
        "groups",
        "Machine",
        [
            {
                "kind": "group",
                "action": "C",
                "properties": {"groupName": "X"},
                "members": [{"name": "EXAMPLE\\Domain Admins"}],
            }
        ],
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unknown_member_action"


def test_a_scheduled_task_cannot_be_created(api, gpo):
    response = write(
        api,
        gpo,
        "tasks",
        "Machine",
        [{"kind": "task_v2", "action": "C", "properties": {"name": "X"}}],
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "preference_not_creatable"


def test_a_concurrent_change_is_refused(api, gpo):
    stale = read(api, gpo, "registry", "Machine")["version_number"]
    write(api, gpo, "registry", "Machine", [REGISTRY_ITEM])

    response = write(
        api, gpo, "registry", "Machine", [REGISTRY_ITEM], expected_version=stale
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "gpo_version_conflict"
