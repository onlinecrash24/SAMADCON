"""Client-side extensions: the list that decides whether a policy applies.

``gPCMachineExtensionNames`` and ``gPCUserExtensionNames`` are what a client
reads to find out which parts of a GPO are worth fetching. A policy whose
values are written but whose extension is not listed there is read by nobody:
it shows up complete in every console, applies nowhere, and no tool reports
it. It is the single most common way a policy edit ends up doing nothing.

The attribute is ``[{CSE}{Tool}…][{CSE}{Tool}…]`` — one group per extension,
the first GUID naming the extension and the rest naming the tools that wrote
it — and the groups must be **sorted ascending, case-insensitively, by the
extension GUID**. Out of order, a client may skip entries.

Shared rather than per feature: administrative templates, scripts and folder
redirection all register here, and the sorting has to consider the entries the
others left behind. Samba's own ``register_extension_name`` appends without
reordering, which is right until something was registered before.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from samadcon.ad import values as ad_values
from samadcon.ad.connection import DirectoryConnection

logger = logging.getLogger(__name__)

HALF_ATTRIBUTE = {
    "Machine": "gPCMachineExtensionNames",
    "User": "gPCUserExtensionNames",
}

# The extensions SAMADCON writes, each with the tool GUID GPMC records beside
# it. **Every pair here was read off a GPO that Windows created**, not taken
# from the specification — writing the pair Windows writes is what makes a
# policy edited here indistinguishable from one edited there, and a wrong or
# invented GUID fails silently.
#
#   registry  — administrative templates, from a GPO carrying an ADMX setting
#   scripts   — startup/shutdown and logon/logoff, from "Deploy Tactical RMM
#               Agent" in the domain this is verified against; the extension
#               GUID also appears in that domain's gpresult under Component
#               Status
REGISTRY_CSE = "35378EAC-683F-11D2-A89A-00C04FBBCFA2"
REGISTRY_TOOL = "D02B1F72-3407-48AE-BA88-E8213C6761F1"

SCRIPTS_CSE = "42B5FAAE-6536-11D2-AE5A-0000F87571E3"
SCRIPTS_TOOL = "40B6664F-4972-11D1-A7CA-0000F87571E3"

# folder redirection — from a throwaway GPO created in GPMC for exactly this,
# read off `gPCUserExtensionNames`. User configuration only.
REDIRECTION_CSE = "25537BA6-77A8-11D2-9B6C-0000F8080861"
REDIRECTION_TOOL = "88E729D6-BDC1-11D1-BD2A-00C04FB9603F"

# security settings — same GPO, after setting a password policy, a lockout
# threshold, an audit category and one user right in GPMC. Computer
# configuration only.
SECURITY_CSE = "827D319E-6EAC-11D2-A4EA-00C04F79F83A"
SECURITY_TOOL = "803E14A0-B4FB-11D0-A0D0-00A0C90F574B"

# Group policy preferences — from three throwaway GPOs, each carrying exactly
# one preference type so no pair could be mistaken for another's. Two things
# here contradict what the extensions above would have suggested, and both
# decide whether the setting applies:
#
# * There is **no shared preferences tool GUID**. Every type brings its own.
# * Every type registers **two** groups, not one: the type's own
#   ``[{CSE}{Tool}]`` and a second ``[{00000000-…}{Tool}]`` beside it. All
#   three reference GPOs have it, so it is the rule rather than an artefact.
#
# The null group therefore collects one tool GUID per preference type in the
# half, which is why removing a type has to take its tool out of that group
# instead of dropping the group — see `remove_tool`.
PREFERENCES_NULL_CSE = "00000000-0000-0000-0000-000000000000"

DRIVES_CSE = "5794DAFD-BE60-433F-88A2-1A31939AC01F"
DRIVES_TOOL = "2EA1A81B-48E5-45E9-8BB7-A6E3AC170006"

PREF_REGISTRY_CSE = "B087BE9D-ED37-454F-AF9C-04291E351182"
PREF_REGISTRY_TOOL = "BEE07A6A-EC9F-4659-B8C9-0B1937907C83"

FILES_CSE = "7150F9BF-48AD-4DA4-A49C-29EF4A8369BA"
FILES_TOOL = "3BAE7E51-E3F4-41D0-853D-9BB9FD47605F"

FOLDERS_CSE = "6232C319-91AC-4931-9385-E70C2B099F0E"
FOLDERS_TOOL = "3EC4E9D3-714D-471F-88DC-4DD4471AAB47"

SHORTCUTS_CSE = "C418DD9D-0D14-4EFB-8FBF-CFE535C8FAC7"
SHORTCUTS_TOOL = "CEFFA6E2-E3BD-421B-852C-6F6A79A59BC1"

ENVIRONMENT_CSE = "0E28E245-9368-4853-AD84-6DA3BA35BB75"
ENVIRONMENT_TOOL = "35141B6B-498A-4CC7-AD59-CEF93D89B2CE"

# Printers register the same pair in both halves — read off one GPO carrying a
# shared printer under User and a port and a local printer under Machine.
# Confirms that the tool GUID belongs to the type, not to the half.
PRINTERS_CSE = "BC75B1ED-5833-4858-9BB8-CBF0B166DF9D"
PRINTERS_TOOL = "A8C42CEA-CDB8-4388-97F4-5831F933DA84"

GROUPS_CSE = "17D89FEC-5C44-4972-B12D-241CAEF74509"
GROUPS_TOOL = "79F92669-4224-476C-9C5C-6EFB4D87DF4A"

SERVICES_CSE = "91FBB303-0CD5-4055-BF42-E512A681B325"
SERVICES_TOOL = "CC5746A9-9B74-4BE5-AE2E-64379C86E0E4"

TASKS_CSE = "AADCED64-746C-4633-A97C-D61349046527"
TASKS_TOOL = "CAB54552-DEEA-4691-817E-ED4A4D1AFC72"

# One [{...}] group. A group holds a CSE GUID and any number of tool GUIDs.
_GROUP_RE = re.compile(r"\[(?P<body>[^\]]*)\]")
_GUID_RE = re.compile(r"\{[^}]+\}")


def parse(value: str | None) -> list[list[str]]:
    """Read an extension-names attribute into groups of GUIDs."""
    if not value:
        return []
    return [
        [guid.upper() for guid in _GUID_RE.findall(match.group("body"))]
        for match in _GROUP_RE.finditer(value)
        if _GUID_RE.search(match.group("body"))
    ]


def render(groups: list[list[str]]) -> str:
    """Write the groups back, in the order the specification requires.

    The tools inside a group are sorted too. Only the preferences' shared null
    group ever holds more than one, and a GPO carrying two preference types
    has them ascending there — which is either a rule or the order they
    happened to be added in. Sorting satisfies both readings and is the one
    that gives the same attribute no matter which type was set up first.
    """
    ordered = sorted((group for group in groups if group), key=lambda group: group[0].upper())
    return "".join(
        "[" + group[0] + "".join(sorted(group[1:], key=str.upper)) + "]" for group in ordered
    )


def add(value: str | None, cse: str, tools: list[str] | None = None) -> str:
    """The attribute with *cse* registered, leaving anything else in place."""
    guid = braced(cse)
    groups = parse(value)

    for group in groups:
        if group[0] == guid:
            for tool in tools or []:
                formatted = braced(tool)
                if formatted not in group:
                    group.append(formatted)
            return render(groups)

    groups.append([guid, *[braced(tool) for tool in tools or []]])
    return render(groups)


def remove(value: str | None, cse: str) -> str:
    """The attribute without *cse*.

    Needed when the last setting of a kind is deleted: a registered extension
    with nothing to apply makes every client fetch the policy and find nothing
    there, on every refresh.
    """
    guid = braced(cse)
    return render([group for group in parse(value) if group[0] != guid])


def remove_tool(value: str | None, cse: str, tool: str) -> str:
    """The attribute with one tool taken out of one group.

    `remove` drops a whole group, which is right when the group belongs to one
    extension. The preferences' ``[{00000000-…}…]`` group belongs to all of
    them at once and holds a tool GUID per type present in the half, so giving
    up drive maps there must leave the registry's entry standing. A group left
    without any tool is dropped — it names an extension and nothing that wrote
    it, which is what an unregistered extension looks like.
    """
    wanted, guid = braced(tool), braced(cse)
    groups = []
    for group in parse(value):
        if group[0] == guid:
            group = [group[0], *[item for item in group[1:] if item != wanted]]
            if len(group) == 1:
                continue
        groups.append(group)
    return render(groups)


def braced(guid: str) -> str:
    """A GUID as this attribute spells them: in braces, upper case."""
    return "{" + guid.strip("{}").upper() + "}"


# What GPMC leaves behind when the last extension of a half goes.
#
# Not an empty value, and not a deleted attribute: a single space. Read off a
# GPO whose only administrative template had just been set back to "not
# configured" — ldbsearch reported ``gPCMachineExtensionNames:: IA==``, and
# IA== is base64 for 0x20. Nothing in the format suggests this. It is simply
# what Windows writes, so it is what we write.
EMPTY = " "


# Extensions Windows leaves registered even when their content is gone.
#
# Verified per extension against GPMC, because it does not behave the same for
# all of them. Setting a password policy and removing it again left
# `gPCMachineExtensionNames` holding the security pair and a GptTmpl.inf with
# an empty `[Registry Values]` section — whereas the same exercise with a
# startup script, and with an administrative template, cleared the attribute to
# a single space.
#
# Folder redirection was in this set, on the grounds that nothing had
# established otherwise — treating an unverified extension as "keeps" only
# costs a finding, while treating it as "clears" would flag a healthy
# policy. Something has established otherwise. Removing the last redirected
# folder in GPMC and reading the attribute back gave
# ``gPCUserExtensionNames:: IA==``: a single space, the same empty marker
# scripts and administrative templates leave. So it clears, and a redirection
# extension registered over nothing is a stale registration like any other.
#
# That leaves one member, and it is the one measured rather than assumed.
KEEPS_REGISTRATION = frozenset({braced(SECURITY_CSE)})


# A short name per extension, for the one place a GUID is shown to a person:
# the preview of what reconciling would change. An administrator asked to
# approve a write should be able to read what it does, and
# {35378EAC-683F-11D2-A89A-00C04FBBCFA2} is not that.
#
# Only the extensions this tool writes. Anything else keeps its GUID rather
# than being given a name that guesses at what it is.
NAMES = {
    braced(REGISTRY_CSE): 'registry',
    braced(SECURITY_CSE): 'security',
    braced(SCRIPTS_CSE): 'scripts',
    braced(REDIRECTION_CSE): 'redirection',
    braced(PREFERENCES_NULL_CSE): 'preferences',
    braced(DRIVES_CSE): 'drives',
    braced(PREF_REGISTRY_CSE): 'pref_registry',
    braced(FILES_CSE): 'files',
    braced(FOLDERS_CSE): 'folders',
    braced(SHORTCUTS_CSE): 'shortcuts',
    braced(ENVIRONMENT_CSE): 'environment',
    braced(PRINTERS_CSE): 'printers',
    braced(GROUPS_CSE): 'groups',
    braced(SERVICES_CSE): 'services',
    braced(TASKS_CSE): 'tasks',
}


def name_for(guid: str) -> str:
    """A readable name for an extension, or its GUID when we have none."""
    return NAMES.get(braced(guid), braced(guid))


def registered_extensions(value: str | None) -> set[str]:
    """The CSE GUIDs listed in one extension-names attribute."""
    return {group[0] for group in parse(value)}


def _current(conn: DirectoryConnection, dn: str, attribute: str) -> str:
    """The attribute as groups, with GPMC's empty marker read as empty."""
    entry: Any = conn.get(dn, attrs=[attribute])
    value = ad_values.as_str(entry, attribute) if entry is not None else None
    return (value or "").strip()


