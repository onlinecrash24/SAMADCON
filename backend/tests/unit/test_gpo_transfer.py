"""Backup archives and WMI filter attributes."""

from __future__ import annotations

import pytest

from samadcon.gpo import transfer, wmi

# ---------------------------------------------------------------------------
# Archive member names
# ---------------------------------------------------------------------------


def test_a_plain_relative_name_becomes_a_share_path():
    assert transfer._safe_relative("Machine/Registry.pol") == "Machine\\Registry.pol"
    assert transfer._safe_relative("GPT.INI") == "GPT.INI"


def test_backslashes_in_the_archive_are_accepted():
    """Archives written on Windows use them."""
    assert transfer._safe_relative("Machine\\Scripts\\scripts.ini") == (
        "Machine\\Scripts\\scripts.ini"
    )


def test_redundant_parts_are_dropped():
    assert transfer._safe_relative("./Machine//Registry.pol") == "Machine\\Registry.pol"


@pytest.mark.parametrize(
    "name",
    [
        "../outside.txt",
        "Machine/../../outside.txt",
        "/etc/passwd",
        "",
        "   ",
        "./",
        "..",
    ],
)
def test_a_name_that_escapes_the_policy_is_refused(name):
    """A ZIP can name any path it likes.

    Unpacked with an administrator's own ticket, an entry pointing outside the
    policy would be written wherever it pointed — so it is dropped rather than
    bent into something that looks safe.
    """
    assert transfer._safe_relative(name) is None


# ---------------------------------------------------------------------------
# WMI filter assignment
# ---------------------------------------------------------------------------


def test_an_assignment_is_read_into_its_parts():
    parsed = wmi.parse_assignment("[example.lan;{11111111-2222-3333-4444-555555555555};0]")

    assert parsed == {
        "domain": "example.lan",
        "id": "{11111111-2222-3333-4444-555555555555}",
        "flags": "0",
    }


def test_no_assignment_is_no_filter():
    assert wmi.parse_assignment(None) is None
    assert wmi.parse_assignment("") is None


def test_an_unrecognised_assignment_is_still_reported():
    """Better an identifier we cannot place than a policy that looks unfiltered."""
    parsed = wmi.parse_assignment("something else")
    assert parsed is not None
    assert parsed["id"] == "something else"


def test_an_assignment_round_trips():
    value = wmi.format_assignment("example.lan", "{ABC}")
    assert wmi.parse_assignment(value)["id"] == "{ABC}"


# ---------------------------------------------------------------------------
# WMI queries
# ---------------------------------------------------------------------------


def packed(namespace: str, query: str) -> str:
    """One query in the layout msWMI-Parm2 uses."""
    return f"1;3;{len(namespace)};{len(query)};WQL;{namespace};{query};"


def test_a_query_is_pulled_out_of_the_packed_attribute():
    query = "SELECT * FROM Win32_OperatingSystem"
    queries = wmi.parse_queries(packed("root\\CIMv2", query))

    assert len(queries) == 1
    assert queries[0]["namespace"] == "root\\CIMv2"
    assert queries[0]["query"] == query


def test_a_query_containing_a_semicolon_survives():
    """Which is why the attribute carries lengths and not just separators."""
    query = "SELECT * FROM Win32_Volume WHERE Label = 'a;b'"
    queries = wmi.parse_queries(packed("root\\CIMv2", query))

    assert len(queries) == 1
    assert queries[0]["query"] == query


def test_two_queries_are_both_read():
    first = "SELECT * FROM Win32_ComputerSystem"
    second = "SELECT * FROM Win32_OperatingSystem"

    queries = wmi.parse_queries(packed("root\\CIMv2", first) + packed("root\\CIMv2", second))

    assert [item["query"] for item in queries] == [first, second]


def test_lengths_that_do_not_fit_fall_back_to_the_whole_attribute():
    """A wrong length must not produce a plausible-looking half query."""
    broken = "1;3;10;9999;WQL;root\\CIMv2;SELECT * FROM Win32_OperatingSystem;"

    queries = wmi.parse_queries(broken)

    assert len(queries) == 1
    assert queries[0]["query"] == broken.strip()


def test_no_attribute_is_no_query():
    assert wmi.parse_queries(None) == []
    assert wmi.parse_queries("") == []


def test_an_attribute_we_cannot_take_apart_is_shown_whole():
    """A filter we cannot parse must not read as an empty one."""
    queries = wmi.parse_queries("this is not the expected shape")

    assert len(queries) == 1
    assert queries[0]["query"] == "this is not the expected shape"
