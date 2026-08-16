"""Security settings in a real GPO.

The file format is covered without a domain in tests/unit/test_security.py,
including a byte-for-byte comparison against the GptTmpl.inf GPMC produced.
What needs a domain controller is the rest: the file landing where Windows
looks for it, the extension being registered, only the computer half of the
version moving, and user rights coming back as accounts rather than SIDs.

Nothing here is ever linked anywhere. Password and lockout settings apply
domain-wide when a policy is linked at the root, and a test that locked out
the account it runs as would take the suite with it.
"""

from __future__ import annotations

import uuid
from urllib.parse import quote

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.gpo]

# Read off gPCMachineExtensionNames of a GPO created in GPMC.
SECURITY_CSE = "{827D319E-6EAC-11D2-A4EA-00C04F79F83A}"
SECURITY_TOOL = "{803E14A0-B4FB-11D0-A0D0-00A0C90F574B}"

ADMINISTRATORS = "S-1-5-32-544"


def quoted(value: str) -> str:
    return quote(value, safe="")


@pytest.fixture
def gpo(api):
    response = api.post(
        "/api/v1/gpos", json={"display_name": f"SAMCON security {uuid.uuid4().hex[:8]}"}
    )
    if response.status_code != 200:
        pytest.skip(f"cannot create a group policy: {response.text}")

    created = response.json()
    yield created
    api.delete(f"/api/v1/gpos?dn={quoted(created['dn'])}&force=true")


def read(api, gpo):
    return api.get(f"/api/v1/gpos/security?dn={quoted(gpo['dn'])}").json()


def write(api, gpo, **payload):
    payload.setdefault("section", "System Access")
    payload.setdefault("key", "MinimumPasswordLength")
    return api.post(f"/api/v1/gpos/security?dn={quoted(gpo['dn'])}", json=payload)


def machine_extensions(api, gpo):
    entry = api.get(f"/api/v1/gpos/gpo?dn={quoted(gpo['dn'])}").json()
    return (entry["machine_extensions"] or "").upper()


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def test_a_fresh_policy_has_no_security_settings(api, gpo):
    listed = read(api, gpo)

    assert listed["present"] is False
    assert listed["sections"] == {}
    assert listed["registered"] is False
    # The version comes even with nothing there — it is what a later write is
    # checked against.
    assert listed["version_number"] == 0


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def test_a_setting_survives_the_round_trip(api, gpo):
    response = write(api, gpo, value="14")
    assert response.status_code == 200, response.text
    assert response.json()["changed"] is True

    listed = read(api, gpo)
    assert listed["present"] is True
    assert listed["sections"]["System Access"]["MinimumPasswordLength"] == "14"


def test_writing_registers_the_extension_that_applies_it(api, gpo):
    write(api, gpo, value="14")

    assert read(api, gpo)["registered"] is True

    value = machine_extensions(api, gpo)
    assert SECURITY_CSE in value
    assert SECURITY_TOOL in value


def test_only_the_computer_half_moves(api, gpo):
    """Security settings are computer configuration; a user version that moved
    would make every session re-read a policy that says nothing to it."""
    before = api.get(f"/api/v1/gpos/gpo?dn={quoted(gpo['dn'])}").json()

    write(api, gpo, value="14")

    after = api.get(f"/api/v1/gpos/gpo?dn={quoted(gpo['dn'])}").json()
    assert after["machine_version"] > before["machine_version"]
    assert after["user_version"] == before["user_version"]


def test_writing_the_same_thing_twice_changes_nothing(api, gpo):
    write(api, gpo, value="14")
    again = write(api, gpo, value="14")

    assert again.json()["changed"] is False


def test_settings_in_different_sections_live_side_by_side(api, gpo):
    write(api, gpo, section="System Access", key="MinimumPasswordLength", value="14")
    write(api, gpo, section="Event Audit", key="AuditLogonEvents", value="3")

    sections = read(api, gpo)["sections"]
    assert sections["System Access"]["MinimumPasswordLength"] == "14"
    assert sections["Event Audit"]["AuditLogonEvents"] == "3"


def test_the_header_sections_are_not_reported_as_settings(api, gpo):
    """[Unicode] and [Version] are structure, not configuration. Listing them
    would show a policy as configured when it is not."""
    write(api, gpo, value="14")

    sections = read(api, gpo)["sections"]
    assert "Unicode" not in sections
    assert "Version" not in sections


# ---------------------------------------------------------------------------
# User rights
# ---------------------------------------------------------------------------


def test_a_user_right_comes_back_as_an_account(api, gpo):
    """A list of SIDs in the file, a list of accounts in every console. The
    resolution is the ACL editor's, cache and all."""
    write(
        api,
        gpo,
        section="Privilege Rights",
        key="SeSystemtimePrivilege",
        value=[ADMINISTRATORS],
    )

    trustees = read(api, gpo)["sections"]["Privilege Rights"]["SeSystemtimePrivilege"]
    assert [item["sid"] for item in trustees] == [ADMINISTRATORS]
    assert trustees[0]["name"] and trustees[0]["name"] != ADMINISTRATORS


