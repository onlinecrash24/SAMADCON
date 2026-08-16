"""Sites and services against a live domain controller.

These objects live in the configuration partition, which replicates across the
whole forest. Every test therefore cleans up after itself, and nothing here
touches the existing site a DC is actually in.
"""

from __future__ import annotations

import uuid
from urllib.parse import quote

import pytest

pytestmark = pytest.mark.integration


def quoted(value: str) -> str:
    return quote(value, safe="")


def site_name() -> str:
    return f"samadcon-test-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def test_site(api):
    """A throwaway site, removed afterwards."""
    response = api.post("/api/v1/sites", json={"name": site_name(), "description": "SAMADCON test"})
    if response.status_code != 200:
        pytest.skip(f"cannot create a site: {response.text}")

    site = response.json()
    yield site
    api.delete(f"/api/v1/sites?dn={quoted(site['dn'])}")


@pytest.fixture
def second_site(api):
    response = api.post("/api/v1/sites", json={"name": site_name()})
    if response.status_code != 200:
        pytest.skip(f"cannot create a site: {response.text}")

    site = response.json()
    yield site
    api.delete(f"/api/v1/sites?dn={quoted(site['dn'])}")


# ---------------------------------------------------------------------------
# Sites
# ---------------------------------------------------------------------------


def test_the_topology_has_the_default_site_and_a_dc_in_it(api):
    """Every domain has one site, and every DC sits in one."""
    topology = api.get("/api/v1/sites/topology").json()

    assert topology["sites"], "a domain always has at least one site"
    servers = [server for site in topology["sites"] for server in site["servers"]]
    assert servers, "the DC we are talking to has to be in some site"
    assert any(server["is_dc"] for server in servers)


def test_a_new_site_gets_the_children_it_needs(api, test_site):
    """A bare site object is not a working site.

    Without NTDS Site Settings the KCC has nowhere to record the topology
    generator, and without the Servers container no DC can be moved into it.
    """
    site = api.get(f"/api/v1/sites/site?dn={quoted(test_site['dn'])}").json()

    assert site["settings"]["present"] is True
    assert site["servers"] == []
    assert site["description"] == "SAMADCON test"

    # The Servers container has to be there for a move to work at all.
    servers = api.get(f"/api/v1/sites/servers?dn={quoted(test_site['dn'])}")
    assert servers.status_code == 200


def test_a_site_appears_in_the_listing(api, test_site):
    names = [site["name"] for site in api.get("/api/v1/sites").json()["sites"]]
    assert test_site["name"] in names


def test_a_duplicate_site_is_refused(api, test_site):
    response = api.post("/api/v1/sites", json={"name": test_site["name"]})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "site_exists"


