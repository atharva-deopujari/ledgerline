"""Text-only conversation harness: a plain OpenAI loop over the real tool handlers.

No Pipecat pipeline, no audio. The point is that the prompt, the tool schemas and the handler
bodies are exactly the ones the bot runs, so a behaviour caught here is a real behaviour.
Pipecat is imported only to derive the tool schemas, which is the same derivation the bot uses.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from opentelemetry import trace

from evals.sim_user import SimUser
from ledgerline.agent import prompt as prompt_mod
from ledgerline.agent.tools import ToolContext, build_tools
from ledgerline.domain import state as state_ops
from ledgerline.domain.models import DebtKind, FinancialState, ItemKind
from ledgerline.observability.attributes import Attr

MODEL = "gpt-5.6-luna"
TODAY = dt.date(2026, 9, 11)
MAX_TOOL_ROUNDS = 4
RUNS_DIR = Path(__file__).parent / "runs"
SCENARIOS_DIR = Path(__file__).parent / "scenarios"

# The global tracer: a no-op until `observability.tracing.setup` has run, which is exactly what a
# run without keys should do. Module-level so a test can swap it for one with an exporter.
_tracer = trace.get_tracer("ledgerline.evals")


def run_span(scenario: str, run_id: str | None):
    """One span per simulation run, so a matrix cell reads as a session in Langfuse.

    `langfuse.environment=simulation` is what keeps these out of the numbers a real call is judged
    by; the session id is the matrix run so five runs of five scenarios group as one exercise.
    """
    return _tracer.start_as_current_span(
        "simulation",
        attributes={
            Attr.TRACE_NAME: scenario,
            Attr.SESSION_ID: run_id or scenario,
            Attr.ENVIRONMENT: "simulation",
        },
    )


# The model leads: the prompt says what the call is for, and telling it here to greet and ask one
# question was the first line of the form the redesign set out to stop being.
OPENING = "The call just connected."


def load_scenario(name_or_path: str | Path) -> dict:
    path = Path(name_or_path)
    if not path.is_file():
        path = SCENARIOS_DIR / f"{name_or_path}.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def to_openai_tools(handlers) -> list[dict]:
    """Pipecat derives each schema from the handler's signature and docstring; we reshape it
    into a Responses API function tool so there is one source of truth for both."""
    from pipecat.adapters.schemas.direct_function import DirectFunctionWrapper

    tools = []
    for fn in handlers:
        schema = DirectFunctionWrapper(fn).to_function_schema()
        tools.append(
            {
                "type": "function",
                "name": schema.name,
                "description": schema.description,
                "parameters": {
                    "type": "object",
                    "properties": schema.properties,
                    "required": schema.required,
                    "additionalProperties": False,
                },
            }
        )
    return tools


class _CapturingParams:
    """Stands in for pipecat's FunctionCallParams: handlers only use result_callback."""

    def __init__(self) -> None:
        self.result: str | None = None

    async def result_callback(self, result) -> None:
        self.result = result if isinstance(result, str) else json.dumps(result)


GOODBYE_GRACE_TURNS = 2


def _utterances(said: str | list[str]) -> list[str]:
    """One turn of speech as the messages the model actually receives.

    Voice does not wait for a full sentence: VAD cuts on every pause, so "I have" / "20,000 in
    cash and" / "20,000 in bank balance." reached the model as three consecutive user messages
    with no reply between them. A scripted `say` may therefore be a list, and each element is its
    own user turn; the assistant answers once, after the last of them.
    """
    return [said] if isinstance(said, str) else list(said)


def _seed_carried(state: FinancialState, scenario: dict) -> list[tuple[str, str]]:
    """Hydrate a returning caller, the way C's session will from the store.

    The scenario's `carried` block is what the person told us on a previous call: each entry is
    an item plus the words the coach should read back. The items go into the state with
    `carried=True`, so the domain carries them into the plan exactly as it will in production, and
    the pairs go to the greeting's turn block. A scenario with no `carried` block is a
    first-time caller and nothing here runs.
    """
    pairs: list[tuple[str, str]] = []
    for entry in scenario.get("carried") or []:
        fields: dict = {"amount": Decimal(str(entry["amount"]))}
        if entry.get("day"):
            fields["day_of_month"] = int(entry["day"])
        if entry.get("debt_kind"):
            fields["debt_kind"] = DebtKind(entry["debt_kind"])
        state_ops.upsert(state, ItemKind(entry["kind"]), entry["name"], **fields)
        pairs.append((entry["name"], entry["spoken"]))
    # `upsert` clears `carried`, which is the point of the flag in a live call: a figure the
    # person restates is confirmed. Seeding is the one place that has to set it afterwards.
    for item in _all_items(state):
        item.carried = True
    return pairs


def _all_items(state: FinancialState):
    return [*state.incomes, *state.debts, *state.essentials, *state.optionals]


def _call_is_over(state: FinancialState) -> bool:
    """Only `end_call` ends a call. Agreement is not the end: the model still owes a goodbye,
    and stopping the loop the moment understanding is recorded makes `end_call` unreachable —
    which is exactly what the first run with this tool did."""
    return state.call_ended


def _ready_to_end(state: FinancialState) -> bool:
    """The person has agreed with the plan. From here the model should say goodbye and call
    `end_call`; `GOODBYE_GRACE_TURNS` is how long the harness waits before giving up on it."""
    return state.understood


def _advance_turn(state: FinancialState) -> None:
    """What the voice session does between turns. Counting the turn is all of it since the cut:
    nothing in the domain ages a figure any more, so nothing else happens between utterances."""
    state.turn += 1


async def _respond(client, **kwargs):
    return await asyncio.to_thread(lambda: client.responses.create(**kwargs))


