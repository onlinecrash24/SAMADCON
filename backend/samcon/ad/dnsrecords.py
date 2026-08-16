"""The ``dnsRecord`` attribute: binary in the directory, typed in the API.

Active Directory stores each DNS record as an NDR-packed
``dnsp.DnssrvRpcRecord`` inside the multi-valued ``dnsRecord`` attribute of a
``dnsNode`` object. One node holds every record for one name, so "the A record
of www" is one value among several rather than an object of its own.

This module converts between that binary form and a dictionary per record
type. Validation happens here too, before anything is packed: a malformed
address rejected with a clear message beats one written into the directory and
served to clients.

The parsing and formatting of the textual forms is deliberately free of Samba
imports so it can be tested anywhere; only :func:`decode` and :func:`encode`
need the bindings.
"""

from __future__ import annotations

import ipaddress
from typing import Any

from samcon.core.errors import InvalidRequest

# dnsp record types (MS-DNSP 2.2.2.1.1). Mirrored rather than imported so the
# names are usable without the bindings present.
TYPE_ZERO = 0  # tombstone
TYPE_A = 1
TYPE_NS = 2
TYPE_CNAME = 5
TYPE_SOA = 6
TYPE_PTR = 12
TYPE_MX = 15
TYPE_TXT = 16
TYPE_AAAA = 28
TYPE_SRV = 33

TYPE_NAMES: dict[int, str] = {
    TYPE_ZERO: "TOMBSTONE",
    TYPE_A: "A",
    TYPE_NS: "NS",
    TYPE_CNAME: "CNAME",
    TYPE_SOA: "SOA",
    TYPE_PTR: "PTR",
    TYPE_MX: "MX",
    TYPE_TXT: "TXT",
    TYPE_AAAA: "AAAA",
    TYPE_SRV: "SRV",
}

TYPE_VALUES: dict[str, int] = {name: value for value, name in TYPE_NAMES.items()}

# Types SAMCON lets an administrator create or change. SOA and tombstones are
# readable but not editable here: a hand-edited SOA breaks replication in ways
# that are tedious to undo.
EDITABLE_TYPES = ("A", "AAAA", "CNAME", "NS", "PTR", "MX", "SRV", "TXT")

# DNS_RANK_ZONE — an authoritative record in a zone the server owns.
RANK_ZONE = 240

DEFAULT_TTL = 900
MAX_TTL = 2147483647

# A single TXT string cannot exceed 255 bytes on the wire.
MAX_TXT_STRING = 255


def type_name(value: int) -> str:
    return TYPE_NAMES.get(value, f"TYPE{value}")


def type_value(name: str) -> int:
    key = name.strip().upper()
    if key not in TYPE_VALUES:
        raise InvalidRequest(
            f"Unsupported record type '{name}'.",
            code="unsupported_record_type",
            context={"supported": list(EDITABLE_TYPES)},
        )
    return TYPE_VALUES[key]


# ---------------------------------------------------------------------------
# Validation and normalisation of the typed form
# ---------------------------------------------------------------------------


def normalise_name(name: str, *, what: str = "Name") -> str:
    """Normalise a DNS name: no trailing dot, lower case, non-empty."""
    text = (name or "").strip().rstrip(".").lower()
    if not text:
        raise InvalidRequest(f"{what} is missing.", code="missing_dns_name")
    if len(text) > 253:
        raise InvalidRequest(f"{what} is too long.", code="dns_name_too_long")
    if any(char.isspace() for char in text):
        raise InvalidRequest(
            f"{what} must not contain spaces.", code="invalid_dns_name", context={"name": name}
        )
    return text


def validate_ttl(ttl: int | None) -> int:
    if ttl is None:
        return DEFAULT_TTL
    if ttl < 0 or ttl > MAX_TTL:
        raise InvalidRequest(
            "The TTL is outside the permitted range.",
            code="invalid_ttl",
            context={"min": 0, "max": MAX_TTL},
        )
    return int(ttl)


