"""The scripts.ini format.

Two things decide whether a script ever runs, and neither is visible in a
listing: the file has to be UTF-16LE with a BOM, and the numbering has to be
0, 1, 2 without gaps. Both are covered here rather than left to the manual
check on a Windows client.
"""

from __future__ import annotations

import pytest

from samadcon.core.errors import InvalidRequest
from samadcon.gpo import scripts
from samadcon.gpo.scripts import EVENTS, Script
from tests.conftest import reference

EVENTS_MACHINE = EVENTS["Machine"]

# The file GPMC wrote, read from tests/data rather than retyped here. See
# tests/data/PROVENANCE.md for which GPO it came from and what was substituted
# for publication.
#
# It is the whole reason this file is not guesswork: it settles the leading
# blank line and the absence of an empty [Shutdown], both of which had been
# written the other way here before anyone looked.
GPMC_REFERENCE = reference("scripts.ini")

# Shaped the same way, with a second event so the pairing and the ordering
# have something to work on.
SAMPLE = (
    "\r\n"
    "[Startup]\r\n"
    "0CmdLine=powershell.exe\r\n"
    "0Parameters=-ExecutionPolicy Bypass \\\\dom.lan\\sysvol\\dom.lan\\scripts\\a.ps1\r\n"
    "1CmdLine=map-drives.cmd\r\n"
    "1Parameters=\r\n"
    "[Shutdown]\r\n"
    "0CmdLine=cleanup.cmd\r\n"
    "0Parameters=/quiet\r\n"
)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def test_the_numbered_pairs_become_scripts_in_order():
    parsed = scripts.parse(SAMPLE)

    assert list(parsed) == ["Startup", "Shutdown"]
    assert parsed["Startup"] == [
        Script(
            command="powershell.exe",
            parameters="-ExecutionPolicy Bypass \\\\dom.lan\\sysvol\\dom.lan\\scripts\\a.ps1",
        ),
        Script(command="map-drives.cmd", parameters=""),
    ]
    assert parsed["Shutdown"] == [Script(command="cleanup.cmd", parameters="/quiet")]


def test_the_order_is_the_number_not_the_position_in_the_file():
    """The numbers are the execution order; a file that lists them out of
    sequence still runs in numeric order."""
    parsed = scripts.parse(
        "[Startup]\r\n1CmdLine=second.cmd\r\n0CmdLine=first.cmd\r\n"
    )

    assert [item.command for item in parsed["Startup"]] == ["first.cmd", "second.cmd"]


def test_comments_and_blank_lines_are_ignored():
    parsed = scripts.parse("; written by hand\r\n\r\n[Logon]\r\n0CmdLine=hello.cmd\r\n")
    assert parsed["Logon"] == [Script(command="hello.cmd")]


def test_an_entry_without_a_command_is_dropped():
    """Windows skips it and then stops at the gap it leaves, so keeping it
    would mean showing a script that silently breaks the ones after it."""
    parsed = scripts.parse("[Startup]\r\n0Parameters=/quiet\r\n1CmdLine=real.cmd\r\n")

    assert parsed["Startup"] == [Script(command="real.cmd")]


def test_an_empty_section_survives_as_an_empty_list():
    parsed = scripts.parse("[Startup]\r\n[Shutdown]\r\n0CmdLine=x.cmd\r\n")

    assert parsed["Startup"] == []
    assert parsed["Shutdown"] == [Script(command="x.cmd")]


def test_the_powershell_order_flag_is_read():
    text = "[Startup]\r\n0CmdLine=a.ps1\r\n[ScriptsConfig]\r\nStartExecutePSFirst=true\r\n"

    assert scripts.execute_ps_first(text) is True
    # And it is not mistaken for a script.
    assert scripts.parse(text)["ScriptsConfig"] == []


def test_no_flag_is_not_the_same_as_false():
    """Absent means Windows decides; false means somebody chose. Writing false
    where the file said nothing would be a change nobody asked for."""
    assert scripts.execute_ps_first(SAMPLE) is None


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def test_the_file_is_utf16le_with_a_bom():
    """Saved as UTF-8 the file reads as mojibake on the client and the scripts
    never run — with nothing in any console to say why."""
    raw = scripts.render({"Startup": [Script(command="a.cmd")]})

    assert raw.startswith(b"\xff\xfe")
    assert raw.decode("utf-16") == "\r\n[Startup]\r\n0CmdLine=a.cmd\r\n0Parameters=\r\n"


def test_lines_end_with_crlf():
    """Every newline carries its carriage return — counting both is the way to
    say that without a regular expression."""
    text = scripts.render(
        {"Startup": [Script(command="a.cmd"), Script(command="b.cmd")]}
    ).decode("utf-16")

    assert text.count("\n") > 1
    assert text.count("\r\n") == text.count("\n")


def test_a_round_trip_changes_nothing():
    parsed = scripts.parse(SAMPLE)
    again = scripts.render(parsed, order=("Startup", "Shutdown"))

    assert again.decode("utf-16") == SAMPLE


def test_removing_the_first_script_renumbers_the_rest():
    """The whole reason this module reads into a list. Windows stops at the
    first missing index, so a file that jumps from 0 to 2 runs one script and
    silently drops everything after it."""
    parsed = scripts.parse(SAMPLE)
    parsed["Startup"] = parsed["Startup"][1:]

    text = scripts.render(parsed, order=("Startup", "Shutdown")).decode("utf-16")

    assert "0CmdLine=map-drives.cmd" in text
    assert "1CmdLine=" not in text


