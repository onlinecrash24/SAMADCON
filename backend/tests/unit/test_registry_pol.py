"""Registry.pol handling that does not need the Samba bindings.

The packing itself goes through samba.dcerpc.preg and is covered by the
integration tests; what is here is the part that decides what gets packed —
above all the size field, which is written into the file and makes every
following entry unreadable when it is wrong.
"""

from __future__ import annotations

import base64

import pytest

from samcon.core.errors import InvalidRequest
from samcon.gpo import registry_pol as pol

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "name"),
    [(1, "REG_SZ"), (4, "REG_DWORD"), (7, "REG_MULTI_SZ"), (11, "REG_QWORD")],
)
def test_a_known_type_gets_its_name(value, name):
    assert pol.type_name(value) == name
    assert pol.type_value(name) == value


def test_an_unknown_type_is_still_named():
    """A value we do not know must not make a whole policy unreadable."""
    assert pol.type_name(42) == "TYPE42"


def test_an_unknown_type_name_is_refused_when_writing():
    with pytest.raises(InvalidRequest) as raised:
        pol.type_value("REG_SOMETHING")
    assert raised.value.code == "unknown_registry_type"


# ---------------------------------------------------------------------------
# Sizes — the field that has to be right
# ---------------------------------------------------------------------------


def test_a_string_counts_its_terminator_and_two_bytes_per_character():
    # "on" -> 2 characters + 1 terminator, UTF-16.
    assert pol.data_size(pol.REG_SZ, "on") == 6
    assert pol.data_size(pol.REG_SZ, "") == 2


def test_an_expandable_string_is_sized_like_a_string():
    assert pol.data_size(pol.REG_EXPAND_SZ, "%SystemRoot%") == 26


def test_a_multi_string_carries_one_terminator_each_and_a_final_one():
    # "a" and "bb": (1+1)*2 + (2+1)*2 = 4 + 6, plus the closing 2.
    assert pol.data_size(pol.REG_MULTI_SZ, ["a", "bb"]) == 12
    assert pol.data_size(pol.REG_MULTI_SZ, []) == 2


def test_numbers_have_fixed_sizes():
    assert pol.data_size(pol.REG_DWORD, 1) == 4
    assert pol.data_size(pol.REG_QWORD, 1) == 8


def test_binary_data_is_its_own_length():
    assert pol.data_size(pol.REG_BINARY, b"\x00\x01\x02") == 3
    assert pol.data_size(pol.REG_BINARY, None) == 0


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------


def test_a_number_is_shown_in_both_bases():
    """Policy values are documented in hex and entered in decimal."""
    assert pol.format_data(pol.REG_DWORD, 16) == "16 (0x10)"


def test_a_multi_string_is_joined():
    assert pol.format_data(pol.REG_MULTI_SZ, ["one", "two"]) == "one; two"


def test_a_string_is_shown_as_it_is():
    assert pol.format_data(pol.REG_SZ, "value") == "value"
    assert pol.format_data(pol.REG_SZ, None) == ""


def test_binary_data_is_shown_as_its_length():
    """The bytes say nothing to a reader, and there can be many of them."""
    encoded = base64.b64encode(b"\x00" * 40).decode()
    assert pol.format_data(pol.REG_BINARY, encoded) == "<40 bytes>"


def test_a_type_name_works_as_well_as_its_number():
    assert pol.format_data("REG_DWORD", 3) == "3 (0x3)"


# ---------------------------------------------------------------------------
# Encoding what gets written
# ---------------------------------------------------------------------------


def test_a_number_given_as_text_is_accepted():
    """Form fields arrive as strings."""
    assert pol._encode_data(pol.REG_DWORD, "16") == 16


def test_something_that_is_not_a_number_is_refused():
    with pytest.raises(InvalidRequest) as raised:
        pol._encode_data(pol.REG_DWORD, "sixteen")
    assert raised.value.code == "invalid_registry_value"


def test_a_single_string_becomes_a_one_element_multi_string():
    assert pol._encode_data(pol.REG_MULTI_SZ, "only") == ["only"]


def test_binary_data_comes_in_as_base64():
    encoded = base64.b64encode(b"\x01\x02").decode()
    assert pol._encode_data(pol.REG_BINARY, encoded) == b"\x01\x02"


def test_binary_data_that_is_not_base64_is_refused():
    with pytest.raises(InvalidRequest):
        pol._encode_data(pol.REG_BINARY, "not base64 !!")


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------


def test_entries_are_grouped_under_their_key():
    """A flat list of a few hundred values is unreadable."""
    entries = [
        {"key": "Software\\Policies\\B", "value": "one", "type": "REG_DWORD", "data": 1},
        {"key": "Software\\Policies\\A", "value": "two", "type": "REG_DWORD", "data": 1},
        {"key": "Software\\Policies\\A", "value": "three", "type": "REG_DWORD", "data": 1},
    ]

    groups = pol.by_key(entries)

    assert [group["key"] for group in groups] == [
        "Software\\Policies\\A",
        "Software\\Policies\\B",
    ]
    assert [value["value"] for value in groups[0]["values"]] == ["two", "three"]


def test_grouping_an_empty_policy_gives_nothing():
    assert pol.by_key([]) == []