async def run_scenario(
    scenario: dict | str | Path,
    *,
    model: str = MODEL,
    today: dt.date = TODAY,
    prompt_version: str = "v2",
    save: bool = True,
    run_id: str | None = None,
) -> dict:
    """Run one scenario end to end and return the transcript."""
    from dotenv import load_dotenv
    from openai import OpenAI

    if not isinstance(scenario, dict):
        scenario = load_scenario(scenario)

    name = scenario.get("name", "unnamed")
    load_dotenv(Path.cwd() / ".env")
    with run_span(name, run_id):
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        state = FinancialState(today=today)
        carried = _seed_carried(state, scenario)
        cards: list[int] = []

        async def push_cards(message) -> None:
            cards.append(message.v)

        ctx = ToolContext(state, push_cards)
        handlers = {fn.__name__: fn for fn in build_tools(ctx)}
        tools = to_openai_tools(handlers.values())
        sim = SimUser(scenario, client=client, model=model)

        items: list[dict[str, Any]] = [{"role": "developer", "content": OPENING}]
        turns: list[dict] = []
        usage = {"input_tokens": 0, "output_tokens": 0}
        max_turns = int(scenario.get("max_turns", 14))
        agreed_at: int | None = None

        for turn_no in range(1, max_turns + 1):
            # Only the greeting carries the figures in its block: the first tool result carries
            # them after that, and a line repeated every turn reads as an instruction to keep
            # re-reading it.
            greeting = carried if turn_no == 1 else None
            text, calls = await _agent_turn(
                client, model, state, prompt_version, items, tools, handlers, usage, greeting
            )
            turns.append({"role": "assistant", "text": text, "tool_calls": calls})

            said = await sim.reply(text, turn_no, plan_final=state.plan_final, usage=usage)
            if said is None:
                break
            for utterance in _utterances(said):
                turns.append({"role": "user", "text": utterance})
                items.append({"role": "user", "content": utterance})
            _advance_turn(state)
            if _call_is_over(state):
                break
            if _ready_to_end(state):
                agreed_at = agreed_at or turn_no
                if turn_no - agreed_at >= GOODBYE_GRACE_TURNS:
                    break  # agreed, but the model never said goodbye

        transcript = {
            "scenario": scenario.get("name", "unnamed"),
            "prompt_version": prompt_version,
            "model": model,
            "today": today.isoformat(),
            "turns": turns,
            "state": json.loads(state.model_dump_json()),
            # What the person actually had, so `state_matches_facts` can compare the plan's inputs
            # against the truth without going back to the scenario file. A transcript that carries
            # its own answer key stays checkable after the scenario is edited.
            "hidden_facts": (scenario.get("persona") or {}).get("hidden_facts") or {},
            # What was hydrated from the previous call. A source for the number rules, and the only
            # record of it: the figures reach the model through the greeting block, not a result.
            "carried": [list(pair) for pair in carried],
            "plan_final": state.plan_final,
            "call_ended": state.call_ended,
            "cards_versions": cards,
            "usage": usage,
        }
        if save:
            RUNS_DIR.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            path = RUNS_DIR / f"{transcript['scenario']}-{stamp}.json"
            # Five copies of a scenario run concurrently, so two can finish inside the same
            # second and the second silently overwrote the first -- which lost the transcript
            # of a failing run in the first post-cut matrix, the one whose evidence was wanted.
            suffix = 1
            while path.exists():
                suffix += 1
                path = RUNS_DIR / f"{transcript['scenario']}-{stamp}-{suffix}.json"
            path.write_text(json.dumps(transcript, indent=1), encoding="utf-8")
            transcript["path"] = str(path)
        return transcript


async def _agent_turn(
    client, model, state, prompt_version, items, tools, handlers, usage, greeting=None
):
    """One assistant turn: call the model, run whatever tools it asks for, return its text."""
    calls: list[dict] = []
    text_parts: list[str] = []

    for _ in range(MAX_TOOL_ROUNDS):
        response = await _respond(
            client,
            model=model,
            instructions=prompt_mod.system_instruction(state, prompt_version, carried=greeting),
            input=items,
            tools=tools,
            reasoning={"effort": "none"},
            parallel_tool_calls=True,
            store=False,
        )
        _add_usage(usage, response)
        pending = [item for item in response.output if item.type == "function_call"]
        if response.output_text:
            text_parts.append(response.output_text)
        items.extend(item.model_dump() for item in response.output)
        if not pending:
            break
        for item in pending:
            calls.append(await _run_tool(handlers, item, items))

    return " ".join(text_parts).strip(), calls


async def _run_tool(handlers, item, items) -> dict:
    args = json.loads(item.arguments or "{}")
    params = _CapturingParams()
    handler = handlers.get(item.name)
    if handler is None:
        params.result = f"There is no tool called {item.name}."
    else:
        await handler(params, **args)
    items.append(
        {"type": "function_call_output", "call_id": item.call_id, "output": params.result or ""}
    )
    return {"name": item.name, "args": args, "result": params.result or ""}


def _add_usage(usage: dict, response) -> None:
    if getattr(response, "usage", None):
        usage["input_tokens"] += response.usage.input_tokens or 0
        usage["output_tokens"] += response.usage.output_tokens or 0


if __name__ == "__main__":  # pragma: no cover - manual runs
    import sys

    from ledgerline.judge.checks.checks import run_checks

    name = sys.argv[1] if len(sys.argv) > 1 else "timing_emi_before_salary"
    result = asyncio.run(run_scenario(name))
    print(json.dumps(result["usage"]), result.get("path"))
    for violation in run_checks(result):
        print(violation)
