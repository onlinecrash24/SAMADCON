"""What a group policy actually contains.

Reads every part of a GPO that carries settings and reports it in one
structure. Read-only throughout — this is the view that says *what is in
there*, which is also the thing to check after every edit in the milestones
that follow.

The parts, and where they live under the GPO's SYSVOL directory::

    Machine|User/Registry.pol                        administrative templates
    Machine/Microsoft/Windows NT/SecEdit/GptTmpl.inf security settings
    Machine|User/Scripts/scripts.ini                 startup/logon scripts
    Machine|User/Preferences/<Type>/<Type>.xml       group policy preferences
    Machine|User/VGP/VTLA/.../manifest.xml           Samba's Linux policies

Two decisions shape the implementation:

* **The tree is listed once and matched afterwards**, rather than probed path
  by path. Names on SYSVOL come in whatever case the tool that created them
  used — Samba's provisioning writes ``MACHINE``, Windows writes ``Machine`` —
  and whether a share hides that difference is a server setting. Matching
  against a listing removes the question instead of relying on the answer.
* **Anything present and unrecognised is still reported**, as a file. A report
  that omits what it does not understand reads as "this policy is empty",
  which is the one conclusion it must never invite by accident.
"""

from __future__ import annotations

import logging
from typing import Any
from xml.etree import ElementTree

from samadcon.ad.connection import DirectoryConnection
from samadcon.core.errors import InvalidRequest
from samadcon.gpo import container, folders, registry_pol, sysvol

logger = logging.getLogger(__name__)

HALVES = ("Machine", "User")

REGISTRY_FILE = "Registry.pol"
SECEDIT_PATH = "Microsoft\\Windows NT\\SecEdit\\GptTmpl.inf"
SCRIPTS_PATH = "Scripts\\scripts.ini"
FDEPLOY_FILE = "Documents & Settings\\fdeploy1.ini"
PREFERENCES_DIR = "Preferences"
VGP_DIR = "VGP"
VGP_MANIFEST = "manifest.xml"

# Structure rather than settings; listing them as unrecognised content is noise.
IGNORED_FILES = frozenset({"gpt.ini", "desktop.ini"})

# The header sections every GptTmpl.inf carries. They say the file is UTF-16
# and which format revision it is — nothing an administrator set, and nothing
# a client applies.
INF_BOILERPLATE = frozenset({"unicode", "version"})

# How deep a policy tree is walked. Preferences sit three levels down and VGP
# four; the bound is here because this walks a network share, and a tree that
# is somehow deeper must not turn a report into an unbounded number of round
# trips.
MAX_DEPTH = 8


def build_report(conn: DirectoryConnection, dn: str) -> dict[str, Any]:
    """Everything one policy holds, in one structure."""
    gpo = container.get_gpo(conn, dn)
    report: dict[str, Any] = {
        "gpo": gpo,
        "status": container.status(conn, gpo),
        "machine": _empty_half(),
        "user": _empty_half(),
        "unreadable": [],
        "empty": True,
    }

    if not gpo["path"]:
        report["unreadable"].append({"path": "", "reason": "no_path"})
        return report

    try:
        _, _, base = sysvol.parse_unc(gpo["path"])
    except InvalidRequest:
        report["unreadable"].append({"path": gpo["path"], "reason": "invalid_path"})
        return report

    share = sysvol.sysvol_for(conn)
    children = _listdir(share, base, report["unreadable"])

    for half in HALVES:
        directory = _match(children, half)
        if directory is None:
            # Not an error in itself, but worth saying: a policy without the
            # half it claims to configure is the state that looks like an
            # empty policy and is not one.
            report["unreadable"].append(
                {"path": sysvol.join(base, half), "reason": "half_missing"}
            )
            continue
        report[half.lower()] = _read_half(share, directory, report["unreadable"], name=half)

    report["empty"] = not any(_applies_anything(report[half.lower()]) for half in HALVES)
    return report


def _empty_half() -> dict[str, Any]:
    return {
        "registry": [],
        "registry_count": 0,
        "security": {},
        "scripts": {},
        # User configuration only; there is no computer half for this one.
        "redirection": {},
        "preferences": [],
        "vgp": [],
        "other_files": [],
    }


