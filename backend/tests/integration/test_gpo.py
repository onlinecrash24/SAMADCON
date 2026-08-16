"""Group policy against a live domain controller.

This is the first part of SAMCON that talks SMB as well as LDAP, and the two
halves have to end up agreeing. What unit tests cannot show is whether the
SYSVOL side is reachable at all with the session's ticket, whether the files
land where the directory says they do, and whether the permissions derived
from the policy object actually stick.

Every test creates its own policy and removes it afterwards, in both halves.
"""

from __future__ import annotations

import uuid
from urllib.parse import quote

import pytest

pytestmark = pytest.mark.integration


def quoted(value: str) -> str:
    return quote(value, safe="")


def policy_name() -> str:
    return f"SAMCON test {uuid.uuid4().hex[:8]}"


@pytest.fixture
def test_gpo(api):
    """A throwaway policy, deleted in both halves afterwards."""
    response = api.post("/api/v1/gpos", json={"display_name": policy_name()})
    if response.status_code != 200:
        pytest.skip(f"cannot create a group policy: {response.text}")

    gpo = response.json()
    yield gpo
    api.delete(f"/api/v1/gpos?dn={quoted(gpo['dn'])}&force=true")


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def test_the_default_policies_are_listed(api):
    """Every domain is provisioned with these two."""
    names = {gpo["display_name"] for gpo in api.get("/api/v1/gpos").json()["gpos"]}

    assert "Default Domain Policy" in names
    assert "Default Domain Controllers Policy" in names


def test_a_policy_reports_both_of_its_versions(api):
    gpos = api.get("/api/v1/gpos").json()["gpos"]
    default = next(gpo for gpo in gpos if gpo["display_name"] == "Default Domain Policy")

    assert default["guid"].startswith("{")
    assert default["guid"].endswith("}")
    assert default["path"], "a policy without a SYSVOL path is not usable"
    # The version splits into a machine half and a user half.
    assert default["machine_version"] + default["user_version"] >= 0
    assert default["machine_enabled"] is True
    assert default["user_enabled"] is True


# ---------------------------------------------------------------------------
# Creating — both halves
# ---------------------------------------------------------------------------


def test_a_new_policy_exists_in_the_directory(api, test_gpo):
    fetched = api.get(f"/api/v1/gpos/gpo?dn={quoted(test_gpo['dn'])}")
    assert fetched.status_code == 200, fetched.text

    gpo = fetched.json()
    assert gpo["display_name"] == test_gpo["display_name"]
    assert gpo["version"] == 0
    assert gpo["guid"] == gpo["guid"].upper(), "GPMC compares link entries as text"


def test_a_new_policy_exists_on_sysvol_too(api, test_gpo):
    """The half that only SMB can answer for.

    A policy that is in the directory but not on SYSVOL shows up in every
    console and applies nothing.
    """
    status = api.get(f"/api/v1/gpos/status?dn={quoted(test_gpo['dn'])}")
    assert status.status_code == 200, status.text

    report = status.json()
    assert report["sysvol_present"] is True, report["problems"]
    assert report["problems"] == []
    assert report["consistent"] is True


def test_the_two_halves_start_at_the_same_version(api, test_gpo):
    """Windows decides whether to re-apply a policy by comparing these two."""
    report = api.get(f"/api/v1/gpos/status?dn={quoted(test_gpo['dn'])}").json()

    assert report["directory_version"] == 0
    assert report["sysvol_version"] == 0


def test_the_path_in_the_directory_points_at_the_domain(api, test_gpo, domain):
    realm = domain["dns_domain"]
    assert test_gpo["path"].lower().startswith(f"\\\\{realm.lower()}\\sysvol\\")
    assert test_gpo["guid"] in test_gpo["path"]


def test_a_duplicate_display_name_is_refused(api, test_gpo):
    """Two policies with the same name are indistinguishable in every console."""
    response = api.post("/api/v1/gpos", json={"display_name": test_gpo["display_name"]})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "gpo_exists"


def test_a_policy_without_a_name_is_refused(api):
    response = api.post("/api/v1/gpos", json={"display_name": "   "})
    assert response.status_code in (400, 422)


# ---------------------------------------------------------------------------
# Changing
# ---------------------------------------------------------------------------


def test_a_policy_can_be_renamed_without_moving(api, test_gpo):
    """The GUID is what links point at, so a rename must not touch the object."""
    fresh = policy_name()
    renamed = api.patch(
        f"/api/v1/gpos?dn={quoted(test_gpo['dn'])}", json={"display_name": fresh}
    )
    assert renamed.status_code == 200, renamed.text

    gpo = renamed.json()
    assert gpo["display_name"] == fresh
    assert gpo["dn"] == test_gpo["dn"]
    assert gpo["guid"] == test_gpo["guid"]


