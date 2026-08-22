"""Fetching what the rules judge.

:mod:`samadcon.core.findings` is a pure function over data; this is the part
that goes and gets it. Kept apart so a rule never does a round trip, and
shared between the callers so that what a model is shown, what the screen
shows and what a document prints are one reading. Separate gatherers would
drift, and the drift would be invisible: the preview would faithfully
describe a payload nobody sent, and a report would carry a timestamp
belonging to none of its parts.

For that reason a collection hands back the values as well as the findings.
Whoever wants to print the password policy in full must not fetch it again —
two reads are two moments, and a document that says "read at 14:02" would be
describing neither.

The two areas differ more in the fetching than in the rules. Security reads
three things about the domain. Policies read every policy, one sweep for every
link in it, and — only when asked — a walk of each policy's files on SYSVOL.
That last part is why `deep` is a switch rather than the default: it is one
walk per policy, and a report that takes a minute to say "nothing is wrong"
is a report that gets run once.
"""

from __future__ import annotations

import logging
from typing import Any

from samadcon.ad import diagnostics
from samadcon.core import findings
from samadcon.gpo import container, gpmc, report

logger = logging.getLogger(__name__)

AREAS = ("security", "policies")


def collect(conn: Any, area: str, *, deep: bool = False) -> dict[str, Any]:
    """One read of an area: its findings, what could not be read, and the values.

    `unreadable` names sections nobody could read, kept apart from the
    findings on purpose: "we did not look" is not a finding about the domain,
    and a section that yielded nothing is not the same as one with nothing
    in it.
    """
    if area == "policies":
        return _policies(conn, deep=deep)
    return _security(conn)


def gather(conn: Any, area: str, *, deep: bool = False) -> list[dict[str, Any]]:
    """Only the findings, for a caller with no use for the rest."""
    return collect(conn, area, deep=deep)["findings"]


def _security(conn: Any) -> dict[str, Any]:
    gathered: dict[str, Any] = {}
    unreadable: list[str] = []

    for name, read in (
        ("policy", diagnostics.password_policy),
        ("replication", diagnostics.replication),
        # The computer accounts, for what their trust with the domain
        # permits — unconstrained delegation and broken ciphers. One more
        # search, and it answers a question nothing else here does.
        ("members", diagnostics.domain_members),
    ):
        try:
            gathered[name] = read(conn)
        except Exception:  # one section failing must not cost the report
            logger.warning("cannot read %s for the findings", name, exc_info=True)
            unreadable.append(name)

    connection = conn.transport.describe() if conn.transport else None
    evaluated = findings.evaluate(
        policy=gathered.get("policy"),
        replication=gathered.get("replication"),
        connection=connection,
        members=gathered.get("members"),
    )

    return {
        "findings": [item.describe() for item in evaluated],
        "unreadable": unreadable,
        "policy": gathered.get("policy"),
        "replication": gathered.get("replication"),
        "connection": connection,
        "members": gathered.get("members"),
    }


def _policies(conn: Any, *, deep: bool) -> dict[str, Any]:
    gpos = container.list_gpos(conn)
    # One sweep for the whole domain. find_links is two searches per policy,
    # which is right on a policy's own page and forty searches here.
    links = gpmc.link_map(conn)

    problems: dict[str, list[str]] | None = None
    state: dict[str, dict[str, Any]] = {}
    unreadable: list[str] = []

    if deep:
        problems = {}
        for gpo in gpos:
            guid = (gpo.get("guid") or "").upper()
            try:
                found, inspected = _inspect(conn, gpo)
            except Exception:  # one policy failing must not cost the report
                # Its deep findings are missing; its shallow ones still stand,
                # which beats losing the report over one unreadable policy.
                logger.warning("cannot inspect %s on SYSVOL", guid, exc_info=True)
                unreadable.append(gpo.get("display_name") or guid)
                continue
            state[guid] = inspected
            if found:
                problems[guid] = found

    evaluated = findings.evaluate_policies(gpos, links=links, deep=problems)

    return {
        "findings": [item.describe() for item in evaluated],
        "unreadable": unreadable,
        "gpos": gpos,
        "links": links,
        "status": state,
    }


def _inspect(conn: Any, gpo: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    """What only the files can answer, for one policy."""
    inspected = container.status(conn, gpo)
    found = [name for name in inspected["problems"] if name == "version_mismatch"]
    if inspected["sysvol_present"]:
        found += report.registration_problems(gpo, report.build_report(conn, gpo["dn"]))
    return found, inspected
