"""Directory logic that does not need a DC: flags, group types, filters, ACLs."""

from __future__ import annotations

import pytest

from samcon.ad import directory, groups, sacl, uac
from samcon.core.errors import InvalidRequest

# ---------------------------------------------------------------------------
# userAccountControl
# ---------------------------------------------------------------------------


def test_decode_reports_named_flags():
    flags = uac.decode(uac.NORMAL_ACCOUNT | uac.ACCOUNTDISABLE)
    assert flags["account_disabled"] is True
    assert flags["normal_account"] is True
    assert flags["password_never_expires"] is False


def test_apply_sets_and_clears():
    value = uac.apply(uac.NORMAL_ACCOUNT, {"password_never_expires": True})
    assert value & uac.DONT_EXPIRE_PASSWD
    value = uac.apply(value, {"password_never_expires": False})
    assert not value & uac.DONT_EXPIRE_PASSWD


def test_apply_keeps_unrelated_bits():
    """Toggling one option must not clear the account type."""
    start = uac.NORMAL_ACCOUNT | uac.DONT_EXPIRE_PASSWD
    result = uac.apply(start, {"account_disabled": True})
    assert result & uac.NORMAL_ACCOUNT
    assert result & uac.DONT_EXPIRE_PASSWD
    assert result & uac.ACCOUNTDISABLE


def test_apply_ignores_none():
    assert uac.apply(uac.NORMAL_ACCOUNT, {"account_disabled": None}) == uac.NORMAL_ACCOUNT


def test_apply_rejects_readonly_flag():
    with pytest.raises(InvalidRequest) as excinfo:
        uac.apply(uac.NORMAL_ACCOUNT, {"locked_out": False})
    assert excinfo.value.code == "readonly_account_flag"


def test_apply_rejects_unknown_flag():
    with pytest.raises(InvalidRequest) as excinfo:
        uac.apply(uac.NORMAL_ACCOUNT, {"definitely_not_a_flag": True})
    assert excinfo.value.code == "unknown_account_flag"


def test_account_type_detection():
    assert uac.account_type(uac.NORMAL_ACCOUNT) == "user"
    assert uac.account_type(uac.WORKSTATION_TRUST_ACCOUNT) == "computer"
    assert uac.account_type(uac.SERVER_TRUST_ACCOUNT) == "domain_controller"


def test_dangerous_flags_are_flagged_for_the_ui():
    assert "trusted_for_delegation" in uac.DANGEROUS_FLAGS
    assert "no_preauth_required" in uac.DANGEROUS_FLAGS
    # Everything named dangerous must actually be editable, or the warning
    # would point at something nobody can change.
    assert set(uac.EDITABLE_FLAGS) >= uac.DANGEROUS_FLAGS


# ---------------------------------------------------------------------------
# groupType — signed 32-bit, the classic trap
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("scope", "security", "expected"),
    [
        ("global", True, -2147483646),
        ("domain_local", True, -2147483644),
        ("universal", True, -2147483640),
        ("global", False, 2),
        ("domain_local", False, 4),
        ("universal", False, 8),
    ],
)
def test_group_type_values_match_active_directory(scope: str, security: bool, expected: int):
    """AD rejects the positive form of a security group type."""
    assert groups.group_type_value(scope, security) == expected


def test_security_group_types_are_negative():
    for scope in ("global", "domain_local", "universal"):
        assert groups.group_type_value(scope, True) < 0


def test_group_type_round_trip():
    for scope in ("global", "domain_local", "universal"):
        for security in (True, False):
            value = groups.group_type_value(scope, security)
            assert directory.group_scope_name(value) == scope
            assert directory.is_security_group(value) is security


def test_unknown_scope_is_rejected():
    with pytest.raises(InvalidRequest) as excinfo:
        groups.group_type_value("nonsense", True)
    assert excinfo.value.code == "unknown_group_scope"


# ---------------------------------------------------------------------------
# Search filters
# ---------------------------------------------------------------------------


def test_filter_for_single_type():
    assert directory.build_filter(types=["user"]) == "(&(objectCategory=person)(objectClass=user))"


def test_filter_for_multiple_types_is_an_or():
    result = directory.build_filter(types=["user", "group"])
    assert result.startswith("(&(|") or result.startswith("(|")
    assert "objectCategory=group" in result


def test_filter_combines_type_and_query():
    result = directory.build_filter(types=["user"], query="max")
    assert result.startswith("(&")
    assert "(anr=max)" in result


def test_filter_escapes_the_query():
    """A wildcard typed into the search box must not widen the filter."""
    result = directory.build_filter(query="*")
    assert "(anr=\\2A)" in result


def test_filter_hides_advanced_objects_when_asked():
    result = directory.build_filter(include_advanced=False)
    assert "showInAdvancedViewOnly=TRUE" in result
    assert result.startswith("(!") or result.startswith("(&")


def test_filter_rejects_unknown_type():
    with pytest.raises(InvalidRequest) as excinfo:
        directory.build_filter(types=["banana"])
    assert excinfo.value.code == "unknown_object_type"


def test_empty_filter_matches_everything():
    assert directory.build_filter() == "(objectClass=*)"


def test_scope_names_map_to_ldb_constants():
    assert directory.base_scope("base") == 0
    assert directory.base_scope("one") == 1
    assert directory.base_scope("subtree") == 2
    with pytest.raises(InvalidRequest):
        directory.base_scope("sideways")


# ---------------------------------------------------------------------------
# Deletion protection (SDDL)
# ---------------------------------------------------------------------------

SDDL_UNPROTECTED = "O:DAG:DAD:AI(A;;RPWPCRCCDCLCLORCWOWDSDDTSW;;;DA)"
SDDL_PROTECTED = "O:DAG:DAD:AI(D;;SDDT;;;WD)(A;;RPWPCRCCDCLCLORCWOWDSDDTSW;;;DA)"


def test_protection_is_detected():
    assert sacl.is_delete_protected(SDDL_PROTECTED) is True


def test_absence_of_protection_is_detected():
    assert sacl.is_delete_protected(SDDL_UNPROTECTED) is False


def test_partial_deny_is_not_protection():
    """Denying delete but not delete-tree is not what ADUC calls protected."""
    assert sacl.is_delete_protected("D:(D;;SD;;;WD)") is False


def test_deny_for_someone_else_is_not_protection():
    assert sacl.is_delete_protected("D:(D;;SDDT;;;DA)") is False


def test_ace_is_inserted_after_the_dacl_flags():
    result = sacl._insert_ace("O:DAG:DAD:AI(A;;RP;;;DA)", "(D;;SDDT;;;WD)")
    assert result == "O:DAG:DAD:AI(D;;SDDT;;;WD)(A;;RP;;;DA)"
    assert sacl.is_delete_protected(result)


def test_ace_insertion_survives_an_empty_dacl():
    result = sacl._insert_ace("O:DAG:DAD:", "(D;;SDDT;;;WD)")
    assert sacl.is_delete_protected(result)
