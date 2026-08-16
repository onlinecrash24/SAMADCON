"""Between a policy's state and its registry values.

This is the layer that decides whether an edit does anything, so the tests go
in both directions for every shape: what gets written, and what the same
values read back as.
"""

from __future__ import annotations

import pytest

from samcon.core.errors import InvalidRequest
from samcon.gpo import registry_pol
from samcon.gpo.admx.model import Element, EnumItem, Policy, Value, ValueItem
from samcon.gpo.admx.resolver import Entry, claims, entries_for, plan, state_of

KEY = "Software\\Policies\\Example"


def make_policy(**overrides) -> Policy:
    defaults = {
        "id": "Example:Test",
        "name": "Test",
        "policy_class": "Machine",
        "key": KEY,
        "value_name": "Enabled",
    }
    return Policy(**{**defaults, **overrides})


def current(*entries: tuple[str, str, int, object]) -> list[dict]:
    """A parsed Registry.pol, in the shape registry_pol.parse returns."""
    return [
        {
            "index": index,
            "key": key,
            "value": name,
            "type": registry_pol.type_name(type_id),
            "type_id": type_id,
            "size": 0,
            "data": data,
            "display": "",
        }
        for index, (key, name, type_id, data) in enumerate(entries)
    ]


# ---------------------------------------------------------------------------
# The three states
# ---------------------------------------------------------------------------


def test_a_policy_with_no_values_of_its_own_writes_one_by_default():
    """Most templates specify neither, and rely on 1 and 0."""
    policy = make_policy()

    enabled = entries_for(policy, "enabled")
    assert enabled == [Entry(KEY, "Enabled", registry_pol.REG_DWORD, 1)]

    disabled = entries_for(policy, "disabled")
    assert disabled == [Entry(KEY, "Enabled", registry_pol.REG_DWORD, 0)]


def test_not_configured_writes_nothing():
    """What has to disappear is worked out from what is actually there."""
    assert entries_for(make_policy(), "not_configured") == []


def test_the_values_from_the_template_win_over_the_defaults():
    policy = make_policy(
        enabled_value=Value("decimal", 2), disabled_value=Value("string", "off")
    )

    assert entries_for(policy, "enabled")[0].data == 2
    assert entries_for(policy, "disabled")[0] == Entry(
        KEY, "Enabled", registry_pol.REG_SZ, "off"
    )


def test_an_off_state_expressed_as_a_deletion_writes_a_marker():
    """Not the absence of an entry — a marker telling the client to remove
    the value it may already have.

    Verified against a GPO written by GPMC: value name prefixed with
    ``**del.``, REG_SZ, a single space as data. Leaving it out would let a
    setting made earlier survive being switched off.
    """
    policy = make_policy(disabled_value=Value("delete"))

    entry = entries_for(policy, "disabled")[0]
    assert entry.value_name == "**del.Enabled"
    assert entry.type == registry_pol.REG_SZ
    assert entry.data == " "


def test_an_unknown_state_is_refused():
    with pytest.raises(InvalidRequest) as raised:
        entries_for(make_policy(), "maybe")
    assert raised.value.code == "unknown_policy_state"


def test_a_value_list_is_written_alongside():
    policy = make_policy(
        enabled_list=(ValueItem(Value("decimal", 1), value_name="Extra"),),
    )
    written = entries_for(policy, "enabled")

    assert [entry.value_name for entry in written] == ["Enabled", "Extra"]


def test_a_list_item_may_write_into_another_key():
    policy = make_policy(
        value_name=None,
        enabled_list=(ValueItem(Value("decimal", 1), key="Other\\Key", value_name="Extra"),),
    )
    assert entries_for(policy, "enabled")[0].key == "Other\\Key"


# ---------------------------------------------------------------------------
# Elements — only while enabled
# ---------------------------------------------------------------------------


def test_elements_are_written_only_when_the_policy_is_enabled():
    """A form that keeps them while disabled shows what is not in the GPO."""
    policy = make_policy(
        elements=(Element(id="Interval", kind="decimal", value_name="Interval"),)
    )

    enabled = entries_for(policy, "enabled", {"Interval": 4})
    assert any(entry.value_name == "Interval" for entry in enabled)

    disabled = entries_for(policy, "disabled", {"Interval": 4})
    assert not any(entry.value_name == "Interval" for entry in disabled)


