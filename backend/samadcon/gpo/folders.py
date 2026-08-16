"""Folder redirection — reading it.

``User/Documents & Settings/fdeploy1.ini``, user configuration only. The
structure is not guessed: it is what Samba's own ``GPFDeploy1IniParser``
special-cases, which is the closest thing to a specification available without
a file Windows wrote.

    [Folder_Redirection]
    {folder-guid}=S-1-5-21-…-513;S-1-5-21-…-512;

    [Version]
    …

    [{folder-guid}_S-1-5-21-…-513]
    FullPath=\\\\server\\share\\%USERNAME%\\Documents
    …

The header names each redirected folder and, per folder, the groups it applies
to. Each of those pairs then gets a section of its own, keyed
``{GUID}_{SID}``, holding the path and the options.

**Reading only, for now.** Writing needs three things this module does not
have on evidence: the file's encoding, the option keys that sit beside
``FullPath``, and the client-side extension GUIDs. Every one of them has been
wrong-from-memory at least once in this project already, and a folder
redirection written wrong relocates people's profiles — so the writer waits
for a file GPMC produced, the same way the scripts writer did.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from samadcon.ad import values as ad_values
from samadcon.ad.connection import DirectoryConnection
from samadcon.core.errors import Conflict, InvalidRequest
from samadcon.gpo import container, cse, sysvol

logger = logging.getLogger(__name__)

# User configuration only; there is no computer half for this.
FDEPLOY_PATH = "User\\Documents & Settings\\fdeploy1.ini"

HEADER_SECTION = "folder_redirection"
VERSION_SECTION = "version"

# The folders GPMC offers to redirect, by the id Windows knows them under.
#
# Only entries verified against a real system belong here. Windows keeps the
# same table in the registry under
# ``HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Explorer\\FolderDescriptions``,
# which is where these come from — a label guessed from memory would offer to
# redirect "Documents" and move somebody's music instead, and the editor would
# look right while doing it. Anything the file names but this table does not is
# still shown, by its id.
# The names are Windows' own — "Personal" is what it calls Documents — and the
# editor translates them for display rather than renaming them here.
KNOWN_FOLDERS: dict[str, str] = {
    "{3EB685DB-65F9-4CF6-A03A-E3EF65729F3D}": "AppData",
    "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}": "Desktop",
    "{625B53C3-AB48-4EC1-BA1F-A1EF4146FC19}": "Start Menu",
    "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}": "Personal",
    "{33E28130-4E1E-4676-835A-98395C3BC3BB}": "My Pictures",
    "{4BD8D571-6D19-48D3-BE97-422220080E43}": "My Music",
    "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}": "My Video",
    "{1777F761-68AD-4D8A-87BD-30B759FA33DD}": "Favorites",
    "{56784854-C6CB-462B-8169-88E350ACB882}": "Contacts",
    "{374DE290-123F-4565-9164-39C4925E467B}": "Downloads",
    "{BFB9D5E0-C6A9-404C-B2B2-AE6DB6AF4968}": "Links",
    "{7D1D3A04-DEBB-4115-95CF-2F29DA2920DA}": "Searches",
    # Two independent confirmations: the registry, and the reference GPO whose
    # FullPath ends in "Saved Games".
    "{4C5C32FF-BB9D-43B0-B5B4-2D72E54EAAA4}": "SavedGames",
}


def known_folders() -> list[dict[str, str]]:
    """The redirectable folders, for the editor's list."""
    return [{"guid": guid, "name": name} for guid, name in sorted(KNOWN_FOLDERS.items())]

# A per-redirection section is the folder's GUID and the group's SID joined by
# an underscore — the split Samba's parser performs to generalise a backup.
_SECTION_RE = re.compile(r"^(?P<guid>\{[^}]+\})_(?P<sid>.+)$")


