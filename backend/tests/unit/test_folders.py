"""Reading fdeploy1.ini.

The shape comes from Samba's own GPFDeploy1IniParser, which special-cases
exactly two things: the [Folder_Redirection] header, whose values are
semicolon-separated SID lists, and the per-redirection sections named
{GUID}_{SID}, whose FullPath is a network path.
"""

from __future__ import annotations

from samcon.gpo import folders

DOCUMENTS = "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}"
DESKTOP = "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}"
USERS = "S-1-5-21-1-2-3-513"
ADMINS = "S-1-5-21-1-2-3-512"

SAMPLE = (
    "[Folder_Redirection]\r\n"
    f"{DOCUMENTS}={USERS};{ADMINS};\r\n"
    f"{DESKTOP}={USERS};\r\n"
    "[Version]\r\n"
    "Revision=1\r\n"
    f"[{DOCUMENTS}_{USERS}]\r\n"
    "FullPath=\\\\dom.lan\\home\\%USERNAME%\\Documents\r\n"
    "GrantType=1\r\n"
    f"[{DOCUMENTS}_{ADMINS}]\r\n"
    "FullPath=\\\\dom.lan\\admin\\%USERNAME%\\Documents\r\n"
    f"[{DESKTOP}_{USERS}]\r\n"
    "FullPath=\\\\dom.lan\\home\\%USERNAME%\\Desktop\r\n"
)


def test_the_header_names_the_redirected_folders():
    parsed = folders.parse(SAMPLE)

    assert [item["guid"] for item in parsed["folders"]] == sorted([DOCUMENTS, DESKTOP])


def test_a_folder_carries_the_groups_it_applies_to():
    """The header's values are a SID list, with a trailing semicolon even when
    there is only one — a convention Samba's parser calls out by name."""
    parsed = folders.parse(SAMPLE)
    documents = next(item for item in parsed["folders"] if item["guid"] == DOCUMENTS)

    assert documents["trustees"] == [USERS, ADMINS]


def test_a_single_trustee_does_not_pick_up_an_empty_one():
    parsed = folders.parse(SAMPLE)
    desktop = next(item for item in parsed["folders"] if item["guid"] == DESKTOP)

    assert desktop["trustees"] == [USERS]


def test_each_group_gets_its_own_target():
    """One folder, two groups, two paths — the section name is what pairs
    them up."""
    parsed = folders.parse(SAMPLE)
    documents = next(item for item in parsed["folders"] if item["guid"] == DOCUMENTS)

    assert [(item["sid"], item["path"]) for item in documents["targets"]] == [
        (USERS, "\\\\dom.lan\\home\\%USERNAME%\\Documents"),
        (ADMINS, "\\\\dom.lan\\admin\\%USERNAME%\\Documents"),
    ]


def test_the_other_keys_are_kept_verbatim():
    """Naming them would be the first step towards writing them wrongly."""
    parsed = folders.parse(SAMPLE)
    documents = next(item for item in parsed["folders"] if item["guid"] == DOCUMENTS)

    assert documents["targets"][0]["options"] == {"GrantType": "1"}
    assert documents["targets"][1]["options"] == {}


def test_the_version_section_is_kept():
    assert folders.parse(SAMPLE)["version"] == {"Revision": "1"}


def test_a_section_of_an_unknown_shape_is_shown_not_dropped():
    """This is a read. A file we do not fully understand is better shown whole
    than silently thinned out."""
    parsed = folders.parse(SAMPLE + "[Something]\r\nKey=value\r\n")

    assert parsed["other"] == {"Something": {"Key": "value"}}


def test_a_target_without_a_header_entry_still_shows_up():
    """A file that lists a redirection the header forgot is malformed, and
    hiding half of it would make that impossible to see."""
    parsed = folders.parse(f"[{DESKTOP}_{USERS}]\r\nFullPath=\\\\dom.lan\\x\r\n")

    assert [item["guid"] for item in parsed["folders"]] == [DESKTOP]
    assert parsed["folders"][0]["trustees"] == []
    assert parsed["folders"][0]["targets"][0]["path"] == "\\\\dom.lan\\x"


def test_an_empty_file_reads_as_nothing_redirected():
    assert folders.parse("")["folders"] == []


# ---------------------------------------------------------------------------
# The file GPMC wrote
# ---------------------------------------------------------------------------

SAVED_GAMES = "{4C5C32FF-BB9D-43B0-B5B4-2D72E54EAAA4}"
EVERYONE = "s-1-1-0"

