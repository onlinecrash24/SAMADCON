"""GPT.INI, version numbers and SYSVOL paths."""

from __future__ import annotations

import pytest

from samadcon.core.errors import InvalidRequest
from samadcon.gpo import container, sysvol

GUID = "{A1B2C3D4-1111-2222-3333-444455556666}"


# ---------------------------------------------------------------------------
# Version numbers
# ---------------------------------------------------------------------------


def test_the_two_halves_of_a_version_are_packed_into_one_number():
    """The **low** word counts computer changes, the high word user changes.

    That way round, and easy to get backwards — the symptom is a version that
    seems not to move when the other half is edited.
    """
    assert sysvol.combine_version(0, 0) == 0
    assert sysvol.combine_version(1, 0) == 1
    assert sysvol.combine_version(0, 1) == 65536
    assert sysvol.combine_version(3, 2) == 131075


def test_the_word_order_matches_what_windows_writes():
    """Read off two policies made by GPMC.

    A drive-mapping policy — all user configuration — reads 0x00100001:
    sixteen user changes, one computer change. A Windows Update policy, all
    computer configuration, reads 6.
    """
    assert sysvol.split_version(0x00100001) == (1, 16)
    assert sysvol.split_version(6) == (6, 0)


@pytest.mark.parametrize(("machine", "user"), [(0, 0), (1, 0), (0, 1), (7, 42), (65535, 65535)])
def test_a_version_survives_being_split_and_recombined(machine, user):
    version = sysvol.combine_version(machine, user)
    assert sysvol.split_version(version) == (machine, user)


def test_bumping_one_half_leaves_the_other_alone():
    """A machine-side edit must not make clients re-read the user side."""
    version = sysvol.combine_version(3, 9)
    machine, user = sysvol.split_version(version)
    assert sysvol.split_version(sysvol.combine_version(machine + 1, user)) == (4, 9)


# ---------------------------------------------------------------------------
# GPT.INI
# ---------------------------------------------------------------------------


def test_a_minimal_gpt_ini_is_read():
    parsed = sysvol.parse_gpt_ini("[General]\r\nVersion=0\r\n")
    assert parsed["version"] == 0
    assert parsed["display_name"] is None


def test_the_version_is_split_the_same_way_it_is_stored():
    parsed = sysvol.parse_gpt_ini("[General]\r\nVersion=131075\r\n")
    assert parsed["machine_version"] == 3
    assert parsed["user_version"] == 2


def test_keys_are_matched_regardless_of_case():
    """Windows writes displayName, some tools write DisplayName."""
    parsed = sysvol.parse_gpt_ini("[general]\r\nVERSION=5\r\ndisplayname=Test\r\n")
    assert parsed["version"] == 5
    assert parsed["display_name"] == "Test"


def test_keys_outside_the_general_section_are_ignored():
    text = "[Other]\r\nVersion=99\r\n[General]\r\nVersion=1\r\n"
    assert sysvol.parse_gpt_ini(text)["version"] == 1


def test_a_damaged_version_reads_as_zero():
    """A file we cannot parse must not stop a policy from being listed."""
    assert sysvol.parse_gpt_ini("[General]\r\nVersion=whoops\r\n")["version"] == 0
    assert sysvol.parse_gpt_ini("")["version"] == 0


def test_comments_and_blank_lines_are_skipped():
    text = "; written by something\r\n\r\n[General]\r\nVersion=4\r\n"
    assert sysvol.parse_gpt_ini(text)["version"] == 4


def test_gpt_ini_is_written_with_crlf():
    """Clients that read this file predate anyone's patience for parsers."""
    written = sysvol.format_gpt_ini(7)
    assert written == b"[General]\r\nVersion=7\r\n"


def test_a_display_name_is_written_when_there_is_one():
    written = sysvol.format_gpt_ini(7, "Test policy")
    assert written == b"[General]\r\nVersion=7\r\ndisplayName=Test policy\r\n"


def test_what_is_written_can_be_read_back():
    text = sysvol.format_gpt_ini(sysvol.combine_version(2, 5), "Round trip").decode()
    parsed = sysvol.parse_gpt_ini(text)
    assert parsed["machine_version"] == 2
    assert parsed["user_version"] == 5
    assert parsed["display_name"] == "Round trip"


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def test_a_unc_path_is_split_into_its_parts():
    host, share, path = sysvol.parse_unc(f"\\\\example.lan\\sysvol\\example.lan\\Policies\\{GUID}")
    assert host == "example.lan"
    assert share == "sysvol"
    assert path == f"example.lan\\Policies\\{GUID}"


