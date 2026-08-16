"""Security settings — ``Machine/Microsoft/Windows NT/SecEdit/GptTmpl.inf``.

Computer configuration only. The file is an INI in **UTF-16LE with a BOM and
CRLF**, and its sections are the ones the Windows editor shows under
*Security Settings*::

    [Unicode]            Unicode=yes, always
    [Version]            signature="$CHICAGO$", Revision=1
    [System Access]      password and lockout policy
    [Kerberos Policy]    ticket lifetimes
    [Event Audit]        the nine audit categories
    [Registry Values]    security options
    [Privilege Rights]   user rights assignment, SID lists
    [Group Membership]   restricted groups

Three details are copied from a file GPMC wrote rather than reasoned out, and
each one contradicts one of the *other* two policy formats this project
already writes — which is the whole argument for reading a real file first:

* **No preamble.** ``scripts.ini`` opens with a blank line and ``fdeploy1.ini``
  with a blank line, five spaces and another blank line. This one starts
  straight at ``[Unicode]``.
* **Empty sections are written.** GPMC leaves ``[Registry Values]`` behind as a
  bare header, where in ``scripts.ini`` an unused event gets no section at all.
* **Spaces around the equals sign — but not everywhere.** ``[Unicode]`` and
  ``[Version]`` use ``Key=Value``; every other section uses ``Key = Value``.
  Not a rule anyone would guess, and one that shows up in every diff.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from samadcon.ad import rights
from samadcon.ad import values as ad_values
from samadcon.ad.connection import DirectoryConnection
from samadcon.core.errors import Conflict, InvalidRequest
from samadcon.gpo import container, cse, security_catalogue, sysvol

logger = logging.getLogger(__name__)

SECEDIT_PATH = "Machine\\Microsoft\\Windows NT\\SecEdit\\GptTmpl.inf"

BOM = b"\xff\xfe"
NEWLINE = "\r\n"

# The two header sections, written without spaces around the equals sign.
UNICODE = "Unicode"
VERSION = "Version"
TIGHT_SECTIONS = frozenset({UNICODE.lower(), VERSION.lower()})

# What every such file opens with. Windows writes both regardless of content.
HEADER: dict[str, dict[str, str]] = {
    UNICODE: {"Unicode": "yes"},
    VERSION: {"signature": '"$CHICAGO$"', "Revision": "1"},
}

# The order GPMC writes. The first six are observed in a file it produced; the
# rest follow in the order the editor lists them, which is a guess about
# placement only — the contents are not affected either way.
SECTION_ORDER = (
    UNICODE,
    VERSION,
    "System Access",
    "Kerberos Policy",
    "Event Audit",
    "Registry Values",
    "Privilege Rights",
    "Group Membership",
    "Service General Setting",
    "Registry Keys",
    "File Security",
)

# Sections whose values are lists of trustees rather than single numbers.
# ``[Group Membership]`` belongs here too: its keys are ``<group>__Members``
# and ``<group>__Memberof``, and both hold trustee lists.
SID_LIST_SECTIONS = frozenset({"privilege rights", "group membership"})


def parse(text: str) -> dict[str, dict[str, str]]:
    """Read the file into its sections, in the order they appear.

    Everything is kept as text. What a given key means differs per section —
    a number here, a SID list there, a quoted string in ``[Version]`` — and
    deciding that belongs to the caller that knows which section it is asking
    about.
    """
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


def render(sections: dict[str, dict[str, str]]) -> bytes:
    """Render ``GptTmpl.inf``, ready to be written to SYSVOL.

    ``[Unicode]`` and ``[Version]`` are supplied when missing: a file without
    them is not one the Windows editor will open.
    """
    complete = {**HEADER, **sections}

    ordered = [name for name in SECTION_ORDER if name in complete]
    ordered.extend(name for name in complete if name not in ordered)

    lines: list[str] = []
    for name in ordered:
        lines.append(f"[{name}]")
        tight = name.lower() in TIGHT_SECTIONS
        for key, value in complete[name].items():
            if tight:
                lines.append(f"{key}={value}")
            elif value:
                lines.append(f"{key} = {value}")
            else:
                # An empty value keeps the space *before* the equals sign and
                # loses the one after it — that is how GPMC writes a
                # restricted group with no Memberof, and a trailing space
                # would show up in every diff.
                lines.append(f"{key} =")

    text = "".join(f"{line}{NEWLINE}" for line in lines)
    return BOM + text.encode("utf-16-le")


def check_safe(text: str, what: str) -> str:
    """Refuse anything that would write a second line into the file.

    The danger here is not a path — a key never reaches the file system, it
    goes *inside* the ini. It is injection: a newline in a key or a value ends
    the line and starts another, and one more ``[Privilege Rights]`` below it
    grants a right nobody set. In an editor for security settings that is the
    whole ballgame, so it is refused here, where the file is built, rather
    than only at the API.

    Brackets and the equals sign go with it: both change what a line means.
    Backslashes stay — ``[Registry Values]`` keys are registry paths.
    """
    if any(char in text for char in "\r\n\x00[]=") or text != text.strip():
        raise InvalidRequest(
            f"This {what} contains characters that would change the file's structure.",
            code="unsafe_security_name",
            hint="Line breaks, brackets and equals signs are not allowed here.",
            context={what: text},
        )
    return text


def set_value(
    text: str | None, section: str, key: str, value: str | None
) -> bytes:
    """Set or clear one setting, leaving everything else in place.

    A value of None removes the key — which is what "not defined" means here.
    The section stays behind: GPMC leaves empty sections in the file, and
    removing one would show up as a change nobody made.
    """
    check_safe(section, "section")
    check_safe(key, "key")
    if value is not None and any(char in value for char in "\r\n\x00"):
        raise InvalidRequest(
            "This value contains a line break.",
            code="unsafe_security_value",
            hint="A line break would add settings to the policy that nobody set.",
            context={"value": value},
        )

    sections = parse(text) if text else {}
    entries = sections.setdefault(section, {})

    if value is None:
        entries.pop(key, None)
    else:
        entries[key] = value

    return render(sections)


# ---------------------------------------------------------------------------
# Trustee lists
# ---------------------------------------------------------------------------


def parse_trustees(value: str) -> list[str]:
    """The SIDs of one user right.

    Written as ``*S-1-5-32-544,*S-1-5-21-…-512``: comma separated, each one
    marked with a leading asterisk. A name without the asterisk is legal in a
    hand-written template and is kept as it is.
    """
    return [item.strip() for item in value.split(",") if item.strip()]


def format_trustees(trustees: list[str]) -> str:
    """Back to the file's form, with the asterisk each SID carries."""
    formatted = []
    for trustee in trustees:
        cleaned = trustee.strip()
        if not cleaned:
            continue
        # A comma would split one trustee into two, the rest would end the
        # line — same class of problem as check_safe guards against.
        if any(char in cleaned for char in "\r\n\x00,[]="):
            raise InvalidRequest(
                "This account name contains characters the file cannot carry.",
                code="unsafe_security_value",
                context={"trustee": trustee},
            )
        if cleaned.upper().startswith("S-1-") and not cleaned.startswith("*"):
            cleaned = f"*{cleaned}"
        formatted.append(cleaned)
    return ",".join(formatted)


