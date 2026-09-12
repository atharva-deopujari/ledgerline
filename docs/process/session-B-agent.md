# Session B · agent (tools, prompt, text harness)

Read `docs/process/00-orchestration.md` first. You own `ledgerline/agent/tools.py`, `prompt.py`,
`prompts/*.md`, `tests/agent/**`, and `evals/**`. You read `ledgerline/domain/**` but never edit it.

Research to read: `docs/research/10-state-and-tools.md` (all), `docs/research/05-llm-openai.md` sections 4 to 6,
`docs/research/11-testing-evals.md` sections 1 to 5, `docs/architecture/02-hld.md` sections 4, 7, 9.

Session A is implementing `ledgerline/domain/state.py`, `engine.py`, `cards.py` in parallel. Until they land,
their functions raise `NotImplementedError`. **Test your handlers against fakes**, not the real domain:
`tests/agent/conftest.py` monkeypatches `ledgerline.domain.state.upsert` and friends with simple recording
fakes, and `ledgerline.domain.engine.build_plan` with a stub that returns a canned `PlanResult`. Your tests must
stay green whether or not Session A is finished.

`ledgerline.agent` must not import `pipecat` at module level (import-linter enforces it). The only Pipecat type
you need is `FunctionCallParams` for handler signatures. Import it inside `build_tools()` and type the parameter
as `Any` at module level, or use `TYPE_CHECKING`.

## 1. Prompt (`prompts/v1.md`, `prompt.py`)
Write `prompts/v1.md` from research 10 section 7 and HLD section 7. Sections: role and English only; hard rules
(no invented numbers, no approval promises, no settlement offers, no new loans, never claim an action is done);
numbers rule (speak only figures from tool results, repeat a newly recorded figure once, say "rupees" never a
symbol); spoken style (short sentences, one question per turn, no lists or markdown); behaviour (upsert
immediately, one missing thing at a time, mark unknowns, ask which is right on conflict, confirm outliers);
ending (finalize_plan when readiness allows and the user agrees, explain top two actions, ask the user to say
them back, record_understanding). Under 450 tokens; count with a rough 4 chars per token.

`turn_block(state)`: uses `ledgerline.domain.state.snapshot`, `missing`, `readiness` (fake them in tests).
Format: today and window end; counts; "Still missing: ..." up to five; "Needs confirmation: ..." for open
conflicts and unconfirmed outliers; "Phase: ...". Under 200 tokens. Tests: block contains each section, caps at
five missing, omits empty sections.

## 2. Tools (`tools.py`)
Implement `ToolContext.recompute_and_push`, `build_tools`, `describe`.

Direct functions: Pipecat 1.9 derives the JSON schema from the signature and a Google-style docstring. Verify the
exact convention with `pipecat-context-hub get-code-snippet "direct functions"` and the `function-calling`
examples before writing. Signature shape: `async def upsert_item(params: FunctionCallParams, kind: str, name: str,
amount: float | None = None, ...)`. Use `Literal[...]` for enums where Pipecat supports it; if not, validate in the
body and return a corrective result string.

Each handler:
1. validate and coerce (amount -> Decimal quantised; kind -> ItemKind; day_of_month int 1..31)
2. call the domain function, get an Outcome
3. `plan = await ctx.recompute_and_push(focus)` where focus is the card the kind maps to
4. `await params.result_callback(describe(outcome, plan))`

`describe`: one line, under 60 words. Always includes "in X, out Y" from `plan.summary` when present; the conflict
or outlier question verbatim when set; for finalize_plan the top two actions and the shortfall or surplus; for
BLOCKED the first question. Never invents a number.

`finalize_plan`: if `readiness(state).blockers` non-empty return "blocked: ..." and do not set plan_final. Else set
`state.plan_final = True`, recompute with focus "plan".

`record_understanding`: compare restated actions to `ctx.last_plan.actions` by fuzzy match on target name and
type; gaps = actions not restated. Store `Understanding` on state.

Tests (`tests/agent/test_tools.py`), with fakes: each tool calls the right domain function with coerced args; each
pushes exactly one cards message with bumped version; result string contains the totals and the question; bad
kind returns a corrective string and pushes nothing; finalize refuses when blockers exist; record_understanding
computes gaps. Assert no handler awaits anything but `push_cards` and `result_callback`.

## 3. Text harness (`evals/harness.py`, `evals/sim_user.py`, `evals/checks.py`)
Bypass Pipecat. A plain OpenAI loop: system prompt from `prompt.system_instruction(state)`, tools from
`build_tools(ctx)` converted to OpenAI tool schemas (write a tiny converter or reuse Pipecat's schema derivation
if it can run without a pipeline; check with context hub), model `gpt-5.6-luna` via the Responses API with
`reasoning={"effort": "none"}` and `parallel_tool_calls=True`. Each turn: user text in, run tool calls through the
real handlers with a fake `FunctionCallParams` whose `result_callback` captures the string, feed results back,
collect assistant text. Log a JSON transcript: turns, tool calls with args, tool results, state snapshot, cards
version.

`sim_user.py`: persona with hidden facts from a scenario YAML, answers one thing at a time, includes one
scripted correction ("actually my salary is 45,000") and one conflicting statement, says "yes, I understand" and
restates two actions at the end. Also gpt-5.6-luna.

`checks.py`: rule checks over a transcript: every number in assistant text appears in a tool result or the last
user turn; at most one question mark per assistant turn; no banned phrases (approved, guaranteed, take a loan,
settlement offer, I have transferred, I have paid); no markdown characters; every recorded amount was repeated
back within two turns.

`evals/scenarios/`: three YAML scenarios to start: comfortable surplus, timing shortfall fixed by deferral,
structural shortfall with a correction and a conflict. Shape per research 11 "Example scenario fixture".

`tests/agent/test_harness_smoke.py` marked `llm`: runs one scenario once, asserts the transcript ends with
`plan_final` True and checks pass. Not run by default.

## Done when
`uv run pytest tests/agent` green offline; `uv run ruff check ledgerline/agent evals tests/agent` clean;
`uv run lint-imports` green; `OPENAI_API_KEY=... uv run pytest -m llm tests/agent` passes at least once and its
transcript is saved to `evals/runs/` (gitignored). Write `docs/process/status-B.md` including the cost of that run.
