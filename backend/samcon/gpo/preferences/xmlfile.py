"""The preference XML files, byte for byte.

Nine files written by GPMC — two drive maps a year apart, a registry, files,
folders, shortcuts, environment variables and printers in both halves — agree
on a layout worth reproducing exactly rather than approximately::

    <?xml version="1.0" encoding="utf-8"?>CRLF
    <Root clsid="{…}"><Item …>…</Item>CRLF
    TAB<Item …>…</Item>CRLF
    </Root>CRLF

Note what that is: no newline before the *first* item, a tab before every one
after it, CRLF after each closing tag and after the root's. It is the artefact
of a console that appends to a document rather than reformatting it, and every
one of the nine has it. Reproducing it costs nothing and makes a diff against a
GPMC-written file mean something.

The elements are rendered by hand rather than through ElementTree for one
concrete reason: ElementTree writes an empty element as ``<Properties … />``
and GPMC writes ``<Properties …/>``. Both parse the same, but a byte
comparison against a reference file is the check that has caught a wrong
assumption in every format so far, and it only works if the differences left
are the ones that matter.

**Nothing is dropped on the way through.** Attributes this module does not
model travel from the file to the item and back, in the order the file used,
and the ``<Filters>`` subtree — item-level targeting — is preserved as read.
Wave one and two do not edit filters; they must not silently delete them.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from xml.etree import ElementTree
from xml.sax.saxutils import escape

from samcon.core.errors import InvalidRequest
from samcon.gpo.preferences.catalogue import ACTION, ItemKind, PreferenceType

logger = logging.getLogger(__name__)

DECLARATION = '<?xml version="1.0" encoding="utf-8"?>'
NEWLINE = "\r\n"
INDENT = "\t"

FILTERS_TAG = "Filters"
PROPERTIES_TAG = "Properties"

# The item attributes this module builds itself, in the order it writes them
# for an item it creates. GPMC's own order varies — the 2025 and 2026 drive-map
# files disagree, and a shortcut leads with `userContext` — so this is a
# choice, and an item read from a file keeps the order it came with.
#
# Everything else, `bypassErrors` and `userContext` included, travels through
# `extra` untouched. They are not booleans to us: a drive writes
# `userContext="1"` and omits it when off, while a group writes
# `userContext="0"` outright. Regenerating them from a boolean would drop the
# second spelling; carrying the attribute keeps both.
KNOWN = frozenset(("clsid", "name", "status", "image", "changed", "uid"))

# XML 1.0 allows tab, carriage return and line feed and no other control
# character. A value carrying one would produce a file no parser accepts,
# which is worse than refusing it here.
_FORBIDDEN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

_ATTRIBUTE_ESCAPES = {'"': "&quot;", "\r": "&#13;", "\n": "&#10;", "\t": "&#9;"}


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def parse(preference: PreferenceType, text: str) -> list[dict[str, Any]]:
    """The items of one preference file, in the order the file holds them.

    Elements of a kind this build does not know are skipped rather than
    guessed at — but they are only skipped on the way *in*. Writing a file
    that had one refuses instead, in `store`, so nothing is quietly dropped.
    """
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        logger.info("a preference file is not readable XML", exc_info=True)
        return []

    items = []
    for element in root:
        kind = preference.kind_for_tag(element.tag)
        if kind is None:
            logger.info("skipping an unknown preference element: %s", element.tag)
            continue
        items.append(_read_item(kind, element))
    return items


def unknown_tags(preference: PreferenceType, text: str) -> list[str]:
    """Element names in the file that this build has no kind for.

    `parse` skips them; a caller about to rewrite the file needs to know they
    were there, because writing would drop them.
    """
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return []
    return sorted({child.tag for child in root if preference.kind_for_tag(child.tag) is None})


def _read_item(kind: ItemKind, element: Any) -> dict[str, Any]:
    attributes = dict(element.attrib)
    properties_element = element.find(PROPERTIES_TAG)
    properties = dict(properties_element.attrib) if properties_element is not None else {}
    action = properties.pop(ACTION, "")

    filters_element = element.find(FILTERS_TAG)
    filters = None if filters_element is None else _render_element(filters_element)

    # <Properties> is empty for every kind but one: a REG_MULTI_SZ carries its
    # lines in a <Values> block underneath, with a space-joined summary left in
    # the `value` attribute beside it. Kept as read so anything else that turns
    # up under there survives a save.
    children = (
        "".join(_render_element(child, with_tail=True) for child in properties_element)
        if properties_element is not None
        else ""
    )
    values = (
        [item.text or "" for item in properties_element.findall("Values/Value")]
        if properties_element is not None
        else []
    )
    members = (
        [dict(item.attrib) for item in properties_element.findall("Members/Member")]
        if properties_element is not None
        else []
    )

    # An XP-era immediate task writes its filters before the properties; every
    # other kind writes them after. Read rather than assumed, so a file keeps
    # whichever order it came with.
    children_of = list(element)
    filters_first = bool(
        children_of
        and children_of[0].tag == FILTERS_TAG
        and any(child.tag == PROPERTIES_TAG for child in children_of)
    )

    return {
        "kind": kind.id,
        "uid": attributes.get("uid", ""),
        "name": attributes.get("name", ""),
        "status": attributes.get("status", ""),
        "image": _as_int(attributes.get("image")),
        "changed": attributes.get("changed", ""),
        "bypass_errors": attributes.get("bypassErrors") == "1",
        "user_context": attributes.get("userContext") == "1",
        "action": action,
        "properties": properties,
        "properties_children": children,
        "values": values,
        "members": members,
        # A stored password is never shown and never written; it is flagged so
        # the editor can say why. An empty `cpassword` — which is what GPMC
        # writes for a local user with no password — is not one.
        "has_password": bool(properties.get("cpassword")),
        "filters": filters,
        "filters_first": filters_first,
        "filter_names": _filter_names(filters_element),
        "extra": {name: value for name, value in attributes.items() if name not in KNOWN},
        # The orders the file used. Writing ours into a file GPMC wrote would
        # produce a diff that means nothing.
        "order": list(attributes),
        "properties_order": list(properties_element.attrib)
        if properties_element is not None
        else [],
    }


def _as_int(value: str | None) -> int:
    try:
        return int(value or 0)
    except ValueError:
        return 0


def _filter_names(element: Any) -> list[str]:
    """A short description of each filter, for a list the user only reads."""
    if element is None:
        return []
    names = []
    for child in element.iter():
        if child is element:
            continue
        label = child.attrib.get("name") or child.attrib.get("path") or ""
        names.append(f"{child.tag}: {label}" if label else child.tag)
    return names


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def render(preference: PreferenceType, items: list[dict[str, Any]]) -> bytes:
    """One preference file, in the layout GPMC writes."""
    body = "".join(
        (INDENT if index else "") + _render_item(preference, item) + NEWLINE
        for index, item in enumerate(items)
    )
    text = (
        f"{DECLARATION}{NEWLINE}"
        f"<{preference.root_tag} clsid={_quote(preference.root_clsid)}>"
        f"{body}"
        f"</{preference.root_tag}>{NEWLINE}"
    )
    return text.encode("utf-8")


def _render_item(preference: PreferenceType, item: dict[str, Any]) -> str:
    kind = preference.kind(item.get("kind"))

    attributes: dict[str, str] = {"clsid": kind.clsid, "name": str(item.get("name", ""))}
    if kind.writes_status:
        attributes["status"] = str(item.get("status", item.get("name", "")))
    if kind.writes_image:
        attributes["image"] = str(item.get("image", 0))
    attributes["changed"] = str(item.get("changed", ""))
    attributes["uid"] = str(item.get("uid", ""))
    for name, value in (item.get("extra") or {}).items():
        attributes.setdefault(name, str(value))
    attributes = _in_order(attributes, item.get("order") or [])

    properties = _wire_properties(kind, item)

    children = str(item.get("properties_children") or "")
    rendered = (
        f"<{PROPERTIES_TAG}{_attributes(properties)}>{children}</{PROPERTIES_TAG}>"
        if children
        else f"<{PROPERTIES_TAG}{_attributes(properties)}/>"
    )
    filters = str(item.get("filters") or "")

    parts = [f"<{kind.tag}{_attributes(attributes)}>"]
    if filters and item.get("filters_first", kind.filters_first):
        parts += [filters, rendered]
    else:
        parts += [rendered, filters] if filters else [rendered]
    parts.append(f"</{kind.tag}>")
    return "".join(parts)


def _wire_properties(kind: ItemKind, item: dict[str, Any]) -> dict[str, str]:
    """The ``<Properties>`` attributes, with the action at its own place.

    It is not always the first: a TCP/IP printer leads with ``ipAddress``, a
    shortcut with ``pidl`` and ``targetType``. The catalogue names where it
    sits; an item read from a file keeps the order it came with.
    """
    given = {str(name): str(value) for name, value in (item.get("properties") or {}).items()}

    wire: dict[str, str] = {}
    for field in kind.fields:
        if field.kind == "action":
            # A service has none: it carries a startup type and a service
            # action instead, and its <Properties> has no `action` attribute.
            if kind.has_action:
                wire[ACTION] = str(item.get(ACTION, ""))
        else:
            wire[field.name] = given.get(field.name, field.default)
    for name, value in given.items():
        wire.setdefault(name, value)

    return _in_order(wire, item.get("properties_order") or [])


def values_block(values: list[str]) -> str:
    """The ``<Values>`` block of a REG_MULTI_SZ, in GPMC's spelling."""
    if not values:
        return ""
    for value in values:
        _check(str(value))
    lines = "".join(f"<Value>{escape(str(value))}</Value>" for value in values)
    return f"<Values>{lines}</Values>"