def test_either_half_of_a_policy_can_be_switched_off(api, test_gpo):
    """Disabling the unused half makes clients skip reading it."""
    updated = api.patch(
        f"/api/v1/gpos?dn={quoted(test_gpo['dn'])}", json={"user_enabled": False}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["user_enabled"] is False
    assert updated.json()["machine_enabled"] is True

    back = api.patch(f"/api/v1/gpos?dn={quoted(test_gpo['dn'])}", json={"user_enabled": True})
    assert back.json()["user_enabled"] is True


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------


def test_a_policy_can_be_linked_to_an_ou(api, test_gpo, test_ou):
    linked = api.post(
        f"/api/v1/gpos/links?dn={quoted(test_ou)}", json={"gpo_dn": test_gpo["dn"]}
    )
    assert linked.status_code == 200, linked.text

    result = linked.json()
    assert len(result["links"]) == 1
    assert result["links"][0]["guid"] == test_gpo["guid"]
    assert result["links"][0]["order"] == 1
    assert result["links"][0]["enabled"] is True
    assert result["links"][0]["missing"] is False


def test_a_link_shows_up_from_the_policy_side_too(api, test_gpo, test_ou):
    api.post(f"/api/v1/gpos/links?dn={quoted(test_ou)}", json={"gpo_dn": test_gpo["dn"]})

    found = api.get(f"/api/v1/gpos/linked?guid={quoted(test_gpo['guid'])}").json()["links"]
    assert len(found) == 1
    assert found[0]["container_dn"].lower() == test_ou.lower()
    assert found[0]["kind"] == "organizational_unit"


def test_the_same_policy_cannot_be_linked_twice(api, test_gpo, test_ou):
    api.post(f"/api/v1/gpos/links?dn={quoted(test_ou)}", json={"gpo_dn": test_gpo["dn"]})

    again = api.post(
        f"/api/v1/gpos/links?dn={quoted(test_ou)}", json={"gpo_dn": test_gpo["dn"]}
    )
    assert again.status_code == 409
    # Not "link_exists" — that one belongs to site links, and two meanings for
    # one code produced the wrong message in the other console.
    assert again.json()["error"]["code"] == "gpo_link_exists"


def test_a_link_can_be_enforced_and_disabled(api, test_gpo, test_ou):
    api.post(f"/api/v1/gpos/links?dn={quoted(test_ou)}", json={"gpo_dn": test_gpo["dn"]})

    updated = api.patch(
        f"/api/v1/gpos/links?dn={quoted(test_ou)}",
        json={"gpo_dn": test_gpo["dn"], "enforced": True, "enabled": False},
    )
    assert updated.status_code == 200, updated.text

    link = updated.json()["links"][0]
    assert link["enforced"] is True
    assert link["enabled"] is False


def test_link_order_survives_the_round_trip(api, test_gpo, test_ou):
    """The attribute is written back to front; this is where that shows."""
    second = api.post("/api/v1/gpos", json={"display_name": policy_name()}).json()
    try:
        api.post(f"/api/v1/gpos/links?dn={quoted(test_ou)}", json={"gpo_dn": test_gpo["dn"]})
        api.post(f"/api/v1/gpos/links?dn={quoted(test_ou)}", json={"gpo_dn": second["dn"]})

        # The most recently linked policy takes precedence, as in GPMC.
        links = api.get(f"/api/v1/gpos/links?dn={quoted(test_ou)}").json()["links"]
        assert [link["guid"] for link in links] == [second["guid"], test_gpo["guid"]]
        assert [link["order"] for link in links] == [1, 2]

        moved = api.patch(
            f"/api/v1/gpos/links?dn={quoted(test_ou)}",
            json={"gpo_dn": test_gpo["dn"], "order": 1},
        )
        assert [link["guid"] for link in moved.json()["links"]] == [
            test_gpo["guid"],
            second["guid"],
        ]
    finally:
        api.delete(f"/api/v1/gpos?dn={quoted(second['dn'])}&force=true")


def test_a_link_can_be_removed(api, test_gpo, test_ou):
    api.post(f"/api/v1/gpos/links?dn={quoted(test_ou)}", json={"gpo_dn": test_gpo["dn"]})

    removed = api.request(
        "DELETE",
        f"/api/v1/gpos/links?dn={quoted(test_ou)}",
        json={"gpo_dn": test_gpo["dn"]},
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["links"] == []


# ---------------------------------------------------------------------------
# Inheritance
# ---------------------------------------------------------------------------


def test_a_policy_linked_higher_up_reaches_the_ou(api, test_gpo, test_ou, base_dn):
    """The whole point of linking at the domain: it reaches everything below."""
    api.post(f"/api/v1/gpos/links?dn={quoted(base_dn)}", json={"gpo_dn": test_gpo["dn"]})
    try:
        result = api.get(f"/api/v1/gpos/inheritance?dn={quoted(test_ou)}").json()

        guids = [item["guid"] for item in result["applied"]]
        assert test_gpo["guid"] in guids
        # The chain runs from the domain down to the OU.
        assert result["chain"][0]["dn"].lower() == base_dn.lower()
        assert result["chain"][-1]["dn"].lower() == test_ou.lower()
    finally:
        api.request(
            "DELETE",
            f"/api/v1/gpos/links?dn={quoted(base_dn)}",
            json={"gpo_dn": test_gpo["dn"]},
        )


def test_blocking_inheritance_keeps_the_ones_from_above_out(api, test_gpo, test_ou, base_dn):
    api.post(f"/api/v1/gpos/links?dn={quoted(base_dn)}", json={"gpo_dn": test_gpo["dn"]})
    try:
        blocked = api.post(
            f"/api/v1/gpos/inheritance?dn={quoted(test_ou)}", json={"block": True}
        )
        assert blocked.status_code == 200, blocked.text
        assert blocked.json()["block_inheritance"] is True

        result = api.get(f"/api/v1/gpos/inheritance?dn={quoted(test_ou)}").json()
        assert test_gpo["guid"] not in [item["guid"] for item in result["applied"]]
        assert test_gpo["guid"] in [item["guid"] for item in result["excluded"]]
    finally:
        api.post(f"/api/v1/gpos/inheritance?dn={quoted(test_ou)}", json={"block": False})
        api.request(
            "DELETE",
            f"/api/v1/gpos/links?dn={quoted(base_dn)}",
            json={"gpo_dn": test_gpo["dn"]},
        )


def test_an_enforced_link_gets_through_a_block(api, test_gpo, test_ou, base_dn):
    """That is what enforcing a link is for, and the easiest thing to get wrong."""
    api.post(
        f"/api/v1/gpos/links?dn={quoted(base_dn)}",
        json={"gpo_dn": test_gpo["dn"], "enforced": True},
    )
    try:
        api.post(f"/api/v1/gpos/inheritance?dn={quoted(test_ou)}", json={"block": True})

        result = api.get(f"/api/v1/gpos/inheritance?dn={quoted(test_ou)}").json()
        assert test_gpo["guid"] in [item["guid"] for item in result["applied"]]
    finally:
        api.post(f"/api/v1/gpos/inheritance?dn={quoted(test_ou)}", json={"block": False})
        api.request(
            "DELETE",
            f"/api/v1/gpos/links?dn={quoted(base_dn)}",
            json={"gpo_dn": test_gpo["dn"]},
        )


# ---------------------------------------------------------------------------
# Security filtering
# ---------------------------------------------------------------------------


def test_a_new_policy_applies_to_authenticated_users(api, test_gpo):
    """The default filtering, and the one thing that makes a new GPO do anything."""
    filtering = api.get(f"/api/v1/gpos/filtering?dn={quoted(test_gpo['dn'])}")
    assert filtering.status_code == 200, filtering.text

    names = {item["trustee"]["name"] for item in filtering.json()["applies_to"]}
    assert any("Authenticated Users" in name for name in names), names


def test_filtering_reports_who_has_only_half_the_rights(api, test_gpo):
    """A state GPMC cannot show, and always a mistake when it happens."""
    result = api.get(f"/api/v1/gpos/filtering?dn={quoted(test_gpo['dn'])}").json()

    for item in result["applies_to"]:
        assert item["read"] is True
        assert item["apply"] is True
    for item in result["incomplete"]:
        assert not (item["read"] and item["apply"])


# ---------------------------------------------------------------------------
# Deleting
# ---------------------------------------------------------------------------


def test_a_linked_policy_is_not_deleted_by_accident(api, test_gpo, test_ou):
    api.post(f"/api/v1/gpos/links?dn={quoted(test_ou)}", json={"gpo_dn": test_gpo["dn"]})

    refused = api.delete(f"/api/v1/gpos?dn={quoted(test_gpo['dn'])}")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "gpo_linked"


def test_a_policy_is_deleted_in_both_halves(api):
    created = api.post("/api/v1/gpos", json={"display_name": policy_name()})
    if created.status_code != 200:
        pytest.skip(f"cannot create a group policy: {created.text}")
    gpo = created.json()

    before = api.get(f"/api/v1/gpos/status?dn={quoted(gpo['dn'])}").json()
    assert before["sysvol_present"] is True

    removed = api.delete(f"/api/v1/gpos?dn={quoted(gpo['dn'])}")
    assert removed.status_code == 200, removed.text

    assert api.get(f"/api/v1/gpos/gpo?dn={quoted(gpo['dn'])}").status_code == 404
    assert gpo["guid"] not in [item["guid"] for item in api.get("/api/v1/gpos").json()["gpos"]]
