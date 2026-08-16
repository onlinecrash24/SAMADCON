"""DNS against a live domain controller.

The unit tests cover validation and naming; what only a real directory can
show is whether our NDR encoding matches what Samba writes and reads. A record
that packs without error but comes back wrong — or is served wrong to clients —
would pass every offline check.

Each test works inside its own throwaway zone, so nothing touches the domain's
real DNS data.
"""

from __future__ import annotations

import uuid
from urllib.parse import quote

import pytest

pytestmark = pytest.mark.integration


def quoted(value: str) -> str:
    """A DN as a query parameter: commas and equals signs need escaping."""
    return quote(value, safe="")


def zone_name() -> str:
    # .invalid is reserved for exactly this (RFC 2606), so the name cannot
    # collide with anything real even if a cleanup is missed.
    return f"samcon-test-{uuid.uuid4().hex[:8]}.invalid"


@pytest.fixture
def test_zone(api):
    """A disposable forward zone, deleted afterwards."""
    response = api.post(
        "/api/v1/dns/zones", json={"name": zone_name(), "partition": "domain"}
    )
    if response.status_code != 200:
        pytest.skip(f"cannot create a DNS zone: {response.text}")

    zone = response.json()
    yield zone
    api.delete(f"/api/v1/dns/zones?zone_dn={quoted(zone['dn'])}")


def records_of(api, zone) -> list[dict]:
    listing = api.get(
        f"/api/v1/dns/records?zone_dn={quoted(zone['dn'])}&zone={quoted(zone['name'])}"
    )
    assert listing.status_code == 200, listing.text
    return listing.json()["records"]


def create(api, zone, **payload) -> dict:
    response = api.post(
        f"/api/v1/dns/records?zone_dn={quoted(zone['dn'])}",
        json={"zone": zone["name"], **payload},
    )
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------


def test_zones_are_listed_with_their_partition(api, domain):
    zones = api.get("/api/v1/dns/zones").json()["zones"]
    assert zones, "a domain always has at least its own forward zone"
    assert {zone["partition"] for zone in zones} <= {"domain", "forest", "legacy"}

    # The domain's own forward zone must be among them.
    own = next((z for z in zones if z["name"].lower() == domain["dns_domain"].lower()), None)
    assert own is not None, "the domain's own DNS zone was not listed"
    assert own["reverse"] is False


def test_a_zone_in_the_forest_partition_is_found_again(api):
    """The forest container hangs off the forest root, not the domain base DN.

    Getting that wrong only shows up here: the zone is created somewhere the
    listing never looks.
    """
    name = zone_name()
    created = api.post("/api/v1/dns/zones", json={"name": name, "partition": "forest"})
    if created.status_code != 200:
        pytest.skip(f"cannot create a forest-wide DNS zone: {created.text}")

    try:
        zones = api.get("/api/v1/dns/zones").json()["zones"]
        listed = next((zone for zone in zones if zone["name"] == name), None)
        assert listed is not None, "a forest-wide zone was created but is not listed"
        assert listed["partition"] == "forest"
    finally:
        api.delete(f"/api/v1/dns/zones?zone_dn={quoted(created.json()['dn'])}")


def test_a_new_zone_gets_its_soa_and_ns(api, test_zone):
    """A zone object without those two loads but answers nothing."""
    records = records_of(api, test_zone)
    types = {record["type"] for record in records}
    assert "SOA" in types
    assert "NS" in types

    soa = next(record for record in records if record["type"] == "SOA")
    assert soa["node"] == "@"
    assert soa["data"]["mname"]
    assert soa["data"]["rname"].startswith("hostmaster.")
    # SOA is readable but must not be offered for editing.
    assert soa["editable"] is False


