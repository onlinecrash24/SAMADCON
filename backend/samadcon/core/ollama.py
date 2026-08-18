"""Asking a locally run model to explain the findings.

The *unbinding* half of the security report. Everything a reader must be able
to rely on comes from :mod:`samadcon.core.findings`; this adds wording,
ordering and — clearly marked as such — hints nobody verified.

Three decisions shape it.

**Off unless configured.** Without ``SAMADCON_OLLAMA_URL`` nothing here runs
and nothing is sent anywhere. A domain management console that quietly talks
to a third party would be a poor trade for nicer prose.

**The address comes from the deployment, never from a request.** The container
makes the call, so a URL taken from the interface would let any signed-in
account — including a delegated one with few rights — use SAMADCON as an HTTP
client against addresses their own browser cannot reach. The model *name*
comes from the interface, because a name is not an address.

**The findings are gathered here, not accepted from the caller.** What gets
sent is exactly what ``/diagnostics/findings`` returns, so the preview the
interface shows before sending is the payload and not a description of it.

The model is asked for structured output through Ollama's ``format`` field,
which takes a JSON schema. Prose would have to be parsed back, and a parser
for free text is a place for a model's mistakes to become the tool's.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from samadcon.config import get_settings
from samadcon.core.errors import SamadconError, UpstreamUnavailable

logger = logging.getLogger(__name__)

# What the model is asked to return. Every field is required: an optional one
# comes back missing exactly when it would have been most useful.
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "order": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["id", "reason"],
            },
        },
        "suggestions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "order", "suggestions"],
}

SYSTEM_PROMPT = (
    "You are helping an administrator read a security report about a Samba "
    "Active Directory domain.\n"
    "\n"
    "The findings you are given were produced by fixed rules over values read "
    "from the domain. They are established. Your job is to explain them in "
    "plain language, put them in a sensible order to work through, and say "
    "why that order.\n"
    "\n"
    "Rules you must follow:\n"
    "- Never contradict a finding, and never restate one as more or less "
    "severe than it is given.\n"
    "- Never invent a finding. If you think something else is worth checking, "
    "put it in `suggestions`, phrased as something to check rather than "
    "something that is true.\n"
    "- `order` may only contain ids that appear in the findings.\n"
    "- If the findings are empty, say so plainly and leave `order` empty. Do "
    "not manufacture concerns to fill the space.\n"
    "\n"
    "Two things this tool leaves out on purpose. Do not suggest them:\n"
    "- Forcing passwords to expire. That was standard advice for decades and "
    "NIST withdrew it, because scheduled changes push people towards "
    "predictable variations of one password.\n"
    "- Listing locked, disabled or expired accounts. The console shows those "
    "elsewhere, and repeating them buries the findings that need a decision.\n"
    "\n"
    "Answer with a single JSON object and nothing else: no explanation "
    "around it, no code fence. Its shape:\n"
    '{"summary": string, "order": [{"id": string, "reason": string}], '
    '"suggestions": [string]}\n'
    "\n"
    "Answer in the language named below."
)


def is_configured() -> bool:
    return bool(get_settings().ollama_url)


def _base_url() -> str:
    url = (get_settings().ollama_url or "").strip().rstrip("/")
    if not url:
        raise SamadconError(
            "No model service is configured.",
            code="ollama_not_configured",
            hint="Set SAMADCON_OLLAMA_URL to reach an Ollama instance.",
        )
    return url


def build_prompt(findings: list[dict[str, Any]], language: str) -> str:
    """What the model is shown, as a string the interface can display verbatim.

    Built here rather than in the router so the preview and the request cannot
    drift apart: they call this.
    """
    spoken = {"de": "German", "en": "English"}.get(language, "English")
    return "\n".join(
        [
            f"Answer in {spoken}.",
            "",
            "Findings:",
            json.dumps(findings, indent=2, ensure_ascii=False),
        ]
    )


def build_request(findings: list[dict[str, Any]], *, model: str, language: str) -> dict[str, Any]:
    """The body of the chat call. Pure, so it can be tested without a network."""
    return {
        "model": model,
        "stream": False,
        "format": RESPONSE_SCHEMA,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_prompt(findings, language)},
        ],
    }


async def list_models() -> list[dict[str, Any]]:
    """The models the configured instance holds."""
    payload = await _get("/api/tags")
    models = payload.get("models")
    if not isinstance(models, list):
        return []
    return [
        {"name": item.get("name", ""), "size": item.get("size"), "family": _family(item)}
        for item in models
        if isinstance(item, dict) and item.get("name")
    ]


def _family(item: dict[str, Any]) -> str | None:
    details = item.get("details")
    return details.get("family") if isinstance(details, dict) else None


async def explain(
    findings: list[dict[str, Any]], *, model: str, language: str
) -> dict[str, Any]:
    """Ask the model to explain and order the findings."""
    body = await _post("/api/chat", build_request(findings, model=model, language=language))
    content = ((body.get("message") or {}).get("content") or "").strip()
    return parse_answer(content, findings, model=model)


def parse_answer(content: str, findings: list[dict[str, Any]], *, model: str) -> dict[str, Any]:
    """The model's reply, checked against what it was allowed to say.

    Separate from the call so the part that catches a model's mistakes can be
    tested without a network — which is where those mistakes will actually be
    caught.

    A model that ignores the schema and writes prose is **not** refused. The
    reason for asking for a schema was that parsing free text back into
    structure is where a model's mistakes become the tool's — and that is an
    argument against *interpreting* prose, not against *showing* it. Verified
    on a real instance: a cloud model proxied through Ollama produced a sound
    explanation in plain text, and throwing it away helped nobody. It comes
    back with ``structured`` false, goes into the same unverified frame, and
    nothing is inferred from it.
    """
    if not content:
        raise UpstreamUnavailable(
            "The model returned nothing.",
            code="ollama_empty_response",
            hint="Check that the model is loaded and answering.",
        )

    try:
        answer = json.loads(_unfenced(content))
    except ValueError:
        return _unstructured(content, model)

    if not isinstance(answer, dict):
        return _unstructured(content, model)

    known = {finding.get("id") for finding in findings}
    order = [
        item
        for item in (answer.get("order") or [])
        # An id the findings do not contain is the model inventing one. Dropped
        # rather than shown: the whole promise of this half is that it adds no
        # findings of its own.
        if isinstance(item, dict) and item.get("id") in known
    ]

    return {
        "summary": str(answer.get("summary") or ""),
        "order": order,
        "suggestions": [str(item) for item in (answer.get("suggestions") or [])],
        "structured": True,
        "model": model,
    }


def _unfenced(content: str) -> str:
    """The reply with a surrounding code fence taken off.

    Not interpretation: when the whole reply is one fenced block, the inside
    is the reply. Models told to answer with JSON and nothing else wrap it
    anyway, and refusing over the wrapper would be pedantry.
    """
    text = content.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if len(lines) < 3 or not lines[-1].strip().startswith("```"):
        return text
    return "\n".join(lines[1:-1]).strip()


def _unstructured(content: str, model: str) -> dict[str, Any]:
    """What is left when the schema was ignored: the text, and nothing read
    out of it. The interface says which of the two it is showing."""
    return {
        "summary": content,
        "order": [],
        "suggestions": [],
        "structured": False,
        "model": model,
    }


async def _get(path: str) -> dict[str, Any]:
    return await _call("GET", path, None)


async def _post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    return await _call("POST", path, body)


async def _call(method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
    import httpx

    settings = get_settings()
    url = f"{_base_url()}{path}"
    try:
        async with httpx.AsyncClient(timeout=settings.ollama_timeout_seconds) as client:
            response = await client.request(method, url, json=body)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        raise UpstreamUnavailable(
            "The model service refused the request.",
            code="ollama_error",
            detail=f"{exc.response.status_code}: {exc.response.text[:300]}",
        ) from exc
    except httpx.HTTPError as exc:
        logger.info("ollama call to %s failed", url, exc_info=True)
        raise UpstreamUnavailable(
            "The model service cannot be reached.",
            code="ollama_unreachable",
            hint="Check SAMADCON_OLLAMA_URL and that the container can reach it.",
            context={"url": _base_url()},
        ) from exc
