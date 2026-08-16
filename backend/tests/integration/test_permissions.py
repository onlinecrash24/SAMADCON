"""Permissions against a live domain controller.

The SDDL round trip is what these check: our text manipulation has to survive
Samba's parser and come back as the same descriptor, and an ACE we write has
to be readable as the entry we meant.
"""

from __future__ import annotations

from urllib.parse import quote

import pytest

from tests.integration.conftest import unique

pytestmark = pytest.mark.integration


def q(dn: str) -> str:
    return quote(dn, safe="")


@pytest.fixture
def test_group(api, test_ou):
    """A group to hand permissions to."""
    return api.post(
        "/api/v1/groups", json={"parent_dn": test_ou, "name": unique("acl-grp")}
    ).json()


def test_reading_an_acl_resolves_names(api, test_ou):
    acl = api.get(f"/api/v1/security/acl?dn={q(test_ou)}").json()

    assert acl["aces"], "a fresh OU always inherits permissions"
    assert acl["sddl"].startswith("O:")

    # Every entry must name its trustee; a bare SID would be useless in a UI.
    for ace in acl["aces"]:
        assert ace["trustee"]["name"]
        assert ace["type"] in ("allow", "deny")
        assert isinstance(ace["rights"], list)

    # Well-known SIDs are resolved from the table, not left as numbers.
    names = {ace["trustee"]["name"] for ace in acl["aces"]}
    assert any(name in names for name in ("Administrators", "System", "Authenticated Users"))


def test_most_entries_on_a_fresh_ou_are_inherited(api, test_ou):
    acl = api.get(f"/api/v1/security/acl?dn={q(test_ou)}").json()
    assert any(ace["inherited"] for ace in acl["aces"])


def test_an_entry_can_be_added_and_removed(api, test_ou, test_group):
    before = api.get(f"/api/v1/security/acl?dn={q(test_ou)}").json()

    added = api.post(
        f"/api/v1/security/acl/entries?dn={q(test_ou)}",
        json={
            "trustee_sid": test_group["sid"],
            # Read properties + list contents + read permissions.
            "mask": 0x00000010 | 0x00000004 | 0x00020000,
            "inherit_to_children": True,
            "expected_sddl": before["sddl"],
        },
    )
    assert added.status_code == 200, added.text

    after = api.get(f"/api/v1/security/acl?dn={q(test_ou)}").json()
    mine = [ace for ace in after["aces"] if ace["trustee"]["sid"] == test_group["sid"]]
    assert len(mine) == 1
    entry = mine[0]
    assert entry["type"] == "allow"
    assert entry["inherited"] is False
    assert entry["applies_to_children"] is True
    assert "read_property" in entry["rights"]

    removed = api.request(
        "DELETE",
        f"/api/v1/security/acl/entries?dn={q(test_ou)}",
        json={"index": entry["index"], "expected_sddl": after["sddl"]},
    )
    assert removed.status_code == 200, removed.text

    final = api.get(f"/api/v1/security/acl?dn={q(test_ou)}").json()
    assert not [ace for ace in final["aces"] if ace["trustee"]["sid"] == test_group["sid"]]


def test_the_rest_of_the_acl_survives_an_edit(api, test_ou, test_group):
    """Our text splicing must not disturb entries it did not touch."""
    before = api.get(f"/api/v1/security/acl?dn={q(test_ou)}").json()
    before_others = sorted(
        (ace["trustee"]["sid"], ace["mask"], ace["type"]) for ace in before["aces"]
    )

    api.post(
        f"/api/v1/security/acl/entries?dn={q(test_ou)}",
        json={"trustee_sid": test_group["sid"], "mask": 0x00000010},
    )
    after = api.get(f"/api/v1/security/acl?dn={q(test_ou)}").json()
    after_others = sorted(
        (ace["trustee"]["sid"], ace["mask"], ace["type"])
        for ace in after["aces"]
        if ace["trustee"]["sid"] != test_group["sid"]
    )

    assert after_others == before_others
    assert after["owner"] == before["owner"]


