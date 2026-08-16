"""Conversions between LDAP wire values and Python types.

ldb hands back :class:`MessageElement` objects holding raw bytes. Active
Directory then layers its own conventions on top: 64-bit FILETIME integers,
"never" encoded as 0 or 0x7FFFFFFFFFFFFFFF, generalized time strings, and
attributes that are single-valued in practice but multi-valued in the schema.
Everything that untangles this lives here so the rest of the code can deal in
ordinary Python values.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

# FILETIME counts 100-nanosecond intervals since 1601-01-01 UTC.
FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=UTC)
FILETIME_TICKS_PER_SECOND = 10_000_000

# AD writes both of these for "no expiry"; 0 also means "not set".
FILETIME_NEVER = 0x7FFFFFFFFFFFFFFF

_GENERALIZED_TIME_RE = re.compile(r"^(\d{14})(?:\.(\d+))?Z$")


def to_text(value: Any) -> str | None:
    """Decode a single LDAP value to text, or None."""
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, str):
        return value
    return str(value)


def first(message: Any, attr: str) -> Any:
    """Return the first raw value of *attr*, or None if absent."""
    if message is None:
        return None
    try:
        element = message.get(attr)
    except (KeyError, TypeError):
        return None
    if element is None:
        return None
    try:
        if len(element) == 0:
            return None
        return element[0]
    except TypeError:
        return element


def as_str(message: Any, attr: str, default: str | None = None) -> str | None:
    value = to_text(first(message, attr))
    return default if value is None else value


def as_int(message: Any, attr: str, default: int | None = None) -> int | None:
    value = to_text(first(message, attr))
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def as_bool(message: Any, attr: str, default: bool | None = None) -> bool | None:
    value = to_text(first(message, attr))
    if value is None:
        return default
    return value.upper() == "TRUE"


def as_bytes(message: Any, attr: str) -> bytes | None:
    value = first(message, attr)
    if value is None:
        return None
    if isinstance(value, bytes):
        return value
    return str(value).encode("utf-8")


def as_list(message: Any, attr: str) -> list[str]:
    if message is None:
        return []
    try:
        element = message.get(attr)
    except (KeyError, TypeError):
        return []
    if element is None:
        return []
    result = []
    for value in element:
        text = to_text(value)
        if text is not None:
            result.append(text)
    return result


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------


def filetime_to_datetime(ticks: int | None) -> datetime | None:
    """Convert a FILETIME to an aware datetime.

    ``None`` for the two "never"/"unset" encodings, so callers can treat
    "no expiry" and "no value" the same way — which is what the UI wants.
    """
    if ticks is None or ticks <= 0 or ticks >= FILETIME_NEVER:
        return None
    try:
        return FILETIME_EPOCH + timedelta(microseconds=ticks // 10)
    except OverflowError:
        return None


def datetime_to_filetime(moment: datetime | None) -> int:
    """Inverse of :func:`filetime_to_datetime`; ``None`` becomes "never"."""
    if moment is None:
        return FILETIME_NEVER
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    delta = moment.astimezone(UTC) - FILETIME_EPOCH
    return int(delta.total_seconds() * FILETIME_TICKS_PER_SECOND)


def as_filetime(message: Any, attr: str) -> datetime | None:
    return filetime_to_datetime(as_int(message, attr))


def generalized_time_to_datetime(value: str | None) -> datetime | None:
    """Parse AD's whenCreated/whenChanged format (``20240517103000.0Z``)."""
    if not value:
        return None
    match = _GENERALIZED_TIME_RE.match(value.strip())
    if match is None:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def as_generalized_time(message: Any, attr: str) -> datetime | None:
    return generalized_time_to_datetime(as_str(message, attr))


def interval_to_timedelta(ticks: int | None) -> timedelta | None:
    """Convert a negative AD interval (maxPwdAge, lockoutDuration, ...).

    These are stored as negative FILETIME intervals; 0 and the "never" value
    both mean the policy is disabled.
    """
    if ticks is None or ticks == 0 or abs(ticks) >= FILETIME_NEVER:
        return None
    return timedelta(seconds=abs(ticks) / FILETIME_TICKS_PER_SECOND)


# ---------------------------------------------------------------------------
# Filters and DNs
# ---------------------------------------------------------------------------