def test_a_number_is_written_as_a_dword():
    policy = make_policy(elements=(Element(id="N", kind="decimal", value_name="N"),))
    entry = entries_for(policy, "enabled", {"N": 7})[1]

    assert entry.type == registry_pol.REG_DWORD
    assert entry.data == 7


def test_a_number_stored_as_text_is_written_as_a_string():
    policy = make_policy(
        elements=(Element(id="N", kind="decimal", value_name="N", store_as_text=True),)
    )
    entry = entries_for(policy, "enabled", {"N": 7})[1]

    assert entry.type == registry_pol.REG_SZ
    assert entry.data == "7"


def test_a_long_number_is_written_as_a_qword():
    policy = make_policy(elements=(Element(id="N", kind="longDecimal", value_name="N"),))
    assert entries_for(policy, "enabled", {"N": 7})[1].type == registry_pol.REG_QWORD


def test_a_number_outside_its_range_is_refused():
    policy = make_policy(
        elements=(Element(id="N", kind="decimal", value_name="N", min_value=1, max_value=24),)
    )

    for value in (0, 25):
        with pytest.raises(InvalidRequest) as raised:
            entries_for(policy, "enabled", {"N": value})
        assert raised.value.code == "element_out_of_range"


def test_something_that_is_not_a_number_is_refused():
    policy = make_policy(elements=(Element(id="N", kind="decimal", value_name="N"),))
    with pytest.raises(InvalidRequest) as raised:
        entries_for(policy, "enabled", {"N": "four"})
    assert raised.value.code == "invalid_element_value"


def test_text_is_written_as_a_string():
    policy = make_policy(elements=(Element(id="T", kind="text", value_name="T"),))
    entry = entries_for(policy, "enabled", {"T": "value"})[1]

    assert entry.type == registry_pol.REG_SZ
    assert entry.data == "value"


def test_expandable_text_keeps_its_type():
    """Otherwise %SystemRoot% reaches the client as a literal string."""
    policy = make_policy(
        elements=(Element(id="T", kind="text", value_name="T", expandable=True),)
    )
    assert entries_for(policy, "enabled", {"T": "%SystemRoot%"})[1].type == (
        registry_pol.REG_EXPAND_SZ
    )


def test_text_longer_than_the_template_allows_is_refused():
    policy = make_policy(
        elements=(Element(id="T", kind="text", value_name="T", max_length=4),)
    )
    with pytest.raises(InvalidRequest) as raised:
        entries_for(policy, "enabled", {"T": "far too long"})
    assert raised.value.code == "element_too_long"


def test_multiple_lines_are_written_as_a_multi_string():
    policy = make_policy(elements=(Element(id="M", kind="multiText", value_name="M"),))
    entry = entries_for(policy, "enabled", {"M": ["one", "two"]})[1]

    assert entry.type == registry_pol.REG_MULTI_SZ
    assert entry.data == ["one", "two"]


def test_an_element_left_empty_is_not_written():
    """Which is what leaving a box empty in GPMC does."""
    policy = make_policy(elements=(Element(id="T", kind="text", value_name="T"),))
    assert entries_for(policy, "enabled", {}) == entries_for(policy, "enabled")


def test_a_required_element_left_empty_is_refused():
    policy = make_policy(
        elements=(Element(id="T", kind="text", value_name="T", required=True),)
    )
    with pytest.raises(InvalidRequest) as raised:
        entries_for(policy, "enabled", {})
    assert raised.value.code == "missing_element_value"


# ---------------------------------------------------------------------------
# Checkboxes and dropdowns
# ---------------------------------------------------------------------------


def test_a_checkbox_writes_one_of_two_values():
    policy = make_policy(
        elements=(
            Element(
                id="B",
                kind="boolean",
                value_name="B",
                true_value=Value("decimal", 1),
                false_value=Value("delete"),
            ),
        )
    )

    assert entries_for(policy, "enabled", {"B": True})[1].data == 1
    assert entries_for(policy, "enabled", {"B": False})[1].value_name == "**del.B"


def test_a_checkbox_without_values_falls_back_to_one_and_zero():
    policy = make_policy(elements=(Element(id="B", kind="boolean", value_name="B"),))

    assert entries_for(policy, "enabled", {"B": True})[1].data == 1
    assert entries_for(policy, "enabled", {"B": False})[1].data == 0


