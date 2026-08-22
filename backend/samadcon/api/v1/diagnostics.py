"""Domain health: roles, replication, policies, problem accounts.

Read-only throughout — there is no write path in this router, and that is
deliberate. Seizing an FSMO role or forcing replication are operations with
consequences that a web console should not make easy; they belong on the DC,
with `samba-tool fsmo seize` and `samba-tool drs replicate`.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Query

from samadcon.ad import diagnostics
from samadcon.ad.access import ad_read
from samadcon.auth.deps import CurrentSession, Worker
from samadcon.core import document, findings_source

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])

# Which set of rules to run. A name, checked against the two that exist —
# it selects a code path, so anything else is refused rather than defaulted.
AreaQuery = Annotated[str, Query(pattern="^(security|policies)$")]


@router.get("")
async def overview(worker: Worker, session: CurrentSession) -> dict[str, Any]:
    """Everything the diagnosis page shows, in one call."""
    return await ad_read(worker, session, diagnostics.overview, label="diag.overview")


@router.get("/roles")
async def fsmo_roles(worker: Worker, session: CurrentSession) -> dict[str, Any]:
    roles = await ad_read(worker, session, diagnostics.fsmo_roles, label="diag.roles")
    return {"roles": roles}


@router.get("/controllers")
async def domain_controllers(worker: Worker, session: CurrentSession) -> dict[str, Any]:
    found = await ad_read(
        worker, session, diagnostics.domain_controllers, label="diag.controllers"
    )
    return {"controllers": found}


@router.get("/replication")
async def replication(worker: Worker, session: CurrentSession) -> dict[str, Any]:
    """Inbound replication status of the DC this session is connected to."""
    return await ad_read(worker, session, diagnostics.replication, label="diag.replication")


@router.get("/policy")
async def password_policy(worker: Worker, session: CurrentSession) -> dict[str, Any]:
    return await ad_read(worker, session, diagnostics.password_policy, label="diag.policy")


@router.get("/accounts")
async def account_problems(
    worker: Worker,
    session: CurrentSession,
    limit: Annotated[int, Query(ge=1, le=2000)] = 200,
) -> dict[str, Any]:
    """Locked, disabled and expired accounts."""
    return await ad_read(
        worker, session, diagnostics.account_problems, limit=limit, label="diag.accounts"
    )


@router.get("/members")
async def domain_members(
    worker: Worker,
    session: CurrentSession,
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
) -> dict[str, Any]:
    """The computer accounts, and what their trust with the domain permits.

    Not who is connected this second — that lives in smbstatus on the
    controller and never reaches the wire. What the directory holds is the
    harder half of the question anyway: what each machine is able to
    negotiate, and which of them could impersonate a user if it were taken.
    """
    return await ad_read(
        worker, session, diagnostics.domain_members, limit=limit, label="diag.members"
    )


@router.get("/findings")
async def security_findings(
    worker: Worker,
    session: CurrentSession,
    area: AreaQuery = "security",
    deep: Annotated[
        bool, Query(description="Walk each policy's files on SYSVOL as well")
    ] = False,
) -> dict[str, Any]:
    """What is worth telling an administrator about this domain.

    The binding half of both reports: rules over values the tool already
    reads, each finding carrying what it was decided from. Nothing is asked
    of a language model here — see :mod:`samadcon.core.findings`.

    `deep` only means anything for the policies: it adds a walk of each
    policy's files, which is what finds settings no registered extension
    will ever apply, and costs one round trip per policy.
    """

    def _run(conn: Any) -> dict[str, Any]:
        # One collection for both: asking separately what was found and
        # what could not be read used to read the same two sections twice.
        collected = findings_source.collect(conn, area, deep=deep)
        return {
            "findings": collected["findings"],
            "unreadable": collected["unreadable"],
        }

    return await ad_read(worker, session, _run, label="diag.findings")


@router.get("/report")
async def domain_report(
    worker: Worker,
    session: CurrentSession,
    deep: Annotated[
        bool, Query(description="Walk each policy's files on SYSVOL as well")
    ] = False,
) -> dict[str, Any]:
    """Both reports in full, as one reading, for printing.

    The screen shows findings; this adds the values they were decided
    from — the password policy in full, replication, every policy in the
    domain with its links. Gathered in one pass so the timestamp at the
    top is true of all of it.
    """

    def _run(conn: Any) -> dict[str, Any]:
        return document.build(conn, deep=deep)

    return await ad_read(worker, session, _run, label="diag.report")