# Byte for byte the fdeploy1.ini of a GPO created in GPMC — "Wegwerf-GPO" in
# the domain this is verified against, Saved Games redirected under a root
# path — read off the share with `od -c` and reassembled here. 460 bytes.
#
# It settles three things no document would have: the file opens with a blank
# line, a line of five spaces and another blank line; [version] is lower case
# beside [Folder_Redirection] in mixed case; and each redirection carries a
# Flags number beside its path.
GPMC_REFERENCE = b"\xff\xfe" + (
    "\r\n"
    "     \r\n"
    "[version]\r\n"
    "version=100\r\n"
    "[Folder_Redirection]\r\n"
    f"{SAVED_GAMES}={EVERYONE};\r\n"
    f"[{SAVED_GAMES}_{EVERYONE}]\r\n"
    "Flags=1211\r\n"
    "FullPath=\\\\dc1.example.lan\\home\\%USERNAME%\\Saved Games\r\n"
).encode("utf-16-le")


# The byte counts these fixtures were checked against are gone. They were the
# sizes `od -c` reported on the domain controller, and they proved the strongest
# thing a test here can prove: that the fixture *is* the file GPMC wrote, not a
# tidied-up recollection of it. When the domain's own names, SIDs and hosts were
# replaced with example ones for publication, that link broke — and a recomputed
# number would only assert that the fixture equals itself.
#
# What the fixtures still carry is every structural detail they were transcribed
# for: the preamble, the encoding, the line endings, the spacing around the
# equals sign, the sections left empty. The round-trip tests below check all of
# it.


def test_the_reference_reads_as_one_redirected_folder():
    parsed = folders.parse(GPMC_REFERENCE.decode("utf-16"))

    assert [item["guid"] for item in parsed["folders"]] == [SAVED_GAMES]
    target = parsed["folders"][0]["targets"][0]
    assert target["sid"] == EVERYONE
    assert target["path"] == "\\\\dc1.example.lan\\home\\%USERNAME%\\Saved Games"
    assert target["options"] == {"Flags": "1211"}


def test_the_lower_case_version_section_is_found():
    """GPMC writes [version] in lower case. Matching it exactly finds nothing,
    and the version would then be silently reset on every write."""
    parsed = folders.parse(GPMC_REFERENCE.decode("utf-16"))

    assert parsed["version"] == {"version": "100"}


def test_our_output_matches_the_file_gpmc_wrote():
    """The cross-check with real RSAT, as a test rather than a ritual: reading
    the reference and writing it back has to come out identical."""
    parsed = folders.parse(GPMC_REFERENCE.decode("utf-16"))

    assert folders.render(parsed["folders"], version="100") == GPMC_REFERENCE


def test_editing_keeps_the_flags_that_were_there():
    """Which bit means what is not on evidence. An entry being edited keeps
    its flags rather than being handed a number we invented."""
    written = folders.set_target(
        GPMC_REFERENCE.decode("utf-16"), SAVED_GAMES, EVERYONE, "\\\\other\\share\\%USERNAME%"
    )
    parsed = folders.parse(written.decode("utf-16"))

    assert parsed["folders"][0]["targets"][0]["options"] == {"Flags": "1211"}
    assert parsed["folders"][0]["targets"][0]["path"] == "\\\\other\\share\\%USERNAME%"


def test_a_new_redirection_starts_from_the_value_windows_used():
    written = folders.set_target(None, DESKTOP, USERS, "\\\\dom.lan\\home\\%USERNAME%\\Desktop")
    parsed = folders.parse(written.decode("utf-16"))

    assert parsed["folders"][0]["targets"][0]["options"] == {"Flags": folders.DEFAULT_FLAGS}


def test_removing_the_last_group_removes_the_folder_from_the_header():
    """A folder named in the header with no section describing it is the
    file's own kind of dangling reference."""
    written = folders.set_target(GPMC_REFERENCE.decode("utf-16"), SAVED_GAMES, EVERYONE, None)
    text = written.decode("utf-16")

    assert SAVED_GAMES not in text
    assert folders.parse(text)["folders"] == []


def test_the_version_survives_an_edit():
    written = folders.set_target(
        GPMC_REFERENCE.decode("utf-16"), DESKTOP, USERS, "\\\\dom.lan\\x"
    )

    assert folders.parse(written.decode("utf-16"))["version"] == {"version": "100"}


def test_the_file_opens_the_way_gpmc_opens_it():
    written = folders.set_target(None, DESKTOP, USERS, "\\\\dom.lan\\x")

    assert written.startswith(b"\xff\xfe")
    assert written.decode("utf-16").startswith("\r\n     \r\n[version]\r\n")