def test_a_dropdown_is_addressed_by_position():
    """Two items may write the same value through different lists."""
    policy = make_policy(
        elements=(
            Element(
                id="E",
                kind="enum",
                value_name="E",
                items=(
                    EnumItem("First", Value("decimal", 2)),
                    EnumItem("Second", Value("decimal", 4)),
                ),
            ),
        )
    )

    assert entries_for(policy, "enabled", {"E": 0})[1].data == 2
    assert entries_for(policy, "enabled", {"E": 1})[1].data == 4


def test_a_choice_that_does_not_exist_is_refused():
    policy = make_policy(
        elements=(
            Element(id="E", kind="enum", value_name="E", items=(EnumItem("Only", Value("decimal", 1)),)),
        )
    )
    with pytest.raises(InvalidRequest) as raised:
        entries_for(policy, "enabled", {"E": 5})
    assert raised.value.code == "invalid_element_value"


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------


def test_a_list_numbers_its_entries_from_the_prefix():
    policy = make_policy(
        value_name=None,
        elements=(Element(id="L", kind="list", key="Other\\Key", value_prefix="Ex"),),
    )

    written = entries_for(policy, "enabled", {"L": ["a", "b"]})

    assert [(entry.value_name, entry.data) for entry in written] == [("Ex1", "a"), ("Ex2", "b")]
    assert all(entry.key == "Other\\Key" for entry in written)


def test_a_list_with_explicit_values_writes_the_names_it_is_given():
    policy = make_policy(
        value_name=None,
        elements=(Element(id="L", kind="list", key="Other\\Key", explicit_value=True),),
    )

    written = entries_for(policy, "enabled", {"L": {"Name": "Data"}})
    assert [(entry.value_name, entry.data) for entry in written] == [("Name", "Data")]


def test_an_empty_list_writes_nothing():
    policy = make_policy(
        value_name=None, elements=(Element(id="L", kind="list", value_prefix="Ex"),)
    )
    assert entries_for(policy, "enabled", {"L": []}) == []


# ---------------------------------------------------------------------------
# Reading back
# ---------------------------------------------------------------------------


def test_an_absent_value_reads_as_not_configured():
    assert state_of(make_policy(), [])["state"] == "not_configured"


def test_a_policy_with_only_a_disabled_list_is_not_configured_when_empty():
    """`all([])` is true — which once made this policy report itself enabled.

    A policy that carries a <disabledList> and no <enabledList> has an empty
    list to check on the enabled side. Asking whether all of nothing is
    present answers yes, so an untouched GPO claimed the setting was on, in
    the status column of the listing and in the "only configured" filter that
    is supposed to hide it. Found on a fresh GPO against the Microsoft
    templates: two whole branches survived a filter that should have emptied
    the tree.
    """
    policy = make_policy(
        value_name=None,
        disabled_list=(ValueItem(Value("decimal", 0), value_name="Off"),),
    )

    assert state_of(policy, [])["state"] == "not_configured"


def test_a_policy_with_only_a_disabled_list_still_reads_as_disabled():
    policy = make_policy(
        value_name=None,
        disabled_list=(ValueItem(Value("decimal", 0), value_name="Off"),),
    )
    stored = current((KEY, "Off", registry_pol.REG_DWORD, 0))

    assert state_of(policy, stored)["state"] == "disabled"


def test_a_policy_with_only_an_enabled_list_is_not_configured_when_empty():
    policy = make_policy(
        value_name=None,
        enabled_list=(ValueItem(Value("decimal", 1), value_name="On"),),
    )

    assert state_of(policy, [])["state"] == "not_configured"


def test_the_written_state_reads_back(monkeypatch):
    policy = make_policy()

    for state in ("enabled", "disabled"):
        written = entries_for(policy, state)
        stored = current(*[(e.key, e.value_name, e.type, e.data) for e in written])
        assert state_of(policy, stored)["state"] == state


def test_a_value_matching_neither_reads_as_enabled():
    """GPMC shows it that way, and the value stays visible and correctable."""
    policy = make_policy()
    stored = current((KEY, "Enabled", registry_pol.REG_DWORD, 42))

    assert state_of(policy, stored)["state"] == "enabled"


def test_an_off_state_expressed_by_deletion_reads_as_not_configured():
    """It cannot be told from never having been set, and the effect is the same."""
    policy = make_policy(disabled_value=Value("delete"))
    assert state_of(policy, [])["state"] == "not_configured"


