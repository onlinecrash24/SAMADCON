"""Item-level targeting: the ``<Filters>`` block of a preference item.

Four filter types are understood — security group, OU, computer name, user —
and the run-once marker GPMC files among them. Their spelling is the one the
reference GPO "SAMADCON-Referenz-ILT" was written in (tests/data); each filter
is ``bool="AND|OR" not="0|1"`` followed by its own attributes, in this order:

    FilterGroup     name sid userContext primaryGroup localGroup
    FilterOrgUnit   name userContext directMember
    FilterComputer  type name
    FilterUser      name sid
    FilterRunOnce   hidden="1" not="0" bool="AND" id   (last, then CRLF TAB TAB)

``userContext`` on a group or an OU is who is meant: "1" the user, "0" the
computer.

**Anything else stays as it was read.** A collection, a filter of another type
(IP range, WMI, operating system, …), an attribute not listed above or a
run-once marker anywhere but last makes the whole block read-only: it is
shown, carried through a save untouched, and never rewritten. A block that is
half understood is the one thing that must not be regenerated — a dropped
condition widens who an item applies to, silently.
"""

from __future__ import annotations

import re
import uuid
from typing import Any
from xml.etree import ElementTree
from xml.sax.saxutils import escape

from samadcon.ad import values
from samadcon.core.errors import InvalidRequest

FILTERS_TAG = "Filters"
RUN_ONCE_TAG = "FilterRunOnce"

# condition type: (tag, attributes after bool and not, in GPMC's order)
_TYPES: dict[str, tuple[str, tuple[str, ...]]] = {
    "group": ("FilterGroup", ("name", "sid", "userContext", "primaryGroup", "localGroup")),
    "ou": ("FilterOrgUnit", ("name", "userContext", "directMember")),
    "computer": ("FilterComputer", ("type", "name")),
    "user": ("FilterUser", ("name", "sid")),
}
_TYPE_OF_TAG = {tag: kind for kind, (tag, _) in _TYPES.items()}
_RUN_ONCE_ATTRIBUTES = ("hidden", "not", "bool", "id")

# GPMC puts a line break and two tabs after the run-once marker, before the
# closing tag; measured on T: in the reference file.
_AFTER_RUN_ONCE = "\r\n\t\t"

_SID = re.compile(r"^S-1-\d+(-\d+)+$")
_FORBIDDEN = re.compile(r"[\x00-\x1f]")
_GUID = re.compile(r"^\{[0-9A-Fa-f]{8}(-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}$")
COMPUTER_TYPES = ("NETBIOS", "DNS")
MAX_CONDITIONS = 64


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def parse(filters: str | None) -> dict[str, Any]:
    """The conditions of a ``<Filters>`` block, and whether it can be edited.

    ``run_once`` is the marker's id, or None. A block that is not editable
    comes back with no conditions: the caller keeps the block as it was.
    """
    if not filters:
        return {"editable": True, "conditions": [], "run_once": None}
    try:
        root = ElementTree.fromstring(filters)
    except ElementTree.ParseError:
        return _read_only()
    if root.tag != FILTERS_TAG or (root.text or "").strip():
        return _read_only()

    children = list(root)
    conditions: list[dict[str, Any]] = []
    run_once: str | None = None
    for index, child in enumerate(children):
        if len(child) or (child.text or "").strip() or (child.tail or "").strip():
            return _read_only()
        attributes = dict(child.attrib)
        if child.tag == RUN_ONCE_TAG:
            if (
                index != len(children) - 1
                or set(attributes) != set(_RUN_ONCE_ATTRIBUTES)
                or (attributes["hidden"], attributes["not"], attributes["bool"])
                != ("1", "0", "AND")
                or not _GUID.match(attributes["id"])
            ):
                return _read_only()
            run_once = attributes["id"]
            continue
        kind = _TYPE_OF_TAG.get(child.tag)
        if kind is None:
            return _read_only()
        condition = _condition(kind, attributes)
        if condition is None:
            return _read_only()
        conditions.append(condition)
    return {"editable": True, "conditions": conditions, "run_once": run_once}


def _read_only() -> dict[str, Any]:
    return {"editable": False, "conditions": [], "run_once": None}


def _condition(kind: str, attributes: dict[str, str]) -> dict[str, Any] | None:
    """One filter as a condition, or None if it carries something unmodelled."""
    _, names = _TYPES[kind]
    if set(attributes) != {"bool", "not", *names}:
        return None
    if attributes["bool"] not in ("AND", "OR") or attributes["not"] not in ("0", "1"):
        return None
    condition: dict[str, Any] = {
        "type": kind,
        "bool": attributes["bool"],
        "not": attributes["not"] == "1",
        "name": attributes["name"],
    }
    if kind == "group":
        condition["sid"] = attributes["sid"]
        condition["user_context"] = attributes["userContext"] == "1"
        condition["primary_group"] = attributes["primaryGroup"] == "1"
        condition["local_group"] = attributes["localGroup"] == "1"
    elif kind == "ou":
        condition["user_context"] = attributes["userContext"] == "1"
        condition["direct_member"] = attributes["directMember"] == "1"
    elif kind == "computer":
        condition["computer_type"] = attributes["type"]
    elif kind == "user":
        condition["sid"] = attributes["sid"]
    return condition


# ---------------------------------------------------------------------------
# Checking what comes in
# ---------------------------------------------------------------------------


