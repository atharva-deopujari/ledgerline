# Session B handover · the voice simulation

Self-contained. Everything below is on disk and green: `uv run pytest tests/agent` → 290 passed,
1 deselected; repo 743 passed; `uv run ruff check ledgerline tests evals` clean; `uv run
lint-imports` 3 kept. Nothing committed.

## What the owner's third call showed

Recording: `evals/runs/voice-2ac2a01f28e9-20260912-141347.json`. Read it whole before changing
anything; the raw text is more convincing than any summary.

1. **Every tool turn produced two spoken segments**, pre-tool text then post-result text, each
   with its own question. Turn 5: "What else would you like to tell me?What's your next income
   or expense?" Turn 14: "What's the next income or expense?What's the next income or expense?"
   Turn 24: "You're welcome. Goodbye.Goodbye." — the second goodbye was the `end_call` result
   string being spoken after the model had already said it.
2. **Turn 16**: "Nothing" produced two `mark_unknown` calls and then four questions in one turn,
   including "What's your monthly income?" immediately after recording that there is none.
3. **Speech arrives in fragments**: "I have" / "20,000 in cash and" / "20,000 in bank balance.";
   "It is" / "on" / "September." The first utterance was STT garbage, "Your WhatsApp."
4. **Turn 22**: `record_understanding(confirmed)` and a goodbye, with **no** `end_call`. The call
   only ended at turn 24, after the person said "Thank you".

## What changed (done)

- **`ledgerline/agent/prompts/v1.md`.** The acknowledge-then-act rule and its example are gone.
  Now: "When you need a tool, call it first and say nothing at all before it. Speak once, after
  the result." Plus "Ask nothing else, and never ask again about something you just marked
  unknown", and "say one goodbye and call end_call in the same reply. Never say goodbye twice."
- **Token ceiling 620** (`tests/agent/test_prompt.py::MAX_BASE_TOKENS`), prompt at 600. Raised
  because the new rules replace a longer one and each closes a defect heard on a real call.
- **`phrases.GOODBYE` is now `"call ended, say nothing more"`** — no speakable text. The model
  owns the farewell and says it in the same reply as the call; agreed with the orchestrator, C
  told. If that ever flips to the pipeline owning it, this constant is the only thing to change.
- **Four gating checks in `evals/checks.py`**, every one reversed or written from this recording:
  - `silent_before_acting` — the old ordering rule inverted. Text before a tool call now fails.
  - `no_repeated_sentence` — the same sentence twice in one assistant turn.
  - `no_question_after_unknown` — a question naming a field the same turn just parked.
  - `one_goodbye_with_the_end_call` — one farewell, in the turn that calls `end_call`.
  `ADVISORY` is now empty; nothing is advisory. Replayed over the bad recording these flag every
  defect above, plus `one_question_per_turn` on turns 5, 8, 14 and 16.

**Caveat**: the voice recorder does not write `event_order`, only `evals/harness.py` does, so
`silent_before_acting` bites on harness transcripts and never on a live recording. Do not read a
clean live replay as evidence for that rule.

## Running the harness

```
uv run pytest -m llm tests/agent          # the single smoke scenario
PYTHONPATH=. uv run python -m evals.harness <scenario-name>   # one scenario, prints cost + path
```
`OPENAI_API_KEY` comes from `.env`; `run_scenario` loads it at call time, and the smoke test
decides whether to skip by reading `.env` with `dotenv_values` **without** mutating `os.environ`
— do not "simplify" that, it breaks Session C's tests that assert the process starts with no keys.
Transcripts land in `evals/runs/` (gitignored). Seven harness runs so far cost **$0.0751** in
total; a full call is about **$0.012–0.014**, so 5 scenarios × 5 runs ≈ **$0.35**.

## Scenarios to build (`evals/scenarios/*.yaml`)

Shape them like the recording, not like a tidy transcript. `sim_user.py` supports
`scripted_behaviours` (turn number → exact utterance), which is how you force the awkward ones.

1. `fragmented_balance` — "I have" / "20,000 in cash and" / "20,000 in bank balance." as three
   consecutive user turns, then rent given the same way.
2. `one_word_answers` — "Nothing.", "Yes.", "September." as whole turns, including "Nothing" to
   "what's your next income or expense".
3. `garbage_opener` — first utterance "Your WhatsApp.", then a normal call.
4. `correction_and_conflict` — a correction, and a conflict answered "I do not know".
5. `estimated_income_happy_path` — income given as "around forty thousand" (certainty estimated),
   through to plan, agreement, goodbye and `end_call`.

## The suite runner to write

`evals/run_suite.py`: every scenario × 5 runs, collect `checks.run_checks` per run, print a table
of **pass rate per check per scenario**, exit non-zero if any check is under 95% across the
matrix. Keep the per-run transcripts; they are the evidence for the report.

## The iteration loop

Run, read the failures, fix, rerun until every check is at or above 95% over 5 × 5.

- Prompt wording: `ledgerline/agent/prompts/v1.md` only. Stay under 620 tokens — the test enforces
  it, and trimming is always possible; do not drop a rule to make room without saying so.
- Result strings: `ledgerline/agent/tools/phrases.py` for fixed fragments,
  `ledgerline/agent/tools/describe.py` for how they are assembled.
- These must stay green after every change: `uv run pytest tests/agent`, `uv run ruff check
  ledgerline tests evals`, `uv run lint-imports` (agent must never import pipecat — the test walks
  every module in the package).
- Report the failure classes found and what fixed each, with before and after pass rates. A rate
  that moves without a named cause is not a fix.
