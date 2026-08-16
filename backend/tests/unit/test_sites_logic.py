"""Site and subnet rules that hold without a directory."""

from __future__ import annotations

import pytest

from samadcon.ad import sites
from samadcon.core.errors import InvalidRequest

# ---------------------------------------------------------------------------
# Subnet names
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("192.168.1.0/24", "192.168.1.0/24"),
        ("10.0.0.0/8", "10.0.0.0/8"),
        ("  172.16.0.0/12  ", "172.16.0.0/12"),
        ("2001:db8::/64", "2001:db8::/64"),
        ("2001:0db8:0000::/48", "2001:db8::/48"),
    ],
)
def test_a_valid_subnet_is_normalised(given, expected):
    assert sites.normalise_subnet(given) == expected


def test_a_host_address_is_refused_with_the_network_it_belongs_to():
    """The name is the prefix, so a host address here would match nothing.

    Silently correcting it would be worse: the administrator would have typed
    one thing and got another without noticing.
    """
    with pytest.raises(InvalidRequest) as raised:
        sites.normalise_subnet("192.168.1.5/24")

    assert raised.value.code == "invalid_subnet"
    assert "192.168.1.0/24" in (raised.value.hint or "")


@pytest.mark.parametrize(
    "given",
    ["", "   ", "192.168.1.0", "192.168.1.0/33", "not-a-subnet", "192.168.1.0/24/8"],
)
def test_a_malformed_subnet_is_refused(given):
    with pytest.raises(InvalidRequest):
        sites.normalise_subnet(given)


def test_subnets_sort_by_address_not_by_text():
    """Text order would put .10 before .9."""
    unsorted = [
        {"name": "192.168.10.0/24"},
        {"name": "192.168.9.0/24"},
        {"name": "10.0.0.0/8"},
        {"name": "2001:db8::/64"},
        {"name": "not-a-subnet"},
    ]
    names = [item["name"] for item in sorted(unsorted, key=sites._subnet_sort_key)]

    assert names == [
        "10.0.0.0/8",
        "192.168.9.0/24",
        "192.168.10.0/24",
        "2001:db8::/64",
        # Whatever cannot be parsed goes last instead of breaking the sort.
        "not-a-subnet",
    ]


# ---------------------------------------------------------------------------
# Site names
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("given", ["Default-First-Site-Name", "Berlin", "site_2", "A"])
def test_a_valid_site_name_is_accepted(given):
    assert sites._validate_site_name(given) == given


def test_a_site_name_is_trimmed():
    assert sites._validate_site_name("  Berlin  ") == "Berlin"


@pytest.mark.parametrize("given", ["", "   ", "Berlin Mitte", "berlin.de", "site/2", "ä"])
def test_a_site_name_that_dns_cannot_carry_is_refused(given):
    """Site names become labels in the _sites records clients look up."""
    with pytest.raises(InvalidRequest):
        sites._validate_site_name(given)


def test_a_site_name_has_a_length_limit():
    with pytest.raises(InvalidRequest) as raised:
        sites._validate_site_name("s" * 64)
    assert raised.value.code == "name_too_long"


# ---------------------------------------------------------------------------
# Positions in the tree
# ---------------------------------------------------------------------------


def test_the_site_of_a_server_is_two_levels_up():
    """A DC's site membership is where its object sits, not an attribute."""
    server = "CN=DC1,CN=Servers,CN=Berlin,CN=Sites,CN=Configuration,DC=example,DC=lan"
    assert sites.site_of_server(server) == (
        "CN=Berlin,CN=Sites,CN=Configuration,DC=example,DC=lan"
    )


def test_a_transport_container_is_derived_from_its_link():
    ip_link = "CN=DEFAULTIPSITELINK,CN=IP,CN=Inter-Site Transports,CN=Sites,CN=Configuration,DC=x"
    smtp_link = "CN=Mail,CN=SMTP,CN=Inter-Site Transports,CN=Sites,CN=Configuration,DC=x"

    assert sites._transport_of(ip_link) == "IP"
    assert sites._transport_of(smtp_link) == "SMTP"


def test_an_unrecognised_container_falls_back_to_ip():
    """IP is the only transport that carries domain replication anyway."""
    assert sites._transport_of("CN=Link,CN=Something,DC=x") == "IP"


# ---------------------------------------------------------------------------
# Site link settings
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cost", [1, 100, 32767])
def test_a_permitted_cost_is_accepted(cost):
    sites._validate_cost(cost)


@pytest.mark.parametrize("cost", [0, -1, 32768])
def test_a_cost_outside_the_schema_range_is_refused(cost):
    with pytest.raises(InvalidRequest) as raised:
        sites._validate_cost(cost)
    assert raised.value.code == "invalid_cost"


@pytest.mark.parametrize("minutes", [15, 180, 10080])
def test_a_permitted_replication_interval_is_accepted(minutes):
    sites._validate_interval(minutes)


@pytest.mark.parametrize("minutes", [0, 14, 10081])
def test_an_interval_the_dc_would_ignore_is_refused(minutes):
    """Below 15 minutes the DC rounds up, so the number would be a fiction."""
    with pytest.raises(InvalidRequest) as raised:
        sites._validate_interval(minutes)
    assert raised.value.code == "invalid_interval"


def test_an_unknown_transport_is_refused():
    class FakeInfo:
        config_dn = "CN=Configuration,DC=example,DC=lan"

    class FakeConn:
        info = FakeInfo()

    with pytest.raises(InvalidRequest) as raised:
        sites.transport_dn(FakeConn(), "carrier-pigeon")
    assert raised.value.code == "unknown_transport"
    assert raised.value.context["supported"] == ["IP", "SMTP"]
