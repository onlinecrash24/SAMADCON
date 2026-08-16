"""Scripts in a real GPO.

The format itself is covered without a domain in tests/unit/test_scripts.py,
including a byte-for-byte comparison against a file GPMC wrote. What needs a
domain controller is the rest of it: the file landing on SYSVOL under the name
Windows looks for, the extension being registered so a client runs it at all,
and the version advancing so a client notices.
"""

from __future__ import annotations

import uuid
from urllib.parse import quote

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.gpo]

# Read off gPCMachineExtensionNames of a GPO that GPMC created. A policy whose
# CSE is missing here is run by nobody and reported by nothing.
SCRIPTS_CSE = "{42B5FAAE-6536-11D2-AE5A-0000F87571E3}"
SCRIPTS_TOOL = "{40B6664F-4972-11D1-A7CA-0000F87571E3}"


def quoted(value: str) -> str:
    return quote(value, safe="")


@pytest.fixture
def gpo(api):
    response = api.post(
        "/api/v1/gpos", json={"display_name": f"SAMCON scripts {uuid.uuid4().hex[:8]}"}
    )
    if response.status_code != 200:
        pytest.skip(f"cannot create a group policy: {response.text}")

    created = response.json()
    yield created
    api.delete(f"/api/v1/gpos?dn={quoted(created['dn'])}&force=true")


def read(api, gpo, half="Machine"):
    return api.get(f"/api/v1/gpos/scripts?dn={quoted(gpo['dn'])}&half={half}").json()


def write(api, gpo, **payload):
    payload.setdefault("half", "Machine")
    payload.setdefault("event", "Startup")
    return api.post(f"/api/v1/gpos/scripts?dn={quoted(gpo['dn'])}", json=payload)


def extensions(api, gpo, half="Machine"):
    """The registered extensions of one half, as the GPO listing reports them."""
    entry = api.get(f"/api/v1/gpos/gpo?dn={quoted(gpo['dn'])}").json()
    key = "machine_extensions" if half == "Machine" else "user_extensions"
    return (entry[key] or "").upper()


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def test_a_fresh_policy_has_no_scripts(api, gpo):
    listed = read(api, gpo)

    assert listed["events"] == {"Startup": [], "Shutdown": []}
    assert listed["registered"] is False


def test_each_half_knows_its_own_events(api, gpo):
    assert sorted(read(api, gpo, "User")["events"]) == ["Logoff", "Logon"]


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def test_a_script_survives_the_round_trip(api, gpo):
    """Written into scripts.ini over SMB, and read back out of it."""
    response = write(
        api,
        gpo,
        scripts=[{"command": "powershell.exe", "parameters": "-File \\\\dom\\sysvol\\a.ps1"}],
    )
    assert response.status_code == 200, response.text
    assert response.json()["changed"] is True

    listed = read(api, gpo)
    assert listed["events"]["Startup"] == [
        {
            "engine": "cmd",
            "command": "powershell.exe",
            "parameters": "-File \\\\dom\\sysvol\\a.ps1",
        }
    ]


def test_writing_registers_the_extension_that_runs_it(api, gpo):
    """The proof that a script applies at all.

    Values written without this are run by no client — visible in every
    console, effective nowhere, and nothing reports it.
    """
    write(api, gpo, scripts=[{"command": "a.cmd"}])

    assert read(api, gpo)["registered"] is True

    value = extensions(api, gpo).upper()
    assert SCRIPTS_CSE in value
    assert SCRIPTS_TOOL in value


def test_writing_advances_the_version(api, gpo):
    """Windows re-reads a policy only when this number changes."""
    before = read(api, gpo)["version"]

    write(api, gpo, scripts=[{"command": "a.cmd"}])

    assert read(api, gpo)["version"] > before


def test_only_the_computer_half_moves_for_a_computer_script(api, gpo):
    """The low word counts computer changes, the high word user changes."""
    before = api.get(f"/api/v1/gpos/gpo?dn={quoted(gpo['dn'])}").json()

    write(api, gpo, scripts=[{"command": "a.cmd"}])

    after = api.get(f"/api/v1/gpos/gpo?dn={quoted(gpo['dn'])}").json()
    assert after["machine_version"] > before["machine_version"]
    assert after["user_version"] == before["user_version"]


def test_writing_the_same_thing_twice_changes_nothing(api, gpo):
    """Advancing the version would make every client in the domain re-read a
    policy that did not change."""
    write(api, gpo, scripts=[{"command": "a.cmd"}])
    again = write(api, gpo, scripts=[{"command": "a.cmd"}])

    assert again.json()["changed"] is False


def test_the_order_is_kept(api, gpo):
    write(
        api,
        gpo,
        scripts=[{"command": "first.cmd"}, {"command": "second.cmd"}],
    )

    listed = read(api, gpo)["events"]["Startup"]
    assert [item["command"] for item in listed] == ["first.cmd", "second.cmd"]