def validate_data(record_type: str, data: dict[str, Any]) -> dict[str, Any]:
    """Check and normalise the type-specific fields.

    Returns the cleaned data; raises with a specific message otherwise. Doing
    this before packing means a bad value never reaches the directory.
    """
    kind = record_type.strip().upper()

    if kind == "A":
        return {"address": _validate_ipv4(data.get("address"))}
    if kind == "AAAA":
        return {"address": _validate_ipv6(data.get("address"))}
    if kind in ("CNAME", "NS", "PTR"):
        return {"target": normalise_name(str(data.get("target") or ""), what="Target")}
    if kind == "MX":
        return {
            "preference": _validate_uint16(data.get("preference"), "Preference"),
            "exchange": normalise_name(str(data.get("exchange") or ""), what="Mail server"),
        }
    if kind == "SRV":
        return {
            "priority": _validate_uint16(data.get("priority"), "Priority"),
            "weight": _validate_uint16(data.get("weight"), "Weight"),
            "port": _validate_uint16(data.get("port"), "Port", minimum=1),
            "target": normalise_name(str(data.get("target") or ""), what="Target"),
        }
    if kind == "TXT":
        return {"strings": _validate_txt(data.get("strings"))}

    raise InvalidRequest(
        f"Records of type '{record_type}' cannot be edited.",
        code="unsupported_record_type",
        context={"supported": list(EDITABLE_TYPES)},
    )


def _validate_ipv4(value: Any) -> str:
    try:
        return str(ipaddress.IPv4Address(str(value).strip()))
    except (ipaddress.AddressValueError, ValueError) as exc:
        raise InvalidRequest(
            "Not a valid IPv4 address.", code="invalid_ipv4", context={"value": value}
        ) from exc


def _validate_ipv6(value: Any) -> str:
    try:
        return str(ipaddress.IPv6Address(str(value).strip()))
    except (ipaddress.AddressValueError, ValueError) as exc:
        raise InvalidRequest(
            "Not a valid IPv6 address.", code="invalid_ipv6", context={"value": value}
        ) from exc


def _validate_uint16(value: Any, what: str, *, minimum: int = 0) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidRequest(
            f"{what} must be a number.", code="invalid_number", context={"value": value}
        ) from exc
    if number < minimum or number > 65535:
        raise InvalidRequest(
            f"{what} must be between {minimum} and 65535.",
            code="number_out_of_range",
            context={"value": number},
        )
    return number


def canonical_address(value: Any) -> str:
    """An address in its short, lower-case form, whatever notation it arrives in.

    Samba hands IPv6 back fully written out — ``2001:0db8:0000:0000:0000:0000:
    0000:0001`` — while an administrator enters ``2001:db8::1``. Both denote
    the same address, so the API settles on the short form: otherwise a record
    reads back differently than it was entered, and since records are
    identified by their values, deleting or editing one by the notation it was
    typed in would no longer find it.

    Lenient by design — this also runs on values read from the directory, where
    something unparseable should still be shown rather than raise.
    """
    text = str(value).strip()
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        return text


def _validate_txt(value: Any) -> list[str]:
    if value is None:
        raise InvalidRequest("The text is missing.", code="missing_txt")
    strings = [value] if isinstance(value, str) else list(value)
    if not strings:
        raise InvalidRequest("The text is missing.", code="missing_txt")

    cleaned: list[str] = []
    for item in strings:
        text = str(item)
        if len(text.encode("utf-8")) > MAX_TXT_STRING:
            raise InvalidRequest(
                f"A single text string may not exceed {MAX_TXT_STRING} bytes.",
                code="txt_too_long",
            )
        cleaned.append(text)
    return cleaned


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------


def format_data(record_type: str, data: dict[str, Any]) -> str:
    """One-line rendering, in the notation a zone file would use."""
    kind = record_type.strip().upper()

    if kind in ("A", "AAAA"):
        return str(data.get("address", ""))
    if kind in ("CNAME", "NS", "PTR"):
        return str(data.get("target", ""))
    if kind == "MX":
        return f"{data.get('preference', 0)} {data.get('exchange', '')}"
    if kind == "SRV":
        return (
            f"{data.get('priority', 0)} {data.get('weight', 0)} "
            f"{data.get('port', 0)} {data.get('target', '')}"
        )
    if kind == "TXT":
        return " ".join(f'"{item}"' for item in data.get("strings", []))
    if kind == "SOA":
        return (
            f"{data.get('mname', '')} {data.get('rname', '')} "
            f"{data.get('serial', 0)} {data.get('refresh', 0)} {data.get('retry', 0)} "
            f"{data.get('expire', 0)} {data.get('minimum', 0)}"
        )
    return str(data)