def test_reordering_is_the_same_operation():
    parsed = scripts.parse(SAMPLE)
    parsed["Startup"] = list(reversed(parsed["Startup"]))

    text = scripts.render(parsed, order=("Startup", "Shutdown")).decode("utf-16")

    assert text.index("0CmdLine=map-drives.cmd") < text.index("1CmdLine=powershell.exe")


def test_the_named_order_comes_first():
    """GPMC writes [Startup] before [Shutdown]; matching that keeps a diff
    against a file it wrote down to the lines that actually differ."""
    text = scripts.render(
        {"Shutdown": [Script(command="b.cmd")], "Startup": [Script(command="a.cmd")]},
        order=("Startup", "Shutdown"),
    ).decode("utf-16")

    assert text.index("[Startup]") < text.index("[Shutdown]")


def test_an_empty_section_is_not_written_at_all():
    """GPMC's own file has one event and no header for the other. Writing a
    bare [Shutdown] would be a change we invented, visible in every diff
    against a policy somebody else created."""
    text = scripts.render(
        {"Startup": [], "Shutdown": [Script(command="a.cmd")]}, order=("Startup", "Shutdown")
    ).decode("utf-16")

    assert "[Startup]" not in text
    assert text == "\r\n[Shutdown]\r\n0CmdLine=a.cmd\r\n0Parameters=\r\n"


def test_our_output_matches_the_file_gpmc_wrote():
    """The plan's cross-check with real RSAT, as a test rather than a ritual.

    Reading the reference and writing it back has to come out identical: this
    is what says a policy edited here is indistinguishable from one edited
    there, and it is how the leading blank line was found in the first place.
    """
    parsed = scripts.parse(GPMC_REFERENCE.decode("utf-16"))
    again = scripts.render(parsed, order=EVENTS_MACHINE)

    assert again == GPMC_REFERENCE


def test_the_reference_reads_as_one_startup_script():
    parsed = scripts.parse(GPMC_REFERENCE.decode("utf-16"))

    assert list(parsed) == ["Startup"]
    assert parsed["Startup"] == [
        Script(
            command="powershell.exe",
            parameters=(
                "-ExecutionPolicy Bypass "
                "\\\\example.lan\\sysvol\\example.lan\\scripts\\deploy-tactical-rmm.ps1"
            ),
        )
    ]


def test_the_powershell_order_flag_is_written_last():
    text = scripts.render(
        {"Startup": [Script(command="a.ps1")]}, ps_first=True
    ).decode("utf-16")

    assert text.endswith("[ScriptsConfig]\r\nStartExecutePSFirst=true\r\n")


# ---------------------------------------------------------------------------
# Changing one event
# ---------------------------------------------------------------------------


def test_writing_one_event_leaves_the_other_alone():
    """Both events share a file. Rendering only the one being edited would
    delete the other, and nothing would report it."""
    raw = scripts.set_scripts(SAMPLE, "Startup", [Script(command="new.cmd")], half="Machine")
    parsed = scripts.parse(raw.decode("utf-16"))

    assert parsed["Startup"] == [Script(command="new.cmd")]
    assert parsed["Shutdown"] == [Script(command="cleanup.cmd", parameters="/quiet")]


def test_the_powershell_order_flag_survives_an_edit():
    text = "[Logon]\r\n0CmdLine=a.ps1\r\n[ScriptsConfig]\r\nStartExecutePSFirst=true\r\n"

    raw = scripts.set_scripts(text, "Logon", [Script(command="b.ps1")], half="User")

    assert scripts.execute_ps_first(raw.decode("utf-16")) is True


def test_a_first_script_creates_the_file():
    raw = scripts.set_scripts(None, "Startup", [Script(command="a.cmd")], half="Machine")

    assert scripts.parse(raw.decode("utf-16"))["Startup"] == [Script(command="a.cmd")]


def test_clearing_an_event_removes_its_section():
    """Not a bare header: GPMC's own file has no section for the event it does
    not use, so that is what "no scripts" looks like."""
    raw = scripts.set_scripts(SAMPLE, "Startup", [], half="Machine")
    parsed = scripts.parse(raw.decode("utf-16"))

    assert "Startup" not in parsed
    assert parsed["Shutdown"] == [Script(command="cleanup.cmd", parameters="/quiet")]


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def test_each_half_and_engine_has_its_file():
    assert scripts.path_for("Machine", "cmd") == "Machine\\Scripts\\scripts.ini"
    assert scripts.path_for("User", "powershell") == "User\\Scripts\\psscripts.ini"


def test_the_script_files_live_in_a_directory_per_event():
    assert scripts.directory_for("Machine", "Startup") == "Machine\\Scripts\\Startup"
    assert scripts.directory_for("User", "Logoff") == "User\\Scripts\\Logoff"


def test_an_event_from_the_wrong_half_is_refused():
    """A logon script under Machine would be written to a directory Windows
    never reads, and nothing would report it as unapplied."""
    with pytest.raises(InvalidRequest) as raised:
        scripts.directory_for("Machine", "Logon")

    assert raised.value.code == "unknown_script_event"


@pytest.mark.parametrize(
    ("half", "engine", "code"),
    [("Nowhere", "cmd", "unknown_script_half"), ("Machine", "perl", "unknown_script_engine")],
)
def test_unknown_halves_and_engines_are_refused(half, engine, code):
    with pytest.raises(InvalidRequest) as raised:
        scripts.path_for(half, engine)

    assert raised.value.code == code
