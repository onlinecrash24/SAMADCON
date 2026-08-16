"""``Registry.pol`` — the PReg format.

Administrative templates end up here: one file per half of a GPO, holding a
flat list of registry values that the client-side extension writes into the
registry. The format is a four-byte signature, a version, and a count,
followed by that many entries of key, value name, type, size and data.

The conversion goes through ``samba.dcerpc.preg`` rather than by hand — the
strings are UTF-16 with terminators and the data union is switched on the
type, both of which are easy to get subtly wrong and impossible to notice
until a client silently ignores the file.

What is *not* here on purpose: writing a policy into a live GPO. That needs
the version numbers and the extension registrations to move in step, which is
:mod:`samcon.gpo.container`'s job.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

from samcon.core.errors import InvalidRequest

logger = logging.getLogger(__name__)

# winreg value types (MS-DTYP 2.2.11).
REG_NONE = 0
REG_SZ = 1
REG_EXPAND_SZ = 2
REG_BINARY = 3
REG_DWORD = 4
REG_DWORD_BIG_ENDIAN = 5
REG_LINK = 6
REG_MULTI_SZ = 7
REG_QWORD = 11

TYPE_NAMES: dict[int, str] = {
    REG_NONE: "REG_NONE",
    REG_SZ: "REG_SZ",
    REG_EXPAND_SZ: "REG_EXPAND_SZ",
    REG_BINARY: "REG_BINARY",
    REG_DWORD: "REG_DWORD",
    REG_DWORD_BIG_ENDIAN: "REG_DWORD_BIG_ENDIAN",
    REG_LINK: "REG_LINK",
    REG_MULTI_SZ: "REG_MULTI_SZ",
    REG_QWORD: "REG_QWORD",
}

TYPE_VALUES: dict[str, int] = {name: value for value, name in TYPE_NAMES.items()}

# Types SAMCON knows how to build a value for. Anything else is readable and
# is carried through unchanged, but not offered for editing.
EDITABLE_TYPES = ("REG_SZ", "REG_EXPAND_SZ", "REG_DWORD", "REG_QWORD", "REG_MULTI_SZ")


def type_name(value: int) -> str:
    return TYPE_NAMES.get(int(value), f"TYPE{int(value)}")


def type_value(name: str | int) -> int:
    if isinstance(name, int):
        return name
    key = name.strip().upper()
    if key not in TYPE_VALUES:
        raise InvalidRequest(
            f"Unknown registry type '{name}'.",
            code="unknown_registry_type",
            context={"supported": list(TYPE_VALUES)},
        )
    return TYPE_VALUES[key]


# ---------------------------------------------------------------------------
# Sizes
# ---------------------------------------------------------------------------


def data_size(type_: int, data: Any) -> int:
    """How many bytes an entry's data occupies in the file.

    Strings are UTF-16 with a terminator, and a multi-string carries one
    terminator per string plus a final empty one. Computed rather than assumed
    because the field is written into the file and a wrong length makes every
    following entry unreadable.
    """
    kind = int(type_)

    if kind in (REG_SZ, REG_EXPAND_SZ, REG_LINK):
        return (len(str(data or "")) + 1) * 2
    if kind == REG_MULTI_SZ:
        strings = list(data or [])
        return sum((len(str(item)) + 1) * 2 for item in strings) + 2
    if kind in (REG_DWORD, REG_DWORD_BIG_ENDIAN):
        return 4
    if kind == REG_QWORD:
        return 8
    if data is None:
        return 0
    if isinstance(data, (bytes, bytearray)):
        return len(data)
    return len(bytes(data))


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def parse(raw: bytes) -> list[dict[str, Any]]:
    """Read a ``Registry.pol`` file into a list of entries.

    An empty file is a valid policy that sets nothing — several tools write
    one when the last setting is removed — so it is not an error.
    """
    if not raw:
        return []

    from samba.dcerpc import preg
    from samba.ndr import ndr_unpack

    pol = ndr_unpack(preg.file, raw)
    return [_describe(entry, index) for index, entry in enumerate(pol.entries)]


def _describe(entry: Any, index: int) -> dict[str, Any]:
    kind = int(entry.type)
    described: dict[str, Any] = {
        "index": index,
        "key": str(entry.keyname),
        "value": str(entry.valuename),
        "type": type_name(kind),
        "type_id": kind,
        "size": int(entry.size),
    }
    described["data"] = _decode_data(entry.data, kind)
    described["display"] = format_data(kind, described["data"])
    return described


def _decode_data(data: Any, kind: int) -> Any:
    """The union arm for this type, as an ordinary Python value.

    The binding hands back the active arm directly, so this is mostly about
    settling on one representation: bytes become base64 text, because the
    value travels through JSON to a browser.
    """
    if kind in (REG_DWORD, REG_DWORD_BIG_ENDIAN, REG_QWORD):
        try:
            return int(data)
        except (TypeError, ValueError):
            return 0
    if kind == REG_MULTI_SZ:
        return [str(item) for item in (data or [])]
    if kind in (REG_SZ, REG_EXPAND_SZ, REG_LINK):
        return str(data or "")
    if data is None:
        return ""
    if isinstance(data, (bytes, bytearray)):
        return base64.b64encode(bytes(data)).decode("ascii")
    return str(data)


def format_data(type_: int | str, data: Any) -> str:
    """One line for a listing."""
    kind = type_value(type_) if isinstance(type_, str) else int(type_)

    if kind in (REG_DWORD, REG_DWORD_BIG_ENDIAN, REG_QWORD):
        return f"{int(data)} (0x{int(data):x})"
    if kind == REG_MULTI_SZ:
        return "; ".join(str(item) for item in (data or []))
    if kind in (REG_SZ, REG_EXPAND_SZ, REG_LINK):
        return str(data or "")
    if kind == REG_NONE:
        return ""
    text = str(data or "")
    # Binary values are shown as their length; the bytes themselves say
    # nothing to a reader and there can be a lot of them.
    try:
        length = len(base64.b64decode(text))
    except Exception:  # noqa: BLE001
        return text
    return f"<{length} bytes>"


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def build(entries: list[dict[str, Any]]) -> bytes:
    """Pack entries back into a ``Registry.pol`` file."""
    from samba.dcerpc import preg
    from samba.ndr import ndr_pack

    pol = preg.file()
    pol.header.signature = "PReg"
    pol.header.version = 1

    packed = []
    for item in entries:
        kind = type_value(item.get("type", REG_SZ))
        data = _encode_data(kind, item.get("data"))

        entry = preg.entry()
        entry.keyname = str(item.get("key", ""))
        entry.valuename = str(item.get("value", ""))
        entry.type = kind
        entry.data = data
        entry.size = data_size(kind, data)
        packed.append(entry)

    pol.num_entries = len(packed)
    pol.entries = packed
    return ndr_pack(pol)


def _encode_data(kind: int, data: Any) -> Any:
    if kind in (REG_DWORD, REG_DWORD_BIG_ENDIAN, REG_QWORD):
        try:
            return int(data)
        except (TypeError, ValueError) as exc:
            raise InvalidRequest(
                "This registry value must be a number.",
                code="invalid_registry_value",
                context={"value": data},
            ) from exc
    if kind == REG_MULTI_SZ:
        if isinstance(data, str):
            return [data]
        return [str(item) for item in (data or [])]
    if kind in (REG_SZ, REG_EXPAND_SZ, REG_LINK):
        return str(data or "")
    if kind == REG_NONE:
        return b""
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    try:
        return base64.b64decode(str(data or ""))
    except Exception as exc:
        raise InvalidRequest(
            "This registry value must be base64-encoded binary.",
            code="invalid_registry_value",
        ) from exc


# ---------------------------------------------------------------------------
# Grouping for display
# ---------------------------------------------------------------------------


def by_key(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group entries under their registry key, in the order they appear.

    A flat list of a few hundred values is unreadable; grouped by key it maps
    onto how the settings were made.
    """
    groups: dict[str, dict[str, Any]] = {}
    for entry in entries:
        group = groups.setdefault(entry["key"], {"key": entry["key"], "values": []})
        group["values"].append(entry)

    return sorted(groups.values(), key=lambda group: group["key"].lower())
