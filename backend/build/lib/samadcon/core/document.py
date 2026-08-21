"""The whole domain in one document, for reading away from the screen.

The console answers questions one at a time; a report answers the question
nobody asked yet, and it gets printed, filed and handed on. Three things
follow from that, and they are the whole design here.

**One reading.** Every part comes from a single pass, so the timestamp at the
top is true of all of it. Composing the document from the endpoints the
screen uses would have been less code and would have produced a page whose
sections were read minutes apart — which is exactly the kind of quiet
untruth a document gets trusted for.

**Nothing is fetched twice.** The findings and the values they were decided
from come back together from :mod:`samadcon.core.findings_source`, so the
password policy printed in full is the one the rules judged, not a second
look at it.

**A section that could not be read says so.** A report that silently omits
replication because the read failed is worse than no report: it reads as a
clean bill of health. Every part is gathered on its own and its failure is
recorded by name.

What is deliberately *not* here: the settings inside each policy. That is a
per-policy report — GPMC's "save report" — and it is a different document
with a different reader. This one is about the domain.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from samadcon.ad import diagnostics
from samadcon.core import findings_source

logger = logging.getLogger(__name__)


def build(conn: Any, *, deep: bool = False) -> dict[str, Any]:
    """Everything the two reports rest on, in the order it should be read."""
    security = findings_source.collect(conn, "security")
    policies = findings_source.collect(conn, "policies", deep=deep)

    unreadable: list[str] = []
    roles = _section(conn, "roles", diagnostics.fsmo_roles, unreadable) or []
    controllers = _section(conn, "controllers", diagnostics.domain_controllers, unreadable) or []

    return {
        # Second precision, in UTC. A report is read in a timezone nobody can
        # know from here, so the offset is carried rather than assumed.
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "deep": deep,
        "domain": diagnostics.domain_facts(conn),
        "connection": security["connection"],
        "roles": roles,
        "controllers": controllers,
        "security": {
            "policy": security["policy"],
            "replication": security["replication"],
            "findings": security["findings"],
            "unreadable": security["unreadable"] + unreadable,
        },
        "policies": {
            "gpos": _policy_entries(policies),
            "findings": policies["findings"],
            "unreadable": policies["unreadable"],
        },
    }


def _section(conn: Any, name: str, read: Any, unreadable: list[str]) -> Any:
    """One part of the document, whose failure costs only that part."""
    try:
        return read(conn)
    except Exception:  # one section failing must not cost the document
        logger.warning("cannot read %s for the report", name, exc_info=True)
        unreadable.append(name)
        return None


def _policy_entries(collected: dict[str, Any]) -> list[dict[str, Any]]:
    """Each policy with the links pointing at it, and its files where walked.

    The links arrive keyed by GUID from one domain-wide sweep. Joining them
    here rather than in the interface keeps the join in one place: a policy
    listed without its links reads as a policy nobody linked, which is a
    finding in its own right and must not be produced by a rendering mistake.
    """
    links = collected["links"]
    state = collected["status"]

    entries = []
    for gpo in collected["gpos"]:
        guid = (gpo.get("guid") or "").upper()
        entries.append({**gpo, "links": links.get(guid, []), "status": state.get(guid)})
    return entries