def test_element_values_read_back():
    policy = make_policy(
        elements=(
            Element(id="N", kind="decimal", value_name="N"),
            Element(id="T", kind="text", value_name="T"),
            Element(id="B", kind="boolean", value_name="B"),
        )
    )
    written = entries_for(policy, "enabled", {"N": 7, "T": "text", "B": True})
    stored = current(*[(e.key, e.value_name, e.type, e.data) for e in written])

    read = state_of(policy, stored)
    assert read["state"] == "enabled"
    assert read["values"] == {"N": 7, "T": "text", "B": True}


def test_a_dropdown_reads_back_as_its_position():
    policy = make_policy(
        elements=(
            Element(
                id="E",
                kind="enum",
                value_name="E",
                items=(EnumItem("First", Value("decimal", 2)), EnumItem("Second", Value("decimal", 4))),
            ),
        )
    )
    stored = current((KEY, "Enabled", registry_pol.REG_DWORD, 1), (KEY, "E", registry_pol.REG_DWORD, 4))

    assert state_of(policy, stored)["values"]["E"] == 1


def test_a_list_reads_back_in_order():
    """The numbering is what carries the order, and 10 must not sort before 2."""
    policy = make_policy(
        value_name=None,
        elements=(Element(id="L", kind="list", value_prefix="Ex"),),
    )
    stored = current(
        (KEY, "Ex2", registry_pol.REG_SZ, "b"),
        (KEY, "Ex10", registry_pol.REG_SZ, "j"),
        (KEY, "Ex1", registry_pol.REG_SZ, "a"),
    )

    assert state_of(policy, stored)["values"]["L"] == ["a", "b", "j"]


def test_a_policy_that_is_only_elements_reads_as_enabled_when_they_are_there():
    policy = make_policy(
        value_name=None, elements=(Element(id="T", kind="text", value_name="T"),)
    )
    stored = current((KEY, "T", registry_pol.REG_SZ, "value"))

    read = state_of(policy, stored)
    assert read["state"] == "enabled"
    assert read["values"] == {"T": "value"}


# ---------------------------------------------------------------------------
# What a policy owns
# ---------------------------------------------------------------------------


def test_a_policy_owns_its_own_value():
    assert claims(make_policy(), KEY, "Enabled") is True
    assert claims(make_policy(), KEY, "SomethingElse") is False


def test_ownership_ignores_case():
    """Registry names are case-insensitive, and templates are inconsistent."""
    assert claims(make_policy(), KEY.lower(), "enabled") is True


def test_a_policy_owns_its_elements_values():
    policy = make_policy(elements=(Element(id="N", kind="decimal", value_name="N"),))
    assert claims(policy, KEY, "N") is True


def test_a_policy_owns_the_numbered_values_of_its_lists():
    policy = make_policy(
        elements=(Element(id="L", kind="list", key="Other\\Key", value_prefix="Ex"),)
    )

    assert claims(policy, "Other\\Key", "Ex1") is True
    assert claims(policy, "Other\\Key", "Ex99") is True
    assert claims(policy, "Other\\Key", "Something") is False


def test_a_policy_does_not_own_what_another_wrote_into_the_same_key():
    """Keys are shared often enough that clearing one wholesale loses settings."""
    policy = make_policy()
    assert claims(policy, KEY, "AnotherPolicysValue") is False


# ---------------------------------------------------------------------------
# Planning a change
# ---------------------------------------------------------------------------


def test_enabling_a_policy_that_was_not_configured_only_writes():
    policy = make_policy()
    result = plan(policy, [], entries_for(policy, "enabled"))

    assert [entry.value_name for entry in result.set] == ["Enabled"]
    assert result.remove == []


def test_setting_a_policy_back_to_not_configured_removes_what_it_wrote():
    policy = make_policy(elements=(Element(id="N", kind="decimal", value_name="N"),))
    stored = current((KEY, "Enabled", registry_pol.REG_DWORD, 1), (KEY, "N", registry_pol.REG_DWORD, 4))

    result = plan(policy, stored, entries_for(policy, "not_configured"))

    assert result.set == []
    assert sorted(entry.value_name for entry in result.remove) == ["Enabled", "N"]