def is_trustee_section(section: str) -> bool:
    return section.lower() in SID_LIST_SECTIONS


def describe(sections: dict[str, dict[str, str]]) -> dict[str, Any]:
    """The file as the editor wants it: values, with trustee lists split up."""
    described: dict[str, Any] = {}
    for name, entries in sections.items():
        if name.lower() in (UNICODE.lower(), VERSION.lower()):
            continue
        if is_trustee_section(name):
            described[name] = {key: parse_trustees(value) for key, value in entries.items()}
        else:
            described[name] = dict(entries)
    return described


# ---------------------------------------------------------------------------
# One GPO
# ---------------------------------------------------------------------------


def read(conn: DirectoryConnection, dn: str) -> dict[str, Any]:
    """The security settings of one GPO, with trustees named.

    A user right is a list of SIDs in the file and a list of accounts in every
    console. Resolving them here rather than in the browser keeps the lookup —
    and its cache — next to the directory it queries.
    """
    gpo = container.get_gpo(conn, dn)
    answer: dict[str, Any] = {
        "dn": dn,
        "present": False,
        "version_number": gpo["version"],
        "registered": _registered(conn, dn),
        "sections": {},
    }

    text = _read_file(conn, gpo)
    if text is None:
        return answer

    sections = describe(parse(text))
    for name, entries in sections.items():
        if is_trustee_section(name):
            sections[name] = {
                key: [rights.resolve_sid(conn, sid.lstrip("*")) for sid in trustees]
                for key, trustees in entries.items()
            }

    return {**answer, "present": True, "sections": sections}


def write(
    conn: DirectoryConnection,
    dn: str,
    section: str,
    key: str,
    value: str | list[str] | None,
    *,
    expected_version: int | None = None,
) -> dict[str, Any]:
    """Set or clear one setting."""
    return write_many(conn, dn, section, {key: value}, expected_version=expected_version)