# ---------------------------------------------------------------------------
# Binary conversion — the only part that needs the Samba bindings
# ---------------------------------------------------------------------------


def decode(raw: bytes) -> dict[str, Any]:
    """Unpack one ``dnsRecord`` value."""
    from samba.dcerpc import dnsp
    from samba.ndr import ndr_unpack

    record = ndr_unpack(dnsp.DnssrvRpcRecord, raw)
    kind = type_name(int(record.wType))

    decoded: dict[str, Any] = {
        "type": kind,
        "ttl": int(record.dwTtlSeconds),
        "serial": int(record.dwSerial),
        "rank": int(record.rank),
        # Non-zero means the record ages and will be scavenged; static records
        # carry 0. Worth showing, because an aging record can vanish on its own.
        "timestamp": int(record.dwTimeStamp),
        "tombstone": int(record.wType) == TYPE_ZERO,
    }
    decoded["data"] = _decode_data(record, kind)
    decoded["display"] = format_data(kind, decoded["data"])
    return decoded


def _decode_data(record: Any, kind: str) -> dict[str, Any]:
    """Read one record's payload.

    The field names come from librpc/idl/dnsp.idl and are not what the DNS
    specifications call them: MX carries its preference in ``wPriority`` and
    its host in ``nameTarget``, the same names SRV uses. The API deliberately
    uses the DNS terms instead, so this is where the two vocabularies meet.
    """
    data = record.data

    if kind in ("A", "AAAA"):
        return {"address": canonical_address(data)}
    if kind in ("CNAME", "NS", "PTR"):
        return {"target": _name_of(data)}
    if kind == "MX":
        return {"preference": int(data.wPriority), "exchange": _name_of(data.nameTarget)}
    if kind == "SRV":
        return {
            "priority": int(data.wPriority),
            "weight": int(data.wWeight),
            "port": int(data.wPort),
            "target": _name_of(data.nameTarget),
        }
    if kind == "TXT":
        return {"strings": [_text_of(item) for item in (data.str or [])]}
    if kind == "SOA":
        return {
            "serial": int(data.serial),
            "refresh": int(data.refresh),
            "retry": int(data.retry),
            "expire": int(data.expire),
            "minimum": int(data.minimum),
            "mname": _name_of(data.mname),
            "rname": _name_of(data.rname),
        }
    if kind == "TOMBSTONE":
        return {}
    # An unknown type is still worth listing; the raw value is all we can say
    # about it.
    return {"raw": str(data)}


def _text_of(value: Any) -> str:
    """A dnsp_string may arrive as text or as a struct wrapping it."""
    return str(getattr(value, "str", value))


def _name_of(value: Any) -> str:
    """A dnsp_name may arrive as text or as a struct wrapping it."""
    return _text_of(value).rstrip(".")


def encode(record_type: str, data: dict[str, Any], *, ttl: int, serial: int = 1) -> bytes:
    """Pack a record for the ``dnsRecord`` attribute.

    *data* must already have been through :func:`validate_data`.
    """
    from samba.dcerpc import dnsp
    from samba.ndr import ndr_pack

    kind = record_type.strip().upper()
    record = dnsp.DnssrvRpcRecord()
    record.wType = type_value(kind)
    record.rank = RANK_ZONE
    record.dwSerial = serial
    record.dwTtlSeconds = ttl
    # 0 means static: the record is never scavenged. Anything SAMCON writes is
    # entered by hand, so it should not disappear on its own.
    record.dwTimeStamp = 0

    # Structure and field names follow librpc/idl/dnsp.idl; the assignments
    # mirror what samba.provision.sambadns does when it writes the same records.
    if kind in ("A", "AAAA"):
        record.data = data["address"]
    elif kind in ("CNAME", "NS", "PTR"):
        record.data = data["target"]
    elif kind == "MX":
        mx = dnsp.mx()
        # Not a misnomer on our side: dnsp calls the MX preference wPriority.
        mx.wPriority = data["preference"]
        mx.nameTarget = data["exchange"]
        record.data = mx
    elif kind == "SRV":
        srv = dnsp.srv()
        srv.wPriority = data["priority"]
        srv.wWeight = data["weight"]
        srv.wPort = data["port"]
        srv.nameTarget = data["target"]
        record.data = srv
    elif kind == "TXT":
        strings = list(data["strings"])
        text_list = dnsp.string_list()
        text_list.count = len(strings)
        text_list.str = strings
        record.data = text_list
    else:
        raise InvalidRequest(
            f"Records of type '{record_type}' cannot be written.",
            code="unsupported_record_type",
            context={"supported": list(EDITABLE_TYPES)},
        )

    return ndr_pack(record)