def test_a_value_another_policy_owns_is_left_alone():
    policy = make_policy()
    stored = current(
        (KEY, "Enabled", registry_pol.REG_DWORD, 1),
        (KEY, "SomethingElse", registry_pol.REG_DWORD, 1),
    )

    result = plan(policy, stored, entries_for(policy, "not_configured"))

    assert [entry.value_name for entry in result.remove] == ["Enabled"]


def test_an_unchanged_value_is_not_written_again():
    """Every write moves the version number and makes clients re-read."""
    policy = make_policy()
    stored = current((KEY, "Enabled", registry_pol.REG_DWORD, 1))

    result = plan(policy, stored, entries_for(policy, "enabled"))

    assert result.empty is True


def test_a_changed_value_is_written():
    policy = make_policy(elements=(Element(id="N", kind="decimal", value_name="N"),))
    stored = current((KEY, "Enabled", registry_pol.REG_DWORD, 1), (KEY, "N", registry_pol.REG_DWORD, 4))

    result = plan(policy, stored, entries_for(policy, "enabled", {"N": 8}))

    assert [(entry.value_name, entry.data) for entry in result.set] == [("N", 8)]
    assert result.remove == []


def test_shortening_a_list_removes_the_entries_that_are_gone():
    """The failure this prevents: a list that keeps its old tail forever."""
    policy = make_policy(
        value_name=None, elements=(Element(id="L", kind="list", value_prefix="Ex"),)
    )
    stored = current(
        (KEY, "Ex1", registry_pol.REG_SZ, "a"),
        (KEY, "Ex2", registry_pol.REG_SZ, "b"),
        (KEY, "Ex3", registry_pol.REG_SZ, "c"),
    )

    result = plan(policy, stored, entries_for(policy, "enabled", {"L": ["a"]}))

    assert result.set == []
    assert sorted(entry.value_name for entry in result.remove) == ["Ex2", "Ex3"]


def test_a_deletion_marker_is_written_even_when_the_value_is_absent():
    """The marker is for the client, not for this file.

    A machine may already carry the value from an earlier policy; the marker
    is what tells it to drop it. Skipping it because the GPO does not have
    the value would leave that machine as it was.
    """
    policy = make_policy(disabled_value=Value("delete"))

    result = plan(policy, [], entries_for(policy, "disabled"))

    assert [entry.value_name for entry in result.set] == ["**del.Enabled"]


def test_a_marker_that_is_already_there_is_not_written_again():
    policy = make_policy(disabled_value=Value("delete"))
    stored = current((KEY, "**del.Enabled", registry_pol.REG_SZ, " "))

    assert plan(policy, stored, entries_for(policy, "disabled")).empty is True


def test_switching_off_and_on_again_takes_the_marker_away():
    """Otherwise the policy would tell clients to remove the value it just set."""
    policy = make_policy(disabled_value=Value("delete"))
    stored = current((KEY, "**del.Enabled", registry_pol.REG_SZ, " "))

    result = plan(policy, stored, entries_for(policy, "enabled"))

    assert [entry.value_name for entry in result.set] == ["Enabled"]
    assert [entry.value_name for entry in result.remove] == ["**del.Enabled"]


def test_a_deletion_marker_reads_back_as_disabled():
    """It is not the same as never having been configured — GPMC shows the
    difference, and so does this."""
    policy = make_policy(disabled_value=Value("delete"))
    stored = current((KEY, "**del.Enabled", registry_pol.REG_SZ, " "))

    assert state_of(policy, stored)["state"] == "disabled"


def test_a_checkbox_switched_off_by_a_marker_reads_back_as_unticked():
    """Without this the box comes back unset rather than unticked, which is a
    different setting."""
    policy = make_policy(
        elements=(
            Element(
                id="B",
                kind="boolean",
                value_name="B",
                true_value=Value("decimal", 1),
                false_value=Value("delete"),
            ),
        )
    )
    stored = current(
        (KEY, "Enabled", registry_pol.REG_DWORD, 1),
        (KEY, "**del.B", registry_pol.REG_SZ, " "),
    )

    read = state_of(policy, stored)
    assert read["state"] == "enabled"
    assert read["values"]["B"] is False


def test_a_marker_belongs_to_whoever_owns_the_value():
    """So that setting the policy back to not configured takes it away too."""
    from samcon.gpo.admx.resolver import claims

    assert claims(make_policy(), KEY, "**del.Enabled") is True
    assert claims(make_policy(), KEY, "**del.SomethingElse") is False
