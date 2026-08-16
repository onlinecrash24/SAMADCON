"""Startup, shutdown, logon and logoff scripts.

Two files per half, side by side in the same directory:

    Machine/Scripts/scripts.ini      [Startup] [Shutdown]     .cmd/.bat/.exe
    Machine/Scripts/psscripts.ini    [Startup] [Shutdown]     PowerShell
    User/Scripts/scripts.ini         [Logon] [Logoff]         .cmd/.bat/.exe
    User/Scripts/psscripts.ini       [Logon] [Logoff]         PowerShell

Both are **UTF-16LE with a BOM and CRLF line endings**. Windows writes them
that way and reads them back the same way; a file saved as UTF-8 is read as
mojibake and the scripts silently never run.

Inside a section the entries are numbered pairs::

    [Startup]
    0CmdLine=powershell.exe
    0Parameters=-ExecutionPolicy Bypass \\\\dom\\sysvol\\dom\\scripts\\a.ps1
    1CmdLine=map-drives.cmd
    1Parameters=

The numbers *are* the execution order, and they have to run 0, 1, 2 without
gaps — Windows stops at the first missing index. So reordering and removing
are both the same operation: renumber everything from zero. That is why this
module reads into a list and writes the list back out rather than editing keys
in place.

We parse and render these ourselves rather than going through
``samba.gp_parse.gp_scripts``. That parser exists to turn a policy file into
XML for backup and back, not to edit one, and the unit tests for this module
have to run without a domain controller *and* without the Samba bindings —
which is also what lets the byte-for-byte comparison against a file GPMC wrote
be a test rather than a manual check.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from samcon.ad import values as ad_values
from samcon.ad.connection import DirectoryConnection
from samcon.core.errors import Conflict, InvalidRequest
from samcon.gpo import container, cse, sysvol

logger = logging.getLogger(__name__)

# Which events each half knows, in the order the editor shows them.
EVENTS: dict[str, tuple[str, ...]] = {
    "Machine": ("Startup", "Shutdown"),
    "User": ("Logon", "Logoff"),
}

# The two engines, and the file each one lives in.
FILES: dict[str, str] = {"cmd": "scripts.ini", "powershell": "psscripts.ini"}

BOM = b"\xff\xfe"
NEWLINE = "\r\n"

# psscripts.ini carries one setting of its own: whether PowerShell scripts run
# before the others for the same event.
CONFIG_SECTION = "ScriptsConfig"
EXECUTE_PS_FIRST = "StartExecutePSFirst"


@dataclass(frozen=True)
class Script:
    """One command and its arguments, as one numbered pair in the file."""

    command: str
    parameters: str = ""


def path_for(half: str, engine: str) -> str:
    """Where the file for *half* and *engine* lives inside a GPO."""
    _check(half, engine)
    return f"{half}\\Scripts\\{FILES[engine]}"


def directory_for(half: str, event: str) -> str:
    """Where the script files themselves live.

    One directory per event, next to the ini and named after it — both engines
    share it, which is why the engine is not part of the path.
    """
    _check(half)
    if event not in EVENTS[half]:
        raise InvalidRequest(
            "This event does not belong to this half of the policy.",
            code="unknown_script_event",
            hint=f"{half} scripts run at: {', '.join(EVENTS[half])}.",
            context={"half": half, "event": event},
        )
    return f"{half}\\Scripts\\{event}"


def _check(half: str, engine: str | None = None) -> None:
    if half not in EVENTS:
        raise InvalidRequest(
            "Scripts belong to the computer half or the user half.",
            code="unknown_script_half",
            context={"given": half},
        )
    if engine is not None and engine not in FILES:
        raise InvalidRequest(
            "Unknown script engine.",
            code="unknown_script_engine",
            hint=f"Expected one of: {', '.join(FILES)}.",
            context={"given": engine},
        )


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def parse(text: str) -> dict[str, list[Script]]:
    """Read one scripts file into its sections.

    Tolerant on the way in: unknown sections are kept, blank and comment lines
    are dropped, and a gap in the numbering does not stop the read even though
    it would stop Windows. What comes back is ordered by number, and writing it
    out again closes any gap.
    """
    numbered: dict[str, dict[int, dict[str, str]]] = {}
    section = ""

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip()
            numbered.setdefault(section, {})
            continue
        if not section or "=" not in stripped:
            continue

        key, _, value = stripped.partition("=")
        key = key.strip()
        digits = "".join(char for char in key if char.isdigit())
        if not digits:
            # [ScriptsConfig] lives here too; execute_ps_first() reads it.
            continue
        field = key[len(digits) :].strip().lower()
        numbered[section].setdefault(int(digits), {})[field] = value.strip()

    sections: dict[str, list[Script]] = {}
    for name, entries in numbered.items():
        scripts = [
            Script(
                command=entries[index].get("cmdline", ""),
                parameters=entries[index].get("parameters", ""),
            )
            for index in sorted(entries)
        ]
        # An entry with no command is not a script; Windows would skip it and
        # then stop at the gap it leaves behind.
        sections[name] = [script for script in scripts if script.command]

    return sections


def execute_ps_first(text: str) -> bool | None:
    """Whether PowerShell scripts run before the others, or None if unsaid."""
    section = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip()
            continue
        if section.lower() != CONFIG_SECTION.lower() or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key.strip().lower() == EXECUTE_PS_FIRST.lower():
            return value.strip().lower() == "true"
    return None


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def render(
    sections: dict[str, list[Script]],
    *,
    order: tuple[str, ...] = (),
    ps_first: bool | None = None,
) -> bytes:
    """Render a scripts file, ready to be written to SYSVOL.

    *order* names the sections that come first and in which order; anything
    else follows in the order it was given.

    Two details are copied from a file GPMC wrote rather than reasoned out,
    and both would otherwise show up as a spurious change the first time we
    rewrite someone else's policy:

    * a **blank line between the BOM and the first section**, and
    * **no empty sections** — an event with no scripts is simply absent, not a
      bare header.
    """
    names = [name for name in order if sections.get(name)]
    names.extend(name for name, entries in sections.items() if entries and name not in names)

    lines: list[str] = []
    for name in names:
        lines.append(f"[{name}]")
        for index, script in enumerate(sections[name]):
            lines.append(f"{index}CmdLine={script.command}")
            lines.append(f"{index}Parameters={script.parameters}")

    if ps_first is not None:
        lines.append(f"[{CONFIG_SECTION}]")
        lines.append(f"{EXECUTE_PS_FIRST}={'true' if ps_first else 'false'}")

    text = NEWLINE + "".join(f"{line}{NEWLINE}" for line in lines)
    return BOM + text.encode("utf-16-le")


def set_scripts(
    text: str | None,
    event: str,
    scripts: list[Script],
    *,
    half: str,
    ps_first: bool | None = None,
) -> bytes:
    """Replace one event's scripts, leaving the other event alone.

    The two events share a file, so writing one means rendering both — reading
    first is not an optimisation here, it is the only way not to discard the
    other half of the file.
    """
    _check(half)
    sections = parse(text) if text else {}
    sections[event] = list(scripts)

    if ps_first is None and text:
        ps_first = execute_ps_first(text)

    return render(sections, order=EVENTS[half], ps_first=ps_first)


# ---------------------------------------------------------------------------
# One GPO
# ---------------------------------------------------------------------------


def read(conn: DirectoryConnection, dn: str, half: str) -> dict[str, Any]:
    """Every script of one half, from both files.

    ``registered`` is the part no other console shows: scripts written into a
    GPO whose extension is not listed in ``gPC*ExtensionNames`` are run by
    nobody, and the policy looks complete everywhere.
    """
    _check(half)
    gpo = container.get_gpo(conn, dn)

    events: dict[str, list[dict[str, Any]]] = {event: [] for event in EVENTS[half]}
    ps_first: bool | None = None

    for engine in FILES:
        text = _read_file(conn, gpo, half, engine)
        if text is None:
            continue
        if engine == "powershell":
            ps_first = execute_ps_first(text)
        for event, entries in parse(text).items():
            if event not in events:
                continue
            events[event].extend(
                {"engine": engine, "command": item.command, "parameters": item.parameters}
                for item in entries
            )

    registered = cse.braced(cse.SCRIPTS_CSE) in (
        ad_values.as_str(conn.get(dn, attrs=[cse.HALF_ATTRIBUTE[half]]), cse.HALF_ATTRIBUTE[half])
        or ""
    ).upper()

    return {
        "dn": dn,
        "half": half,
        "version": gpo["version"],
        "events": events,
        "ps_first": ps_first,
        "registered": registered,
    }


def write(
    conn: DirectoryConnection,
    dn: str,
    half: str,
    event: str,
    engine: str,
    entries: list[Script],
    *,
    expected_version: int | None = None,
    ps_first: bool | None = None,
) -> dict[str, Any]:
    """Replace one event's scripts for one engine.

    The extension is registered when the half ends up with any script at all
    and taken off again when it does not — a registered extension with nothing
    behind it makes every client fetch the policy on every refresh and find
    nothing there.
    """
    _check(half, engine)
    directory_for(half, event)  # rejects an event from the wrong half

    gpo = container.get_gpo(conn, dn)
    if expected_version is not None and gpo["version"] != expected_version:
        raise Conflict(
            "This policy was changed by someone else in the meantime.",
            code="gpo_version_conflict",
            hint="Reload the scripts and make the change again.",
            context={"expected": expected_version, "current": gpo["version"]},
        )

    current = _read_file(conn, gpo, half, engine)
    updated = set_scripts(current, event, entries, half=half, ps_first=ps_first)

    if current is not None and updated == BOM + current.encode("utf-16-le"):
        # Saying so beats advancing the version and making every client in the
        # domain re-read a policy that did not change.
        return {"dn": dn, "changed": False, "version": gpo["version"]}

    share = sysvol.sysvol_for(conn)
    _, _, base = sysvol.parse_unc(gpo["path"])
    target = sysvol.join(base, path_for(half, engine))
    share.makedirs(target.rsplit("\\", 1)[0])
    share.write(target, updated)

    cse.register(
        conn,
        dn,
        half,
        cse.SCRIPTS_CSE,
        cse.SCRIPTS_TOOL,
        present=_any_scripts(conn, dn, half),
    )

    after = container.bump_version(
        conn, dn, machine_changed=half == "Machine", user_changed=half == "User"
    )
    logger.info(
        "wrote %d %s %s script(s) to %s", len(entries), event.lower(), engine, gpo["display_name"]
    )
    return {"dn": dn, "changed": True, "version": after["version"], "written": len(entries)}


# ---------------------------------------------------------------------------
# The script files themselves
# ---------------------------------------------------------------------------
#
# A script does not have to live inside its GPO. The reference policy in the
# domain this is verified against runs one straight off the SYSVOL `scripts`
# share, and Windows is happy with any path the client can reach. Keeping them
# in the GPO is a convenience — the files travel with a backup and a copy —
# and that is the case these functions serve.


def list_files(conn: DirectoryConnection, dn: str, half: str, event: str) -> list[dict[str, Any]]:
    """The files in one event's directory, or nothing when there is none."""
    directory = directory_for(half, event)
    gpo = container.get_gpo(conn, dn)
    if not gpo["path"]:
        return []

    share = sysvol.sysvol_for(conn)
    _, _, base = sysvol.parse_unc(gpo["path"])
    resolved = share.resolve(base, directory)
    if resolved is None:
        return []

    return [entry for entry in share.listdir(resolved) if not entry["is_directory"]]


