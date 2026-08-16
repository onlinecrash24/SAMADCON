"""Zone-relative name handling.

Getting this wrong writes records under the wrong node: a record created as
``www.example.lan`` inside zone ``example.lan`` must land on node ``www``, not
on a node literally called ``www.example.lan`` — which would answer for
``www.example.lan.example.lan``.
"""

from __future__ import annotations

import pytest

from samcon.ad import dns

ZONE = "example.lan"


@pytest.mark.parametrize(
    ("entered", "expected"),
    [
        ("www", "www"),
        ("www.example.lan", "www"),
        ("www.example.lan.", "www"),
        ("WWW.EXAMPLE.LAN", "www"),
        ("srv.department.example.lan", "srv.department"),
    ],
)
def test_names_inside_the_zone_lose_the_zone_suffix(entered: str, expected: str):
    assert dns.relative_name(entered, ZONE) == expected


@pytest.mark.parametrize("entered", ["", "@", "example.lan", "EXAMPLE.LAN.", "  "])
def test_the_zone_itself_is_the_apex(entered: str):
    assert dns.relative_name(entered, ZONE) == dns.APEX


def test_a_name_from_another_zone_is_left_alone():
    """Not our business to reject it here — the directory will."""
    assert dns.relative_name("host.other.lan", ZONE) == "host.other.lan"


def test_a_name_that_merely_ends_similarly_is_not_shortened():
    """"notexample.lan" does not end with ".example.lan"."""
    assert dns.relative_name("host.notexample.lan", ZONE) == "host.notexample.lan"


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        ("www", "www.example.lan"),
        ("@", "example.lan"),
        ("WWW", "www.example.lan"),
        ("srv.department", "srv.department.example.lan"),
    ],
)
def test_node_names_expand_back_to_fully_qualified(node: str, expected: str):
    assert dns.absolute_name(node, ZONE) == expected


def test_the_round_trip_is_stable():
    for entered in ("www", "srv.department", "@"):
        assert dns.relative_name(dns.absolute_name(entered, ZONE), ZONE) == entered


def test_node_dns_are_built_below_the_zone():
    zone_dn = "DC=example.lan,CN=MicrosoftDNS,DC=DomainDnsZones,DC=example,DC=lan"
    assert dns.node_dn(zone_dn, "www") == f"DC=www,{zone_dn}"


def test_node_names_with_special_characters_are_escaped():
    """A name with a comma would otherwise split the DN."""
    zone_dn = "DC=example.lan,CN=MicrosoftDNS,DC=DomainDnsZones,DC=example,DC=lan"
    built = dns.node_dn(zone_dn, "odd,name")
    assert built.startswith("DC=odd\\,name,")


def test_zone_containers_cover_all_three_partitions():
    class FakeInfo:
        base_dn = "DC=example,DC=lan"
        root_domain_dn = "DC=example,DC=lan"

    class FakeConn:
        info = FakeInfo()

    labels = [label for label, _ in dns.zone_containers(FakeConn())]
    assert labels == ["domain", "forest", "legacy"]

    containers = dict(dns.zone_containers(FakeConn()))
    assert containers["domain"].startswith("CN=MicrosoftDNS,DC=DomainDnsZones,")
    assert containers["forest"].startswith("CN=MicrosoftDNS,DC=ForestDnsZones,")
    # The pre-2003 location, still in use on upgraded domains.
    assert containers["legacy"].startswith("CN=MicrosoftDNS,CN=System,")


def test_forest_zones_hang_off_the_forest_root():
    """_msdcs lives in the forest partition, which is not the local domain on
    a child domain."""

    class FakeInfo:
        base_dn = "DC=child,DC=example,DC=lan"
        root_domain_dn = "DC=example,DC=lan"

    class FakeConn:
        info = FakeInfo()

    containers = dict(dns.zone_containers(FakeConn()))
    assert containers["forest"].endswith("DC=example,DC=lan")
    assert containers["domain"].endswith("DC=child,DC=example,DC=lan")