def test_a_site_name_dns_cannot_carry_is_refused(api):
    """Site names become labels in the _sites records clients look up."""
    response = api.post("/api/v1/sites", json={"name": "samadcon test site"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_site_name"


def test_a_site_can_be_renamed(api, test_site):
    fresh = site_name()
    renamed = api.post(
        f"/api/v1/sites/rename?dn={quoted(test_site['dn'])}", json={"name": fresh}
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == fresh

    # Clean up under the new name; the fixture's DN is gone.
    api.delete(f"/api/v1/sites?dn={quoted(renamed.json()['dn'])}")
    test_site["dn"] = renamed.json()["dn"]


def test_a_site_can_be_described_and_located(api, test_site):
    updated = api.patch(
        f"/api/v1/sites?dn={quoted(test_site['dn'])}",
        json={"description": "Second floor", "location": "Berlin"},
    )
    assert updated.status_code == 200, updated.text

    site = api.get(f"/api/v1/sites/site?dn={quoted(test_site['dn'])}").json()
    assert site["description"] == "Second floor"
    assert site["location"] == "Berlin"


# ---------------------------------------------------------------------------
# Subnets
# ---------------------------------------------------------------------------


def test_a_subnet_can_be_created_and_assigned(api, test_site):
    created = api.post(
        "/api/v1/sites/subnets",
        json={"name": "198.51.100.0/24", "site_dn": test_site["dn"], "location": "Berlin"},
    )
    assert created.status_code == 200, created.text
    subnet = created.json()

    try:
        assert subnet["name"] == "198.51.100.0/24"
        assert subnet["site"] == test_site["name"]

        # And the site knows about it from its side.
        site = api.get(f"/api/v1/sites/site?dn={quoted(test_site['dn'])}").json()
        assert [item["name"] for item in site["subnets"]] == ["198.51.100.0/24"]
    finally:
        api.delete(f"/api/v1/sites/subnets?dn={quoted(subnet['dn'])}")


def test_a_subnet_can_be_moved_to_another_site(api, test_site, second_site):
    created = api.post(
        "/api/v1/sites/subnets", json={"name": "198.51.101.0/24", "site_dn": test_site["dn"]}
    )
    subnet = created.json()

    try:
        moved = api.patch(
            f"/api/v1/sites/subnets?dn={quoted(subnet['dn'])}",
            json={"site_dn": second_site["dn"]},
        )
        assert moved.status_code == 200, moved.text

        subnets = api.get("/api/v1/sites/subnets").json()["subnets"]
        mine = next(item for item in subnets if item["dn"] == subnet["dn"])
        assert mine["site"] == second_site["name"]
    finally:
        api.delete(f"/api/v1/sites/subnets?dn={quoted(subnet['dn'])}")


def test_a_subnet_can_be_detached_from_its_site(api, test_site):
    """"No site" is a real state — entered but not assigned yet."""
    created = api.post(
        "/api/v1/sites/subnets", json={"name": "198.51.102.0/24", "site_dn": test_site["dn"]}
    )
    subnet = created.json()

    try:
        detached = api.patch(
            f"/api/v1/sites/subnets?dn={quoted(subnet['dn'])}", json={"clear_site": True}
        )
        assert detached.status_code == 200, detached.text

        subnets = api.get("/api/v1/sites/subnets").json()["subnets"]
        mine = next(item for item in subnets if item["dn"] == subnet["dn"])
        assert mine["site"] is None
    finally:
        api.delete(f"/api/v1/sites/subnets?dn={quoted(subnet['dn'])}")


def test_a_host_address_is_refused_as_a_subnet(api, test_site):
    """192.168.1.5/24 would be stored happily and then match nothing."""
    response = api.post(
        "/api/v1/sites/subnets", json={"name": "198.51.100.5/24", "site_dn": test_site["dn"]}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_subnet"
    assert "198.51.100.0/24" in response.json()["error"]["hint"]


def test_a_subnet_pointing_at_a_missing_site_is_refused(api):
    response = api.post(
        "/api/v1/sites/subnets",
        json={"name": "198.51.103.0/24", "site_dn": "CN=Nowhere,CN=Sites,CN=Configuration,DC=x"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "site_not_found"


# ---------------------------------------------------------------------------
# Deleting a site
# ---------------------------------------------------------------------------


def test_a_site_still_used_by_a_subnet_is_not_deleted(api, test_site):
    """Deleting it would leave the subnet pointing at nothing."""
    created = api.post(
        "/api/v1/sites/subnets", json={"name": "198.51.104.0/24", "site_dn": test_site["dn"]}
    )
    subnet = created.json()

    try:
        refused = api.delete(f"/api/v1/sites?dn={quoted(test_site['dn'])}")
        assert refused.status_code == 409
        assert refused.json()["error"]["code"] == "site_in_use"
    finally:
        api.delete(f"/api/v1/sites/subnets?dn={quoted(subnet['dn'])}")


def test_the_site_holding_a_dc_is_not_deleted(api):
    """The one guard that matters: it would cut the DC out of the topology."""
    topology = api.get("/api/v1/sites/topology").json()
    occupied = next((site for site in topology["sites"] if site["servers"]), None)
    assert occupied is not None

    refused = api.delete(f"/api/v1/sites?dn={quoted(occupied['dn'])}")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "site_not_empty"


# ---------------------------------------------------------------------------
# Site links
# ---------------------------------------------------------------------------


def test_a_site_link_can_be_created_and_changed(api, test_site, second_site):
    created = api.post(
        "/api/v1/sites/links",
        json={
            "name": site_name(),
            "site_dns": [test_site["dn"], second_site["dn"]],
            "cost": 200,
            "replication_interval": 60,
        },
    )
    assert created.status_code == 200, created.text
    link = created.json()

    try:
        assert link["cost"] == 200
        assert link["replication_interval"] == 60
        assert link["transport"] == "IP"
        assert sorted(link["sites"]) == sorted([test_site["name"], second_site["name"]])

        changed = api.patch(
            f"/api/v1/sites/links?dn={quoted(link['dn'])}",
            json={"cost": 50, "replication_interval": 180},
        )
        assert changed.status_code == 200, changed.text

        links = api.get("/api/v1/sites/links").json()["links"]
        mine = next(item for item in links if item["dn"] == link["dn"])
        assert mine["cost"] == 50
        assert mine["replication_interval"] == 180
    finally:
        api.delete(f"/api/v1/sites/links?dn={quoted(link['dn'])}")


def test_a_link_with_one_site_is_refused(api, test_site):
    """It describes no path, so the KCC would ignore it silently."""
    response = api.post(
        "/api/v1/sites/links", json={"name": site_name(), "site_dns": [test_site["dn"]]}
    )
    # The list minimum is enforced by the schema before the directory is touched.
    assert response.status_code == 422


def test_a_link_naming_the_same_site_twice_is_refused(api, test_site):
    response = api.post(
        "/api/v1/sites/links",
        json={"name": site_name(), "site_dns": [test_site["dn"], test_site["dn"]]},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "too_few_sites"


def test_the_default_site_link_is_listed(api):
    """Every domain is provisioned with DEFAULTIPSITELINK."""
    links = api.get("/api/v1/sites/links").json()["links"]
    assert any(link["transport"] == "IP" for link in links)


# ---------------------------------------------------------------------------
# Servers
# ---------------------------------------------------------------------------


def test_connections_can_be_read_for_a_dc(api):
    topology = api.get("/api/v1/sites/topology").json()
    server = next(
        server for site in topology["sites"] for server in site["servers"] if server["is_dc"]
    )

    response = api.get(f"/api/v1/sites/connections?dn={quoted(server['dn'])}")
    assert response.status_code == 200, response.text
    # A single-DC domain has none, which is correct rather than an error.
    assert isinstance(response.json()["connections"], list)


def test_moving_a_server_to_a_site_that_does_not_exist_is_refused(api):
    topology = api.get("/api/v1/sites/topology").json()
    server = next(
        server for site in topology["sites"] for server in site["servers"] if server["is_dc"]
    )

    response = api.post(
        f"/api/v1/sites/servers/move?dn={quoted(server['dn'])}",
        json={"site_dn": "CN=Nowhere,CN=Sites,CN=Configuration,DC=x"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "site_not_found"
