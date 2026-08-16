"""End-to-end lifecycle tests against a live Samba AD DC."""

from __future__ import annotations

from urllib.parse import quote

import pytest

from tests.integration.conftest import TEST_ADMIN, unique

pytestmark = pytest.mark.integration


def q(dn: str) -> str:
    """DNs contain commas and spaces — always encode them into the query."""
    return quote(dn, safe="")


# ---------------------------------------------------------------------------
# Session and navigation
# ---------------------------------------------------------------------------


def test_session_reports_the_domain(api, domain):
    assert domain["base_dn"].upper().startswith("DC=")
    assert domain["dns_domain"]
    assert domain["dc_hostname"]


def test_whoami_resolves_the_signed_in_account(api):
    payload = api.get("/api/v1/auth/whoami").json()

    expected = TEST_ADMIN.split("@")[0].split("\\")[-1].lower()
    assert payload["sam_account_name"].lower() == expected
    # The account running these tests has to be able to create and delete
    # objects, so it belongs to an administrative group one way or another.
    assert payload["member_of"], "the signed-in account is in no groups at all"


def test_roots_include_the_domain_and_configuration(api, base_dn):
    roots = api.get("/api/v1/directory/roots").json()["roots"]
    kinds = {root["kind"] for root in roots}
    assert {"domain", "configuration", "schema"} <= kinds
    assert any(root["dn"] == base_dn for root in roots)


def test_tree_lists_containers(api, base_dn):
    nodes = api.get(f"/api/v1/directory/tree?dn={q(base_dn)}").json()["nodes"]
    names = {node["name"] for node in nodes}
    assert "Users" in names
    assert "Domain Controllers" in names
    assert all(node["is_container"] for node in nodes)


def test_the_tree_says_which_nodes_can_be_expanded(api, base_dn, test_ou):
    """The tree draws an expander only where there is something below.

    A node claiming to have children when it has none is worse than the other
    way round: the arrow disappears on click and the user wonders what broke.
    """
    # A sub-OU makes the throwaway OU a branch; the sub-OU itself is a leaf.
    sub_dn = api.post(
        "/api/v1/ous",
        json={"parent_dn": test_ou, "name": "leaf", "protect_from_deletion": False},
    ).json()["dn"]

    nodes = api.get(f"/api/v1/directory/tree?dn={q(test_ou)}").json()["nodes"]
    by_dn = {node["dn"]: node for node in nodes}
    assert by_dn[sub_dn]["has_children"] is False

    parent_nodes = api.get(f"/api/v1/directory/tree?dn={q(base_dn)}").json()["nodes"]
    ours = next(node for node in parent_nodes if node["dn"] == test_ou)
    assert ours["has_children"] is True


def test_containers_without_children_report_it(api, base_dn):
    """Whatever the domain happens to contain, the flag must be definite."""
    nodes = api.get(f"/api/v1/directory/tree?dn={q(base_dn)}").json()["nodes"]
    assert nodes
    for node in nodes:
        # None is allowed only as the documented "not determined" fallback,
        # which needs more siblings than a domain root usually has.
        assert node["has_children"] in (True, False)


def test_breadcrumb_path_starts_at_the_domain(api, base_dn, test_ou):
    path = api.get(f"/api/v1/directory/object/path?dn={q(test_ou)}").json()["path"]
    assert path[0]["dn"] == base_dn
    assert path[-1]["dn"] == test_ou


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


