"""DNS record validation and formatting.

The binary conversion needs Samba, but everything that decides whether a value
is acceptable does not — and that is the part where a mistake ends up served
to clients.
"""

from __future__ import annotations

import pytest

from samcon.ad import dnsrecords
from samcon.core.errors import InvalidRequest

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


def test_type_names_and_values_agree():
    for name in dnsrecords.EDITABLE_TYPES:
        assert dnsrecords.type_name(dnsrecords.type_value(name)) == name


def test_type_lookup_is_case_insensitive():
    assert dnsrecords.type_value("a") == dnsrecords.TYPE_A
    assert dnsrecords.type_value(" srv ") == dnsrecords.TYPE_SRV


def test_an_unknown_type_is_rejected_with_the_supported_list():
    with pytest.raises(InvalidRequest) as excinfo:
        dnsrecords.type_value("WKS")
    assert excinfo.value.code == "unsupported_record_type"
    assert "A" in excinfo.value.context["supported"]


def test_unknown_numeric_types_still_get_a_label():
    """An unsupported record must remain listable, not crash the zone view."""
    assert dnsrecords.type_name(99) == "TYPE99"


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------


def test_names_lose_the_trailing_dot_and_case():
    assert dnsrecords.normalise_name("DC1.Example.LAN.") == "dc1.example.lan"


def test_an_empty_name_is_rejected():
    with pytest.raises(InvalidRequest) as excinfo:
        dnsrecords.normalise_name("  ")
    assert excinfo.value.code == "missing_dns_name"


def test_names_with_spaces_are_rejected():
    with pytest.raises(InvalidRequest) as excinfo:
        dnsrecords.normalise_name("dc1 .example.lan")
    assert excinfo.value.code == "invalid_dns_name"


def test_overlong_names_are_rejected():
    with pytest.raises(InvalidRequest) as excinfo:
        dnsrecords.normalise_name("a" * 254)
    assert excinfo.value.code == "dns_name_too_long"


# ---------------------------------------------------------------------------
# TTL
# ---------------------------------------------------------------------------


def test_a_missing_ttl_falls_back_to_the_default():
    assert dnsrecords.validate_ttl(None) == dnsrecords.DEFAULT_TTL


def test_zero_ttl_is_allowed():
    """0 is legal and means "do not cache" — not the same as unset."""
    assert dnsrecords.validate_ttl(0) == 0


@pytest.mark.parametrize("ttl", [-1, dnsrecords.MAX_TTL + 1])
def test_out_of_range_ttls_are_rejected(ttl: int):
    with pytest.raises(InvalidRequest) as excinfo:
        dnsrecords.validate_ttl(ttl)
    assert excinfo.value.code == "invalid_ttl"


# ---------------------------------------------------------------------------
# Address records
# ---------------------------------------------------------------------------


def test_an_ipv4_address_is_accepted():
    assert dnsrecords.validate_data("A", {"address": " 192.168.1.10 "}) == {
        "address": "192.168.1.10"
    }


@pytest.mark.parametrize("bad", ["192.168.1.256", "192.168.1", "not-an-ip", "", "::1"])
def test_bad_ipv4_addresses_are_rejected(bad: str):
    with pytest.raises(InvalidRequest) as excinfo:
        dnsrecords.validate_data("A", {"address": bad})
    assert excinfo.value.code == "invalid_ipv4"


def test_ipv6_is_normalised():
    """2001:0db8::0001 and 2001:db8::1 are the same address."""
    assert dnsrecords.validate_data("AAAA", {"address": "2001:0db8::0001"}) == {
        "address": "2001:db8::1"
    }


def test_an_ipv4_address_is_not_accepted_as_ipv6():
    with pytest.raises(InvalidRequest) as excinfo:
        dnsrecords.validate_data("AAAA", {"address": "192.168.1.10"})
    assert excinfo.value.code == "invalid_ipv6"


# ---------------------------------------------------------------------------
# Name records
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["CNAME", "NS", "PTR"])
def test_name_records_normalise_their_target(kind: str):
    assert dnsrecords.validate_data(kind, {"target": "Host.Example.LAN."}) == {
        "target": "host.example.lan"
    }


@pytest.mark.parametrize("kind", ["CNAME", "NS", "PTR"])
def test_name_records_need_a_target(kind: str):
    with pytest.raises(InvalidRequest):
        dnsrecords.validate_data(kind, {})


# ---------------------------------------------------------------------------
# MX and SRV
# ---------------------------------------------------------------------------


def test_mx_keeps_preference_and_exchange():
    assert dnsrecords.validate_data("MX", {"preference": 10, "exchange": "mail.example.lan"}) == {
        "preference": 10,
        "exchange": "mail.example.lan",
    }


def test_mx_preference_must_be_a_number():
    with pytest.raises(InvalidRequest) as excinfo:
        dnsrecords.validate_data("MX", {"preference": "high", "exchange": "mail.example.lan"})
    assert excinfo.value.code == "invalid_number"


def test_mx_preference_must_fit_in_16_bits():
    with pytest.raises(InvalidRequest) as excinfo:
        dnsrecords.validate_data("MX", {"preference": 70000, "exchange": "mail.example.lan"})
    assert excinfo.value.code == "number_out_of_range"


def test_srv_keeps_all_four_fields():
    assert dnsrecords.validate_data(
        "SRV", {"priority": 0, "weight": 100, "port": 389, "target": "dc1.example.lan"}
    ) == {"priority": 0, "weight": 100, "port": 389, "target": "dc1.example.lan"}


