"""Samba's own group policies — the ones ``samba-gpupdate`` applies on Linux.

Windows clients ignore these entirely; they are why a mixed domain can manage
its Linux members from the same policies as its Windows ones. Each kind lives
in its own ``manifest.xml`` under ``MACHINE/VGP/VTLA/``::

    Sudo/SudoersConfiguration     sudo rights
    Unix/Symlink                  symbolic links
    Unix/MOTD                     message of the day
    Unix/Issue                    the login banner
    SshCfg/SshD                   sshd_config settings
    VAS/HostAccessControl/Allow   who may log in
    VAS/HostAccessControl/Deny    who may not

**The reference here is source code, not a file.** For ``scripts.ini``,
``fdeploy1.ini`` and ``GptTmpl.inf`` only Windows knew the truth, so a file had
to be produced and read byte by byte. These are read by Samba's own
``samba/gp/vgp_*_ext.py``, and written by ``samba-tool gpo manage`` — both
open. The element names below are taken from the modules that consume them.

Two kinds are deliberately left out of this first wave, and for the same
reason the others are in it — evidence:

* **Unix/Files** carries a ``permissions`` sub-structure whose element names
  the reader checks three times over, apparently for user, group and other,
  but the grouping is not visible from the reading code alone.
* **Unix/Scripts/Startup** requires a ``hash`` of the script, and how Samba
  computes it is not something to guess: a wrong hash means the script is
  re-applied on every refresh, or never.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from xml.etree import ElementTree

from samadcon.ad.connection import DirectoryConnection
from samadcon.core.errors import Conflict, InvalidRequest
from samadcon.gpo import container, sysvol

logger = logging.getLogger(__name__)

VGP_ROOT = "MACHINE\\VGP\\VTLA"
MANIFEST = "manifest.xml"

# ElementTree writes this exact declaration, single quotes and all. Matching it
# keeps a file we write and one `samba-tool gpo manage` writes comparable.
DECLARATION = b"<?xml version='1.0' encoding='UTF-8'?>\n"


@dataclass(frozen=True)
class VgpKind:
    """One kind of VGP policy: where it lives and what it says."""

    id: str
    directory: str
    name: str
    description: str
    apply_mode: str | None = None
    # Elements that sit in <data> before the entries, as name/text pairs.
    preamble: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def path(self) -> str:
        return f"{VGP_ROOT}\\{self.directory}\\{MANIFEST}"


# ``name`` and ``description`` are what samba-tool writes; the applier reads
# neither. Both are quoted from its source for sudoers and symlinks — the two
# it implements — and chosen to match that style for the rest.
KINDS: dict[str, VgpKind] = {
    "sudoers": VgpKind(
        id="sudoers",
        directory="Sudo\\SudoersConfiguration",
        name="Sudo Policy",
        description="Sudoers File Configuration Policy",
        apply_mode="merge",
        preamble=(("load_plugin", "true"),),
    ),
    "symlink": VgpKind(
        id="symlink",
        directory="Unix\\Symlink",
        name="Symlink Policy",
        description="Specifies symbolic link data",
    ),
    "motd": VgpKind(
        id="motd",
        directory="Unix\\MOTD",
        name="Message of the Day",
        description="Specifies the message of the day",
    ),
    "issue": VgpKind(
        id="issue",
        directory="Unix\\Issue",
        name="Login Prompt Message",
        description="Specifies the login prompt message",
    ),
    "openssh": VgpKind(
        id="openssh",
        directory="SshCfg\\SshD",
        name="Configuration File",
        description="Configuration File",
    ),
    "access_allow": VgpKind(
        id="access_allow",
        directory="VAS\\HostAccessControl\\Allow",
        name="Allow Login",
        description="Specifies who may log in",
    ),
    "access_deny": VgpKind(
        id="access_deny",
        directory="VAS\\HostAccessControl\\Deny",
        name="Deny Login",
        description="Specifies who may not log in",
    ),
}


def kind_for(policy: str) -> VgpKind:
    try:
        return KINDS[policy]
    except KeyError:
        raise InvalidRequest(
            "Unknown Samba policy.",
            code="unknown_vgp_policy",
            hint=f"Expected one of: {', '.join(sorted(KINDS))}.",
            context={"given": policy},
        ) from None


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def parse(policy: str, text: str) -> list[dict[str, Any]]:
    """The entries of one manifest.

    Missing elements come back as empty strings rather than raising: Samba's
    readers call ``.text`` on whatever they find, and a manifest written by
    another tool is still worth showing.
    """
    kind = kind_for(policy)
    data = _data_of(text)
    if data is None:
        return []
    return READERS[kind.id](data)


def _sudoers_entries(data: Any) -> list[dict[str, Any]]:
    return [_sudoers_entry(entry) for entry in data.findall("sudoers_entry")]


def _symlink_entries(data: Any) -> list[dict[str, Any]]:
    return [
        {"source": _text(entry, "source"), "target": _text(entry, "target")}
        for entry in data.findall("file_properties")
    ]


def _text_block(data: Any) -> list[dict[str, Any]]:
    """A single block of text, not a list."""
    return [{"text": _text(data, "text"), "filename": _text(data, "filename")}]


def _data_of(text: str) -> Any:
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        logger.info("a VGP manifest is not readable XML", exc_info=True)
        return None
    policy = root.find("policysetting")
    return None if policy is None else policy.find("data")


def _text(element: Any, name: str) -> str:
    found = None if element is None else element.find(name)
    return (found.text or "") if found is not None else ""


def _sudoers_entry(entry: Any) -> dict[str, Any]:
    principals: list[str] = []
    for listelement in entry.findall("listelement"):
        principals.extend((item.text or "") for item in listelement.findall("principal"))
    return {
        "command": _text(entry, "command"),
        "user": _text(entry, "user"),
        "principals": [item for item in principals if item],
        # Samba reads it the other way round: no <password> means no password
        # is asked for. Saying "password" here keeps the editor's checkbox
        # from meaning the opposite of its label.
        "password": entry.find("password") is not None,
    }


def _openssh_entries(data: Any) -> list[dict[str, Any]]:
    configfile = data.find("configfile")
    if configfile is None:
        return []
    entries: list[dict[str, Any]] = []
    for section in configfile.findall("configsection"):
        for pair in section.findall("keyvaluepair"):
            entries.append({"key": _text(pair, "key"), "value": _text(pair, "value")})
    return entries


def _access_entries(data: Any) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for listelement in data.findall("listelement"):
        adobject = listelement.find("adobject")
        if adobject is None:
            continue
        entries.append({"name": _text(adobject, "name"), "domain": _text(adobject, "domain")})
    return entries


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def render(policy: str, entries: list[dict[str, Any]]) -> bytes:
    """Render one manifest the way ``samba-tool gpo manage`` writes it."""
    kind = kind_for(policy)

    root = ElementTree.Element("vgppolicy")
    setting = ElementTree.SubElement(root, "policysetting")
    ElementTree.SubElement(setting, "version").text = "1"
    ElementTree.SubElement(setting, "name").text = kind.name
    ElementTree.SubElement(setting, "description").text = kind.description
    if kind.apply_mode:
        ElementTree.SubElement(setting, "apply_mode").text = kind.apply_mode

    data = ElementTree.SubElement(setting, "data")
    for name, value in kind.preamble:
        ElementTree.SubElement(data, name).text = value

    _fill(kind, data, entries)

    return DECLARATION + ElementTree.tostring(root, encoding="utf-8")


def _fill(kind: VgpKind, data: Any, entries: list[dict[str, Any]]) -> None:
    WRITERS[kind.id](data, entries)


def _write_sudoers(data: Any, entries: list[dict[str, Any]]) -> None:
    for entry in entries:
        node = ElementTree.SubElement(data, "sudoers_entry")
        if entry.get("password"):
            ElementTree.SubElement(node, "password")
        ElementTree.SubElement(node, "command").text = str(entry.get("command", ""))
        ElementTree.SubElement(node, "user").text = str(entry.get("user", ""))
        listelement = ElementTree.SubElement(node, "listelement")
        for principal in entry.get("principals") or []:
            ElementTree.SubElement(listelement, "principal").text = str(principal)


def _write_symlink(data: Any, entries: list[dict[str, Any]]) -> None:
    for entry in entries:
        node = ElementTree.SubElement(data, "file_properties")
        ElementTree.SubElement(node, "source").text = str(entry.get("source", ""))
        ElementTree.SubElement(node, "target").text = str(entry.get("target", ""))


def _write_text_block(data: Any, entries: list[dict[str, Any]]) -> None:
    # One block of text. More than one entry would silently lose all but the
    # first, so it is refused instead.
    if len(entries) > 1:
        raise InvalidRequest(
            "This policy holds a single block of text.",
            code="vgp_single_entry",
            context={"given": len(entries)},
        )
    ElementTree.SubElement(data, "text").text = str(entries[0].get("text", "") if entries else "")


def _write_openssh(data: Any, entries: list[dict[str, Any]]) -> None:
    configfile = ElementTree.SubElement(data, "configfile")
    section = ElementTree.SubElement(configfile, "configsection")
    # Samba skips a section whose name has text, so the settings it reads are
    # the ones in the unnamed section. The element has to be there.
    ElementTree.SubElement(section, "sectionname")
    for entry in entries:
        pair = ElementTree.SubElement(section, "keyvaluepair")
        ElementTree.SubElement(pair, "key").text = str(entry.get("key", ""))
        ElementTree.SubElement(pair, "value").text = str(entry.get("value", ""))


def _write_access(data: Any, entries: list[dict[str, Any]]) -> None:
    for entry in entries:
        listelement = ElementTree.SubElement(data, "listelement")
        adobject = ElementTree.SubElement(listelement, "adobject")
        ElementTree.SubElement(adobject, "name").text = str(entry.get("name", ""))
        ElementTree.SubElement(adobject, "domain").text = str(entry.get("domain", ""))


# ---------------------------------------------------------------------------
# Which reader and writer belong to which kind
#
# A table rather than a chain of ``if kind.id == …``. The chain ended in a
# fallback, so a kind added to KINDS and forgotten here was read as an access
# list and written as `adobject` elements — silently, and onto a share every
# domain member reads. Missing from the table, the same mistake is a KeyError
# on the first call, and `test_every_kind_has_a_reader_and_a_writer` catches
# it before that.
# ---------------------------------------------------------------------------

READERS: dict[str, Callable[[Any], list[dict[str, Any]]]] = {
    "sudoers": _sudoers_entries,
    "symlink": _symlink_entries,
    "motd": _text_block,
    "issue": _text_block,
    "openssh": _openssh_entries,
    "access_allow": _access_entries,
    "access_deny": _access_entries,
}

WRITERS: dict[str, Callable[[Any, list[dict[str, Any]]], None]] = {
    "sudoers": _write_sudoers,
    "symlink": _write_symlink,
    "motd": _write_text_block,
    "issue": _write_text_block,
    "openssh": _write_openssh,
    "access_allow": _write_access,
    "access_deny": _write_access,
}


# ---------------------------------------------------------------------------
# One GPO
# ---------------------------------------------------------------------------
#
# **No client-side extension is registered here**, and that is deliberate.
# ``samba-tool gpo manage`` writes the manifest and calls ``increment_gpt_ini``
# — nothing else — and ``samba-gpupdate`` runs every loaded extension against
# every applicable GPO rather than filtering by ``gPCMachineExtensionNames``.
# Registering one anyway would put a GUID Windows does not know in front of
# every Windows client in the domain, for no gain.


def read(conn: DirectoryConnection, dn: str, policy: str) -> dict[str, Any]:
    """One Samba policy of one GPO."""
    kind = kind_for(policy)
    gpo = container.get_gpo(conn, dn)

    text = _read_manifest(conn, gpo, kind)
    return {
        "dn": dn,
        "policy": kind.id,
        "present": text is not None,
        "version_number": gpo["version"],
        "entries": parse(kind.id, text) if text else [],
    }


def read_all(conn: DirectoryConnection, dn: str) -> dict[str, Any]:
    """Every Samba policy of one GPO, for the editor to draw at once."""
    gpo = container.get_gpo(conn, dn)

    policies = {}
    for kind in KINDS.values():
        text = _read_manifest(conn, gpo, kind)
        policies[kind.id] = {
            "present": text is not None,
            "entries": parse(kind.id, text) if text else [],
        }

    return {"dn": dn, "version_number": gpo["version"], "policies": policies}


def write(
    conn: DirectoryConnection,
    dn: str,
    policy: str,
    entries: list[dict[str, Any]],
    *,
    expected_version: int | None = None,
) -> dict[str, Any]:
    """Replace one Samba policy, the way ``samba-tool gpo manage`` does."""
    kind = kind_for(policy)
    gpo = container.get_gpo(conn, dn)

    if expected_version is not None and gpo["version"] != expected_version:
        raise Conflict(
            "This policy was changed by someone else in the meantime.",
            code="gpo_version_conflict",
            hint="Reload the entries and make the change again.",
            context={"expected": expected_version, "current": gpo["version"]},
        )
    if not gpo["path"]:
        raise InvalidRequest(
            "This policy has no SYSVOL path.", code="gpo_without_path", context={"dn": dn}
        )

    updated = render(kind.id, entries)
    current = _read_manifest(conn, gpo, kind)
    if current is not None and updated == current.encode("utf-8"):
        return {"dn": dn, "changed": False, "version": gpo["version"]}

    share = sysvol.sysvol_for(conn)
    _, _, base = sysvol.parse_unc(gpo["path"])
    target = share.resolve(base, kind.path) or sysvol.join(base, kind.path)
    share.makedirs(target.rsplit("\\", 1)[0])
    share.write(target, updated)

    # Machine half only: every one of these lives under MACHINE.
    after = container.bump_version(conn, dn, machine_changed=True, user_changed=False)
    logger.info("wrote %d %s entries to %s", len(entries), kind.id, gpo["display_name"])
    return {"dn": dn, "changed": True, "version": after["version"], "written": len(entries)}


def _read_manifest(
    conn: DirectoryConnection, gpo: dict[str, Any], kind: VgpKind
) -> str | None:
    if not gpo["path"]:
        return None
    share = sysvol.sysvol_for(conn)
    _, _, base = sysvol.parse_unc(gpo["path"])
    resolved = share.resolve(base, kind.path)
    return None if resolved is None else share.read_text(resolved)
