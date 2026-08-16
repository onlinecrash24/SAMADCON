"""The gPLink format.

Precedence lives in the order of one string, and the string is written in the
reverse of the order an administrator sees. That inversion is the thing to get
wrong, so most of these tests are about it.
"""

from __future__ import annotations

import pytest

from samadcon.core.errors import InvalidRequest
from samadcon.gpo import links

BASE = "cn=policies,cn=system,DC=example,DC=lan"
FIRST = f"cn={{11111111-1111-1111-1111-111111111111}},{BASE}"
SECOND = f"cn={{22222222-2222-2222-2222-222222222222}},{BASE}"
THIRD = f"cn={{33333333-3333-3333-3333-333333333333}},{BASE}"


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def test_an_empty_attribute_is_no_links():
    assert links.parse(None) == []
    assert links.parse("") == []


def test_a_single_link_is_read():
    parsed = links.parse(f"[LDAP://{FIRST};0]")

    assert len(parsed) == 1
    assert parsed[0]["dn"] == FIRST
    assert parsed[0]["order"] == 1
    assert parsed[0]["enabled"] is True
    assert parsed[0]["enforced"] is False


def test_the_last_entry_in_the_attribute_is_link_order_one():
    """The attribute is written back to front.

    AD applies the entries from the end forwards, so the *last* one in the
    string is applied first and therefore overridden by everything before it —
    which makes it the highest link order, the one GPMC shows at the top.
    """
    parsed = links.parse(f"[LDAP://{FIRST};0][LDAP://{SECOND};0][LDAP://{THIRD};0]")

    assert [link["dn"] for link in parsed] == [THIRD, SECOND, FIRST]
    assert [link["order"] for link in parsed] == [1, 2, 3]


@pytest.mark.parametrize(
    ("options", "enabled", "enforced"),
    [(0, True, False), (1, False, False), (2, True, True), (3, False, True)],
)
def test_the_option_bits_are_read(options, enabled, enforced):
    parsed = links.parse(f"[LDAP://{FIRST};{options}]")
    assert parsed[0]["enabled"] is enabled
    assert parsed[0]["enforced"] is enforced


def test_whitespace_between_entries_is_tolerated():
    """Hand-edited attributes turn up with newlines in them."""
    parsed = links.parse(f"[LDAP://{FIRST};0]\n[LDAP://{SECOND};2]")
    assert len(parsed) == 2


def test_something_that_is_not_a_link_is_ignored():
    parsed = links.parse(f"nonsense[LDAP://{FIRST};0]more nonsense")
    assert [link["dn"] for link in parsed] == [FIRST]


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def test_a_round_trip_keeps_the_order():
    original = f"[LDAP://{FIRST};0][LDAP://{SECOND};2][LDAP://{THIRD};1]"
    assert links.format(links.parse(original)) == original


def test_writing_reverses_the_display_order_again():
    """What is shown first has to be written last."""
    written = links.format(
        [
            {"dn": FIRST, "enabled": True, "enforced": False},
            {"dn": SECOND, "enabled": True, "enforced": False},
        ]
    )
    assert written == f"[LDAP://{SECOND};0][LDAP://{FIRST};0]"


def test_options_are_derived_when_not_given():
    written = links.format([{"dn": FIRST, "enabled": False, "enforced": True}])
    assert written == f"[LDAP://{FIRST};3]"


def test_an_explicit_options_value_wins():
    """Round-tripping a link must not recompute what was read."""
    written = links.format([{"dn": FIRST, "options": 2, "enabled": False, "enforced": False}])
    assert written == f"[LDAP://{FIRST};2]"


def test_no_links_is_an_empty_string():
    assert links.format([]) == ""


def test_a_dn_that_would_corrupt_the_attribute_is_refused():
    """The format has no escaping, so a delimiter inside a DN breaks the rest."""
    for bad in (f"cn=a]b,{BASE}", f"cn=a;b,{BASE}", f"cn=a[b,{BASE}"):
        with pytest.raises(InvalidRequest) as raised:
            links.format([{"dn": bad, "enabled": True}])
        assert raised.value.code == "invalid_link_dn"


def test_a_link_without_a_target_is_refused():
    with pytest.raises(InvalidRequest):
        links.format([{"dn": "  ", "enabled": True}])


# ---------------------------------------------------------------------------
# Finding and moving
# ---------------------------------------------------------------------------


def test_a_link_is_found_regardless_of_case():
    """AD writes the DN in the case it was given; comparisons must not care."""
    parsed = links.parse(f"[LDAP://{FIRST};0]")
    assert links.find(parsed, FIRST.upper()) == 0


def test_a_link_that_is_not_there_is_not_found():
    parsed = links.parse(f"[LDAP://{FIRST};0]")
    assert links.find(parsed, SECOND) is None


def test_moving_a_link_renumbers_the_rest():
    parsed = links.parse(f"[LDAP://{THIRD};0][LDAP://{SECOND};0][LDAP://{FIRST};0]")
    assert [link["dn"] for link in parsed] == [FIRST, SECOND, THIRD]

    moved = links.move(parsed, 2, 0)

    assert [link["dn"] for link in moved] == [THIRD, FIRST, SECOND]
    assert [link["order"] for link in moved] == [1, 2, 3]


def test_moving_past_the_end_lands_at_the_end():
    parsed = links.parse(f"[LDAP://{SECOND};0][LDAP://{FIRST};0]")
    moved = links.move(parsed, 0, 99)
    assert [link["dn"] for link in moved] == [SECOND, FIRST]


def test_moving_a_link_that_does_not_exist_is_refused():
    with pytest.raises(InvalidRequest) as raised:
        links.move(links.parse(f"[LDAP://{FIRST};0]"), 5, 0)
    assert raised.value.code == "link_not_found"
