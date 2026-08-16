"""Reading and editing access control lists.

Everything here manipulates SDDL as text. That makes the round trip through
Samba's parser safe, but it also means a mistake in the splitting or assembly
would silently rewrite an object's permissions — so the shape of every string
is pinned down.
"""

from __future__ import annotations

import pytest

from samcon.ad import delegation, rights, sacl
from samcon.core.errors import Conflict, InvalidRequest, NotFound

# A realistic descriptor: owner, group, an inherited allow ACE, a deny ACE and
# an object ACE granting the "reset password" extended right.
SDDL = (
    "O:DAG:DA"
    "D:AI"
    "(D;;SDDT;;;WD)"
    "(A;;RPWPCRCCDCLCLORCWOWDSDDTSW;;;DA)"
    "(OA;CIID;CR;00299570-246d-11d0-a768-00aa006e0529;;S-1-5-21-1-2-3-1105)"
)


# ---------------------------------------------------------------------------
# Access masks
# ---------------------------------------------------------------------------


def test_mask_decoding_names_each_right():
    mask = rights.SEC_ADS_READ_PROP | rights.SEC_ADS_WRITE_PROP
    assert rights.decode_mask(mask) == ["read_property", "write_property"]


def test_an_empty_mask_has_no_rights():
    assert rights.decode_mask(0) == []


def test_full_control_is_recognised():
    assert rights.is_full_control(rights.SEC_ADS_FULL_CONTROL) is True


def test_generic_all_counts_as_full_control():
    """Windows writes GA on some objects instead of the expanded mask."""
    assert rights.is_full_control(rights.SEC_GENERIC_ALL) is True


def test_a_partial_mask_is_not_full_control():
    assert rights.is_full_control(rights.SEC_ADS_READ_PROP) is False


# ---------------------------------------------------------------------------
# Splitting an SDDL string
# ---------------------------------------------------------------------------


def test_split_keeps_owner_and_dacl_flags_in_the_prefix():
    prefix, aces, suffix = sacl._split_dacl(SDDL)
    assert prefix == "O:DAG:DAD:AI"
    assert len(aces) == 3
    assert suffix == ""


def test_split_round_trips():
    """Reassembling untouched parts must reproduce the input exactly."""
    prefix, aces, suffix = sacl._split_dacl(SDDL)
    assert prefix + "".join(aces) + suffix == SDDL


def test_split_preserves_a_sacl():
    sddl = "O:DAG:DAD:(A;;RP;;;WD)S:(AU;SA;WDWO;;;WD)"
    prefix, aces, suffix = sacl._split_dacl(sddl)
    assert aces == ["(A;;RP;;;WD)"]
    assert suffix == "S:(AU;SA;WDWO;;;WD)"
    assert prefix + "".join(aces) + suffix == sddl


def test_split_handles_an_empty_dacl():
    assert sacl._split_dacl("O:DAG:DAD:")[1] == []


def test_split_rejects_a_descriptor_without_a_dacl():
    with pytest.raises(InvalidRequest) as excinfo:
        sacl._split_dacl("O:DAG:DA")
    assert excinfo.value.code == "no_dacl"


# ---------------------------------------------------------------------------
# ACE parsing
# ---------------------------------------------------------------------------


def test_ace_fields_are_parsed():
    parsed = sacl.parse_ace("(OA;CIID;CR;00299570-246d-11d0-a768-00aa006e0529;;S-1-5-21-1-2-3)")
    assert parsed["type"] == "OA"
    assert parsed["flags"] == "CIID"
    assert parsed["rights"] == "CR"
    assert parsed["object_guid"] == "00299570-246d-11d0-a768-00aa006e0529"
    assert parsed["trustee"] == "S-1-5-21-1-2-3"


def test_flags_are_split_pairwise():
    """A substring search would find "ID" inside unrelated combinations."""
    assert sacl.ace_flags("(A;OICIID;RP;;;WD)") == {"OI", "CI", "ID"}


def test_inherited_entries_are_detected():
    assert sacl.is_inherited_ace("(A;CIID;RP;;;WD)") is True
    assert sacl.is_inherited_ace("(A;CI;RP;;;WD)") is False
    assert sacl.is_inherited_ace("(A;;RP;;;WD)") is False