def _has_content(half: dict[str, Any]) -> bool:
    """Whether there is anything to show for this half."""
    return bool(
        half["registry"]
        or half["security"]
        or half["scripts"]
        or half["redirection"]
        or half["preferences"]
        or half["vgp"]
        or half["other_files"]
    )


def _applies_anything(half: dict[str, Any]) -> bool:
    """Whether this half changes anything on a client.

    Deliberately stricter than having something to show. An empty Samba
    manifest is a real file and belongs in the report — samba-tool leaves one
    behind when the last entry is removed, so it is the normal residue of
    clearing a policy — but it reaches no client, and calling such a policy
    non-empty sends someone hunting for a setting that is not there.
    """
    return bool(
        half["registry"]
        or half["security"]
        or half["scripts"]
        or half["redirection"]
        or half["preferences"]
        or any(group["entries"] for group in half["vgp"])
        # Not understood, so not assumed harmless.
        or half["other_files"]
    )


def _note(unreadable: list[dict[str, Any]], path: str, exc: Exception) -> None:
    logger.warning("cannot read %s", path, exc_info=True)
    unreadable.append({"path": path, "reason": type(exc).__name__})


# ---------------------------------------------------------------------------
# Walking the tree
# ---------------------------------------------------------------------------


def _listdir(
    share: sysvol.SysvolConnection, base: str, unreadable: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    try:
        return share.listdir(base)
    except Exception as exc:  # noqa: BLE001
        _note(unreadable, base, exc)
        return []


def _match(entries: list[dict[str, Any]], name: str) -> str | None:
    """The full path of a child called *name*, whatever case it is stored in."""
    wanted = name.lower()
    for entry in entries:
        if entry["name"].lower() == wanted:
            return entry["path"]
    return None


def _walk(
    share: sysvol.SysvolConnection, base: str, *, depth: int = MAX_DEPTH
) -> list[str]:
    """Every file below *base*, to a bounded depth."""
    if depth <= 0:
        return []

    files: list[str] = []
    try:
        entries = share.listdir(base)
    except Exception:
        logger.debug("cannot list %s", base, exc_info=True)
        return files

    for entry in entries:
        if entry["is_directory"]:
            files.extend(_walk(share, entry["path"], depth=depth - 1))
        else:
            files.append(entry["path"])
    return files


def _find(files: list[str], base: str, relative: str) -> str | None:
    """The file at *base*/*relative*, matched without regard to case."""
    wanted = sysvol.join(base, relative).lower()
    for path in files:
        if path.lower() == wanted:
            return path
    return None


def _under(files: list[str], base: str, directory: str) -> list[str]:
    prefix = sysvol.join(base, directory).lower() + "\\"
    return [path for path in files if path.lower().startswith(prefix)]


# ---------------------------------------------------------------------------
# One half
# ---------------------------------------------------------------------------


def _read_half(
    share: sysvol.SysvolConnection,
    base: str,
    unreadable: list[dict[str, Any]],
    *,
    name: str,
) -> dict[str, Any]:
    half = _empty_half()
    files = _walk(share, base)
    claimed: set[str] = set()

    registry = _find(files, base, REGISTRY_FILE)
    if registry:
        claimed.add(registry.lower())
        half["registry"] = _read_registry(share, registry, unreadable)
        half["registry_count"] = sum(len(group["values"]) for group in half["registry"])

    secedit = _find(files, base, SECEDIT_PATH)
    if secedit:
        claimed.add(secedit.lower())
        half["security"] = _read_ini_sections(share, secedit, unreadable)

    scripts = _find(files, base, SCRIPTS_PATH)
    if scripts:
        claimed.add(scripts.lower())
        half["scripts"] = _read_scripts(share, scripts, unreadable)

    if name == "User":
        redirection = _find(files, base, FDEPLOY_FILE)
        if redirection:
            claimed.add(redirection.lower())
            half["redirection"] = _read_redirection(share, redirection, unreadable)

    for path in _under(files, base, PREFERENCES_DIR):
        claimed.add(path.lower())
        if not path.lower().endswith(".xml"):
            continue
        items = _read_xml_items(share, path, unreadable)
        if items is not None:
            parts = path.split("\\")
            half["preferences"].append(
                {"type": parts[-2] if len(parts) > 1 else "", "file": parts[-1], "items": items}
            )

    for path in _under(files, base, VGP_DIR):
        claimed.add(path.lower())
        if path.rsplit("\\", 1)[-1].lower() != VGP_MANIFEST:
            continue
        manifest = _read_vgp_manifest(share, path, unreadable)
        if manifest is not None:
            half["vgp"].append({"path": path, **manifest})

    half["other_files"] = [
        {"path": path, "name": path.rsplit("\\", 1)[-1]}
        for path in files
        if path.lower() not in claimed and path.rsplit("\\", 1)[-1].lower() not in IGNORED_FILES
    ]
    return half


# ---------------------------------------------------------------------------
# The individual formats
# ---------------------------------------------------------------------------


def _read_registry(
    share: sysvol.SysvolConnection, path: str, unreadable: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    try:
        return registry_pol.by_key(registry_pol.parse(share.read(path)))
    except Exception as exc:  # noqa: BLE001
        _note(unreadable, path, exc)
        return []


def _read_ini_sections(
    share: sysvol.SysvolConnection, path: str, unreadable: list[dict[str, Any]]
) -> dict[str, Any]:
    """``GptTmpl.inf`` — password policy, user rights, restricted groups.

    UTF-16 with a BOM, which :meth:`SysvolConnection.read_text` handles. The
    section names are the ones an administrator sees in the security editor,
    so they are passed through rather than translated into a vocabulary of
    our own.

    ``[Unicode]`` and ``[Version]`` are dropped. Every tool that writes this
    file writes them — ``Unicode=yes``, ``signature="$CHICAGO$"``,
    ``Revision=1`` — and they configure nothing. Reported as settings, they
    made a template holding no policy at all look like one holding two.
    """
    try:
        text = share.read_text(path)
    except Exception as exc:  # noqa: BLE001
        _note(unreadable, path, exc)
        return {}

    sections: dict[str, list[dict[str, str]]] = {}
    current = ""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            current = stripped[1:-1].strip()
            sections.setdefault(current, [])
            continue
        if not current or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        sections[current].append({"name": name.strip(), "value": value.strip()})

    return {
        name: values
        for name, values in sections.items()
        if values and name.lower() not in INF_BOILERPLATE
    }


def _read_scripts(
    share: sysvol.SysvolConnection, path: str, unreadable: list[dict[str, Any]]
) -> dict[str, Any]:
    """``scripts.ini`` — startup/shutdown or logon/logoff commands.

    Numbered keys per section: ``0CmdLine``, ``0Parameters``, ``1CmdLine`` and
    so on. Pairing them up is what makes the file readable.
    """
    try:
        text = share.read_text(path)
    except Exception as exc:  # noqa: BLE001
        _note(unreadable, path, exc)
        return {}

    sections: dict[str, dict[int, dict[str, str]]] = {}
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
        key = key.strip()
        digits = "".join(char for char in key if char.isdigit())
        if not digits:
            continue
        field = key[len(digits) :].lower()
        entry = sections[current].setdefault(int(digits), {})
        entry[field] = value.strip()

    return {
        name: [scripts[index] for index in sorted(scripts)]
        for name, scripts in sections.items()
        if scripts
    }


def _read_redirection(
    share: sysvol.SysvolConnection, path: str, unreadable: list[dict[str, Any]]
) -> dict[str, Any]:
    """``fdeploy1.ini`` — which user folders point somewhere else.

    Read-only for now, and reported rather than edited: the option keys beside
    ``FullPath`` are not on evidence yet, and a folder redirection written
    wrong relocates people's profiles.
    """
    try:
        parsed = folders.parse(share.read_text(path))
    except Exception as exc:  # noqa: BLE001
        _note(unreadable, path, exc)
        return {}

    return parsed if parsed["folders"] or parsed["other"] else {}


def _read_xml_items(
    share: sysvol.SysvolConnection, path: str, unreadable: list[dict[str, Any]]
) -> list[dict[str, Any]] | None:
    """One preference or VGP file, element by element.

    Reported generically. Every preference type spells its attributes
    differently, and inventing a common vocabulary would lose exactly the
    detail someone reads a report for.
    """
    try:
        raw = share.read(path)
    except Exception as exc:  # noqa: BLE001
        _note(unreadable, path, exc)
        return None

    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        _note(unreadable, path, exc)
        return None

    items = []
    for element in root:
        item: dict[str, Any] = {
            "element": _tag(element),
            "attributes": dict(element.attrib),
            "filters": [],
        }
        for child in element:
            if _tag(child) == "Filters":
                item["filters"] = [
                    {"element": _tag(entry), "attributes": dict(entry.attrib)} for entry in child
                ]
            else:
                # Properties carry the setting itself; the item element carries
                # only its name and action.
                item.setdefault("properties", []).append(
                    {"element": _tag(child), "attributes": dict(child.attrib)}
                )
        items.append(item)
    return items


def _read_vgp_manifest(
    share: sysvol.SysvolConnection, path: str, unreadable: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """One Samba policy manifest: its name, and the entries it holds.

    Not read with :func:`_read_xml_items` the way preferences are. That walks
    the root's children, which for a manifest is exactly one element —
    ``policysetting`` — so every Samba policy reported itself as the single
    line "policysetting", identically whether it held ten entries or none.

    The shape is fixed and worth descending into::

        vgppolicy
          policysetting
            name, description, apply_mode
            data
              <one element per entry>

    Entries carry their content as child text rather than as attributes, which
    is the other half of why the generic reader showed nothing useful.
    """
    try:
        raw = share.read(path)
    except Exception as exc:  # noqa: BLE001
        _note(unreadable, path, exc)
        return None

    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        _note(unreadable, path, exc)
        return None

    setting = _child(root, "policysetting")
    if setting is None:
        # Present, parseable, and not shaped like a manifest. Reporting it as
        # unreadable beats reporting it as empty.
        _note(unreadable, path, ValueError("no policysetting element"))
        return None

    data = _child(setting, "data")
    entries = []
    for element in data if data is not None else []:
        entries.append(
            {
                "element": _tag(element),
                "fields": [
                    {"name": _tag(child), "value": (child.text or "").strip()}
                    for child in element
                ],
                "text": (element.text or "").strip() if len(element) == 0 else "",
            }
        )

    return {
        "name": _text_of(setting, "name"),
        "description": _text_of(setting, "description"),
        "entries": entries,
    }


def _child(element: Any, name: str) -> Any | None:
    for child in element:
        if _tag(child) == name:
            return child
    return None


def _text_of(element: Any, name: str) -> str:
    child = _child(element, name)
    return (child.text or "").strip() if child is not None else ""


def _tag(element: Any) -> str:
    """The element name without its namespace."""
    return str(element.tag).rsplit("}", 1)[-1]


# ---------------------------------------------------------------------------
# HTML export
# ---------------------------------------------------------------------------


def to_html(report: dict[str, Any]) -> str:
    """The same report as a standalone HTML file.

    For attaching to a change record or a ticket, where a link into a console
    behind a login is no use. Deliberately one file, styles inline, no scripts.
    """
    gpo = report["gpo"]
    title = gpo["display_name"] or gpo["guid"]

    parts: list[str] = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{_esc(title)}</title>",
        "<style>",
        "body{font:14px/1.5 system-ui,sans-serif;margin:2rem;max-width:60rem;color:#20222f}",
        "h1{font-size:1.4rem} h2{font-size:1.1rem;margin-top:2rem;border-bottom:1px solid #ddd}",
        "h3{font-size:1rem;margin-top:1.2rem} h4{font-size:.95rem;margin:.8rem 0 .2rem}",
        "table{border-collapse:collapse;width:100%;margin:.5rem 0}",
        "th,td{text-align:left;padding:4px 8px;border-bottom:1px solid #eee;vertical-align:top}",
        "th{color:#5f6275;font-weight:500}",
        "code{font-family:ui-monospace,monospace;font-size:.9em}",
        ".muted{color:#5f6275}",
        "</style></head><body>",
        f"<h1>{_esc(title)}</h1>",
        "<table>",
        f"<tr><th>Identifier</th><td><code>{_esc(gpo['guid'])}</code></td></tr>",
        f"<tr><th>Path</th><td><code>{_esc(gpo['path'] or '')}</code></td></tr>",
        f"<tr><th>Version</th><td>Computer {gpo['machine_version']} / "
        f"User {gpo['user_version']}</td></tr>",
        f"<tr><th>Computer half</th><td>{'enabled' if gpo['machine_enabled'] else 'disabled'}"
        "</td></tr>",
        f"<tr><th>User half</th><td>{'enabled' if gpo['user_enabled'] else 'disabled'}</td></tr>",
        "</table>",
    ]

    if report.get("empty"):
        parts.append('<p class="muted">This policy holds no settings.</p>')

    for half in HALVES:
        parts.extend(_half_html(half, report[half.lower()]))

    if report["unreadable"]:
        parts.append("<h2>Not readable</h2><ul>")
        for item in report["unreadable"]:
            parts.append(f"<li><code>{_esc(item['path'])}</code> — {_esc(item['reason'])}</li>")
        parts.append("</ul>")

    parts.append("</body></html>")
    return "\n".join(parts)


def _half_html(name: str, half: dict[str, Any]) -> list[str]:
    if not _has_content(half):
        return []

    parts = [f"<h2>{name} configuration</h2>"]

    if half["registry"]:
        parts.append("<h3>Administrative templates</h3>")
        for group in half["registry"]:
            parts.append(f"<h4><code>{_esc(group['key'])}</code></h4><table>")
            parts.append("<tr><th>Value</th><th>Type</th><th>Data</th></tr>")
            for value in group["values"]:
                parts.append(
                    f"<tr><td>{_esc(value['value'])}</td>"
                    f"<td class='muted'>{_esc(value['type'])}</td>"
                    f"<td>{_esc(value['display'])}</td></tr>"
                )
            parts.append("</table>")

    if half["security"]:
        parts.append("<h3>Security settings</h3>")
        for section, values in half["security"].items():
            parts.append(f"<h4>{_esc(section)}</h4><table>")
            for value in values:
                parts.append(
                    f"<tr><td>{_esc(value['name'])}</td><td>{_esc(value['value'])}</td></tr>"
                )
            parts.append("</table>")

    if half["scripts"]:
        parts.append("<h3>Scripts</h3>")
        for section, scripts in half["scripts"].items():
            parts.append(f"<h4>{_esc(section)}</h4><table>")
            for script in scripts:
                parts.append(
                    f"<tr><td><code>{_esc(script.get('cmdline', ''))}</code></td>"
                    f"<td>{_esc(script.get('parameters', ''))}</td></tr>"
                )
            parts.append("</table>")

    if half["redirection"]:
        parts.append("<h3>Folder redirection</h3><table>")
        parts.append("<tr><th>Folder</th><th>Applies to</th><th>Target</th></tr>")
        for folder in half["redirection"]["folders"]:
            for target in folder["targets"] or [{"sid": "", "path": ""}]:
                parts.append(
                    f"<tr><td><code>{_esc(folder['guid'])}</code></td>"
                    f"<td>{_esc(target['sid'])}</td>"
                    f"<td><code>{_esc(target['path'])}</code></td></tr>"
                )
        parts.append("</table>")

    for group in half["preferences"]:
        parts.append(f"<h3>Preferences — {_esc(group['type'])}</h3><table>")
        parts.append("<tr><th>Item</th><th>Attributes</th></tr>")
        for item in group["items"]:
            parts.append(
                f"<tr><td>{_esc(item['element'])}</td>"
                f"<td>{_esc(_attributes(item['attributes']))}</td></tr>"
            )
        parts.append("</table>")

    for group in half["vgp"]:
        heading = group["name"] or "Samba policy"
        parts.append(f"<h3>{_esc(heading)}</h3>")
        parts.append(f"<p><code>{_esc(group['path'])}</code></p>")
        if not group["entries"]:
            # Said outright. An empty manifest is what samba-tool leaves behind
            # when the last entry is removed, so it is a normal state rather
            # than a fault — but a heading with nothing under it reads as a
            # report that gave up.
            parts.append("<p>No entries.</p>")
            continue
        parts.append("<table>")
        for entry in group["entries"]:
            fields = ", ".join(f"{field['name']}={field['value']}" for field in entry["fields"])
            parts.append(
                f"<tr><td>{_esc(entry['element'])}</td>"
                f"<td>{_esc(fields or entry['text'])}</td></tr>"
            )
        parts.append("</table>")

    if half["other_files"]:
        parts.append("<h3>Other files</h3><ul>")
        for item in half["other_files"]:
            parts.append(f"<li><code>{_esc(item['path'])}</code></li>")
        parts.append("</ul>")

    return parts


def _attributes(attributes: dict[str, str]) -> str:
    return ", ".join(f"{key}={value}" for key, value in attributes.items())


def _esc(text: Any) -> str:
    """Escape for HTML.

    Everything in a report comes off a share that is writable by more accounts
    than one might assume, so nothing goes in unescaped.
    """
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