def read_file(conn: DirectoryConnection, dn: str, half: str, event: str, name: str) -> bytes:
    """One script file, for downloading it back out."""
    return sysvol.sysvol_for(conn).read(_file_path(conn, dn, half, event, name))


def write_file(
    conn: DirectoryConnection, dn: str, half: str, event: str, name: str, data: bytes
) -> dict[str, Any]:
    """Put a script file into its event's directory.

    Deliberately *not* added to the ini as well: a file on the share and an
    entry in the list are separate decisions — an administrator may upload a
    helper that another script calls, and silently adding a line for it would
    schedule something nobody asked to run.
    """
    path = _file_path(conn, dn, half, event, name)
    share = sysvol.sysvol_for(conn)
    share.makedirs(path.rsplit("\\", 1)[0])
    share.write(path, data)
    logger.info("stored %s in the %s scripts of %s", name, event.lower(), dn)
    return {"name": name, "size": len(data)}


def delete_file(conn: DirectoryConnection, dn: str, half: str, event: str, name: str) -> None:
    """Remove a script file. Any entry naming it stays — see write_file."""
    sysvol.sysvol_for(conn).unlink(_file_path(conn, dn, half, event, name))
    logger.info("removed %s from the %s scripts of %s", name, event.lower(), dn)


def _file_path(conn: DirectoryConnection, dn: str, half: str, event: str, name: str) -> str:
    """Where one script file goes, with the name checked first.

    This writes onto a share every domain member reads, so a name that climbs
    out of the directory is refused rather than reshaped.
    """
    directory = directory_for(half, event)
    cleaned = name.replace("/", "\\").strip().strip("\\")
    if not cleaned or "\\" in cleaned or cleaned in (".", "..") or ":" in cleaned:
        raise InvalidRequest(
            "A script file needs a plain name, without a path.",
            code="invalid_script_name",
            context={"given": name},
        )

    gpo = container.get_gpo(conn, dn)
    if not gpo["path"]:
        raise InvalidRequest(
            "This policy has no SYSVOL path.",
            code="gpo_without_path",
            context={"dn": dn},
        )
    _, _, base = sysvol.parse_unc(gpo["path"])
    return sysvol.join(base, f"{directory}\\{cleaned}")


def _read_file(
    conn: DirectoryConnection, gpo: dict[str, Any], half: str, engine: str
) -> str | None:
    """One scripts file of a GPO, or None when it has none."""
    if not gpo["path"]:
        return None
    share = sysvol.sysvol_for(conn)
    _, _, base = sysvol.parse_unc(gpo["path"])
    resolved = share.resolve(base, path_for(half, engine))
    return None if resolved is None else share.read_text(resolved)


def _any_scripts(conn: DirectoryConnection, dn: str, half: str) -> bool:
    """Whether this half has a script left, in either file."""
    gpo = container.get_gpo(conn, dn)
    for engine in FILES:
        text = _read_file(conn, gpo, half, engine)
        if text and any(parse(text).get(event) for event in EVENTS[half]):
            return True
    return False