def test_a_zone_can_be_deleted_with_its_records(api):
    name = zone_name()
    created = api.post("/api/v1/dns/zones", json={"name": name})
    if created.status_code != 200:
        pytest.skip(f"cannot create a DNS zone: {created.text}")
    zone = created.json()

    # A zone that still holds records only deletes if the removal recurses.
    create(api, zone, name="host", type="A", data={"address": "192.0.2.10"})

    removed = api.delete(f"/api/v1/dns/zones?zone_dn={quoted(zone['dn'])}")
    assert removed.status_code == 200, removed.text
    assert not [z for z in api.get("/api/v1/dns/zones").json()["zones"] if z["name"] == name]


def test_a_duplicate_zone_is_refused(api, test_zone):
    response = api.post("/api/v1/dns/zones", json={"name": test_zone["name"]})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "zone_exists"


# ---------------------------------------------------------------------------
# Round trips — one per record type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("record_type", "data", "display"),
    [
        ("A", {"address": "192.0.2.10"}, "192.0.2.10"),
        ("AAAA", {"address": "2001:db8::1"}, "2001:db8::1"),
        ("CNAME", {"target": "host.example.lan"}, "host.example.lan"),
        ("NS", {"target": "ns1.example.lan"}, "ns1.example.lan"),
        ("PTR", {"target": "host.example.lan"}, "host.example.lan"),
        ("MX", {"preference": 10, "exchange": "mail.example.lan"}, "10 mail.example.lan"),
        (
            "SRV",
            {"priority": 0, "weight": 100, "port": 389, "target": "dc1.example.lan"},
            "0 100 389 dc1.example.lan",
        ),
        ("TXT", {"strings": ["v=spf1 -all"]}, '"v=spf1 -all"'),
    ],
)
def test_a_record_survives_the_round_trip(api, test_zone, record_type, data, display):
    """Written, read back from the directory, and still the same values.

    This is where a wrong dnsp field name shows up: MX carries its preference
    in wPriority, and mixing that up produces a record that packs fine and
    means something else.
    """
    name = f"rt-{record_type.lower()}"
    create(api, test_zone, name=name, type=record_type, data=data, ttl=1200)

    stored = [
        record
        for record in records_of(api, test_zone)
        if record["node"] == name and record["type"] == record_type
    ]
    assert len(stored) == 1, f"expected exactly one {record_type} record"

    record = stored[0]
    assert record["ttl"] == 1200
    assert record["display"] == display
    for key, value in data.items():
        assert record["data"][key] == value


def test_txt_keeps_several_strings(api, test_zone):
    create(api, test_zone, name="multi", type="TXT", data={"strings": ["one", "two"]})
    record = next(r for r in records_of(api, test_zone) if r["node"] == "multi")
    assert record["data"]["strings"] == ["one", "two"]


def test_records_written_here_do_not_age(api, test_zone):
    """A hand-entered record must not be scavenged away."""
    create(api, test_zone, name="static", type="A", data={"address": "192.0.2.20"})
    record = next(r for r in records_of(api, test_zone) if r["node"] == "static")
    assert record["timestamp"] == 0


# ---------------------------------------------------------------------------
# The zone serial
# ---------------------------------------------------------------------------


def soa_serial(api, zone) -> int:
    soa = next(record for record in records_of(api, zone) if record["type"] == "SOA")
    return soa["data"]["serial"]


def test_every_change_advances_the_zone_serial(api, test_zone):
    """That number is how a secondary server notices there is anything to fetch.

    Samba raises it on every write of its own — see dnsserver_update_soa() —
    so a zone edited from here has to move the same way.
    """
    before = soa_serial(api, test_zone)

    create(api, test_zone, name="serial", type="A", data={"address": "192.0.2.110"})
    after_create = soa_serial(api, test_zone)
    assert after_create > before

    api.patch(
        f"/api/v1/dns/records?zone_dn={quoted(test_zone['dn'])}",
        json={
            "zone": test_zone["name"],
            "name": "serial",
            "type": "A",
            "old_data": {"address": "192.0.2.110"},
            "data": {"address": "192.0.2.111"},
        },
    )
    after_update = soa_serial(api, test_zone)
    assert after_update > after_create

    api.request(
        "DELETE",
        f"/api/v1/dns/records?zone_dn={quoted(test_zone['dn'])}",
        json={
            "zone": test_zone["name"],
            "name": "serial",
            "type": "A",
            "data": {"address": "192.0.2.111"},
        },
    )
    assert soa_serial(api, test_zone) > after_update