def test_reordering_is_written_back(api, gpo):
    write(api, gpo, scripts=[{"command": "first.cmd"}, {"command": "second.cmd"}])
    write(api, gpo, scripts=[{"command": "second.cmd"}, {"command": "first.cmd"}])

    listed = read(api, gpo)["events"]["Startup"]
    assert [item["command"] for item in listed] == ["second.cmd", "first.cmd"]


def test_the_two_events_do_not_overwrite_each_other(api, gpo):
    """Both live in one file, so writing one means rendering both."""
    write(api, gpo, event="Startup", scripts=[{"command": "up.cmd"}])
    write(api, gpo, event="Shutdown", scripts=[{"command": "down.cmd"}])

    events = read(api, gpo)["events"]
    assert [item["command"] for item in events["Startup"]] == ["up.cmd"]
    assert [item["command"] for item in events["Shutdown"]] == ["down.cmd"]


def test_the_two_engines_do_not_overwrite_each_other(api, gpo):
    """Separate files, one list in the editor."""
    write(api, gpo, engine="cmd", scripts=[{"command": "a.cmd"}])
    write(api, gpo, engine="powershell", scripts=[{"command": "b.ps1"}])

    listed = read(api, gpo)["events"]["Startup"]
    assert {item["engine"] for item in listed} == {"cmd", "powershell"}


def test_the_powershell_order_flag_round_trips(api, gpo):
    write(api, gpo, engine="powershell", scripts=[{"command": "b.ps1"}], ps_first=True)

    assert read(api, gpo)["ps_first"] is True


# ---------------------------------------------------------------------------
# Taking them away
# ---------------------------------------------------------------------------


def test_removing_the_last_script_unregisters_the_extension(api, gpo):
    """A registered extension with nothing behind it makes every client fetch
    the policy on every refresh and find nothing there."""
    write(api, gpo, scripts=[{"command": "a.cmd"}])
    assert read(api, gpo)["registered"] is True

    write(api, gpo, scripts=[])

    listed = read(api, gpo)
    assert listed["events"]["Startup"] == []
    assert listed["registered"] is False
    assert SCRIPTS_CSE not in extensions(api, gpo).upper()


def test_the_extension_stays_while_the_other_event_has_one(api, gpo):
    write(api, gpo, event="Startup", scripts=[{"command": "a.cmd"}])
    write(api, gpo, event="Shutdown", scripts=[{"command": "b.cmd"}])

    write(api, gpo, event="Startup", scripts=[])

    assert read(api, gpo)["registered"] is True


# ---------------------------------------------------------------------------
# The script files themselves
# ---------------------------------------------------------------------------


def files_url(gpo, half="Machine", event="Startup", suffix=""):
    return (
        f"/api/v1/gpos/scripts/files{suffix}"
        f"?dn={quoted(gpo['dn'])}&half={half}&event={event}"
    )


def test_a_fresh_policy_has_no_script_files(api, gpo):
    assert api.get(files_url(gpo)).json()["files"] == []


def test_a_file_can_be_stored_and_read_back(api, gpo):
    """Keeping the script in the GPO is a convenience: it travels with a
    backup and with a copy. Windows runs any path the client can reach."""
    body = b"@echo off\r\necho hello\r\n"
    stored = api.post(
        files_url(gpo), files={"file": ("hello.cmd", body, "application/octet-stream")}
    )
    assert stored.status_code == 200, stored.text

    listed = api.get(files_url(gpo)).json()["files"]
    assert [item["name"] for item in listed] == ["hello.cmd"]

    fetched = api.get(files_url(gpo, suffix="/content") + "&name=hello.cmd")
    assert fetched.content == body


def test_storing_a_file_does_not_schedule_it(api, gpo):
    """A helper another script calls belongs on the share without being run.
    Adding a line for it would schedule something nobody asked for."""
    api.post(files_url(gpo), files={"file": ("helper.cmd", b"rem", "application/octet-stream")})

    assert read(api, gpo)["events"]["Startup"] == []


def test_a_file_can_be_removed(api, gpo):
    api.post(files_url(gpo), files={"file": ("gone.cmd", b"rem", "application/octet-stream")})

    removed = api.request("DELETE", files_url(gpo) + "&name=gone.cmd")
    assert removed.status_code == 200, removed.text

    assert api.get(files_url(gpo)).json()["files"] == []


def test_each_event_has_its_own_directory(api, gpo):
    api.post(files_url(gpo, event="Startup"), files={"file": ("up.cmd", b"rem")})

    assert api.get(files_url(gpo, event="Shutdown")).json()["files"] == []


@pytest.mark.parametrize("name", ["..\\..\\evil.cmd", "sub/dir.cmd", "C:evil.cmd", ".."])
def test_a_name_that_climbs_out_is_refused(api, gpo, name):
    """This writes onto a share every domain member reads."""
    response = api.post(files_url(gpo), files={"file": (name, b"rem")})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_script_name"


