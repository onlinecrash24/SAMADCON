"""The optional model service: what it offers, and what it says about findings.

Kept apart from the diagnostics router on purpose. Everything there is decided
by rules and holds without a network call; everything here depends on a
service someone chose to configure, and may be absent, slow or wrong. Two
different kinds of answer deserve two different places to come from.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from samadcon.ad import diagnostics
from samadcon.ad.access import ad_read
from samadcon.auth.deps import CurrentSession, VerifiedSession, VerifiedWorker, Worker
from samadcon.core import findings, ollama

router = APIRouter(prefix="/assistant", tags=["assistant"])

# A model name, not an address — that distinction is the whole security model
# here. See samadcon.core.ollama.
ModelQuery = Annotated[str, Query(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:/-]+$")]
LanguageQuery = Annotated[str, Query(pattern=r"^[a-z]{2}$")]


@router.get("")
async def describe(session: CurrentSession) -> dict[str, Any]:
    """Whether a model service is configured at all.

    Answered without calling it: the interface needs to know whether to offer
    the feature before anything is reachable.
    """
    return {"configured": ollama.is_configured()}


@router.get("/models")
async def models(session: CurrentSession) -> dict[str, Any]:
    """What the configured instance holds."""
    return {"models": await ollama.list_models()}


@router.get("/payload")
async def payload(
    worker: Worker, session: CurrentSession, language: LanguageQuery = "en"
) -> dict[str, Any]:
    """Exactly what leaves this container if the report is asked for.

    Shown before sending rather than described. Domain configuration going to
    another service is a decision, and it can only be made by someone who can
    see what goes.
    """
    gathered = await _findings(worker, session)
    return {
        "findings": gathered,
        "prompt": ollama.build_prompt(gathered, language),
    }


@router.post("/report")
async def report(
    worker: VerifiedWorker,
    session: VerifiedSession,
    model: ModelQuery,
    language: LanguageQuery = "en",
) -> dict[str, Any]:
    """Ask the model to explain and order the findings.

    The findings are gathered here rather than taken from the request, so what
    is sent is what /diagnostics/findings would return — and the preview above
    is the payload rather than an account of it.
    """
    gathered = await _findings(worker, session)
    answer = await ollama.explain(gathered, model=model, language=language)
    return {"findings": gathered, "answer": answer}


async def _findings(worker: Any, session: Any) -> list[dict[str, Any]]:
    def _run(conn: Any) -> list[dict[str, Any]]:
        found = findings.evaluate(
            policy=diagnostics.password_policy(conn),
            replication=diagnostics.replication(conn),
            connection=conn.transport.describe() if conn.transport else None,
        )
        return [item.describe() for item in found]

    return await ad_read(worker, session, _run, label="assistant.findings")