def register(
    conn: DirectoryConnection,
    dn: str,
    half: str,
    cse: str,
    tool: str,
    *,
    present: bool = True,
) -> str | None:
    """Add or remove one extension on a GPO. Returns the new value, or None
    when it already read that way."""
    attribute = HALF_ATTRIBUTE[half]
    current = _current(conn, dn, attribute)

    updated = add(current, cse, [tool]) if present else remove(current, cse)
    if updated == current:
        return None

    conn.modify_attributes(dn, {attribute: updated or EMPTY})
    logger.info(
        "%s extension %s on %s (%s)",
        "registered" if present else "unregistered",
        braced(cse),
        dn,
        attribute,
    )
    return updated


def register_pairs(
    conn: DirectoryConnection,
    dn: str,
    half: str,
    pairs: list[tuple[str, str]],
    *,
    present: bool = True,
) -> str | None:
    """Add or remove several extension/tool pairs in one write.

    The preferences need two pairs per type, and writing them one at a time
    would leave the attribute half registered if the second write failed.
    """
    attribute = HALF_ATTRIBUTE[half]
    current = _current(conn, dn, attribute)

    updated = current
    for cse, tool in pairs:
        updated = add(updated, cse, [tool]) if present else remove_tool(updated, cse, tool)

    if updated == current:
        return None

    conn.modify_attributes(dn, {attribute: updated or EMPTY})
    logger.info(
        "%s %d extension pairs on %s (%s)",
        "registered" if present else "unregistered",
        len(pairs),
        dn,
        attribute,
    )
    return updated
