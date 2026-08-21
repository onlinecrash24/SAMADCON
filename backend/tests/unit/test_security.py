"""The GptTmpl.inf format.

Every assertion about layout here comes from a file GPMC produced, not from
the specification. The three formats this project writes disagree with one
another on all of it — preamble, empty sections, spacing around the equals
sign — so each one has to be read before it is written.
"""

from __future__ import annotations

import pytest

from samadcon.core.errors import InvalidRequest
from samadcon.gpo import security
from tests.conftest import reference

DOMAIN_ADMINS = "*S-1-5-21-1004336348-1177238915-682003330-512"
ADMINISTRATORS = "*S-1-5-32-544"

# The file GPMC wrote, read from tests/data rather than retyped here. See
# tests/data/PROVENANCE.md for which GPO it came from, which settings were made
# in it, and what was substituted for publication.
GPMC_REFERENCE = reference("GptTmpl.inf")


# The reference above is a file, not a literal, and the fixtures built from it
# below are variations on it. Where a test needs something GPMC never wrote, it
# says so in its own name.


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def test_the_sections_are_read_in_order():
    parsed = security.parse(GPMC_REFERENCE.decode("utf-16"))

    assert list(parsed) == [
        "Unicode",
        "Version",
        "System Access",
        "Event Audit",
        "Registry Values",
        "Privilege Rights",
    ]


def test_the_values_lose_the_spacing_around_the_equals_sign():
    parsed = security.parse(GPMC_REFERENCE.decode("utf-16"))

    assert parsed["System Access"]["MinimumPasswordLength"] == "12"
    assert parsed["Event Audit"]["AuditLogonEvents"] == "3"


def test_an_empty_section_reads_as_an_empty_one_not_a_missing_one():
    """The difference matters on the way out: GPMC leaves the header behind,
    and dropping it would show up as a change nobody made."""
    parsed = security.parse(GPMC_REFERENCE.decode("utf-16"))

    assert parsed["Registry Values"] == {}


def test_the_version_section_keeps_its_quotes():
    parsed = security.parse(GPMC_REFERENCE.decode("utf-16"))

    assert parsed["Version"]["signature"] == '"$CHICAGO$"'


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def test_our_output_matches_the_file_gpmc_wrote():
    """The cross-check with real RSAT, as a test rather than a ritual."""
    parsed = security.parse(GPMC_REFERENCE.decode("utf-16"))

    assert security.render(parsed) == GPMC_REFERENCE


def test_the_file_starts_at_the_first_section():
    """No preamble — unlike scripts.ini and fdeploy1.ini, which both open with
    a blank line. Each of the three formats does this differently."""
    raw = security.render({"System Access": {"MinimumPasswordLength": "8"}})

    assert raw.startswith(b"\xff\xfe")
    assert raw.decode("utf-16").startswith("[Unicode]\r\n")


def test_the_header_sections_are_supplied():
    """A file without them is not one the Windows editor will open."""
    text = security.render({"System Access": {"MinimumPasswordLength": "8"}}).decode("utf-16")

    assert "Unicode=yes" in text
    assert 'signature="$CHICAGO$"' in text
    assert "Revision=1" in text


def test_the_header_sections_have_no_spaces_and_the_others_do():
    """Observed, not derived, and visible in every diff if it is wrong."""
    text = security.render({"System Access": {"MinimumPasswordLength": "8"}}).decode("utf-16")

    assert "Unicode=yes" in text
    assert "MinimumPasswordLength = 8" in text


def test_an_empty_section_is_written_as_a_bare_header():
    text = security.render({"Registry Values": {}}).decode("utf-16")

    assert "[Registry Values]\r\n" in text


def test_the_sections_come_out_in_the_order_gpmc_uses():
    text = security.render(
        {"Privilege Rights": {"SeDenyBatchLogonRight": ADMINISTRATORS}, "System Access": {"a": "1"}}
    ).decode("utf-16")

    assert text.index("[System Access]") < text.index("[Privilege Rights]")


def test_an_unknown_section_is_kept_at_the_end():
    """A file we do not fully understand is better written back whole than
    thinned out to what we recognise."""
    text = security.render({"Something Else": {"key": "value"}}).decode("utf-16")

    assert text.rstrip().endswith("[Something Else]\r\nkey = value")


# ---------------------------------------------------------------------------
# Changing one setting
# ---------------------------------------------------------------------------


def test_one_setting_changes_and_the_rest_stays():
    raw = security.set_value(
        GPMC_REFERENCE.decode("utf-16"), "System Access", "MinimumPasswordLength", "16"
    )
    parsed = security.parse(raw.decode("utf-16"))

    assert parsed["System Access"]["MinimumPasswordLength"] == "16"
    assert parsed["System Access"]["LockoutBadCount"] == "5"
    assert parsed["Privilege Rights"]["SeSystemtimePrivilege"]


def test_clearing_a_setting_removes_the_key_but_keeps_the_section():
    """"Not defined" is an absent key. The section stays because GPMC leaves
    empty sections in the file."""
    raw = security.set_value(
        GPMC_REFERENCE.decode("utf-16"), "Event Audit", "AuditLogonEvents", None
    )
    parsed = security.parse(raw.decode("utf-16"))

    assert "AuditLogonEvents" not in parsed["Event Audit"]
    assert "Event Audit" in parsed


def test_a_first_setting_creates_the_file():
    raw = security.set_value(None, "System Access", "MinimumPasswordLength", "14")

    assert security.parse(raw.decode("utf-16"))["System Access"] == {
        "MinimumPasswordLength": "14"
    }