def test_user_lifecycle(api, test_ou):
    sam = unique("tu")

    created = api.post(
        "/api/v1/users",
        json={
            "parent_dn": test_ou,
            "sam_account_name": sam,
            "common_name": f"Test {sam}",
            "password": "Sup3rSecret!Pass",
            "enabled": True,
            "attributes": {"first_name": "Test", "last_name": "User", "mail": f"{sam}@test.lan"},
        },
    )
    assert created.status_code == 200, created.text
    user = created.json()
    dn = user["dn"]

    assert user["sam_account_name"] == sam
    assert user["status"]["disabled"] is False
    assert user["attributes"]["first_name"] == "Test"
    assert user["attributes"]["upn"] is not None

    # Read back
    fetched = api.get(f"/api/v1/users?dn={q(dn)}").json()
    assert fetched["dn"] == dn
    assert fetched["attributes"]["mail"] == f"{sam}@test.lan"

    # Update attributes
    patched = api.patch(
        f"/api/v1/users?dn={q(dn)}",
        json={"attributes": {"title": "Tester", "department": "QA"}},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["applied"]["title"]["new"] == "Tester"

    reread = api.get(f"/api/v1/users?dn={q(dn)}").json()
    assert reread["attributes"]["title"] == "Tester"

    # Account options
    flagged = api.patch(
        f"/api/v1/users?dn={q(dn)}", json={"flags": {"password_never_expires": True}}
    )
    assert flagged.status_code == 200
    assert api.get(f"/api/v1/users?dn={q(dn)}").json()["flags"]["password_never_expires"] is True

    # Disable / enable
    api.post(f"/api/v1/users/enabled?dn={q(dn)}", json={"enabled": False})
    assert api.get(f"/api/v1/users?dn={q(dn)}").json()["status"]["disabled"] is True
    api.post(f"/api/v1/users/enabled?dn={q(dn)}", json={"enabled": True})
    assert api.get(f"/api/v1/users?dn={q(dn)}").json()["status"]["disabled"] is False

    # Password reset with "must change at next logon"
    reset = api.post(
        f"/api/v1/users/password?dn={q(dn)}",
        json={"password": "An0therSecret!Pass", "must_change": True},
    )
    assert reset.status_code == 200, reset.text
    assert api.get(f"/api/v1/users?dn={q(dn)}").json()["status"]["must_change_password"] is True

    # Delete
    deleted = api.delete(f"/api/v1/directory/object?dn={q(dn)}")
    assert deleted.status_code == 200
    assert api.get(f"/api/v1/users?dn={q(dn)}").status_code == 404


def test_a_new_user_lands_in_domain_users(api, test_ou):
    """Primary group membership is stored on the member, not on the group.

    A new account belongs to "Domain Users" through primaryGroupID, which never
    appears in memberOf — so any view built only on memberOf makes a perfectly
    normal account look like it belongs to nothing.
    """
    dn = api.post(
        "/api/v1/users",
        json={
            "parent_dn": test_ou,
            "sam_account_name": unique("prim"),
            "password": "Sup3rSecret!Pass",
        },
    ).json()["dn"]

    detail = api.get(f"/api/v1/users?dn={q(dn)}").json()
    # 513 is the well-known RID of Domain Users.
    assert detail["primary_group_id"] == 513

    groups = api.get(f"/api/v1/groups/member-of?dn={q(dn)}").json()["groups"]
    names = {group["name"] for group in groups}
    assert names, "the account appears to be in no group at all"
    assert any(group["primary_group"] for group in groups)


def test_a_new_user_is_actually_enabled(api, test_ou):
    """The account is created disabled and enabled once it has a password;
    if that second step were lost, the account would look fine but not work."""
    dn = api.post(
        "/api/v1/users",
        json={
            "parent_dn": test_ou,
            "sam_account_name": unique("en"),
            "password": "Sup3rSecret!Pass",
            "enabled": True,
        },
    ).json()["dn"]

    detail = api.get(f"/api/v1/users?dn={q(dn)}").json()
    assert detail["status"]["disabled"] is False
    assert detail["flags"]["account_disabled"] is False
    assert detail["flags"]["normal_account"] is True


def test_a_new_user_can_be_created_without_forcing_a_password_change(api, test_ou):
    """pwdLastSet = 0 blocks some logon paths outright, so it must not be
    forced on when the caller did not ask for it."""
    dn = api.post(
        "/api/v1/users",
        json={
            "parent_dn": test_ou,
            "sam_account_name": unique("nochg"),
            "password": "Sup3rSecret!Pass",
            "must_change_password": False,
        },
    ).json()["dn"]

    status = api.get(f"/api/v1/users?dn={q(dn)}").json()["status"]
    assert status["must_change_password"] is False
    assert status["password_last_set"] is not None


def test_creating_an_enabled_user_without_a_password_is_refused(api, test_ou):
    response = api.post(
        "/api/v1/users",
        json={"parent_dn": test_ou, "sam_account_name": unique("np"), "enabled": True},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "password_required"


def test_duplicate_logon_name_is_refused(api, test_ou):
    sam = unique("dup")
    payload = {
        "parent_dn": test_ou,
        "sam_account_name": sam,
        "password": "Sup3rSecret!Pass",
    }
    assert api.post("/api/v1/users", json=payload).status_code == 200

    # Same sAMAccountName, different CN — must still be refused.
    payload["common_name"] = f"Other {sam}"
    response = api.post("/api/v1/users", json=payload)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "sam_account_name_taken"


def test_weak_password_reports_the_policy(api, test_ou):
    """The DC's complexity refusal must arrive as a policy message, not as
    'LDAP error 19'."""
    sam = unique("weak")
    response = api.post(
        "/api/v1/users",
        json={"parent_dn": test_ou, "sam_account_name": sam, "password": "a", "enabled": True},
    )
    if response.status_code == 200:
        pytest.skip("the test domain has password complexity disabled")
    assert response.json()["error"]["code"] in (
        "password_policy_violation",
        "constraint_violation",
    )


def test_a_failed_creation_leaves_nothing_behind(api, test_ou):
    """The add-then-set-password sequence must roll back on failure."""
    sam = unique("rb")
    response = api.post(
        "/api/v1/users",
        json={"parent_dn": test_ou, "sam_account_name": sam, "password": "a", "enabled": True},
    )
    if response.status_code == 200:
        pytest.skip("the test domain has password complexity disabled")

    listing = api.get(f"/api/v1/directory/children?dn={q(test_ou)}").json()
    assert not any(item.get("sam_account_name") == sam for item in listing["entries"])


def test_move_and_rename(api, test_ou, base_dn):
    sam = unique("mv")
    dn = api.post(
        "/api/v1/users",
        json={"parent_dn": test_ou, "sam_account_name": sam, "password": "Sup3rSecret!Pass"},
    ).json()["dn"]

    sub_dn = api.post(
        "/api/v1/ous",
        json={"parent_dn": test_ou, "name": "sub", "protect_from_deletion": False},
    ).json()["dn"]

    moved = api.post(f"/api/v1/directory/object/move?dn={q(dn)}", json={"target_dn": sub_dn})
    assert moved.status_code == 200, moved.text
    new_dn = moved.json()["dn"]
    assert new_dn.endswith(sub_dn)

    renamed = api.post(
        f"/api/v1/directory/object/rename?dn={q(new_dn)}", json={"name": f"Renamed {sam}"}
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["dn"].startswith(f"CN=Renamed {sam}")


def test_names_with_commas_survive_rename(api, test_ou):
    """A CN of "Muster, Max" must be escaped correctly in the DN."""
    sam = unique("cm")
    dn = api.post(
        "/api/v1/users",
        json={"parent_dn": test_ou, "sam_account_name": sam, "password": "Sup3rSecret!Pass"},
    ).json()["dn"]

    renamed = api.post(
        f"/api/v1/directory/object/rename?dn={q(dn)}", json={"name": "Muster, Max"}
    )
    assert renamed.status_code == 200, renamed.text
    new_dn = renamed.json()["dn"]
    assert "\\," in new_dn

    fetched = api.get(f"/api/v1/users?dn={q(new_dn)}")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Muster, Max"


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("scope", "security"),
    [("global", True), ("domain_local", True), ("universal", True), ("global", False)],
)
def test_group_types_round_trip(api, test_ou, scope: str, security: bool):
    """The signed groupType encoding is the classic place to get this wrong."""
    created = api.post(
        "/api/v1/groups",
        json={
            "parent_dn": test_ou,
            "name": unique(f"g-{scope}-"),
            "scope": scope,
            "security": security,
        },
    )
    assert created.status_code == 200, created.text
    group = created.json()
    assert group["scope"] == scope
    assert group["security_group"] is security

    reread = api.get(f"/api/v1/groups?dn={q(group['dn'])}").json()
    assert reread["scope"] == scope
    assert reread["security_group"] is security


def test_group_membership(api, test_ou):
    group_dn = api.post(
        "/api/v1/groups", json={"parent_dn": test_ou, "name": unique("grp")}
    ).json()["dn"]

    user_dns = [
        api.post(
            "/api/v1/users",
            json={
                "parent_dn": test_ou,
                "sam_account_name": unique("m"),
                "password": "Sup3rSecret!Pass",
            },
        ).json()["dn"]
        for _ in range(2)
    ]

    added = api.post(f"/api/v1/groups/members?dn={q(group_dn)}", json={"members": user_dns})
    assert added.status_code == 200, added.text
    assert len(added.json()["added"]) == 2

    members = api.get(f"/api/v1/groups/members?dn={q(group_dn)}").json()["members"]
    assert {m["dn"] for m in members} == set(user_dns)

    # Adding an existing member must not fail the whole request.
    again = api.post(f"/api/v1/groups/members?dn={q(group_dn)}", json={"members": user_dns})
    assert again.status_code == 200
    assert again.json()["added"] == []
    assert len(again.json()["already_members"]) == 2

    # The reverse view
    member_of = api.get(f"/api/v1/groups/member-of?dn={q(user_dns[0])}").json()["groups"]
    assert group_dn in {g["dn"] for g in member_of}

    removed = api.request(
        "DELETE",
        f"/api/v1/groups/members?dn={q(group_dn)}",
        json={"members": [user_dns[0]]},
    )
    assert removed.status_code == 200
    remaining = api.get(f"/api/v1/groups/members?dn={q(group_dn)}").json()["members"]
    assert {m["dn"] for m in remaining} == {user_dns[1]}


def test_nested_group_membership_is_resolved(api, test_ou):
    outer = api.post("/api/v1/groups", json={"parent_dn": test_ou, "name": unique("outer")}).json()
    inner = api.post("/api/v1/groups", json={"parent_dn": test_ou, "name": unique("inner")}).json()
    user = api.post(
        "/api/v1/users",
        json={
            "parent_dn": test_ou,
            "sam_account_name": unique("n"),
            "password": "Sup3rSecret!Pass",
        },
    ).json()

    api.post(f"/api/v1/groups/members?dn={q(outer['dn'])}", json={"members": [inner["dn"]]})
    api.post(f"/api/v1/groups/members?dn={q(inner['dn'])}", json={"members": [user["dn"]]})

    direct = api.get(f"/api/v1/groups/members?dn={q(outer['dn'])}").json()["members"]
    assert {m["dn"] for m in direct} == {inner["dn"]}

    nested = api.get(f"/api/v1/groups/members?dn={q(outer['dn'])}&recursive=true").json()["members"]
    assert {m["dn"] for m in nested} >= {inner["dn"], user["dn"]}

    upward = api.get(f"/api/v1/groups/member-of?dn={q(user['dn'])}&recursive=true").json()["groups"]
    assert {g["dn"] for g in upward} >= {inner["dn"], outer["dn"]}


def test_domain_users_shows_its_primary_members(api, base_dn):
    """Primary membership lives on the member, so the group looks empty
    without it."""
    resolved = api.get("/api/v1/directory/resolve?identifier=Domain%20Users").json()
    group_dn = resolved["dn"]

    without = api.get(
        f"/api/v1/groups/members?dn={q(group_dn)}&include_primary=false"
    ).json()["members"]
    with_primary = api.get(
        f"/api/v1/groups/members?dn={q(group_dn)}&include_primary=true"
    ).json()["members"]

    assert len(with_primary) > len(without)
    assert any(m["primary_group_member"] for m in with_primary)


# ---------------------------------------------------------------------------
# Computers
# ---------------------------------------------------------------------------


def test_computer_lifecycle(api, test_ou):
    name = unique("PC")[:15].upper()
    created = api.post(
        "/api/v1/computers",
        json={"parent_dn": test_ou, "name": name, "description": "test machine"},
    )
    assert created.status_code == 200, created.text
    computer = created.json()
    assert computer["sam_account_name"] == f"{name}$"
    assert computer["role"] == "computer"

    dn = computer["dn"]
    assert api.post(f"/api/v1/computers/reset?dn={q(dn)}").status_code == 200

    laps = api.get(f"/api/v1/computers/laps?dn={q(dn)}").json()
    assert laps["available"] is False  # nothing has enrolled this account

    assert api.delete(f"/api/v1/directory/object?dn={q(dn)}").status_code == 200


def test_computer_name_length_is_enforced(api, test_ou):
    response = api.post(
        "/api/v1/computers", json={"parent_dn": test_ou, "name": "THIS-NAME-IS-WAY-TOO-LONG"}
    )
    assert response.status_code == 422  # rejected by the schema before the DC


# ---------------------------------------------------------------------------
# Organizational units
# ---------------------------------------------------------------------------


def test_ou_deletion_protection(api, base_dn):
    name = unique("prot")
    created = api.post(
        "/api/v1/ous",
        json={"parent_dn": base_dn, "name": name, "protect_from_deletion": True},
    )
    assert created.status_code == 200, created.text
    dn = created.json()["dn"]
    assert created.json().get("delete_protected") is True

    refused = api.delete(f"/api/v1/ous?dn={q(dn)}")
    assert refused.status_code == 400
    assert refused.json()["error"]["code"] == "delete_protected"

    unprotected = api.patch(f"/api/v1/ous?dn={q(dn)}", json={"protect_from_deletion": False})
    assert unprotected.status_code == 200, unprotected.text

    assert api.delete(f"/api/v1/ous?dn={q(dn)}").status_code == 200


def test_non_empty_ou_is_not_deleted_by_accident(api, test_ou):
    api.post(
        "/api/v1/users",
        json={
            "parent_dn": test_ou,
            "sam_account_name": unique("keep"),
            "password": "Sup3rSecret!Pass",
        },
    )

    refused = api.delete(f"/api/v1/ous?dn={q(test_ou)}")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "not_empty"

    assert api.delete(f"/api/v1/ous?dn={q(test_ou)}&recursive=true").status_code == 200


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def test_search_finds_a_created_user(api, test_ou):
    sam = unique("srch")
    api.post(
        "/api/v1/users",
        json={
            "parent_dn": test_ou,
            "sam_account_name": sam,
            "password": "Sup3rSecret!Pass",
            "attributes": {"first_name": "Findme"},
        },
    )

    results = api.get(f"/api/v1/directory/search?q={sam}&types=user").json()["entries"]
    assert any(item["sam_account_name"] == sam for item in results)


def test_search_wildcard_is_escaped(api, base_dn):
    """A bare * must be searched for literally, not expanded into a match-all."""
    results = api.get("/api/v1/directory/search?q=*&types=user").json()["entries"]
    assert results == []


def test_type_filter_narrows_results(api, base_dn):
    groups = api.get(f"/api/v1/directory/children?dn={q(base_dn)}&types=group").json()["entries"]
    assert all(item["type"] == "group" for item in groups)


# ---------------------------------------------------------------------------
# Error surfaces
# ---------------------------------------------------------------------------


def test_missing_object_returns_404(api, base_dn):
    missing_dn = f"CN={unique('nope-')},{base_dn}"
    response = api.get(f"/api/v1/users?dn={q(missing_dn)}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def listing_dn(api, dn: str) -> str:
    return api.get(f"/api/v1/directory/object/attributes?dn={q(dn)}").json()["dn"]


def test_attribute_listing_marks_what_may_be_written(api, test_ou):
    """The editor takes this from the server rather than keeping its own list,
    so it cannot drift from what is actually enforced."""
    dn = api.post(
        "/api/v1/users",
        json={
            "parent_dn": test_ou,
            "sam_account_name": unique("attr"),
            "password": "Sup3rSecret!Pass",
        },
    ).json()["dn"]

    attributes = api.get(f"/api/v1/directory/object/attributes?dn={q(dn)}").json()["attributes"]

    # "dn" is part of every ldb.Message but is not an attribute — its value is
    # an ldb.Dn, and treating it as one raises.
    assert "dn" not in attributes
    assert listing_dn(api, dn) == dn

    # Directory-managed identity must never be offered for editing.
    assert attributes["objectSid"]["editable"] is False
    assert attributes["objectClass"]["editable"] is False
    assert attributes["name"]["editable"] is False
    # Binary values are excluded too — retyping base64 by hand corrupts objects.
    assert any(value.get("binary") for value in attributes["objectSid"]["values"])
    # Something ordinary has to remain editable, or the tab would be useless.
    assert attributes["userPrincipalName"]["editable"] is True


def test_an_attribute_can_be_written_and_removed(api, test_ou):
    dn = api.post(
        "/api/v1/users",
        json={
            "parent_dn": test_ou,
            "sam_account_name": unique("raw"),
            "password": "Sup3rSecret!Pass",
        },
    ).json()["dn"]

    written = api.patch(
        f"/api/v1/directory/object/attributes?dn={q(dn)}",
        json={"attributes": {"comment": "set through the attribute editor"}},
    )
    assert written.status_code == 200, written.text

    listing = api.get(f"/api/v1/directory/object/attributes?dn={q(dn)}").json()["attributes"]
    assert listing["comment"]["values"][0]["text"] == "set through the attribute editor"
    assert listing["comment"]["editable"] is True

    removed = api.patch(
        f"/api/v1/directory/object/attributes?dn={q(dn)}",
        json={"attributes": {"comment": None}},
    )
    assert removed.status_code == 200, removed.text
    assert "comment" not in api.get(
        f"/api/v1/directory/object/attributes?dn={q(dn)}"
    ).json()["attributes"]


def test_protected_attributes_are_refused(api, test_ou):
    dn = api.post(
        "/api/v1/users",
        json={
            "parent_dn": test_ou,
            "sam_account_name": unique("pa"),
            "password": "Sup3rSecret!Pass",
        },
    ).json()["dn"]

    response = api.patch(
        f"/api/v1/directory/object/attributes?dn={q(dn)}",
        json={"attributes": {"objectSid": "S-1-5-21-1-2-3-500"}},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "protected_attribute"