def test_a_new_record_carries_the_serial_it_was_written_at(api, test_zone):
    """Samba stamps each record with the serial it got from the SOA."""
    create(api, test_zone, name="stamped", type="A", data={"address": "192.0.2.120"})

    records = records_of(api, test_zone)
    written = next(record for record in records if record["node"] == "stamped")
    soa = next(record for record in records if record["type"] == "SOA")
    assert written["serial"] == soa["data"]["serial"]


def test_a_rejected_change_leaves_the_serial_alone(api, test_zone):
    """Nothing changed, so there is nothing for a secondary to fetch."""
    create(api, test_zone, name="untouched", type="A", data={"address": "192.0.2.130"})
    before = soa_serial(api, test_zone)

    duplicate = api.post(
        f"/api/v1/dns/records?zone_dn={quoted(test_zone['dn'])}",
        json={
            "zone": test_zone["name"],
            "name": "untouched",
            "type": "A",
            "data": {"address": "192.0.2.130"},
        },
    )
    assert duplicate.status_code == 409

    stale = api.patch(
        f"/api/v1/dns/records?zone_dn={quoted(test_zone['dn'])}",
        json={
            "zone": test_zone["name"],
            "name": "untouched",
            "type": "A",
            "old_data": {"address": "192.0.2.199"},
            "data": {"address": "192.0.2.131"},
        },
    )
    assert stale.status_code == 404

    assert soa_serial(api, test_zone) == before


def test_a_record_on_the_zone_name_does_not_lose_the_soa(api, test_zone):
    """The apex node holds the SOA and gets written twice for one change.

    Raising the serial rewrites that node, so the record write has to start
    from what is there afterwards — otherwise it puts the old SOA back, or
    drops it.
    """
    create(api, test_zone, name="@", type="A", data={"address": "192.0.2.140"})

    apex = [record for record in records_of(api, test_zone) if record["node"] == "@"]
    types = {record["type"] for record in apex}
    assert types == {"SOA", "NS", "A"}


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------


def test_a_fully_qualified_name_lands_on_the_right_node(api, test_zone):
    """Entering "www.<zone>" must not create a node called that."""
    create(
        api,
        test_zone,
        name=f"www.{test_zone['name']}",
        type="A",
        data={"address": "192.0.2.30"},
    )
    nodes = {record["node"] for record in records_of(api, test_zone)}
    assert "www" in nodes
    assert f"www.{test_zone['name']}" not in nodes


def test_the_zone_itself_can_carry_records(api, test_zone):
    create(api, test_zone, name="@", type="A", data={"address": "192.0.2.40"})
    apex = [r for r in records_of(api, test_zone) if r["node"] == "@" and r["type"] == "A"]
    assert len(apex) == 1
    assert apex[0]["name"] == test_zone["name"]


# ---------------------------------------------------------------------------
# Several records on one name
# ---------------------------------------------------------------------------


def test_one_name_can_hold_several_records(api, test_zone):
    """All records of a name share one directory object."""
    create(api, test_zone, name="multi", type="A", data={"address": "192.0.2.50"})
    create(api, test_zone, name="multi", type="A", data={"address": "192.0.2.51"})
    create(api, test_zone, name="multi", type="TXT", data={"strings": ["hello"]})

    mine = [record for record in records_of(api, test_zone) if record["node"] == "multi"]
    assert len(mine) == 3
    assert {r["type"] for r in mine} == {"A", "TXT"}