def escape_filter(value: str) -> str:
    """Escape a value for use inside an LDAP search filter (RFC 4515).

    Never interpolate user input into a filter without this — a bare ``*`` or
    ``)`` would otherwise change which objects the query matches.
    """
    try:
        from ldb import binary_encode

        return binary_encode(value)
    except ImportError:
        # Same escaping rules, for hosts without the samba bindings (tests).
        #
        # Upper case on purpose. `ldb.binary_encode` writes `\2A` and this
        # wrote `\2a`, so the escaped value changed shape depending on whether
        # the bindings were installed — and every test of it asserted the
        # environment rather than the behaviour. RFC 4515 allows either
        # spelling and every server reads them alike, so matching the real
        # path costs nothing and removes the divergence.
        out = []
        for char in value:
            if char in "\\*()\0/" or ord(char) > 127:
                out.append("".join(f"\\{byte:02X}" for byte in char.encode("utf-8")))
            else:
                out.append(char)
        return "".join(out)


# ---------------------------------------------------------------------------
# Binary identifiers
# ---------------------------------------------------------------------------


def guid_to_str(raw: bytes | None) -> str | None:
    """Format an objectGUID as ``{xxxxxxxx-xxxx-...}``-style text."""
    if not raw:
        return None
    try:
        from samba.dcerpc import misc
        from samba.ndr import ndr_unpack

        return str(ndr_unpack(misc.GUID, raw))
    except Exception:  # noqa: BLE001 — fall back to manual decoding
        if len(raw) != 16:
            return None
        # objectGUID is little-endian in its first three fields.
        import uuid

        return str(uuid.UUID(bytes_le=raw))


def sid_to_str(raw: bytes | None) -> str | None:
    """Format an objectSid as ``S-1-5-21-...``."""
    if not raw:
        return None
    try:
        from samba.dcerpc import security
        from samba.ndr import ndr_unpack

        return str(ndr_unpack(security.dom_sid, raw))
    except Exception:  # noqa: BLE001 — fall back to manual decoding
        return _decode_sid(raw)


def _decode_sid(raw: bytes) -> str | None:
    """Minimal SID decoder for hosts without the samba bindings."""
    import struct

    if len(raw) < 8:
        return None
    revision = raw[0]
    sub_count = raw[1]
    authority = int.from_bytes(raw[2:8], "big")
    if len(raw) < 8 + 4 * sub_count:
        return None
    subs = struct.unpack(f"<{sub_count}I", raw[8 : 8 + 4 * sub_count])
    return "S-" + "-".join([str(revision), str(authority), *[str(s) for s in subs]])


def rid_of(sid: str | None) -> int | None:
    """Last component of a SID — the RID."""
    if not sid:
        return None
    try:
        return int(sid.rsplit("-", 1)[1])
    except (IndexError, ValueError):
        return None


_DN_ESCAPES = {
    ",": "\\,",
    "+": "\\+",
    '"': '\\"',
    "\\": "\\\\",
    "<": "\\<",
    ">": "\\>",
    ";": "\\;",
    "=": "\\=",
}


def escape_rdn_value(value: str) -> str:
    """Escape a value for use in an RDN (RFC 4514)."""
    if not value:
        return value
    out = []
    for index, char in enumerate(value):
        if char in _DN_ESCAPES:
            out.append(_DN_ESCAPES[char])
        elif char == " " and (index == 0 or index == len(value) - 1):
            out.append("\\ ")
        elif char == "#" and index == 0:
            out.append("\\#")
        elif ord(char) < 32:
            out.append(f"\\{ord(char):02x}")
        else:
            out.append(char)
    return "".join(out)


def rdn_of(dn: str) -> str:
    """First RDN of a DN as text, e.g. ``CN=Max Muster``."""
    if not dn:
        return ""
    depth = 0
    for index, char in enumerate(dn):
        if char == "\\":
            depth += 1
            continue
        if char == "," and depth % 2 == 0:
            return dn[:index]
        depth = 0
    return dn


def name_from_dn(dn: str) -> str:
    """Value of the first RDN, e.g. ``Max Muster`` from ``CN=Max Muster,...``."""
    rdn = rdn_of(dn)
    _, _, value = rdn.partition("=")
    return value.replace("\\,", ",").replace("\\=", "=").strip()


def parent_dn(dn: str) -> str | None:
    """Everything after the first RDN, or None for a naming context root."""
    rdn = rdn_of(dn)
    if rdn == dn:
        return None
    return dn[len(rdn) + 1 :].lstrip()