# The attributes of a <Member>, in the order the reference file writes them.
MEMBER_ATTRIBUTES = ("name", "action", "sid")
MEMBER_ACTIONS = ("ADD", "REMOVE")


def members_block(members: list[dict[str, str]]) -> str:
    """The ``<Members>`` block of a local group.

    The second nested structure in any preference file, and the reason groups
    are worth having: adding a domain group to the local Administrators is the
    single most common thing this branch is used for.
    """
    if not members:
        return ""
    rendered = []
    for member in members:
        attributes = {
            name: str(member.get(name) or "") for name in MEMBER_ATTRIBUTES if member.get(name)
        }
        rendered.append(f"<Member{_attributes(attributes)}/>")
    return f"<Members>{''.join(rendered)}</Members>"


def _in_order(attributes: dict[str, str], order: list[str]) -> dict[str, str]:
    """The attributes in the file's own order, anything new appended."""
    if not order:
        return attributes
    ordered = {name: attributes[name] for name in order if name in attributes}
    ordered.update({name: value for name, value in attributes.items() if name not in ordered})
    return ordered


def _attributes(attributes: dict[str, str]) -> str:
    return "".join(f" {name}={_quote(value)}" for name, value in attributes.items())


def _quote(value: str) -> str:
    _check(value)
    return '"' + escape(value, _ATTRIBUTE_ESCAPES) + '"'


