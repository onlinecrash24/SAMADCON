"""What is sent to a model, and what is believed of what comes back.

No network here. The parts worth testing are the request that gets built — a
reader is shown it before deciding to send anything, so it had better be what
is actually sent — and the checks on the reply, which is where a model's
mistakes have to be caught.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from samadcon.core import ollama
from samadcon.core.errors import UpstreamUnavailable

FINDINGS: list[dict[str, Any]] = [
    {
        "id": "password_no_lockout",
        "severity": "medium",
        "area": "password_policy",
        "evidence": {"lockout_threshold": 0},
    },
    {
        "id": "replication_failing",
        "severity": "high",
        "area": "replication",
        "evidence": {"failing": 1},
    },
]


def answer(**overrides: Any) -> str:
    body = {"summary": "s", "order": [], "suggestions": []}
    body.update(overrides)
    return json.dumps(body)


# ---------------------------------------------------------------------------
# What goes out
# ---------------------------------------------------------------------------


def test_the_request_asks_for_the_schema_rather_than_prose():
    """A parser for free text is where a model's mistakes become the tool's."""
    request = ollama.build_request(FINDINGS, model="llama3.1", language="en")

    assert request["format"] == ollama.RESPONSE_SCHEMA
    assert request["stream"] is False


def test_every_field_of_the_schema_is_required():
    """An optional field comes back missing exactly when it mattered."""
    schema = ollama.RESPONSE_SCHEMA
    assert set(schema["required"]) == set(schema["properties"])


def test_the_prompt_carries_the_findings_verbatim():
    prompt = ollama.build_prompt(FINDINGS, "en")

    assert "password_no_lockout" in prompt
    assert '"lockout_threshold": 0' in prompt


def test_the_preview_is_the_payload_and_not_a_description_of_it():
    """The interface shows build_prompt before sending; the request has to use
    the same string, or the preview is a promise nobody keeps."""
    request = ollama.build_request(FINDINGS, model="m", language="de")
    assert request["messages"][1]["content"] == ollama.build_prompt(FINDINGS, "de")


def test_the_answer_is_asked_for_in_the_console_language():
    assert "German" in ollama.build_prompt(FINDINGS, "de")
    assert "English" in ollama.build_prompt(FINDINGS, "en")


def test_an_unknown_language_falls_back_rather_than_failing():
    assert "English" in ollama.build_prompt(FINDINGS, "xx")


def test_the_model_is_told_not_to_invent_findings():
    assert "Never invent a finding" in ollama.SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# What comes back
# ---------------------------------------------------------------------------


def test_a_well_formed_answer_is_passed_through():
    parsed = ollama.parse_answer(
        answer(summary="Two things", order=[{"id": "replication_failing", "reason": "first"}]),
        FINDINGS,
        model="llama3.1",
    )

    assert parsed["summary"] == "Two things"
    assert parsed["order"] == [{"id": "replication_failing", "reason": "first"}]
    assert parsed["model"] == "llama3.1"


def test_an_id_the_findings_do_not_contain_is_dropped():
    """The promise of this half is that it adds no findings of its own. A model
    that names one anyway must not get it onto the screen through the ordering."""
    parsed = ollama.parse_answer(
        answer(
            order=[
                {"id": "replication_failing", "reason": "real"},
                {"id": "smb1_enabled", "reason": "invented"},
            ]
        ),
        FINDINGS,
        model="m",
    )

    assert [item["id"] for item in parsed["order"]] == ["replication_failing"]


def test_suggestions_survive_because_they_are_marked_as_unverified():
    """Unlike the ordering, a suggestion does not claim to be established, so
    there is nothing to check it against — the interface labels it instead."""
    parsed = ollama.parse_answer(
        answer(suggestions=["Check whether SMB1 is still enabled"]), FINDINGS, model="m"
    )
    assert parsed["suggestions"] == ["Check whether SMB1 is still enabled"]


def test_an_empty_reply_is_reported_rather_than_shown_as_an_empty_report():
    """Which is what a model without structured-output support tends to send."""
    with pytest.raises(UpstreamUnavailable) as raised:
        ollama.parse_answer("", FINDINGS, model="m")
    assert raised.value.code == "ollama_empty_response"


def test_prose_is_shown_rather_than_thrown_away():
    """Asking for a schema was about not *parsing* free text; showing it
    infers nothing. Verified against a real instance: a cloud model proxied
    through Ollama ignored the schema and wrote a sound explanation, and
    refusing it helped nobody."""
    parsed = ollama.parse_answer(
        "## Erklärung -- die Sperrschwelle steht auf 0.", FINDINGS, model="glm"
    )

    assert parsed["structured"] is False
    assert "Sperrschwelle" in parsed["summary"]
    assert parsed["order"] == []


def test_json_that_is_not_an_object_is_also_shown_as_text():
    parsed = ollama.parse_answer('["a", "b"]', FINDINGS, model="m")
    assert parsed["structured"] is False


def test_a_schema_answer_is_marked_as_structured():
    parsed = ollama.parse_answer(answer(), FINDINGS, model="m")
    assert parsed["structured"] is True


def test_missing_fields_come_back_empty_rather_than_absent():
    """The interface renders them unconditionally; None would show as 'null'."""
    parsed = ollama.parse_answer("{}", FINDINGS, model="m")
    assert parsed == {
        "summary": "",
        "order": [],
        "suggestions": [],
        "structured": True,
        "model": "m",
    }

def test_the_schema_is_in_the_prompt_as_well_as_the_format_field():
    """Verified against a real instance: a cloud model proxied through Ollama
    produced exactly the requested shape as markdown, which says the
    instruction lands while the format field does not reach it. A model that
    ignores the field can still be asked in words."""
    assert '"summary": string' in ollama.SYSTEM_PROMPT
    assert "single JSON object" in ollama.SYSTEM_PROMPT


def test_the_model_is_told_which_advice_this_tool_rejects():
    """The same run suggested checking password expiry — precisely what the
    findings layer leaves out because NIST withdrew it. The model had no way
    to know, so now it is told."""
    assert "NIST withdrew it" in ollama.SYSTEM_PROMPT


def test_json_inside_a_code_fence_is_unwrapped():
    """Told to answer with JSON and nothing else, models wrap it anyway.
    Taking the fence off is unwrapping, not interpreting: when the whole
    reply is one fenced block, the inside is the reply."""
    fenced = "```json\n" + answer(summary="ok") + "\n```"

    parsed = ollama.parse_answer(fenced, FINDINGS, model="m")

    assert parsed["structured"] is True
    assert parsed["summary"] == "ok"


def test_a_fence_around_prose_is_still_prose():
    fenced = "```\nNot JSON at all.\n```"
    assert ollama.parse_answer(fenced, FINDINGS, model="m")["structured"] is False