def write_many(
    conn: DirectoryConnection,
    dn: str,
    section: str,
    changes: dict[str, str | list[str] | None],
    *,
    expected_version: int | None = None,
) -> dict[str, Any]:
    """Set or clear several keys of one section in a single write.

    One key at a time is how the editor thinks and how a conflict is reported,
    so that stays the common path. A restricted group is the exception: it is
    *two* keys — who belongs to it and what it belongs to — and removing it
    means clearing both. Two separate writes would raise the version in
    between, so the second would be refused as a concurrent change by the
    first.

    Security settings are computer configuration, so only the computer half of
    the version advances and only ``gPCMachineExtensionNames`` is touched.
    """
    gpo = container.get_gpo(conn, dn)
    if expected_version is not None and gpo["version"] != expected_version:
        raise Conflict(
            "This policy was changed by someone else in the meantime.",
            code="gpo_version_conflict",
            hint="Reload the settings and make the change again.",
            context={"expected": expected_version, "current": gpo["version"]},
        )
    if not gpo["path"]:
        raise InvalidRequest(
            "This policy has no SYSVOL path.", code="gpo_without_path", context={"dn": dn}
        )

    current = _read_file(conn, gpo)

    # `set_value` takes text and hands back the encoded file, so each key after
    # the first works from the previous result decoded again. Cheap, and it
    # keeps one place responsible for how the file is written.
    text = current
    updated = BOM + (current or "").encode("utf-16-le")
    for key, value in changes.items():
        if isinstance(value, list):
            value = format_trustees(value) or None
        updated = set_value(text, section, key, value)
        text = updated.decode("utf-16")
    if current is not None and updated == BOM + current.encode("utf-16-le"):
        return {"dn": dn, "changed": False, "version": gpo["version"]}

    share = sysvol.sysvol_for(conn)
    _, _, base = sysvol.parse_unc(gpo["path"])
    target = share.resolve(base, SECEDIT_PATH) or sysvol.join(base, SECEDIT_PATH)
    share.makedirs(target.rsplit("\\", 1)[0])
    share.write(target, updated)

    cse.register(
        conn,
        dn,
        "Machine",
        cse.SECURITY_CSE,
        cse.SECURITY_TOOL,
        present=_has_settings(updated),
    )

    after = container.bump_version(conn, dn, machine_changed=True, user_changed=False)
    logger.info(
        "set %s\\%s in %s", section, ", ".join(changes), gpo["display_name"]
    )
    return {"dn": dn, "changed": True, "version": after["version"]}


def set_restricted_group(
    conn: DirectoryConnection,
    dn: str,
    sid: str,
    *,
    present: bool,
    expected_version: int | None = None,
) -> dict[str, Any]:
    """Add or remove a restricted group — both of its keys at once.

    A group in this section is not one setting but two, ``__Members`` and
    ``__Memberof``. Removing it has to clear both, and clearing them one after
    the other is not possible: the first write raises the policy version, so
    the second is refused as somebody else's change.
    """
    _check_group_sid(sid)
    members = f"{sid}{security_catalogue.MEMBERS_SUFFIX}"
    memberof = f"{sid}{security_catalogue.MEMBEROF_SUFFIX}"

    # Adding writes the empty membership list GPMC writes, so the group shows
    # up in every console; removing takes both keys out.
    changes: dict[str, str | list[str] | None] = (
        {memberof: ""} if present else {members: None, memberof: None}
    )
    return write_many(
        conn,
        dn,
        security_catalogue.GROUP_MEMBERSHIP,
        changes,
        expected_version=expected_version,
    )


def _has_settings(raw: bytes) -> bool:
    """Whether anything beyond the two header sections is set.

    A file holding only ``[Unicode]`` and ``[Version]`` configures nothing, and
    an extension registered for it makes every client fetch the policy on each
    refresh and find nothing there.
    """
    return any(entries for entries in describe(parse(raw.decode("utf-16"))).values())


def _read_file(conn: DirectoryConnection, gpo: dict[str, Any]) -> str | None:
    if not gpo["path"]:
        return None
    share = sysvol.sysvol_for(conn)
    _, _, base = sysvol.parse_unc(gpo["path"])
    resolved = share.resolve(base, SECEDIT_PATH)
    return None if resolved is None else share.read_text(resolved)


def _registered(conn: DirectoryConnection, dn: str) -> bool:
    attribute = cse.HALF_ATTRIBUTE["Machine"]
    entry = conn.get(dn, attrs=[attribute])
    value = (ad_values.as_str(entry, attribute) if entry is not None else None) or ""
    return cse.braced(cse.SECURITY_CSE) in value.upper()


# GPMC names a restricted group by its SID with a leading asterisk. Anything
# else would create a key that no client resolves and no console shows as the
# group it was meant to be.
_GROUP_SID = re.compile(r"^\*S-1-[0-9-]+$")


def _check_group_sid(sid: str) -> None:
    if not _GROUP_SID.match(sid):
        raise InvalidRequest(
            "A restricted group is named by its SID.",
            code="unsafe_security_key",
            hint="For example: *S-1-5-32-544",
            context={"given": sid},
        )
