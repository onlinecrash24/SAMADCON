"""DNS zones and records."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from samadcon.ad import dns, dnsrecords
from samadcon.ad.access import ad_read, ad_write
from samadcon.api.common import Audit
from samadcon.auth.deps import CurrentSession, VerifiedSession, VerifiedWorker, Worker
from samadcon.schemas.requests import (
    CreateDnsRecordRequest,
    CreateDnsZoneRequest,
    DeleteDnsRecordRequest,
    UpdateDnsRecordRequest,
)

router = APIRouter(prefix="/dns", tags=["dns"])

ZoneDn = Annotated[str, Query(min_length=3, description="Distinguished name of the zone")]


@router.get("/zones")
async def list_zones(
    worker: Worker,
    session: CurrentSession,
    include_system: Annotated[
        bool, Query(description="Include zones the directory maintains itself")
    ] = False,
) -> dict[str, Any]:
    """Every zone, across the domain, forest and legacy partitions."""
    zones = await ad_read(
        worker, session, dns.list_zones, include_system=include_system, label="dns.zones"
    )
    return {"zones": zones}


@router.get("/records")
async def list_records(
    worker: Worker,
    session: CurrentSession,
    zone_dn: ZoneDn,
    zone: Annotated[
        str | None, Query(description="Zone name; derived from the DN if absent")
    ] = None,
    include_tombstones: Annotated[
        bool, Query(description="Include records marked for removal")
    ] = False,
) -> dict[str, Any]:
    """All records of a zone, one entry per record rather than per name."""
    return await ad_read(
        worker,
        session,
        dns.list_records,
        zone_dn,
        zone_name=zone,
        include_tombstones=include_tombstones,
        label="dns.records",
    )


@router.get("/record-types")
def record_types() -> dict[str, Any]:
    """Which record types can be created, and what each one needs.

    Lets the form be built from the same definition the validation uses,
    instead of a second copy in the front end.
    """
    return {
        "types": [
            {"type": "A", "fields": ["address"]},
            {"type": "AAAA", "fields": ["address"]},
            {"type": "CNAME", "fields": ["target"]},
            {"type": "NS", "fields": ["target"]},
            {"type": "PTR", "fields": ["target"]},
            {"type": "MX", "fields": ["preference", "exchange"]},
            {"type": "SRV", "fields": ["priority", "weight", "port", "target"]},
            {"type": "TXT", "fields": ["strings"]},
        ],
        "default_ttl": dnsrecords.DEFAULT_TTL,
    }


@router.post("/records")
async def create_record(
    payload: CreateDnsRecordRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    zone_dn: ZoneDn,
) -> dict[str, Any]:
    with audit.operation("dns.create_record", target=zone_dn) as record:
        created = await ad_write(
            worker,
            session,
            dns.create_record,
            zone_dn,
            zone_name=payload.zone,
            name=payload.name,
            record_type=payload.type,
            data=payload.data,
            ttl=payload.ttl,
            label="dns.create_record",
        )
        record["target"] = created["dn"]
        record["changes"] = {
            "dnsRecord": {"new": f"{created['name']} {created['type']} {created['display']}"}
        }
    return created


@router.patch("/records")
async def update_record(
    payload: UpdateDnsRecordRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    zone_dn: ZoneDn,
) -> dict[str, Any]:
    """Replace one record, identified by the values it currently has.

    A node holds several records and the directory gives them no identifiers,
    so the old values are how the right one is found. If it no longer looks
    that way, someone else changed it and the request is refused rather than
    guessed at.
    """
    with audit.operation("dns.update_record", target=zone_dn) as record:
        updated = await ad_write(
            worker,
            session,
            dns.update_record,
            zone_dn,
            zone_name=payload.zone,
            name=payload.name,
            record_type=payload.type,
            old_data=payload.old_data,
            data=payload.data,
            ttl=payload.ttl,
            label="dns.update_record",
        )
        record["target"] = updated["dn"]
        record["changes"] = {
            "dnsRecord": {
                "old": dnsrecords.format_data(payload.type, payload.old_data),
                "new": updated["display"],
            }
        }
    return updated


@router.delete("/records")
async def delete_record(
    payload: DeleteDnsRecordRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    zone_dn: ZoneDn,
) -> dict[str, Any]:
    with audit.operation("dns.delete_record", target=zone_dn) as record:
        result = await ad_write(
            worker,
            session,
            dns.delete_record,
            zone_dn,
            zone_name=payload.zone,
            name=payload.name,
            record_type=payload.type,
            data=payload.data,
            label="dns.delete_record",
        )
        record["changes"] = {
            "dnsRecord": {
                "removed": f"{result['name']} {result['type']} "
                f"{dnsrecords.format_data(payload.type, payload.data)}"
            }
        }
    return result


@router.post("/zones")
async def create_zone(
    payload: CreateDnsZoneRequest,
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
) -> dict[str, Any]:
    """Create a zone together with the SOA and NS records it needs."""
    with audit.operation("dns.create_zone", target=payload.name) as record:
        created = await ad_write(
            worker,
            session,
            dns.create_zone,
            payload.name,
            partition=payload.partition,
            label="dns.create_zone",
        )
        record["target"] = created["dn"]
        record["changes"] = {"zone": {"new": created["name"]}}
    return created


@router.delete("/zones")
async def delete_zone(
    worker: VerifiedWorker,
    session: VerifiedSession,
    audit: Audit,
    zone_dn: ZoneDn,
) -> dict[str, Any]:
    """Delete a zone and every record in it."""
    with audit.operation("dns.delete_zone", target=zone_dn):
        await ad_write(worker, session, dns.delete_zone, zone_dn, label="dns.delete_zone")
    return {"dn": zone_dn, "deleted": True}