# ---------------------------------------------------------------------------
# Trustee lists
# ---------------------------------------------------------------------------


def test_a_user_right_is_a_list_of_sids():
    parsed = security.parse(GPMC_REFERENCE.decode("utf-16"))

    assert security.parse_trustees(parsed["Privilege Rights"]["SeSystemtimePrivilege"]) == [
        DOMAIN_ADMINS,
        ADMINISTRATORS,
    ]


def test_the_asterisk_is_added_back_when_writing():
    """The file marks each SID with one; a caller that hands us a bare SID
    should not have to know that."""
    assert security.format_trustees(["S-1-5-32-544"]) == "*S-1-5-32-544"


def test_an_asterisk_that_is_already_there_is_not_doubled():
    assert security.format_trustees([ADMINISTRATORS]) == ADMINISTRATORS


def test_a_name_is_left_as_it_is():
    """Hand-written templates name accounts rather than SIDs, and rewriting
    one into something else would change who the right applies to."""
    assert security.format_trustees(["Administrators"]) == "Administrators"


def test_a_trustee_list_survives_the_round_trip():
    value = security.format_trustees([DOMAIN_ADMINS, ADMINISTRATORS])

    assert security.parse_trustees(value) == [DOMAIN_ADMINS, ADMINISTRATORS]


# ---------------------------------------------------------------------------
# Restricted groups
# ---------------------------------------------------------------------------

# The same GPO after adding one restricted group in GPMC — 998 bytes, the
# earlier 752 plus this tail.
GROUP_TAIL = (
    "[Group Membership]\r\n"
    "*S-1-5-32-544__Memberof =\r\n"
    f"*S-1-5-32-544__Members = {DOMAIN_ADMINS},do\r\n"
)
GPMC_WITH_GROUPS = GPMC_REFERENCE + GROUP_TAIL.encode("utf-16-le")


def test_a_restricted_group_is_two_keys():
    """``<group>__Members`` and ``<group>__Memberof``, the group named by SID
    with the same asterisk the trustees carry."""
    parsed = security.parse(GPMC_WITH_GROUPS.decode("utf-16"))

    assert set(parsed["Group Membership"]) == {
        "*S-1-5-32-544__Memberof",
        "*S-1-5-32-544__Members",
    }


def test_an_empty_value_keeps_the_space_before_the_equals_and_drops_the_one_after():
    """How GPMC writes a group with no Memberof. A trailing space would show
    up in every diff against a policy somebody else made."""
    text = security.render(
        {"Group Membership": {"*S-1-5-32-544__Memberof": "", "*S-1-5-32-544__Members": "x"}}
    ).decode("utf-16")

    assert "*S-1-5-32-544__Memberof =\r\n" in text
    assert "*S-1-5-32-544__Members = x\r\n" in text


def test_our_output_matches_the_file_with_groups_in_it():
    parsed = security.parse(GPMC_WITH_GROUPS.decode("utf-16"))

    assert security.render(parsed) == GPMC_WITH_GROUPS


def test_a_group_member_may_be_a_name():
    """The reference carries one — trustees are not always SIDs, and turning
    a name into something else would change who the setting applies to."""
    parsed = security.parse(GPMC_WITH_GROUPS.decode("utf-16"))
    members = security.parse_trustees(parsed["Group Membership"]["*S-1-5-32-544__Members"])

    assert members == [DOMAIN_ADMINS, "do"]


# ---------------------------------------------------------------------------
# Refusing what would rewrite the file
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    ["Min\r\nSeDebugPrivilege", "Min\nLength", "Min[Privilege Rights]", "Min=8", " Min"],
)
def test_a_key_that_would_start_a_new_line_is_refused(key):
    """The danger is not a path — a key never reaches the file system. It is
    injection: a newline ends the line, and a bracket below it opens a section
    that grants a right nobody set."""
    with pytest.raises(InvalidRequest) as raised:
        security.set_value(None, "System Access", key, "8")

    assert raised.value.code == "unsafe_security_name"


def test_a_value_with_a_line_break_is_refused():
    """The one that was not checked at all: a value ending the line could add
    an entire [Privilege Rights] section below it."""
    with pytest.raises(InvalidRequest) as raised:
        security.set_value(
            None, "System Access", "MinimumPasswordLength", "8\r\n[Privilege Rights]\r\nSeDebugPrivilege = *S-1-5-32-544"
        )

    assert raised.value.code == "unsafe_security_value"


def test_a_registry_path_is_still_a_valid_key():
    """Backslashes and dots belong here — [Registry Values] keys are registry
    paths, and refusing them would refuse half the section."""
    raw = security.set_value(
        None,
        "Registry Values",
        "MACHINE\\Software\\Microsoft\\Windows\\CurrentVersion\\Policies\\System\\EnableLUA",
        "4,1",
    )

    assert "EnableLUA = 4,1" in raw.decode("utf-16")


def test_a_trustee_that_would_split_into_two_is_refused():
    """A comma separates trustees; one inside a name would grant the right to
    something nobody chose."""
    with pytest.raises(InvalidRequest):
        security.format_trustees(["Administrators,*S-1-5-32-544"])


def test_the_editor_view_splits_the_lists_and_drops_the_header():
    described = security.describe(security.parse(GPMC_REFERENCE.decode("utf-16")))

    assert "Unicode" not in described
    assert "Version" not in described
    assert described["System Access"]["LockoutBadCount"] == "5"
    assert described["Privilege Rights"]["SeSystemtimePrivilege"] == [
        DOMAIN_ADMINS,
        ADMINISTRATORS,
    ]