def test_a_malformed_ace_is_rejected():
    with pytest.raises(InvalidRequest) as excinfo:
        sacl.parse_ace("(A;;RP)")
    assert excinfo.value.code == "malformed_ace"


# ---------------------------------------------------------------------------
# Building an ACE
# ---------------------------------------------------------------------------


def test_a_plain_allow_ace():
    ace = sacl.build_ace(trustee_sid="S-1-5-21-1-2-3-1105", mask=rights.SEC_ADS_READ_PROP)
    assert ace == "(A;;0x00000010;;;S-1-5-21-1-2-3-1105)"


def test_a_deny_ace_uses_the_deny_type():
    ace = sacl.build_ace(
        trustee_sid="S-1-5-21-1-2-3-1105", mask=rights.SEC_STD_DELETE, deny=True
    )
    assert ace.startswith("(D;")


def test_an_object_ace_switches_type():
    """A GUID in the ACE means it is an object ACE — OA rather than A."""
    ace = sacl.build_ace(
        trustee_sid="S-1-5-21-1-2-3-1105",
        mask=rights.SEC_ADS_CONTROL_ACCESS,
        object_guid=delegation.RIGHT_RESET_PASSWORD,
        applies_to_guid=delegation.CLASS_USER,
    )
    parsed = sacl.parse_ace(ace)
    assert parsed["type"] == "OA"
    assert parsed["object_guid"] == delegation.RIGHT_RESET_PASSWORD
    assert parsed["applies_to_guid"] == delegation.CLASS_USER


def test_inheritance_adds_the_container_flag():
    ace = sacl.build_ace(
        trustee_sid="S-1-5-21-1-2-3-1105",
        mask=rights.SEC_ADS_READ_PROP,
        inherit_to_children=True,
    )
    assert "CI" in sacl.ace_flags(ace)


def test_the_mask_is_written_numerically():
    """Right abbreviations are easy to mis-transcribe; a hex mask is not."""
    ace = sacl.build_ace(trustee_sid="S-1-5-21-1-2-3", mask=0x00000130)
    assert sacl.parse_ace(ace)["rights"] == "0x00000130"


def test_braces_around_guids_are_stripped():
    ace = sacl.build_ace(
        trustee_sid="S-1-5-21-1-2-3",
        mask=rights.SEC_ADS_CONTROL_ACCESS,
        object_guid="{00299570-246d-11d0-a768-00aa006e0529}",
    )
    assert "{" not in ace


def test_an_empty_mask_is_refused():
    with pytest.raises(InvalidRequest) as excinfo:
        sacl.build_ace(trustee_sid="S-1-5-21-1-2-3", mask=0)
    assert excinfo.value.code == "empty_access_mask"


def test_a_missing_trustee_is_refused():
    with pytest.raises(InvalidRequest) as excinfo:
        sacl.build_ace(trustee_sid="", mask=rights.SEC_ADS_READ_PROP)
    assert excinfo.value.code == "missing_trustee"


# ---------------------------------------------------------------------------
# Adding and removing, with the descriptor faked out
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_acl(monkeypatch: pytest.MonkeyPatch):
    """Replaces the Samba round trip with in-memory SDDL."""
    state = {"sddl": SDDL, "written": None}

    monkeypatch.setattr(sacl, "read_sddl", lambda conn, dn: state["sddl"])

    def write(conn, dn, sddl):
        state["written"] = sddl
        state["sddl"] = sddl

    monkeypatch.setattr(sacl, "write_sddl", write)
    return state


def test_an_allow_ace_is_appended(fake_acl):
    ace = "(A;;0x00000010;;;S-1-5-21-9-9-9-1234)"
    sacl.add_ace(None, "CN=x", ace=ace)
    assert fake_acl["written"].endswith(ace)


def test_a_deny_ace_is_placed_before_the_allow_entries(fake_acl):
    """Deny before allow is the order the directory evaluates them in."""
    ace = "(D;;0x00010000;;;S-1-5-21-9-9-9-1234)"
    sacl.add_ace(None, "CN=x", ace=ace)

    _, aces, _ = sacl._split_dacl(fake_acl["written"])
    assert aces.index(ace) < next(
        index for index, existing in enumerate(aces) if existing.startswith("(A;")
    )