def test_deleting_one_record_leaves_the_others(api, test_zone):
    create(api, test_zone, name="pair", type="A", data={"address": "192.0.2.60"})
    create(api, test_zone, name="pair", type="A", data={"address": "192.0.2.61"})

    removed = api.request(
        "DELETE",
        f"/api/v1/dns/records?zone_dn={quoted(test_zone['dn'])}",
        json={
            "zone": test_zone["name"],
            "name": "pair",
            "type": "A",
            "data": {"address": "192.0.2.60"},
        },
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["node_deleted"] is False

    remaining = [r for r in records_of(api, test_zone) if r["node"] == "pair"]
    assert len(remaining) == 1
    assert remaining[0]["data"]["address"] == "192.0.2.61"


def test_the_node_goes_when_its_last_record_does(api, test_zone):
    """An empty node would answer as an existing name with no data."""
    create(api, test_zone, name="solo", type="A", data={"address": "192.0.2.70"})

    removed = api.request(
        "DELETE",
        f"/api/v1/dns/records?zone_dn={quoted(test_zone['dn'])}",
        json={
            "zone": test_zone["name"],
            "name": "solo",
            "type": "A",
            "data": {"address": "192.0.2.70"},
        },
    )
    assert removed.json()["node_deleted"] is True
    assert not [r for r in records_of(api, test_zone) if r["node"] == "solo"]


def test_a_duplicate_record_is_refused(api, test_zone):
    create(api, test_zone, name="dup", type="A", data={"address": "192.0.2.80"})
    response = api.post(
        f"/api/v1/dns/records?zone_dn={quoted(test_zone['dn'])}",
        json={
            "zone": test_zone["name"],
            "name": "dup",
            "type": "A",
            "data": {"address": "192.0.2.80"},
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "record_exists"


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------


def test_a_record_can_be_changed(api, test_zone):
    create(api, test_zone, name="edit", type="A", data={"address": "192.0.2.90"}, ttl=600)

    updated = api.patch(
        f"/api/v1/dns/records?zone_dn={quoted(test_zone['dn'])}",
        json={
            "zone": test_zone["name"],
            "name": "edit",
            "type": "A",
            "old_data": {"address": "192.0.2.90"},
            "data": {"address": "192.0.2.91"},
            "ttl": 300,
        },
    )
    assert updated.status_code == 200, updated.text

    record = next(r for r in records_of(api, test_zone) if r["node"] == "edit")
    assert record["data"]["address"] == "192.0.2.91"
    assert record["ttl"] == 300


def test_editing_a_record_that_changed_meanwhile_is_refused(api, test_zone):
    """Without identifiers, the old values are what finds the record — and
    what proves nobody else moved it."""
    create(api, test_zone, name="stale", type="A", data={"address": "192.0.2.100"})

    response = api.patch(
        f"/api/v1/dns/records?zone_dn={quoted(test_zone['dn'])}",
        json={
            "zone": test_zone["name"],
            "name": "stale",
            "type": "A",
            "old_data": {"address": "192.0.2.199"},
            "data": {"address": "192.0.2.101"},
        },
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "record_not_found"


# ---------------------------------------------------------------------------
# Validation reaches the API
# ---------------------------------------------------------------------------


def test_a_malformed_address_is_rejected_before_writing(api, test_zone):
    response = api.post(
        f"/api/v1/dns/records?zone_dn={quoted(test_zone['dn'])}",
        json={
            "zone": test_zone["name"],
            "name": "bad",
            "type": "A",
            "data": {"address": "192.0.2.999"},
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_ipv4"
    assert not [r for r in records_of(api, test_zone) if r["node"] == "bad"]


def test_soa_cannot_be_created_by_hand(api, test_zone):
    response = api.post(
        f"/api/v1/dns/records?zone_dn={quoted(test_zone['dn'])}",
        json={"zone": test_zone["name"], "name": "@", "type": "SOA", "data": {"serial": 1}},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_record_type"