def parse(text: str) -> dict[str, Any]:
    """Read ``fdeploy1.ini`` into the folders it redirects.

    Sections that fit neither shape are kept under ``other`` rather than
    dropped: this is a read, and a file we do not fully understand is better
    shown than silently thinned out.
    """
    sections = _sections(text)

    header: dict[str, str] = {}
    version: dict[str, str] = {}
    for name, entries in sections.items():
        # Both are matched without regard to case, and that is not politeness:
        # GPMC writes "[version]" in lower case next to "[Folder_Redirection]"
        # in mixed case, so an exact match finds one and misses the other.
        if name.lower() == HEADER_SECTION:
            header = entries
        elif name.lower() == VERSION_SECTION:
            version = entries

    folders: dict[str, dict[str, Any]] = {}
    for guid, sids in header.items():
        folders[guid.upper()] = {
            "guid": guid.upper(),
            "trustees": [sid for sid in sids.strip().strip(";").split(";") if sid],
            "targets": [],
        }

    other: dict[str, dict[str, str]] = {}
    for name, entries in sections.items():
        lowered = name.lower()
        if lowered in (HEADER_SECTION, VERSION_SECTION):
            continue

        match = _SECTION_RE.match(name)
        if match is None:
            other[name] = entries
            continue

        guid = match.group("guid").upper()
        folder = folders.setdefault(guid, {"guid": guid, "trustees": [], "targets": []})
        folder["targets"].append(
            {
                "sid": match.group("sid"),
                "path": entries.get("FullPath", ""),
                # Everything else verbatim. The option keys are not on
                # evidence yet, and inventing names for them would be the
                # first step towards writing them wrongly.
                "options": {
                    key: value for key, value in entries.items() if key != "FullPath"
                },
            }
        )

    return {
        "version": version,
        "folders": sorted(folders.values(), key=lambda item: item["guid"]),
        "other": other,
    }


def _sections(text: str) -> dict[str, dict[str, str]]:
    """The file as sections of key/value pairs, in the order they appear."""
    sections: dict[str, dict[str, str]] = {}
    current = ""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            current = stripped[1:-1].strip()
            sections.setdefault(current, {})
            continue
        if not current or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        sections[current][key.strip()] = value.strip()
    return sections


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------
#
# The layout below is copied from a file GPMC wrote — 460 bytes, read off the
# share with `od -c` and reassembled in the tests. Three of its details would
# never have been guessed: the file opens with a blank line, then a line of
# five spaces, then another blank line; the version section is spelled
# ``[version]`` in lower case beside ``[Folder_Redirection]`` in mixed case;
# and each redirection carries a ``Flags`` number next to its path.

BOM = b"\xff\xfe"
NEWLINE = "\r\n"
PREAMBLE = f"{NEWLINE}     {NEWLINE}"

VERSION_KEY = "version"
DEFAULT_VERSION = "100"

FULL_PATH = "FullPath"
FLAGS = "Flags"

# What GPMC wrote for "create a folder for each user under the root path" with
# its default options. **Carried, not computed**: which bit means what is not
# on evidence, so an entry being edited keeps the flags it has and a new one
# starts from the value Windows itself used. Inventing a number here would
# change how a client treats people's existing files.
DEFAULT_FLAGS = "1211"


def render(
    folders: list[dict[str, Any]],
    *,
    version: str = DEFAULT_VERSION,
) -> bytes:
    """Render ``fdeploy1.ini``, ready to be written to SYSVOL.

    *folders* is the shape :func:`parse` returns. A folder with no targets is
    dropped: it would name a redirection in the header that no section
    describes, which is the file's own version of a dangling reference.
    """
    lines: list[str] = [f"[{VERSION_SECTION}]", f"{VERSION_KEY}={version}"]

    kept = [folder for folder in folders if folder.get("targets")]

    lines.append("[Folder_Redirection]")
    for folder in kept:
        sids = [target["sid"] for target in folder["targets"]]
        # The trailing semicolon is not decoration: Samba's own parser calls
        # out the convention, and the file GPMC wrote has it.
        lines.append(f"{folder['guid']}=" + "".join(f"{sid};" for sid in sids))

    for folder in kept:
        for target in folder["targets"]:
            lines.append(f"[{folder['guid']}_{target['sid']}]")
            options = dict(target.get("options") or {})
            lines.append(f"{FLAGS}={options.pop(FLAGS, DEFAULT_FLAGS)}")
            lines.append(f"{FULL_PATH}={target['path']}")
            # Anything else the file carried, kept in place. We do not know
            # what all of it means, which is the reason to keep it rather than
            # the reason to drop it.
            lines.extend(f"{key}={value}" for key, value in options.items())

    text = PREAMBLE + "".join(f"{line}{NEWLINE}" for line in lines)
    return BOM + text.encode("utf-16-le")