def encode_soa(
    *,
    mname: str,
    rname: str,
    serial: int = 1,
    refresh: int = 900,
    retry: int = 600,
    expire: int = 86400,
    minimum: int = 3600,
    zone_ttl: int = DEFAULT_TTL,
) -> bytes:
    """Pack the SOA record a new zone needs.

    Not reachable through :func:`encode`: SOA is created with a zone and never
    edited by hand afterwards.
    """
    from samba.dcerpc import dnsp
    from samba.ndr import ndr_pack

    soa = dnsp.soa()
    soa.serial = serial
    soa.refresh = refresh
    soa.retry = retry
    soa.expire = expire
    soa.minimum = minimum
    soa.mname = normalise_name(mname, what="Primary server")
    soa.rname = normalise_name(rname, what="Responsible person")

    record = dnsp.DnssrvRpcRecord()
    record.wType = TYPE_SOA
    record.rank = RANK_ZONE
    record.dwSerial = serial
    record.dwTtlSeconds = zone_ttl
    record.dwTimeStamp = 0
    record.data = soa

    return ndr_pack(record)


# Fields holding a DNS name, which is case-insensitive and may carry a
# trailing dot, and fields holding a number that may arrive as a string.
_NAME_FIELDS = frozenset({"target", "exchange", "mname", "rname"})
_NUMBER_FIELDS = frozenset(
    {"preference", "priority", "weight", "port", "serial", "refresh", "retry", "expire", "minimum"}
)


def comparable(data: dict[str, Any]) -> dict[str, Any]:
    """*data* reduced to the form used for comparing two records.

    Both sides of that comparison have to be written the same way, and only one
    of them comes from our own validation: the other is whatever the client
    sent along to say which record it means.
    """
    result: dict[str, Any] = {}
    for key, value in data.items():
        if key == "address":
            result[key] = canonical_address(value)
        elif key in _NAME_FIELDS:
            result[key] = str(value).strip().rstrip(".").lower()
        elif key in _NUMBER_FIELDS:
            try:
                result[key] = int(value)
            except (TypeError, ValueError):
                result[key] = value
        else:
            result[key] = value
    return result


def bump_soa_serial(raw: bytes) -> tuple[bytes, int]:
    """The SOA record with its serial advanced by one, and that new serial.

    Deliberately works on the unpacked record rather than going through
    :func:`decode` and :func:`encode_soa`: everything except the serial has to
    come back exactly as it was, down to how the names are written. This is
    what ``dnsserver_update_soa()`` does on Samba's own write path.
    """
    from samba.dcerpc import dnsp
    from samba.ndr import ndr_pack, ndr_unpack

    record = ndr_unpack(dnsp.DnssrvRpcRecord, raw)
    if int(record.wType) != TYPE_SOA:
        raise ValueError("not an SOA record")

    serial = int(record.data.serial) + 1
    record.data.serial = serial
    record.dwSerial = serial
    return ndr_pack(record), serial


def matches(decoded: dict[str, Any], record_type: str, data: dict[str, Any]) -> bool:
    """Whether a decoded record is the one described by *record_type* / *data*.

    Used to find the value to replace or delete inside a node that holds
    several records — the directory gives us no per-record identifier.
    """
    if decoded.get("type") != record_type.strip().upper():
        return False
    existing = comparable(decoded.get("data") or {})
    return all(existing.get(key) == value for key, value in comparable(data).items())