def test_srv_port_zero_is_rejected():
    """Port 0 is reserved and never what someone means."""
    with pytest.raises(InvalidRequest) as excinfo:
        dnsrecords.validate_data(
            "SRV", {"priority": 0, "weight": 0, "port": 0, "target": "dc1.example.lan"}
        )
    assert excinfo.value.code == "number_out_of_range"


# ---------------------------------------------------------------------------
# TXT
# ---------------------------------------------------------------------------


def test_a_single_txt_string_is_wrapped_in_a_list():
    assert dnsrecords.validate_data("TXT", {"strings": "v=spf1 -all"}) == {
        "strings": ["v=spf1 -all"]
    }


def test_several_txt_strings_are_kept():
    assert dnsrecords.validate_data("TXT", {"strings": ["one", "two"]})["strings"] == [
        "one",
        "two",
    ]


def test_an_overlong_txt_string_is_rejected():
    with pytest.raises(InvalidRequest) as excinfo:
        dnsrecords.validate_data("TXT", {"strings": "x" * 256})
    assert excinfo.value.code == "txt_too_long"


def test_txt_length_counts_bytes_not_characters():
    """255 umlauts are 510 bytes on the wire."""
    with pytest.raises(InvalidRequest):
        dnsrecords.validate_data("TXT", {"strings": "ä" * 200})


def test_empty_txt_is_rejected():
    with pytest.raises(InvalidRequest) as excinfo:
        dnsrecords.validate_data("TXT", {"strings": []})
    assert excinfo.value.code == "missing_txt"


# ---------------------------------------------------------------------------
# Editing restrictions
# ---------------------------------------------------------------------------


def test_soa_cannot_be_edited():
    """Hand-edited SOA records break replication in hard-to-undo ways."""
    with pytest.raises(InvalidRequest) as excinfo:
        dnsrecords.validate_data("SOA", {"serial": 1})
    assert excinfo.value.code == "unsupported_record_type"


def test_soa_is_missing_from_the_editable_list():
    assert "SOA" not in dnsrecords.EDITABLE_TYPES
    assert "TOMBSTONE" not in dnsrecords.EDITABLE_TYPES


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------


def test_addresses_render_bare():
    assert dnsrecords.format_data("A", {"address": "192.168.1.10"}) == "192.168.1.10"


def test_mx_renders_like_a_zone_file():
    assert dnsrecords.format_data("MX", {"preference": 10, "exchange": "mail.example.lan"}) == (
        "10 mail.example.lan"
    )


def test_srv_renders_in_field_order():
    rendered = dnsrecords.format_data(
        "SRV", {"priority": 0, "weight": 100, "port": 389, "target": "dc1.example.lan"}
    )
    assert rendered == "0 100 389 dc1.example.lan"


def test_txt_strings_are_quoted():
    assert dnsrecords.format_data("TXT", {"strings": ["a", "b"]}) == '"a" "b"'


def test_soa_renders_all_timers():
    rendered = dnsrecords.format_data(
        "SOA",
        {
            "mname": "dc1.example.lan",
            "rname": "hostmaster.example.lan",
            "serial": 42,
            "refresh": 900,
            "retry": 600,
            "expire": 86400,
            "minimum": 3600,
        },
    )
    assert rendered.startswith("dc1.example.lan hostmaster.example.lan 42 ")
    assert rendered.endswith(" 86400 3600")


# ---------------------------------------------------------------------------
# Identifying a record inside a node
# ---------------------------------------------------------------------------


def test_a_record_matches_its_own_description():
    decoded = {"type": "A", "data": {"address": "192.168.1.10"}}
    assert dnsrecords.matches(decoded, "A", {"address": "192.168.1.10"}) is True


def test_a_different_address_does_not_match():
    decoded = {"type": "A", "data": {"address": "192.168.1.10"}}
    assert dnsrecords.matches(decoded, "A", {"address": "192.168.1.11"}) is False


def test_a_different_type_does_not_match():
    """Same value, different type — a node can hold both."""
    decoded = {"type": "CNAME", "data": {"target": "host.example.lan"}}
    assert dnsrecords.matches(decoded, "PTR", {"target": "host.example.lan"}) is False


def test_matching_ignores_fields_that_were_not_given():
    """Deleting an MX by exchange alone must not need its preference."""
    decoded = {"type": "MX", "data": {"preference": 10, "exchange": "mail.example.lan"}}
    assert dnsrecords.matches(decoded, "MX", {"exchange": "mail.example.lan"}) is True


def test_the_same_ipv6_address_matches_in_either_notation():
    """Samba returns IPv6 written out in full; people type the short form.

    Records are identified by their values, so a difference in notation alone
    would make an existing record impossible to edit or delete.
    """
    decoded = {"type": "AAAA", "data": {"address": "2001:0db8:0000:0000:0000:0000:0000:0001"}}
    assert dnsrecords.matches(decoded, "AAAA", {"address": "2001:db8::1"}) is True
    assert dnsrecords.matches(decoded, "AAAA", {"address": "2001:db8::2"}) is False


def test_matching_a_name_ignores_case_and_a_trailing_dot():
    """DNS names are case-insensitive, and the root dot is optional."""
    decoded = {"type": "CNAME", "data": {"target": "host.example.lan"}}
    assert dnsrecords.matches(decoded, "CNAME", {"target": "Host.Example.LAN."}) is True


def test_a_number_sent_as_text_still_matches():
    """A form field arrives as a string; the decoded record holds an int."""
    decoded = {"type": "MX", "data": {"preference": 10, "exchange": "mail.example.lan"}}
    assert dnsrecords.matches(decoded, "MX", {"preference": "10"}) is True


def test_an_unreadable_address_is_passed_through():
    """Canonicalisation runs on directory data too, where it must not raise."""
    assert dnsrecords.canonical_address("not-an-address") == "not-an-address"