def test_a_user_right_can_hold_several_accounts(api, gpo):
    write(
        api,
        gpo,
        section="Privilege Rights",
        key="SeDenyBatchLogonRight",
        value=[ADMINISTRATORS, "S-1-5-32-546"],
    )

    trustees = read(api, gpo)["sections"]["Privilege Rights"]["SeDenyBatchLogonRight"]
    assert [item["sid"] for item in trustees] == [ADMINISTRATORS, "S-1-5-32-546"]


# ---------------------------------------------------------------------------
# Taking it away
# ---------------------------------------------------------------------------


def test_clearing_the_last_setting_unregisters_the_extension(api, gpo):
    """A file holding only its two header sections configures nothing, and a
    registered extension for it makes every client fetch the policy on each
    refresh and find nothing there."""
    write(api, gpo, value="14")
    assert read(api, gpo)["registered"] is True

    write(api, gpo, value=None)

    listed = read(api, gpo)
    assert listed["sections"].get("System Access") in ({}, None)
    assert listed["registered"] is False
    assert SECURITY_CSE not in machine_extensions(api, gpo)


def test_the_extension_stays_while_another_setting_is_there(api, gpo):
    write(api, gpo, section="System Access", key="MinimumPasswordLength", value="14")
    write(api, gpo, section="Event Audit", key="AuditLogonEvents", value="3")

    write(api, gpo, section="System Access", key="MinimumPasswordLength", value=None)

    assert read(api, gpo)["registered"] is True


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_a_key_that_would_open_a_section_is_refused(api, gpo):
    """Not path traversal — a key never reaches the file system. The danger is
    a second line: a bracket or a newline turns one setting into two, and the
    second one can be a user right nobody granted."""
    response = write(api, gpo, key="Min[Privilege Rights]", value="1")

    assert response.status_code == 422


def test_a_value_with_a_line_break_is_refused(api, gpo):
    """The one that was not checked at all until a test asked."""
    response = write(
        api,
        gpo,
        value="8\r\n[Privilege Rights]\r\nSeDebugPrivilege = *S-1-5-32-544",
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsafe_security_value"

    # And nothing was written on the way to refusing.
    assert read(api, gpo)["present"] is False


def test_a_registry_path_is_a_valid_key(api, gpo):
    """[Registry Values] keys are registry paths; refusing backslashes would
    refuse half the section."""
    response = write(
        api,
        gpo,
        section="Registry Values",
        key="MACHINE\\Software\\Microsoft\\Windows\\CurrentVersion\\Policies\\System\\EnableLUA",
        value="4,1",
    )

    assert response.status_code == 200, response.text


def test_a_concurrent_change_is_refused(api, gpo):
    stale = read(api, gpo)["version_number"]
    write(api, gpo, value="14")

    response = write(api, gpo, value="16", expected_version=stale)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "gpo_version_conflict"


# ---------------------------------------------------------------------------
# Restricted groups
# ---------------------------------------------------------------------------


def restricted_group(api, gpo, sid, present):
    return api.post(
        f"/api/v1/gpos/security/restricted-group?dn={quoted(gpo['dn'])}",
        json={"sid": sid, "present": present},
    )


def test_a_restricted_group_can_be_added_and_taken_back_out(api, gpo):
    """A group here is two keys, not one. Removing it clears both in a single
    write — two writes would raise the version in between, and the second
    would come back as somebody else's change."""
    added = restricted_group(api, gpo, f"*{ADMINISTRATORS}", True)
    assert added.status_code == 200, added.text

    section = read(api, gpo)["sections"]["Group Membership"]
    assert f"*{ADMINISTRATORS}__Memberof" in section

    removed = restricted_group(api, gpo, f"*{ADMINISTRATORS}", False)
    assert removed.status_code == 200, removed.text

    section = read(api, gpo)["sections"].get("Group Membership", {})
    assert not [key for key in section if ADMINISTRATORS in key]


def test_removing_a_group_takes_its_members_with_it(api, gpo):
    restricted_group(api, gpo, f"*{ADMINISTRATORS}", True)
    write(
        api,
        gpo,
        section="Group Membership",
        key=f"*{ADMINISTRATORS}__Members",
        value=["S-1-5-32-544"],
    )

    restricted_group(api, gpo, f"*{ADMINISTRATORS}", False)

    section = read(api, gpo)["sections"].get("Group Membership", {})
    assert not [key for key in section if ADMINISTRATORS in key]


def test_a_group_name_that_is_not_a_sid_is_refused(api, gpo):
    """GPMC names a restricted group by its SID. Anything else produces a key
    no client resolves and no console shows as the group it meant."""
    response = restricted_group(api, gpo, "Administratoren", True)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsafe_security_key"