def test_a_deny_entry_is_placed_before_the_allow_entries(api, test_ou, test_group):
    api.post(
        f"/api/v1/security/acl/entries?dn={q(test_ou)}",
        json={"trustee_sid": test_group["sid"], "mask": 0x00010000, "deny": True},
    )

    aces = api.get(f"/api/v1/security/acl?dn={q(test_ou)}").json()["aces"]
    explicit = [ace for ace in aces if not ace["inherited"]]
    deny_positions = [i for i, ace in enumerate(explicit) if ace["type"] == "deny"]
    allow_positions = [i for i, ace in enumerate(explicit) if ace["type"] == "allow"]

    if deny_positions and allow_positions:
        assert max(deny_positions) < min(allow_positions)


def test_inherited_entries_cannot_be_removed(api, test_ou):
    acl = api.get(f"/api/v1/security/acl?dn={q(test_ou)}").json()
    inherited = next((ace for ace in acl["aces"] if ace["inherited"]), None)
    if inherited is None:
        pytest.skip("this OU has no inherited entries")

    response = api.request(
        "DELETE",
        f"/api/v1/security/acl/entries?dn={q(test_ou)}",
        json={"index": inherited["index"], "expected_sddl": acl["sddl"]},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ace_inherited"


def test_a_concurrent_change_is_refused(api, test_ou, test_group):
    """Two administrators editing one ACL must not silently overwrite."""
    stale = api.get(f"/api/v1/security/acl?dn={q(test_ou)}").json()["sddl"]

    api.post(
        f"/api/v1/security/acl/entries?dn={q(test_ou)}",
        json={"trustee_sid": test_group["sid"], "mask": 0x00000010},
    )

    response = api.post(
        f"/api/v1/security/acl/entries?dn={q(test_ou)}",
        json={"trustee_sid": test_group["sid"], "mask": 0x00000020, "expected_sddl": stale},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "acl_changed"


def test_delegating_password_resets(api, test_ou, test_group):
    """The template has to produce entries the directory accepts and reports
    back as the extended right we intended."""
    response = api.post(
        f"/api/v1/security/delegation?dn={q(test_ou)}",
        json={"template_id": "reset_user_passwords", "trustee_sid": test_group["sid"]},
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["applied"]) == 2

    aces = api.get(f"/api/v1/security/acl?dn={q(test_ou)}").json()["aces"]
    mine = [ace for ace in aces if ace["trustee"]["sid"] == test_group["sid"]]
    assert len(mine) == 2

    # The extended right is resolved to its display name from the directory's
    # own catalogue, not from a hard-coded table.
    names = {ace.get("object", {}).get("name", "") for ace in mine}
    assert any("password" in name.lower() for name in names)
    assert all(ace["applies_to_children"] for ace in mine)


def test_every_delegation_template_is_accepted_by_the_directory(api, test_ou, test_group):
    templates = api.get("/api/v1/security/delegation/templates").json()["templates"]
    assert templates

    for template in templates:
        response = api.post(
            f"/api/v1/security/delegation?dn={q(test_ou)}",
            json={"template_id": template["id"], "trustee_sid": test_group["sid"]},
        )
        assert response.status_code == 200, f"{template['id']}: {response.text}"


def test_an_unknown_template_is_rejected(api, test_ou, test_group):
    response = api.post(
        f"/api/v1/security/delegation?dn={q(test_ou)}",
        json={"template_id": "not-a-task", "trustee_sid": test_group["sid"]},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "unknown_delegation_template"


def test_a_malformed_sid_is_rejected_before_the_directory(api, test_ou):
    response = api.post(
        f"/api/v1/security/acl/entries?dn={q(test_ou)}",
        json={"trustee_sid": "not-a-sid", "mask": 0x00000010},
    )
    assert response.status_code == 422


def test_deletion_protection_round_trips(api, test_ou):
    protection = api.get(f"/api/v1/security/protection?dn={q(test_ou)}").json()
    assert protection["delete_protected"] is False

    api.post(f"/api/v1/security/protection?dn={q(test_ou)}", json={"protect": True})
    assert api.get(f"/api/v1/security/protection?dn={q(test_ou)}").json()["delete_protected"] is True

    api.post(f"/api/v1/security/protection?dn={q(test_ou)}", json={"protect": False})
    assert (
        api.get(f"/api/v1/security/protection?dn={q(test_ou)}").json()["delete_protected"] is False
    )