def _check(value: str) -> None:
    if _FORBIDDEN.search(value):
        raise InvalidRequest(
            "This value contains a character XML cannot carry.",
            code="preference_control_character",
            hint="Remove control characters from the value.",
        )


def _render_element(element: Any, *, with_tail: bool = False) -> str:
    """One element and everything under it, in this module's spelling.

    Used for the parts we keep but do not model, so that reading a file and
    writing it back leaves them exactly as they were.
    """
    attributes = _attributes({name: str(value) for name, value in element.attrib.items()})
    text = escape(element.text) if element.text else ""
    children = "".join(_render_element(child, with_tail=True) for child in element)
    tail = escape(element.tail) if (with_tail and element.tail) else ""

    if not text and not children:
        # An empty element with attributes self-closes; one without them is
        # written out in full. That is how the corpus reads — every
        # self-closing element in it carries attributes, and the one that
        # carries none, a task's `<Description></Description>`, is expanded.
        # The two spellings are the same element to any XML parser, so nothing
        # rides on this beyond keeping a round trip byte for byte comparable.
        if attributes:
            return f"<{element.tag}{attributes}/>{tail}"
        return f"<{element.tag}></{element.tag}>{tail}"
    return f"<{element.tag}{attributes}>{text}{children}</{element.tag}>{tail}"
