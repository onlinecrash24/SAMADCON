"""Value conversions: FILETIME, SIDs, GUIDs, filter and RDN escaping."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from samcon.ad import values


class FakeElement(list):
    """Mimics ldb.MessageElement: a list of raw byte values."""


class FakeMessage(dict):
    """Mimics an ldb.Message enough for the value helpers."""

    def get(self, key, default=None):
        for name, value in self.items():
            if name.lower() == key.lower():
                return value
        return default


def msg(**attrs) -> FakeMessage:
    message = FakeMessage()
    for name, value in attrs.items():
        raw = value if isinstance(value, list) else [value]
        message[name] = FakeElement(
            v if isinstance(v, bytes) else str(v).encode("utf-8") for v in raw
        )
    return message


# ---------------------------------------------------------------------------
# Scalars
# ---------------------------------------------------------------------------


def test_as_str_decodes_bytes():
    assert values.as_str(msg(cn="Max Müller"), "cn") == "Max Müller"


def test_attribute_lookup_is_case_insensitive():
    # LDAP attribute names are case-insensitive and AD echoes back whatever
    # case the client used.
    assert values.as_str(msg(sAMAccountName="mmuster"), "samaccountname") == "mmuster"


def test_missing_attribute_returns_default():
    assert values.as_str(msg(), "cn", "fallback") == "fallback"
    assert values.as_int(msg(), "uac", 0) == 0


def test_as_int_ignores_non_numeric():
    assert values.as_int(msg(count="abc"), "count", -1) == -1


def test_as_bool_reads_ldap_booleans():
    assert values.as_bool(msg(flag="TRUE"), "flag") is True
    assert values.as_bool(msg(flag="FALSE"), "flag") is False


def test_as_list_returns_all_values():
    entry = msg(memberOf=["CN=A,DC=t", "CN=B,DC=t"])
    assert values.as_list(entry, "memberOf") == ["CN=A,DC=t", "CN=B,DC=t"]


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------


def test_filetime_round_trip():
    moment = datetime(2024, 5, 17, 10, 30, 0, tzinfo=UTC)
    assert values.filetime_to_datetime(values.datetime_to_filetime(moment)) == moment


def test_filetime_epoch_is_1601():
    """One day past the epoch must be exactly 864e9 ticks of 100 ns."""
    known = values.datetime_to_filetime(datetime(1601, 1, 2, tzinfo=UTC))
    assert known == 864_000_000_000
    assert values.filetime_to_datetime(known) == datetime(1601, 1, 2, tzinfo=UTC)


@pytest.mark.parametrize("never", [0, values.FILETIME_NEVER, -1])
def test_never_and_unset_become_none(never: int):
    """Both AD encodings of "no expiry" must read as None, not as year 30828."""
    assert values.filetime_to_datetime(never) is None


def test_none_converts_to_never():
    assert values.datetime_to_filetime(None) == values.FILETIME_NEVER


def test_naive_datetime_is_treated_as_utc():
    naive = datetime(2024, 1, 1, 12, 0, 0)
    aware = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    assert values.datetime_to_filetime(naive) == values.datetime_to_filetime(aware)


def test_generalized_time_parsing():
    parsed = values.generalized_time_to_datetime("20240517103000.0Z")
    assert parsed == datetime(2024, 5, 17, 10, 30, 0, tzinfo=UTC)


def test_generalized_time_rejects_garbage():
    assert values.generalized_time_to_datetime("not a time") is None
    assert values.generalized_time_to_datetime(None) is None


def test_interval_to_timedelta_handles_negative_ad_intervals():
    # maxPwdAge of 42 days is stored as a negative interval.
    ticks = -(42 * 24 * 3600 * 10_000_000)
    delta = values.interval_to_timedelta(ticks)
    assert delta is not None
    assert delta.days == 42


def test_disabled_policy_interval_is_none():
    assert values.interval_to_timedelta(0) is None
    assert values.interval_to_timedelta(-values.FILETIME_NEVER) is None


# ---------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------


def _pack_sid(authority: int, *sub_authorities: int) -> bytes:
    """Build a binary SID the way AD stores it: big-endian authority, LE subs."""
    import struct

    return (
        bytes([1, len(sub_authorities)])
        + authority.to_bytes(6, "big")
        + struct.pack(f"<{len(sub_authorities)}I", *sub_authorities)
    )


def test_sid_decoding_of_wellknown_sid():
    # BUILTIN\Administrators — a SID whose text form is not in dispute.
    assert values._decode_sid(_pack_sid(5, 32, 544)) == "S-1-5-32-544"


def test_sid_decoding_of_domain_sid():
    raw = _pack_sid(5, 21, 1004336348, 1177238915, 682003330, 512)
    assert values._decode_sid(raw) == "S-1-5-21-1004336348-1177238915-682003330-512"


def test_sid_decoding_rejects_truncated_input():
    assert values._decode_sid(b"\x01\x05") is None
    # Claims five sub-authorities but carries one.
    assert values._decode_sid(bytes([1, 5, 0, 0, 0, 0, 0, 5]) + b"\x00" * 4) is None


def test_rid_extraction():
    assert values.rid_of("S-1-5-21-1-2-3-512") == 512
    assert values.rid_of(None) is None
    assert values.rid_of("nonsense") is None


def test_guid_decoding_is_little_endian():
    raw = bytes.fromhex("78563412" "3412" "7856" "1234567890abcdef")
    assert values.guid_to_str(raw) == "12345678-1234-5678-1234-567890abcdef"


# ---------------------------------------------------------------------------
# Escaping — the security-relevant part
# ---------------------------------------------------------------------------


def test_filter_escaping_neutralises_wildcards():
    """A bare * would turn an exact lookup into a prefix match."""
    escaped = values.escape_filter("*")
    assert "*" not in escaped
    # Upper case, the way `ldb.binary_encode` writes it. This asserted `\2a`
    # until the suite first ran on a host that has the samba bindings, where
    # the real encoder runs instead of our fallback — the test had been
    # checking the fallback's spelling rather than the escaping.
    assert escaped == "\\2A"


def test_filter_escaping_neutralises_parentheses():
    escaped = values.escape_filter("a)(objectClass=*")
    assert ")" not in escaped
    assert "(" not in escaped


def test_filter_escaping_leaves_plain_text_alone():
    assert values.escape_filter("mmuster") == "mmuster"


def test_rdn_escaping_handles_commas():
    assert values.escape_rdn_value("Muster, Max") == "Muster\\, Max"


def test_rdn_escaping_handles_leading_and_trailing_space():
    assert values.escape_rdn_value(" Max ") == "\\ Max\\ "


def test_rdn_escaping_handles_plus_and_equals():
    assert values.escape_rdn_value("a+b=c") == "a\\+b\\=c"


# ---------------------------------------------------------------------------
# DN handling
# ---------------------------------------------------------------------------


def test_rdn_of():
    assert values.rdn_of("CN=Max,OU=Users,DC=test,DC=lan") == "CN=Max"


def test_rdn_of_respects_escaped_commas():
    dn = "CN=Muster\\, Max,OU=Users,DC=test,DC=lan"
    assert values.rdn_of(dn) == "CN=Muster\\, Max"


def test_name_from_dn_unescapes():
    dn = "CN=Muster\\, Max,OU=Users,DC=test,DC=lan"
    assert values.name_from_dn(dn) == "Muster, Max"


def test_parent_dn():
    assert values.parent_dn("CN=Max,OU=Users,DC=test") == "OU=Users,DC=test"


def test_parent_dn_of_root_is_none():
    assert values.parent_dn("DC=test") is None