def validate(conditions: list[Any]) -> list[dict[str, Any]]:
    """Conditions from outside, checked and in the shape :func:`render` takes."""
    if not isinstance(conditions, list) or len(conditions) > MAX_CONDITIONS:
        _refuse(-1, "count")
    checked = []
    for index, raw in enumerate(conditions):
        if not isinstance(raw, dict):
            _refuse(index, "type")
        kind = raw.get("type")
        if kind not in _TYPES:
            _refuse(index, "type")
        bool_ = raw.get("bool", "AND")
        if bool_ not in ("AND", "OR"):
            _refuse(index, "bool")
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 1024:
            _refuse(index, "name")
        if _FORBIDDEN.search(name):
            _refuse(index, "name")
        condition: dict[str, Any] = {
            "type": kind,
            "bool": bool_,
            "not": bool(raw.get("not", False)),
            "name": name.strip(),
        }
        if kind in ("group", "user"):
            sid = raw.get("sid")
            if not isinstance(sid, str) or not _SID.match(sid):
                _refuse(index, "sid")
            condition["sid"] = sid
        if kind == "group":
            condition["user_context"] = bool(raw.get("user_context", True))
            condition["primary_group"] = bool(raw.get("primary_group", False))
            condition["local_group"] = bool(raw.get("local_group", False))
        elif kind == "ou":
            if "=" not in name:
                _refuse(index, "name")
            condition["user_context"] = bool(raw.get("user_context", True))
            condition["direct_member"] = bool(raw.get("direct_member", False))
        elif kind == "computer":
            computer_type = raw.get("computer_type", "NETBIOS")
            if computer_type not in COMPUTER_TYPES:
                _refuse(index, "computer_type")
            condition["computer_type"] = computer_type
        checked.append(condition)
    return checked


def _refuse(index: int, reason: str) -> None:
    raise InvalidRequest(
        "A targeting condition is not valid.",
        code="preference_condition_invalid",
        context={"reason": reason, "index": index},
    )


def resolve(conn: Any, conditions: list[Any]) -> list[Any]:
    """Conditions picked from the directory, given their name and SID.

    A condition with a ``dn`` was picked in the console. Its name and SID are
    read from the directory rather than taken from the browser, and written
    as GPMC writes them: ``DOMAIN\\sAMAccountName`` for a group or a user,
    the DN for an OU, the account name without its ``$`` for a computer.
    """
    resolved = []
    for index, raw in enumerate(conditions):
        if not isinstance(raw, dict) or not raw.get("dn"):
            resolved.append(raw)
            continue
        kind = raw.get("type")
        entry = conn.get(
            str(raw["dn"]),
            attrs=["objectClass", "objectSid", "sAMAccountName", "distinguishedName"],
        )
        classes = {value.lower() for value in values.as_list(entry, "objectClass")}
        wanted = {
            "group": "group",
            "user": "user",
            "ou": "organizationalunit",
            "computer": "computer",
        }.get(str(kind))
        if entry is None or wanted is None or wanted not in classes:
            _refuse(index, "dn")
        if kind == "user" and "computer" in classes:
            _refuse(index, "dn")

        condition = {key: value for key, value in raw.items() if key != "dn"}
        if kind == "ou":
            condition["name"] = values.as_str(entry, "distinguishedName") or str(raw["dn"])
        elif kind == "computer":
            condition["name"] = (values.as_str(entry, "sAMAccountName") or "").rstrip("$")
            condition.setdefault("computer_type", "NETBIOS")
        else:
            account = values.as_str(entry, "sAMAccountName") or ""
            condition["name"] = f"{conn.info.netbios_name}\\{account}"
            condition["sid"] = values.sid_to_str(values.first(entry, "objectSid"))
        resolved.append(condition)
    return resolved


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def new_run_once_id() -> str:
    return "{" + str(uuid.uuid4()).upper() + "}"


def render(conditions: list[dict[str, Any]], run_once: str | None) -> str | None:
    """The ``<Filters>`` block, as GPMC writes it; None when there is nothing."""
    if not conditions and not run_once:
        return None
    parts = []
    for index, condition in enumerate(validate(conditions)):
        kind = condition["type"]
        tag, _ = _TYPES[kind]
        attributes = {
            # The first condition has nothing to join; GPMC writes AND for it.
            "bool": "AND" if index == 0 else condition["bool"],
            "not": "1" if condition["not"] else "0",
        }
        if kind == "group":
            attributes |= {
                "name": condition["name"],
                "sid": condition["sid"],
                "userContext": _flag(condition["user_context"]),
                "primaryGroup": _flag(condition["primary_group"]),
                "localGroup": _flag(condition["local_group"]),
            }
        elif kind == "ou":
            attributes |= {
                "name": condition["name"],
                "userContext": _flag(condition["user_context"]),
                "directMember": _flag(condition["direct_member"]),
            }
        elif kind == "computer":
            attributes |= {"type": condition["computer_type"], "name": condition["name"]}
        else:
            attributes |= {"name": condition["name"], "sid": condition["sid"]}
        parts.append(f"<{tag}{_attributes(attributes)}/>")
    if run_once:
        if not _GUID.match(run_once):
            raise InvalidRequest("The run-once marker is malformed.", code="preference_run_once")
        marker = {"hidden": "1", "not": "0", "bool": "AND", "id": run_once}
        parts.append(f"<{RUN_ONCE_TAG}{_attributes(marker)}/>{_AFTER_RUN_ONCE}")
    return f"<{FILTERS_TAG}>{''.join(parts)}</{FILTERS_TAG}>"


def _flag(value: bool) -> str:
    return "1" if value else "0"


def _attributes(attributes: dict[str, str]) -> str:
    return "".join(
        f' {name}="{escape(value, {chr(34): "&quot;"})}"' for name, value in attributes.items()
    )