def test_forward_slashes_are_accepted():
    """They turn up in hand-edited attributes and mean the same thing."""
    host, share, path = sysvol.parse_unc(f"//example.lan/sysvol/example.lan/Policies/{GUID}")
    assert (host, share) == ("example.lan", "sysvol")
    assert path == f"example.lan\\Policies\\{GUID}"


@pytest.mark.parametrize("given", ["", "not-a-path", "\\\\host", "\\\\host\\share", "C:\\somewhere"])
def test_something_that_is_not_a_unc_path_is_refused(given):
    with pytest.raises(InvalidRequest) as raised:
        sysvol.parse_unc(given)
    assert raised.value.code == "invalid_unc"


def test_the_path_we_build_is_the_one_we_can_read_back():
    unc = sysvol.gpo_unc("example.lan", GUID)
    _, _, path = sysvol.parse_unc(unc)
    assert path == sysvol.gpo_path("example.lan", GUID)


def test_joining_does_not_double_the_separators():
    assert sysvol.join("example.lan", "Policies", GUID) == f"example.lan\\Policies\\{GUID}"
    assert sysvol.join("a\\", "\\b") == "a\\b"


def test_empty_parts_are_dropped_when_joining():
    assert sysvol.join("a", "", "b") == "a\\b"


# ---------------------------------------------------------------------------
# Existence on the share
# ---------------------------------------------------------------------------


class FakeSmb:
    """An SMB connection that answers the way Samba's does.

    The point of the fake is the one behaviour that caught us out: ``chkpath``
    is a directory check, and raises on a perfectly good file.
    """

    def __init__(self, directories: set[str], files: set[str]) -> None:
        self.directories = directories
        self.files = files

    def chkpath(self, path: str) -> bool:
        if path in self.directories:
            return True
        raise OSError("NT_STATUS_NOT_A_DIRECTORY")

    def list(self, path: str) -> list[dict]:
        if path not in self.directories:
            raise OSError("NT_STATUS_OBJECT_PATH_NOT_FOUND")
        prefix = f"{path}\\" if path else ""
        names = [item for item in self.files | self.directories if item.startswith(prefix)]
        return [
            {"name": name[len(prefix) :], "attrib": 0x10 if name in self.directories else 0}
            for name in names
            if "\\" not in name[len(prefix) :]
        ]


def share(directories: set[str], files: set[str]) -> sysvol.SysvolConnection:
    return sysvol.SysvolConnection(FakeSmb(directories, files), "dc1", "example.lan")


def test_a_directory_is_found():
    conn = share({"example.lan", "example.lan\\Policies"}, set())
    assert conn.exists("example.lan\\Policies") is True
    assert conn.is_directory("example.lan\\Policies") is True


def test_a_file_is_found_even_though_chkpath_refuses_it():
    """chkpath answers "is this a directory", and says no to every file.

    Using it alone made GPT.INI look missing on every policy — the folders
    beside it were found, so nothing else looked wrong.
    """
    conn = share({"example.lan"}, {"example.lan\\GPT.INI"})

    assert conn.exists("example.lan\\GPT.INI") is True
    assert conn.is_directory("example.lan\\GPT.INI") is False


def test_something_that_is_not_there_is_not_found():
    conn = share({"example.lan"}, {"example.lan\\GPT.INI"})
    assert conn.exists("example.lan\\missing.ini") is False


def test_a_file_under_an_unreadable_parent_is_not_found():
    conn = share({"example.lan"}, set())
    assert conn.exists("nowhere\\GPT.INI") is False


def test_names_are_compared_without_regard_to_case():
    """SMB is case-insensitive, and tools disagree on how to spell GPT.INI."""
    conn = share({"example.lan"}, {"example.lan\\GPT.INI"})
    assert conn.exists("example.lan\\gpt.ini") is True


# ---------------------------------------------------------------------------
# GUIDs
# ---------------------------------------------------------------------------


def test_a_guid_is_normalised_to_braces_and_upper_case():
    """GPMC compares link entries as text, so the spelling has to match."""
    assert container.normalise_guid("a1b2c3d4-1111-2222-3333-444455556666") == GUID
    assert container.normalise_guid(GUID.lower()) == GUID
    assert container.normalise_guid(f"  {GUID}  ") == GUID


@pytest.mark.parametrize("given", ["", "   ", "not-a-guid", "{}", "{1234}"])
def test_something_that_is_not_a_guid_is_refused(given):
    with pytest.raises(InvalidRequest):
        container.normalise_guid(given)


# ---------------------------------------------------------------------------
# Policy flags
# ---------------------------------------------------------------------------


def test_the_flag_bits_match_what_the_directory_stores():
    assert container.GPO_FLAG_USER_DISABLED == 1
    assert container.GPO_FLAG_MACHINE_DISABLED == 2
