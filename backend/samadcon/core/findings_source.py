"""Fetching what the rules judge.

:mod:`samadcon.core.findings` is a pure function over data; this is the part
that goes and gets it. Kept apart so a rule never does a round trip, and
shared between the two callers so that what a model is shown is what the
screen shows. Two gathering functions would drift, and the drift would be
invisible: the preview would faithfully describe a payload nobody sent.

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


def gather(conn: Any, area: str, *, deep: bool = False) -> list[dict[str, Any]]:
    """The findings of one area, ready for the interface or for a model."""
    if area == "policies":
        return [item.describe() for item in _policies(conn, deep=deep)]
    return [item.describe() for item in _security(conn)]


def unreadable(conn: Any, area: str) -> list[str]:
    """Sections that could not be read, so the caller can say so.

    A section nobody could read has no findings, and that is not the same as
    having none. Reported separately rather than folded into the findings,
    because "we did not look" is not a finding about the domain.
    """
    if area == "policies":
        return []
    missing = []
    for name, read in (
        ("policy", diagnostics.password_policy),
        ("replication", diagnostics.replication),
    ):
        try:
            read(conn)
        except Exception:  # noqa: BLE001 — one section, not the report
            missing.append(name)
    return missing


def _security(conn: Any) -> list[findings.Finding]:
    gathered: dict[str, Any] = {}
    for name, read in (
        ("policy", diagnostics.password_policy),
        ("replication", diagnostics.replication),
    ):
        try:
            gathered[name] = read(conn)
        except Exception:
            logger.warning("cannot read %s for the findings", name, exc_info=True)

    return findings.evaluate(
        policy=gathered.get("policy"),
        replication=gathered.get("replication"),
        connection=conn.transport.describe() if conn.transport else None,
    )


def _policies(conn: Any, *, deep: bool) -> list[findings.Finding]:
    gpos = container.list_gpos(conn)
    # One sweep for the whole domain. find_links is two searches per policy,
    # which is right on a policy's own page and forty searches here.
    links = gpmc.link_map(conn)

    problems: dict[str, list[str]] | None = None
    if deep:
        problems = {}
        for gpo in gpos:
            guid = (gpo.get("guid") or "").upper()
            try:
                found = _deep_problems(conn, gpo)
            except Exception:
                # Its deep findings are missing; its shallow ones still stand,
                # which beats losing the report over one unreadable policy.
                logger.warning("cannot inspect %s on SYSVOL", guid, exc_info=True)
                continue
            if found:
                problems[guid] = found

    return findings.evaluate_policies(gpos, links=links, deep=problems)


def _deep_problems(conn: Any, gpo: dict[str, Any]) -> list[str]:
    """What only the files can answer, for one policy."""
    status = container.status(conn, gpo)
    found = [name for name in status["problems"] if name == "version_mismatch"]
    if status["sysvol_present"]:
        found += report.registration_problems(gpo, report.build_report(conn, gpo["dn"]))
    return found
