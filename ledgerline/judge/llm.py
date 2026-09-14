"""One structured-output call: the transcript in, a three-valued answer per criterion out.

Pure of infra. The model id arrives from the caller rather than from `config`, so this package
imports nothing that knows about the deployment -- and so a literal cannot outlive the setting.
The caller passes `JUDGE_MODEL`.

Nothing here normalises a score. The judge answers questions; turning answers into a number is
arithmetic and lives in `judge.py`, where it can be read, tested and changed without touching a
prompt. A judge prompt asked to output 1 to 5 would put the scale inside the model's head, which
is precisely where it cannot be audited.
"""

from __future__ import annotations

import json
from typing import Any

from ledgerline.judge.criteria import Criterion, applicable
from ledgerline.judge.models import CriterionResult

SYSTEM = (
    "You are reviewing one recorded call between a money coach and a person planning their next "
    "thirty days. Answer each question about the coach's conduct with pass, fail, or "
    "not_applicable, one short reason, and the index of the turn your answer rests on.\n"
    "Answer only the questions you are given. Do not fault a reply for something the question "
    "does not ask of it. If a question cannot be answered from this transcript, say "
    "not_applicable rather than guessing."
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["results"],
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["criterion", "outcome", "reason", "turn"],
                "properties": {
                    "criterion": {"type": "string"},
                    "outcome": {"enum": ["pass", "fail", "not_applicable"]},
                    "reason": {"type": "string"},
                    "turn": {"type": ["integer", "null"]},
                },
            },
        }
    },
}


def transcript(recording: dict, *, with_tools: bool = True) -> str:
    """The conversation as a model reads it: who spoke and what they said.

    The judge needs `with_tools`, because half of what the coach says is something a result told
    it to say and a judge blind to results grades the coach for obedience. The notes extractor
    does not: it reads what the PERSON said, and tool results would give it figures to remember,
    which is the one thing notes may never carry.
    """
    lines = []
    for i, turn in enumerate(recording.get("turns", ())):
        lines.append(f"[{i}] {turn.get('role')}: {turn.get('text', '')}")
        if with_tools:
            for tool_call in turn.get("tool_calls", ()) or ():
                lines.append(f"    tool {tool_call.get('name')} -> {tool_call.get('result', '')}")
    return "\n".join(lines)


def _questions(criteria: list[Criterion]) -> str:
    return "\n".join(f"- {c.id}: {c.question}" for c in criteria)


def ask(
    recording: dict,
    *,
    model: str,
    effort: str = "low",
    client: Any = None,
    criteria: list[Criterion] | None = None,
) -> list[CriterionResult]:
    """Ask the judge model about the criteria that apply to this call.

    Raises on a bad answer or a failed call. `judge.run` is the layer that must never raise;
    keeping this one honest means the caller can tell a failure from a verdict of "nothing wrong".
    """
    asked = criteria if criteria is not None else applicable(recording)
    if not asked:
        return []
    if client is None:  # pragma: no cover - exercised only by the paid test
        from openai import OpenAI

        client = OpenAI()

    response = client.responses.create(
        model=model,
        reasoning={"effort": effort},
        input=[
            {"role": "developer", "content": SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Questions:\n{_questions(asked)}\n\nTranscript:\n{transcript(recording)}"
                ),
            },
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "verdict",
                "strict": True,
                "schema": SCHEMA,
            }
        },
    )
    payload = json.loads(response.output_text)
    wanted = {c.id for c in asked}
    return [CriterionResult(**row) for row in payload["results"] if row.get("criterion") in wanted]