def set_target(
    text: str | None,
    guid: str,
    sid: str,
    path: str | None,
) -> bytes:
    """Redirect one folder for one group, or stop redirecting it.

    *path* of None removes that pairing; removing the last one for a folder
    removes the folder from the header too.
    """
    parsed = parse(text) if text else {"folders": [], "version": {}}
    folders = [dict(item) for item in parsed["folders"]]
    guid = guid.upper()

    folder = next((item for item in folders if item["guid"] == guid), None)
    if folder is None:
        if path is None:
            return render(folders, version=_version_of(parsed))
        folder = {"guid": guid, "trustees": [], "targets": []}
        folders.append(folder)

    targets = [item for item in folder["targets"] if item["sid"].lower() != sid.lower()]
    if path is not None:
        existing = next(
            (item for item in folder["targets"] if item["sid"].lower() == sid.lower()), None
        )
        targets.append(
            {
                "sid": sid,
                "path": path,
                # An edit keeps the flags the entry already had.
                "options": dict(existing["options"]) if existing else {},
            }
        )
    folder["targets"] = targets

    return render(folders, version=_version_of(parsed))


def _version_of(parsed: dict[str, Any]) -> str:
    for key, value in (parsed.get("version") or {}).items():
        if key.lower() == VERSION_KEY:
            return value
    return DEFAULT_VERSION


def read(conn: DirectoryConnection, dn: str) -> dict[str, Any]:
    """The folder redirection of one GPO, or nothing when it has none.

    One shape in every case, including "no file yet". The version is what a
    later write is checked against, so leaving it out of the empty answer
    would take the conflict protection away from exactly the policy most
    likely to be edited by two people at once — a fresh one.
    """
    gpo = container.get_gpo(conn, dn)
    answer: dict[str, Any] = {
        "dn": dn,
        "present": False,
        "version_number": gpo["version"],
        "registered": _registered(conn, dn),
        "folders": [],
        "version": {},
        "other": {},
    }

    if not gpo["path"]:
        return answer

    share = sysvol.sysvol_for(conn)
    _, _, base = sysvol.parse_unc(gpo["path"])
    resolved = share.resolve(base, FDEPLOY_PATH)
    if resolved is None:
        return answer

    return {**answer, "present": True, **parse(share.read_text(resolved))}


def write(
    conn: DirectoryConnection,
    dn: str,
    guid: str,
    sid: str,
    path: str | None,
    *,
    expected_version: int | None = None,
) -> dict[str, Any]:
    """Redirect one folder for one group, or stop redirecting it.

    Folder redirection is user configuration only, so only the user half of
    the version advances and only ``gPCUserExtensionNames`` is touched.
    """
    gpo = container.get_gpo(conn, dn)
    if expected_version is not None and gpo["version"] != expected_version:
        raise Conflict(
            "This policy was changed by someone else in the meantime.",
            code="gpo_version_conflict",
            hint="Reload the redirection and make the change again.",
            context={"expected": expected_version, "current": gpo["version"]},
        )
    if not gpo["path"]:
        raise InvalidRequest(
            "This policy has no SYSVOL path.", code="gpo_without_path", context={"dn": dn}
        )

    share = sysvol.sysvol_for(conn)
    _, _, base = sysvol.parse_unc(gpo["path"])
    resolved = share.resolve(base, FDEPLOY_PATH)
    current = share.read_text(resolved) if resolved else None

    updated = set_target(current, guid, sid, path)
    if current is not None and updated == BOM + current.encode("utf-16-le"):
        return {"dn": dn, "changed": False, "version": gpo["version"]}

    target = resolved or sysvol.join(base, FDEPLOY_PATH)
    share.makedirs(target.rsplit("\\", 1)[0])
    share.write(target, updated)

    cse.register(
        conn,
        dn,
        "User",
        cse.REDIRECTION_CSE,
        cse.REDIRECTION_TOOL,
        present=bool(parse(updated.decode("utf-16"))["folders"]),
    )

    after = container.bump_version(conn, dn, machine_changed=False, user_changed=True)
    logger.info("redirected %s for %s in %s", guid, sid, gpo["display_name"])
    return {"dn": dn, "changed": True, "version": after["version"]}


def _registered(conn: DirectoryConnection, dn: str) -> bool:
    """Whether the extension that applies redirection is listed on this GPO."""
    attribute = cse.HALF_ATTRIBUTE["User"]
    entry = conn.get(dn, attrs=[attribute])
    value = (ad_values.as_str(entry, attribute) if entry is not None else None) or ""
    return cse.braced(cse.REDIRECTION_CSE) in value.upper()