def test_adding_the_same_ace_twice_is_refused(fake_acl):
    ace = "(A;;0x00000010;;;S-1-5-21-9-9-9-1234)"
    sacl.add_ace(None, "CN=x", ace=ace)
    with pytest.raises(Conflict) as excinfo:
        sacl.add_ace(None, "CN=x", ace=ace)
    assert excinfo.value.code == "ace_exists"


def test_a_concurrent_change_is_detected(fake_acl):
    with pytest.raises(Conflict) as excinfo:
        sacl.add_ace(
            None,
            "CN=x",
            ace="(A;;0x00000010;;;S-1-5-21-9-9-9-1234)",
            expected_sddl="O:DAG:DAD:(A;;RP;;;WD)",
        )
    assert excinfo.value.code == "acl_changed"


def test_a_matching_expectation_is_accepted(fake_acl):
    sacl.add_ace(
        None, "CN=x", ace="(A;;0x00000010;;;S-1-5-21-9-9-9-1234)", expected_sddl=SDDL
    )
    assert fake_acl["written"] is not None


def test_an_entry_is_removed_by_index(fake_acl):
    # Index 1 is the explicit allow ACE for Domain Admins.
    sacl.remove_ace(None, "CN=x", index=1)
    _, aces, _ = sacl._split_dacl(fake_acl["written"])
    assert len(aces) == 2
    assert not any(ace.startswith("(A;;RPWP") for ace in aces)


def test_removing_an_inherited_entry_is_refused(fake_acl):
    # Index 2 carries the ID flag.
    with pytest.raises(InvalidRequest) as excinfo:
        sacl.remove_ace(None, "CN=x", index=2)
    assert excinfo.value.code == "ace_inherited"
    assert fake_acl["written"] is None, "nothing may be written when the entry is refused"


def test_removing_a_nonexistent_index_is_refused(fake_acl):
    with pytest.raises(NotFound) as excinfo:
        sacl.remove_ace(None, "CN=x", index=99)
    assert excinfo.value.code == "ace_not_found"


def test_removal_leaves_the_rest_untouched(fake_acl):
    prefix_before, _, suffix_before = sacl._split_dacl(SDDL)
    sacl.remove_ace(None, "CN=x", index=0)
    prefix_after, _, suffix_after = sacl._split_dacl(fake_acl["written"])
    assert (prefix_after, suffix_after) == (prefix_before, suffix_before)


# ---------------------------------------------------------------------------
# Delegation templates
# ---------------------------------------------------------------------------


def test_every_template_produces_usable_aces():
    for template in delegation.TEMPLATES:
        aces = delegation.build_aces(template.id, "S-1-5-21-1-2-3-1105")
        assert aces, f"{template.id} produced no ACEs"
        for ace in aces:
            parsed = sacl.parse_ace(ace)
            assert parsed["trustee"] == "S-1-5-21-1-2-3-1105"
            # Delegation is about the objects inside the container.
            assert "CI" in sacl.ace_flags(ace)


def test_password_reset_grants_the_extended_right():
    aces = delegation.build_aces("reset_user_passwords", "S-1-5-21-1-2-3-1105")
    guids = {sacl.parse_ace(ace)["object_guid"] for ace in aces}
    assert delegation.RIGHT_RESET_PASSWORD in guids


def test_password_reset_also_allows_forcing_a_change():
    """A help-desk reset without pwdLastSet is only half the task."""
    aces = delegation.build_aces("reset_user_passwords", "S-1-5-21-1-2-3-1105")
    guids = {sacl.parse_ace(ace)["object_guid"] for ace in aces}
    assert delegation.ATTR_PWD_LAST_SET in guids


def test_membership_delegation_targets_the_member_attribute():
    aces = delegation.build_aces("manage_group_membership", "S-1-5-21-1-2-3-1105")
    parsed = sacl.parse_ace(aces[0])
    assert parsed["object_guid"] == delegation.ATTR_MEMBER
    assert parsed["applies_to_guid"] == delegation.CLASS_GROUP


def test_an_unknown_template_is_rejected():
    with pytest.raises(NotFound) as excinfo:
        delegation.build_aces("no-such-task", "S-1-5-21-1-2-3")
    assert excinfo.value.code == "unknown_delegation_template"


def test_the_catalogue_is_serialisable():
    described = delegation.describe_templates()
    assert {item["id"] for item in described} == {t.id for t in delegation.TEMPLATES}
    assert all(item["ace_count"] > 0 for item in described)
