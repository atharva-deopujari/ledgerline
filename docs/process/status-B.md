# Status B · agent (tools, prompt, text harness)

State: **complete. Offline suite green, the paid `llm` smoke test passes against the real
domain.** Nothing committed; working tree left dirty.

## Implemented

| File | What it does |
|---|---|
| `ledgerline/agent/prompts/v1.md` | Static base prompt. 2,391 chars, 597 tokens at 4 chars/token — **over the brief's 450 and over the approved 540**, see Assumptions. Role and English-only; hard rules (no invented numbers, no approval or eligibility claims, no new loan or settlement, no skipping a payment without the tool's consequence, never claim an action is done, never mention cards or the system); numbers rule (speak only what a tool returned, repeat a new figure once, "rupees" never a symbol); spoken style, contractions and no form phrases; behaviour (acknowledge the fact in one line *then* call the tool in the same reply, one call per fact, income certainty and ranges, one missing thing at a time, `mark_unknown`, conflicts); ending (`finalize_plan`, top two actions with consequences, ask once whether it works, `record_understanding`, goodbye and `end_call`). |
| `ledgerline/agent/prompt.py` | `base_prompt(version)` reads `prompts/<version>.md` (cached, raises `FileNotFoundError` on an unknown version). `turn_block(state, today=None)` builds today + window end, counts, "Still missing" capped at five, "Needs confirmation", "Phase:" — empty sections omitted, 30-60 tokens typical. `system_instruction` joins them. |
| `ledgerline/agent/tools/` | `ToolContext.recompute_and_push`, the seven direct functions in `TOOL_NAMES` order, and `describe`. Every handler validates and coerces, calls one domain function, pushes exactly one cards message, then returns one short string. `ToolContext.replay`/`remember` drop a repeated call with identical arguments inside one turn. `end_call` sets `state.call_ended`, pushes the final snapshot (readiness reads `call_ended` as phase `done`), then awaits `ctx.request_end` when the voice session wired one (`None` in the harness). |
| `evals/checks.py` | Six gating transcript rules plus one advisory: `numbers_traceable`, `one_question_per_turn`, `banned_phrases` (recommendation language, never debt names), `no_markdown`, `amounts_repeated`, `no_iso_dates`. Includes a small spoken-number parser so "forty five thousand" traces to 45000. The advisory rule, `speaks_before_acting`, reports whether the model spoke its acknowledgement before calling a recording tool; it is reported, never used to fail a run, because it describes how the model chose to order one response. |
| `evals/harness.py` | Pipecat-free OpenAI Responses loop: per-turn `system_instruction`, tool schemas derived from the same direct functions Pipecat uses, the real handlers behind a fake `FunctionCallParams`, `reasoning={"effort": "none"}`, `parallel_tool_calls=True`. Writes a JSON transcript (turns, tool calls with args and results, state snapshot, cards versions, token usage) to `evals/runs/` (gitignored). |
| `evals/sim_user.py` | Persona holding the scenario's hidden facts, answering one thing at a time, with scripted turns played verbatim and no model call. |
| `evals/scenarios/*.yaml` | `comfortable_surplus`, `timing_emi_before_salary`, `timing_shortfall`, `structural_shortfall_correction` (the last carries the scripted correction and the conflicting card minimum). The first two are the same person and the same bills one number apart — 20,000 in the account is `OK` with no actions, 8,000 is `TIMING` with the bike EMI moved to 1 October — which is the cheapest way to test that the engine's classification actually reaches the person. |

## Tests

`uv run pytest tests/agent` → **290 passed, 1 deselected** (the deselected one is the `llm` smoke
test) in 0.15 s, fully offline. `uv run ruff check ledgerline/agent evals tests/agent` clean.
`uv run lint-imports` → 3 contracts kept, including "agent never imports pipecat".

- `test_prompt.py` (36): token budgets, every required rule present, section presence, the
  five-item cap, empty sections omitted, conflicts and outliers listed, phase from readiness.
- `test_tools.py` (101): coercion of each argument, one bumped cards message per call with the
  right focus, totals and questions in the result, corrective strings with no push for a bad
  kind / day / debt kind / choice / reason / negative amount, `finalize_plan` refusing while
  blockers remain, `record_understanding` gap computation, every `describe` branch, and a static
  check that no handler awaits anything but `recompute_and_push` and `result_callback`. One test
  runs the real Pipecat `DirectFunctionWrapper` over all six tools and asserts the derived schema.
- `test_checks.py` (106): each rule, both directions, plus the spoken-number parser.
- `test_integration_domain.py` (36): the agent layer against the **real** `state`, `engine` and
  `cards`, no fakes — a conflict on a date, a card minimum, a debt kind and the opening balance
  each reach the model as their speakable `question` with no machine value and no ISO date
  leaking through; `resolve_conflict` passes all five field shapes through unchanged; and a call
  where an essential was answered "I do not know" still reaches a confirmed understanding.
- `test_harness.py` (21): scenario files, schema conversion, persona building, scripted turns.
- `test_harness_smoke.py` (1, `llm`): pending — see below.

## Paid smoke test (run, passing)

`uv run pytest -m llm tests/agent` → **1 passed**, against the real `state`, `engine` and
`cards`. It runs `timing_emi_before_salary`, the scenario that reaches `finalize_plan` with
actions to explain, so the paid run exercises the ending of the call rather than a plan with
nothing in it. Transcripts are saved under `evals/runs/` (gitignored).

**Cost: seven harness runs, 327,447 input + 8,046 output tokens = $0.0751**, plus the $0.0026
plumbing check below, so **$0.078 of OpenAI spend for the whole agent layer**. One
`timing_emi_before_salary` run is now about **$0.014**: roughly 63k input tokens (the system
prompt and per-turn block are resent every turn, and the call now runs to a goodbye) and 1.4k
output, at luna's $0.20 / $1.20 per million.

Six runs, not one, because all but the last exposed a real defect (below). The saved
transcripts are named `comfortable_surplus-*` because they were recorded while that
name held the 8,000 opening balance; that scenario is now `timing_emi_before_salary`, and the
files are left byte-identical rather than relabelled. The last of them,
`evals/runs/comfortable_surplus-20260911-214731.json`, predates the ISO date fix (item 5 below),
so replaying the checks over it now reports five `no_iso_dates` violations. Everything else in
it still matches the code.

### Latest run, `timing_emi_before_salary-20260911-235751.json`

**Gating checks clean, `call_ended` true, and the acknowledge-then-act ordering confirmed live.**
Twenty-five turns. The thing worth reporting: **luna honours the ordering**. Every one of the
eight fact turns came back as `message → function_call → message` — it speaks the
acknowledgement ("Okay, eighteen thousand rupees for rent, due on the fifth of October."), then
calls the tool, then asks the next question. Text to speech can start on that first message
while the handler runs, which is the ~0.9 s of dead air per fact the owner heard. It also picked
up the tone rules: contractions throughout ("I'm", "doesn't", "you'll"), varied openers, no form
phrases.

The ending is the behaviour the owner asked for. The model explained the plan, asked "would you
change anything", took "No, I would not change anything" as agreement, called
`record_understanding(confirmed=true)` and **never asked the person to repeat anything back**.
On the goodbye it called `end_call`, which set `call_ended`.

Two defects this run and the one before it found, both fixed:

1. **`end_call` was unreachable.** I had made `understanding.confirmed` end the harness loop, so
   the run stopped the moment the person agreed and the model never got a turn to say goodbye in
   — `call_ended` came back false. Only `end_call` ends a call now; `_ready_to_end` marks
   agreement, and the loop allows two more turns for the goodbye before giving up. The simulated
   user was also ending the conversation itself; it now says goodbye and waits for one back.
2. **The advisory ordering rule was wrong, not the model.** It flagged `finalize_plan` and
   `end_call` for calling the tool before speaking. Those answer a request rather than record
   something the person said: there is nothing to echo, and calling first is correct. The rule
   now applies only to the four recording tools. Replayed over the same transcript it reports
   nothing.

### Earlier run, `timing_emi_before_salary-20260911-234847.json`

**Zero rule violations, `no_iso_dates` included** — which is the live verification the date fix
had been missing. The agent said "the tenth of October" and "the first of October" throughout;
no ISO string reached the person. Seventeen turns, seven facts recorded with correct arguments
on the first call each time (including `certainty: confirmed` on the salary, so the F2 argument
is reachable in practice), cards versions monotonic 1..7, `finalize_plan` returning TIMING with
the bike loan moved to 1 October and the lender warning attached, and `record_understanding`
closing with `confirmed=true`.

It also found a fifth defect, now fixed. The result of that last call was `not restated: bike
loan`, and `understanding.gaps` stored `["bike loan"]`, even though the person had just said "I
will ask the lender to move the bike-loan due date until after my salary arrives". The matcher
compared the raw strings, so the hyphen in "bike-loan" stopped it matching the target "bike
loan", and `PAY_ON_DATE`'s everyday words ("pay on", "on the") were not in the sentence either.
The consequence is not cosmetic: a false gap makes the agent re-explain something the person has
demonstrably understood. Both sides of the comparison now go through the domain's own
`normalise_name`, which lowercases, strips punctuation and drops articles. Replaying the fix
over the real restatement from that transcript returns no gaps; a test pins the verbatim
sentence, and another pins that a genuinely missed action is still reported.

Two weaknesses worth naming, neither caught by the rules. Turn 14 is a five-clause monologue
where the prompt asks for one or two short sentences — no check measures length. And the new
certainty rule nudged the model into asking "Are any of these figures estimates or uncertain?",
a meta question about the data rather than about the person's money, which is exactly the
form-like feel the research warns against. Both are prompt problems for the next version, not
code.

### Read of the 21:47 transcript

Good, and better than the rule checks alone can show. Across 22 turns the agent recorded seven
facts with correctly typed arguments on the first call every time — `balance`, `income` with
`day_of_month=1`, three `essential`s (`spread=True, survival=True` inferred correctly for
groceries), a `debt` with `debt_kind=secured_emi`, and an `optional` — asked exactly one thing
per turn, never read a list aloud, and never narrated the tools. Every figure it spoke came back
in a tool result or from the person: the five rule checks pass with zero violations, and the
number-provenance check is doing real work here because the agent speaks figures as words
("four thousand five hundred") and the parser traces those. Cards versions were monotonic 1..9.
The ending is the behaviour the brief is actually about: `finalize_plan` returned a timing
shortfall with two distinct actions, the agent explained **one action per turn** and asked after
each, the person restated both, and `record_understanding` closed with `confirmed=true` and no
gaps. Weak spots worth watching: the agent sometimes joins two asks with "and" inside a single
question mark, which `one_question_per_turn` does not catch; it calls `record_understanding`
once per restatement rather than once at the end, which is harmless but noisy; and the
simulated user is far more cooperative than a real caller, so this pass rate is an upper bound.

### Defects the paid runs found, and the fixes

1. **`describe` spoke the same action twice.** The engine emits one `DEFER_OPTIONAL` per
   prorated day of a spread optional, so `plan.actions[:2]` was "Move streaming, Move streaming".
   `_top_actions` now takes the first two *distinct* `(type, target)` pairs. It also stopped
   repeating a target the rationale already names, and stopped producing "..".
2. **A closing surplus was spoken next to a list of deferrals**, which reads as "you are fine"
   during a timing shortfall. `describe` now names the plan shape for `TIMING`, `STRUCTURAL` and
   `UNSOLVABLE` before the figure.
3. **The harness ended the call one turn early**, on the first `record_understanding` even when
   it carried `confirmed=False` and only one restated action. `_call_is_over` now requires
   `understanding.confirmed`.
4. **The smoke test's `.env` load leaked into every other test.** Loading the key at module
   import broke two of Session C's `tests/api` tests that assert the process starts with no keys
   set. The test now reads `.env` with `dotenv_values` (no mutation) to decide whether to skip;
   `run_scenario` still loads it at run time.

5. **The agent read dates aloud as digits** — "before 2026-10-10". `turn_block` was writing
   today and the window end in ISO and the model echoed the format; TTS says that one digit at a
   time. `prompt.spoken_date` now renders "10 October 2026", `prompts/v1.md` gains an explicit
   rule under Numbers, and `checks.no_iso_dates` is a sixth rule so the harness fails on it
   rather than letting it through (`numbers_traceable` strips ISO dates, so nothing caught it).
   **This fix is verified by unit tests only — it has not been re-run against a live model**,
   per the orchestrator's instruction not to spend again. Replaying the new rule over the three
   saved transcripts flags the second and third (five ISO dates in the last one) and leaves the
   first clean, which is the evidence that the check works; the next paid run is what will show
   the prompt and block changes actually stop it.

Also fixed against Session A's finished domain: handlers catch `ValueError` from the domain and
return a corrective string with no cards push (a new debt with no `debt_kind` gets the four
allowed values back), and result strings now format rupees with `state.group_inr`, so a tool
result never mixes two groupings with the conflict and outlier questions the domain writes.

## Live plumbing check (before the domain landed)

Before Session A's engine landed I ran a four-turn throwaway scenario against `gpt-5.6-luna`
with `build_plan` and `build_cards` stubbed locally (nothing in the repo changed). It proved the
Responses API wiring, the derived tool schemas, the handlers and the simulated user all work:
the model called `upsert_item` with correctly typed arguments three times, spoke only figures
that came back in tool results, and asked exactly one question per turn.
**Cost: 10,539 input + 393 output tokens ≈ $0.0026.**

That run found two real defects, both fixed:
1. `numbers_traceable` flagged the year in "2026-10-10" as an invented number — the model reads
   the window end out of the turn block. `checks.numbers_in` now strips ISO dates first.
2. The model spoke the window end as "2026-10-10", which TTS would read badly. The prompt's
   numbers rule now covers dates as well as figures.

## The eval evidence: a check, replayed over a real call, caught the model doing arithmetic

Worth reading as one sequence, because it is the only place where our evaluation found a defect
nothing else would have.

**The failure.** `numbers_traceable` exists to enforce one product rule: the model never computes.
Replaying it over the owner's real 56-turn call flagged turn 47, where the bot said "keep the
remaining essential spending within **eight thousand rupees**". That number is in no tool result
and in no user turn. It is 28,000 of essentials minus 20,000 of rent — arithmetic the model did
itself and then spoke as fact. Every offline test passed while this was happening; only the
transcript check caught it.

**Why it happened.** The model wanted a figure for how much room the person had, and the tool
result did not contain one. `describe` returned totals in and out, and the surplus, but nothing
about the tightest point of the month. Given a gap between what it needed to say and what it had
been handed, it filled the gap itself.

**The change, in two places.** `describe` now includes the engine's own `lowest_balance` and its
date — "lowest 2,000 on 30 September" — so the number the model reaches for already exists in the
result. We did not add a computed "left after essentials" figure: `closing_balance` and
`shortfall_after_actions` are the same number on every plan we checked, so it would have said the
surplus twice, and a per-category breakdown is not something the engine models, so computing one
in `describe` would just move the invention one layer down. The prompt's Numbers section gained
one line: "If a figure you want to say is not in a tool result, do not say it; say what the
result says."

**Before and after.** Before: eleven saved transcripts, **one traceability flag** (turn 47 of the
real call) and **four false `amounts_repeated` flags** from a stale rule. After: a fresh paid run
of `timing_emi_before_salary` — 21 turns, `call_ended` true — **zero gating flags and zero
advisory flags**, and the replay over every saved transcript is clean except the two pre-date-fix
runs that still carry their known `no_iso_dates` flags. Cost of that run: 53,809 input and 1,172
output tokens, **$0.0122**.

**One thing this made worse, and we left it worse on purpose.** With the real engine a two-action
timing shortfall now produces a 151-word result, against the 60-to-90 word budget. Each action
brings a multi-sentence rationale plus a policy consequence, and an earlier review is exactly why
those consequences are there. We removed the duplication we could — the engine puts the same
sentence on an action's warning and on the unpaid row, and it was being said twice, which is
worse than not hearing it — but cutting further would mean dropping consequences a person needs
before they miss a secured instalment. `test_the_real_finalize_result_carries_every_consequence_once`
pins the real length so the number is visible rather than hidden.

## The owner's third live call · the bot repeated itself

The recording is `evals/runs/voice-2ac2a01f28e9-20260912-141347.json` and it is worth reading
whole. Every tool turn came out as two spoken segments, pre-tool text then post-result text, each
carrying its own question: turn 14 is "What's the next income or expense?What's the next income
or expense?" and turn 24 is "You're welcome. Goodbye.Goodbye." — the second goodbye being the
`end_call` result string spoken after the model had already said it. Turn 16 answered "Nothing"
with four questions, one of them asking about income immediately after recording that there is
none. Turn 22 said goodbye without calling `end_call`.

The cause was a rule I had added and measured as a win: acknowledge first, then call the tool, so
text to speech starts while the handler runs. It did cut the dead air — the earlier paid run
confirmed the model honoured the ordering on all eight fact turns — and it also gave every tool
turn two chances to speak. The eval harness never caught it because it concatenates a turn's text
across tool rounds into one string, so two segments read as one. Only a person listening heard
the repetition. That is the honest lesson: a check that measures the transcript cannot hear what
the call sounds like.

Reversed. The prompt now says "call it first and say nothing at all before it. Speak once, after
the result", with the pipeline speaking a filler so first audio stays fast — Session C owns that
half. `end_call`'s result is `"call ended, say nothing more"`: the model owns the farewell and
says it in the same reply as the call, so nothing invites a second one. Ceiling raised to 620,
prompt at 600.

Four gating checks, each written or reversed from this one recording: `silent_before_acting` (the
old ordering rule, inverted), `no_repeated_sentence`, `no_question_after_unknown`, and
`one_goodbye_with_the_end_call`. `ADVISORY` is now empty. Replayed over the recording they flag
every defect above. One limit worth knowing: the voice recorder does not write `event_order`, so
`silent_before_acting` only bites on harness transcripts, never on a live call.

The simulation the owner asked for — voice-shaped scenarios, a suite runner, 5 × 5 runs to a 95%
pass rate — is handed over in `docs/process/session-B-simulation.md`. I stopped rather than start
it with a quarter of my context left.

## Refactor · one 668-line module became a package

`tools.py` was 668 lines and 39 defs, most of them closures inside one function, with `describe`
branching on the runtime type of its first argument. It is now `ledgerline/agent/tools/`:
`phrases.py` (every fixed fragment the model reads), `coercion.py` (the validators and the
refusal builder), `context.py` (`ToolContext` and the replay guard), `describe.py` (the result
string, dispatched per outcome kind with `singledispatch`), `handlers.py` (the seven tools), and
`__init__.py` re-exporting the same names as before, private helpers included, because the tests
reach for them by name. `evals/checks.py` split the same way: `spoken_numbers.py` for reading
amounts as people say them, `provenance.py` for which figures are still sayable.

The handlers stayed closures. Pipecat derives each schema from a plain async function whose first
parameter is named `params` and validates that shape when the pipeline is built, so the signature
is the tool's public contract; reshaping it to bound methods to satisfy a style preference would
put the whole tool layer at risk for no gain the caller can see.

Raw strings became enum members throughout: `PlanStatus.BLOCKED` rather than `"BLOCKED"`,
`CardId.PLAN` rather than `"plan"`, `ActionType` keys in the restatement word table.

**Two nets, both run before and after.** The first was a line-by-line walk, as asked: the handler
bodies were sliced out of the original file rather than retyped, and a text diff of that region
shows exactly six changed lines, all of them a literal becoming the enum or constant that equals
it. No statement dropped, no reordering of state mutation, push, remember and callback, every
early return intact. An AST comparison of the whole file accounts for the rest: thirty-one
statements changed, each one a constant gaining enum keys, a refusal gaining a template, or the
`describe` if-chain becoming three dispatched functions. The second net was the thirteen-transcript
replay plus `describe`, `turn_block` and the prompt token count, captured before the first line
moved and compared after the last: **byte-identical**.

Test files moved to match where the split was clean — `test_describe.py` now holds the tests for
that module, moved as whole functions and verified by count, not rewritten. The rest stayed put:
`test_tools.py` covers handlers, context and coercion, which are what a tool call actually
exercises together, and splitting it four ways at this point would have been churn with a real
chance of losing a test quietly.

## Twelfth review, F2 · a rejected figure stayed sayable

A conflict result names both figures on purpose — the model has to be able to ask which is
right. `resolve_conflict` then carries only the field and the choice, no amount, so nothing
retired the losing one and both stayed sayable for the rest of the call. The person picks 12,000
and the bot can still say 11,000, contradicting the card beside it.

The checker now remembers the disputed pair when a supersession raises a conflict, and
`resolve_conflict` retires whichever figure lost: `new` drops the previous, `previous` drops the
newer and restores the earlier as current, `both` keeps the pair because the two turned out to be
separate things. Both figures stay sayable while the question stands, and the retirement takes
effect from the turn after the resolution, same rule as a correction.

Writing the test caught a mistake in my own fixture before it caught anything in the code: I had
the `resolve_conflict` result quoting 12,000 while the choice was `previous`. The real tool
returns totals for the figure that won, so the fixture was describing a call that cannot happen.
Fixed the fixture, not the code.

## Eleventh review · the follow-up asked about the wrong actions

**F2.** `describe` narrates `_top_actions(plan)`, which dedupes on `(type, target)` because the
engine emits one `DEFER_OPTIONAL` per prorated day. `_gaps` was still reading `plan.actions[:2]`.
With two daily streaming defers followed by a card action, the person hears streaming and the
card — and if they sound unsure, the follow-up goes over streaming twice and never mentions the
card. The one thing the comprehension check exists to catch, missed by the check itself. `_gaps`
now iterates the same selection `describe` narrates, so the follow-up covers exactly what was
said.

**F3.** `_supersede` keyed items on the raw name, lowercased. The domain keys them through
`normalise_name`, which also strips articles and punctuation and collapses spaces, so "the rent"
and "rent" are one row on the cards and were two items in the checker — and a correction spelled
either way never retired the old amount. `checks.py` now imports `normalise_name` and uses it.
That is the one import of application code in the file, deliberate: identity has to match the
domain's or the check is measuring something else. `evals` sits outside the import-linter
contracts, which cover the `ledgerline` package, and `lint-imports` stays at 3 kept.

## Tenth review · confirming comprehension, and two holes in the number check

**F2, the closing question.** It asked "does that work, or would you change anything", which
establishes that someone is willing to proceed, not that they understood what they agreed to.
A bare yes to that was being recorded as confirmed understanding. The decision not to demand a
recitation stands — that was the owner's complaint about being talked to like a child — but the
question is now comprehension-shaped: "Then ask once whether the actions and what happens if they
skip them make sense." A yes to *that* is understanding. `record_understanding`'s docstring says
the same thing rather than "happy with the plan", since the docstring is what the model reads
when deciding whether to call it. 599 tokens.

**F4, two amounts folded into one.** `_words_to_numbers` treated "and" as part of the current
number always, so "forty-five thousand and twelve thousand" parsed as 57,000 — and that sum then
counted as user-sourced, letting the assistant speak arithmetic nobody had done. The rule is now
about scale ordering rather than the word "and": a scale at or above the one already used starts
a new amount, a smaller one continues the current one. "forty-five thousand and twelve thousand"
gives both figures and not their sum; "one thousand and two hundred" is still 1,200, and
"one lakh twenty thousand" still 120,000.

**F5, corrected figures stayed sayable forever.** Every number ever said or returned was unioned
into `allowed` and never removed, so after rent went 11,000 to 12,000 the assistant could say
11,000 an hour later and pass — while the cards showed 12,000. Recording-tool arguments now carry
provenance per item, and a changed amount strikes its predecessor. The striking happens *before*
that call's own result is added, which is what lets a conflict question keep naming both figures:
"Earlier you said 11,000 for rent, now 12,000. Which is right?" has to remain sayable, and it is.
A different item's amount is untouched by its neighbour's correction.

Two details came in with a second relay of the same review and both were real. The turn that
*makes* a correction may name the old figure — "not eleven thousand then, twelve thousand for
rent" is how a person hears that it landed — so the retirement takes effect from the turn after,
not the turn itself. And `evals/sim_user.py` still had the persona waiting to be asked whether the
plan "works for you"; it now answers the comprehension question, or the paid harness would have
been rehearsing a conversation the prompt no longer has.

**Replayed over all thirteen recorded transcripts: no new flags.** Same two historical ones.

## A-8 · one rule for borrowing, in both layers

Session A wrote the predicate as a semantic one — phrases that *propose getting money*, plus a
narrow rule for the word "credit" — because a word list cannot tell "ask the lender" from "ask a
friend". `evals/checks.py` now carries the same shape, copied rather than re-derived, so the
engine's own text and the spoken transcript are judged by one rule.

**Two phrases from A's list are deliberately not copied: the bare words "loan" and "borrow".**
They are right for engine-authored text, which never needs to name the person's existing debts
generically, and wrong here: a transcript has to be able to say "your personal loan is due on the
twentieth" and "you borrowed that from your brother, so it sits below the card". Banning them
outright would reinstate the exact defect an earlier review raised against this file. Both are
still caught when they appear as a proposal, by the acquiring patterns that were already here —
"take a loan", "get you a small loan", "you could borrow from a friend". Everything else is A's
list verbatim: BNPL, buy now / pay later, overdraft, advance from, lend you, lend me, a tab, on
tab, instalment plan, and A's `credit` rule unchanged.

Fourteen new tests, both directions. "a few days' credit", "put it on tab", "an advance from next
month's pay", "could a friend lend you the difference", "an instalment plan" all fail; "ask the
lender", "reported to the credit bureaus", "your credit report", "credit card minimum", "credit
score", and the two existing-debt sentences all pass.

**Replayed over all twelve recorded transcripts: no new flags.** The only flags remaining are the
two known ones — the pre-date-fix `comfortable_surplus` runs, and the turn-47 arithmetic in the
real voice call, both from before their fixes and kept as history.

The prompt said "never suggest a loan or settlement", which left a shop tab, an employer advance
and money from family outside the rule — the three forms most likely to come up in this
conversation. It now says "never suggest new borrowing or a settlement". A test also checks the
prompt does not itself name a tempting instrument anywhere. 599 tokens.

## Eighth review, F3 · the question the person had just refused

`describe` appended `plan.questions[0]` whenever the plan was `BLOCKED`. After
`mark_unknown("opening_balance")` the state correctly drops the field from `missing()`, but the
engine stays blocked on it forever, and its first question is "How much money do you have right
now". So the result of the very tool that records "they cannot answer this" carried that question
straight back, and the prompt says both *ask what the result carries* and *never ask again*. The
model cannot obey both.

Reproducing it showed the finding understated the scope: it is not only the `mark_unknown`
result. **Every** result for the rest of the call carried the same question, because every plan
stays blocked. A fix scoped to the one tool would have moved the loop by a single turn.

`describe` now takes `parked` — the fields the person has declined — and never repeats a blocked
question for one of them. For the opening balance there is no substitute question, so it returns
the consequence instead: "no plan without a starting balance: say that plainly and offer to end
the call, unless they offer a rough figure." A fresh call with no balance yet is untouched: that
question is the one thing that unblocks everything, and only a parked field silences it. Tested
across all three never-ask-again reasons, and on the turn after.

The signature change is additive with a default and written up as **B-1 in `requests.md`**.
Session C consumes `build_tools`, not `describe`, so nothing outside this file moves.

Two smaller things fell out of it. The prompt's rule covered only questions — "if a result
carries a question, ask it next" — which left an instruction-carrying result with nothing telling
the model to act on it; it now reads "a question or tells you what to say". And results were
ending "...bank balance?." because the join appended a full stop to everything; parts are now
assembled as sentences, so a question keeps its mark and nothing else.

## A-7 · two things verified, two more found by reading the actual strings

Asked to check that `mark_unknown` stops quoting a retracted figure and that one `except
ValueError` covers both domain refusals. Both were already correct, and both now have tests.
What the exercise actually turned up was two defects in my own strings, visible only by printing
what the model receives rather than asserting on fields:

- `mark_unknown` returned **"created. in 45,000, out 0. provisional."** The totals were right and
  the old 1,200 was gone, but nothing said *what* had been parked — `Outcome` carries a `field`
  for this tool, not a `name`, and `describe` only read `name`. It now says "created electricity
  amount", derived from the field.
- The card-pair refusal read **"…ask which is right. Fix that argument and call the tool
  again."** Two different instructions in one breath, and the second is wrong: only the person
  can say which figure is right. `_refused` now leaves a message that already names a next step
  alone, and still adds one where the domain gives none.

Neither would have failed a test that checked status codes and pushes. They were only visible in
the sentence the model actually reads, which is the thing this layer exists to produce.

Four integration tests written against behaviour the domain did not have yet, all
`xfail(strict=True)` so an unexpected pass reddens the suite the moment it lands. Each was run
with `--runxfail` first to confirm it failed for the right reason rather than a typo. All four
flipped within the hour — Session A landed the changes between two of my runs, which is the third
time that mechanism has announced a dependency rather than letting it arrive silently. Markers
removed, all four green:

- a date-only income now puts its amount in `Still missing`, so the model has something to ask
  instead of sitting blocked on "no income recorded";
- marking that income amount unknown lets `finalize_plan` through, provisional, income excluded;
- answering a conflict with "I do not know" clears the conflict and stops it being asked again;
- a card minimum of 10,000 against a total of 5,000 is refused with both figures named, pushes
  no cards, and leaves the state byte-identical.

That last one is the reason the test asserts on pushes as well as state: a refusal that still
redraws the screen looks like success to the person watching it.

**The prompt did need a change.** The don't-know rule lived inside the missing-list bullet — "Ask
one missing thing at a time, the first under Still missing. If they don't know, call
mark_unknown" — so it read as scoped to that list, while the conflict rule pointed only at
`resolve_conflict`. Once `mark_unknown` starts settling conflicts, a person who genuinely cannot
say which of two figures is right would have been asked again and again, which is the exact
promise the tool is supposed to keep. The rule is now its own bullet naming both cases: "If they
don't know, including which of two figures is right, call mark_unknown and never ask again." Five
other lines trimmed to pay for it; still 597 tokens.

## A-6 · a correction after agreement reopens the plan

Session A made any successful mutation clear `state.understanding`, so a correction after the
person has agreed puts the phase back to `plan` with `plan_final` still true. I checked both
things asked and found one of them wanting.

`turn_block` is fine: it prints "Phase: plan" and nothing that reads as a cue to wind up. But the
prompt's Ending section was written as a one-way street — agree, then goodbye — and the model
carries the earlier "yes" in its own conversation history even after the domain has thrown it
away. Nothing stopped it ending the call on an agreement that no longer described the plan in
front of them. One line now covers it: "If anything changes after they agree, go through the plan
again before goodbye." Ten other lines were tightened to pay for it, so the prompt is 597 tokens,
still inside the 600 ceiling.

Two tests: the prompt carries the rule, and an integration test walks the real sequence —
finalize, agree, phase `done`, then a correction — and asserts the phase is back to `plan`, the
understanding is gone, `plan_final` survives, and the word "done" is nowhere in the block.

## Fifth review, F5 · outlier questions vanished after the turn that raised them

`_needs_confirmation` scanned each item's `notes` for the word "outlier". Nothing writes that
note: the domain records the doubt as a `Conflict` in `state.outliers`. So the question appeared
once, in the tool result of the turn that raised it, and was gone from every turn block after —
while `readiness` stayed blocked on that same outlier. The model was left blocked with nothing to
ask, which is the worst shape a bug like this can take: the call cannot finish and nothing on
screen or in the prompt says why.

Conflicts and outliers are both `Conflict` objects with a speakable `question`, so the section is
now simply both lists. The notes scan is gone. Tests use a real outlier-producing `upsert`
(rent 12) and check the question survives the next turn and disappears only when the correction
lands; one more pins that a hand-written "outlier" note is ignored.

## Written ahead of Session A: strict xfails, both now landed

Two reviews changed behaviour we depend on, so the tests were written before the domain arrived
and marked `xfail(strict=True)`. Strict is the point: an *unexpected pass* fails the suite, so
the moment the domain lands the markers must come off. That is not hypothetical — the five
finalize tests flipped to failing between two runs, which is exactly how I learned Session A's
change had landed. All seven markers are gone and every test is green.

The ending-versus-agreeing pair needed one more thing. They kept failing after the domain landed,
and the cause was **my own fake**: `tests/agent/conftest.py` built a `CardsMessage` without
`ended`, so it took the field's default while the real `build_cards` set it from
`state.call_ended`. A fake that lags the contract it stands in for is worse than no fake, because
it reports green on behaviour that does not exist. The fake now mirrors the field, and a test in
`test_integration_domain.py` runs the **real** `build_cards` after `end_call` and asserts
`ended` is true while the phase is whatever readiness actually computed — so the next drift is
caught by something the fake cannot influence.

- **Ending is not agreeing** (two tests, now green). `readiness` used to report `done` on
  `call_ended` alone, so a person who said goodbye without agreeing produced a snapshot the
  screen read as "plan confirmed". `done` now means understanding was confirmed, `ended` means
  the call is over, and the two are independent: the tests assert `ended=True` with a phase that
  is *not* `done` before agreement, and both together after it.
- **Finalize refuses unanswered fields** (five tests, now green). A debt with no amount, a debt
  with no due date, a card with no minimum due, an income with no date: each refuses with the
  field quoted, and `mark_unknown` on that field then lets the plan finish.

The prompt needed no change for this. "Ask one missing thing at a time, the first under Still
missing. If they don't know, call mark_unknown and never ask again" already treats the missing
list as the thing to work through and names the escape hatch, and the Ending rule already says to
call `finalize_plan` only when nothing blocks it. One thing to watch: `turn_block` caps the
missing list at five, so with more than five blocking gaps the model sees them a few at a time as
they clear. `finalize_plan`'s refusal quotes the blockers, so nothing is hidden.

## A-4 · one cashflow, spoken as one cashflow

Session A split the summary: `total_out_planned` is now only money that actually leaves the
account, and a new `unpaid_total` carries what the plan cannot fund. `describe` says "in X, out Y"
from `total_out_planned` and adds "Z stays unpaid" as its own clause — never the two summed,
which is what let a summary imply one closing balance while the timeline reached another. An
integration test asserts the identity on the real engine
(`opening + in - out_planned == closing`, and `shortfall_after_actions == closing`) and that the
string the model hears matches it.

`turn_block` needed no change: it carries counts and questions, never money. There is now a test
pinning that, because a total copied into the per-turn block would be a second place for the two
cashflows to drift apart.

One welcome side effect: with A's priority fix the same timing scenario now leaves one obligation
unpaid instead of two, so the finalize result is **102 words**, down from 151. The 170-word bound
in `test_the_real_finalize_result_carries_every_consequence_once` still holds and still guards
against growth.

## Fourth review, F5 · ending a call did not publish the done phase

`end_call` set `call_ended` and asked the transport to shut down, but pushed nothing. Readiness
maps `call_ended` to phase `done`, and the browser never saw it — it kept whatever snapshot came
last, so the screen could still be asking "Does this work for you?" after the call was over. It
now pushes before requesting the end, and the ordering is asserted, not assumed: tearing the
transport down first would mean the message never reaches the page. A test against the real
`readiness` and `build_cards` confirms the last snapshot the browser receives says `done`.

**This does not cover the End button.** When the person hangs up from the browser there is no
tool call and no bot turn, so no snapshot is pushed at all — the page simply stops receiving. The
ended state for that path has to come from the frontend's own call lifecycle. Raised with the
orchestrator for Session D rather than worked around here.

## Third review, F5 · invented tool arguments authorised themselves

`_sources_up_to` trusted a tool call's **arguments** as evidence alongside its result. So an
invented amount laundered itself in two steps: the model puts 12,300 into an `upsert_item`
argument, the handler echoes it back inside the result string, and from there the model is free
to speak it. The check reported a clean run on a number nobody said.

Tool **results** are still trusted — the engine computes totals nobody says out loud. For the
four recording tools, an argument number now counts only when the person said it in the current
or previous utterance, and any argument number they did *not* say is struck from that call's
result as well. Striking it from the result is the part that actually closes the hole; filtering
arguments alone leaves the echo. `numbers_in` also learned the shorthand people really use —
"12k", "1.5 lakh", "2 crore" — so a figure said that way still traces.

Replaying the new check over all eleven saved transcripts turned up **one true positive in the
owner's real 56-turn call**: at turn 47 the bot said "keep the remaining essential spending
within eight thousand rupees". 8,000 appears in no tool result and no user turn; it is
28,000 of essentials minus 20,000 of rent, arithmetic the model did itself. That is the "never
compute" rule broken on a live call, and the check now catches it.

The same replay exposed a rule of mine that had gone stale: `amounts_repeated` only looked
*forward* from the tool call for the read-back, but since the acknowledge-then-act change the
model speaks the figure *before* it calls the tool, and the recorder can attribute a call to the
turn after the one that acknowledged it. Four false positives in that call. The window is now the
previous assistant turn through the next two, which matches both orderings; an amount never said
at all is still caught.

## Second review, F8 · the banned-phrase check rejected correct sentences

`BANNED` held the literal strings "personal loan" and "take a loan", matched anywhere in an
assistant turn. The product rule forbids recommending *more* debt, not naming a debt the person
already has — so "your personal loan is due on the twentieth", which is exactly the job, failed
the gate. `banned_phrases` now matches nine labelled recommendation-and-claim patterns instead:
acquiring language ("take a loan", "applying for a personal loan", "get you a small loan"),
suggested borrowing, top-up loans, buy-now-pay-later, EMI conversion, settlements, promised
outcomes (approved, pre-approved, guaranteed, eligible) and claims to have acted. The violation
detail names which one matched rather than quoting the phrase.

Fixtures both ways, as asked: a transcript restating an existing personal loan passes, and one
recommending borrowing from a friend fails. Five more sentences that mention existing debt
("you borrowed that from your brother", "let me get your credit card minimum next") are pinned
as passing, since a looser pattern would have caught them. Replayed over all six saved
transcripts: no new flags.

The engine change Session A is making — `ASK_LENDER` with a consequence instead of
`PAY_ON_DATE` — needs nothing from `describe`; the F3 fix already emits each top action's
`warning`. There is now a test pinning it for `ASK_LENDER` specifically, so it will fail loudly
if that stops happening.

## Not done

`evals/cassettes/` is empty and nothing writes to it. Record/replay caching (research 11 §3) is
not implemented; every harness run is live. Neither is the LLM judge (research 11 §1e) or a
multi-run report — the four scenarios exist and the rules gate them, but only
`timing_emi_before_salary` has been run against a live model, and only before the date fix.
`comfortable_surplus` in its current form (20,000 opening, expected `OK` with no actions),
`timing_shortfall` and `structural_shortfall_correction` have never been run live.

## Review findings closed (kiro-20260911T180651Z-62b9df29)

Four of the nine landed in this layer. Each was reproduced before it was fixed, and each fix is
covered by tests written first.

- **F2 · the agent could not express uncertain or date-range income.** `upsert_item` now takes
  `certainty` (confirmed, estimated, uncertain) and `latest_day_of_month`, validated in the
  handler and rejected with a corrective string on any other kind, since both describe income
  only. They are passed to the domain **only when set**, so the handler does not depend on the
  two parameters existing. Verified against the real domain, not just fakes: an uncertain
  freelance income of 12,000 lands as `certainty=uncertain`, `latest_date=2026-09-20`, the plan
  reports `in 0`, and the result ends "This income is not counted as money until it arrives" —
  so the smaller total cannot be read as the person being poorer than they are.
- **F3 · the final result withheld consequences.** `describe(None, plan)` now carries each top
  action's `warning`, up to three unpaid items as name, amount, spoken due date and
  consequence (with "and N more unpaid" beyond that), and the first plan warning. Under 60 words
  for a clean plan and under 90 when it is carrying consequences, both asserted.
- **F4 · an OK plan could not complete the understanding check.** The gate was
  `not ctx.last_plan.actions`; it is now `not ctx.state.plan_final`. With no actions the gaps
  list is empty and an empty restatement is accepted, and the prompt's ending rule tells the
  model to ask for the outcome back when there is nothing to change.
- **"Duplicate tool calls" — which turned out not to be duplicates at all.** A recorded call
  appeared to show four `upsert_item` calls for one utterance, in two identical pairs, so we
  built `ToolContext.replay`: it returns the previous result string for a call with the same name
  and arguments already handled in the same turn, without re-running the domain function or
  pushing a second cards message. Keyed on `state.turn`, so the same call on a later turn runs
  normally — a person really can say the same number twice. Session C then measured it properly:
  Pipecat's `LLMService` broadcasts `FunctionCallResultFrame` both upstream and downstream, so
  the recorder saw one call as two frames sharing a `tool_call_id`. The handler had always run
  once, and luna emits one call per fact on both the Responses and Chat services. The guard stays
  as cheap insurance, but it was written against a framework artifact we had misread as model
  behaviour — the kind of mistake only call ids in the recording could settle.

F1, F5 and F6 are `ledgerline/domain/state.py` (Session A); F7 and F8 are `frontend/`
(Session D); F9 is `README.md` (orchestrator). None were touched here.

## Assumptions

- **The base prompt is 572 tokens: over the brief's 450 and over the 540 the orchestrator
  approved.** I could not hit 540 with the owner's new rules in it — the acknowledge-then-act
  latency rule with its example, the confirm-do-not-recite ending, `end_call`, and the tone
  rules. I trimmed everything trimmable first: the hard rules are merged three-into-two, the
  outlier line folded into "if a result carries a question, ask it next", and the duplicate-call
  rule folded into the acknowledgement bullet. Reaching 540 from here means deleting something
  the owner asked for, so the test ceiling is 600 and this is flagged rather than quietly
  missed. Named explicitly to the orchestrator. The rules added after review — income certainty
  and date ranges, one call per fact, say every consequence, and confirm the outcome when
  nothing changes — cost about 75 tokens, and each closes a verified defect. The 450 figure was
  a starting estimate rather than a constraint, and the economics say so: the base prompt is
  cached input at $0.02 per million on luna, so 75 extra tokens a turn is about two
  ten-thousandths of a cent per turn — roughly $0.00002 across a fifteen-turn call. Dropping a
  rule that closes a real defect to save that would be the wrong trade. The ceiling lives in
  `tests/agent/test_prompt.py::MAX_BASE_TOKENS` with the reason beside it.
- **`Literal` enums are not used in the tool signatures.** Pipecat 1.9.0's direct-function schema
  generator has no `Literal` branch (`adapters/schemas/direct_function.py::_typehint_to_jsonschema`),
  so `kind`, `debt_kind`, `chosen` and `reason` are typed `str`, list their allowed values in the
  docstring, and are validated in the handler, which returns a corrective string and pushes
  nothing when the value is wrong. This is the fallback the brief allows.
- **The first handler parameter is annotated `Any`, not `FunctionCallParams`.** With
  `from __future__ import annotations`, Pipecat calls `get_type_hints` on the handler and
  resolves every annotation in the *module's* globals; a `FunctionCallParams` imported inside
  `build_tools` is not there and raises `NameError` at schema-derivation time. `Any` resolves,
  Pipecat ignores the first parameter anyway, and `ledgerline.agent` needs no pipecat import at all.
- **`describe(outcome, plan)` branches on the type of `outcome`**: an `Outcome` gives the item
  line, `None` is the `finalize_plan` line (top two actions plus shortfall or surplus), an
  `Understanding` gives the gaps line. The contract types `outcome` as `Any`, so no signature changed.
- **Money in tool result strings uses plain grouping** ("1,50,000" would be spoken badly by TTS,
  per research 11 §1d), formatted locally in `tools.py`. `cards.fmt_inr` stays the display path.
- **Outliers in the "Needs confirmation" block** are read off an item's free-text `notes`
  containing the word "outlier", since `Outcome.outlier` is transient and the models carry no
  outlier field. If Session A never writes that note the section simply shows open conflicts;
  no domain change is requested for it.
- **`record_understanding` matches a restatement to an action** by the action's target name
  (substring, then `difflib` at ratio 0.8 over same-length windows), falling back to the action
  type's everyday words. Gaps are the targets of the top two actions nobody restated.
- **The number checks only trace values of 100 or more.** Below that a figure is a day of the
  month or a count, not money.

# Simulation phase

Goal: the bot stops repeating itself and stops asking several questions per turn, measured over
five voice-shaped scenarios × five runs against the real prompt and the real tool handlers, with
every rule in `evals/checks.py` at or above 95%.

This section is written as the work happens, so a partial run still leaves evidence.

## What was built

**Five voice-shaped scenarios** (`evals/scenarios/`), each modelled on a defect heard on the
owner's third call rather than on a tidy transcript:

| scenario | what it forces |
|---|---|
| `fragmented_balance` | "I have" / "20,000 in cash and" / "20,000 in bank balance." as three consecutive user turns, then the rent the same way |
| `one_word_answers` | "Nothing." to "what is your next income or expense", then "September." where a day was asked for, then "Nothing." and "Yes." |
| `garbage_opener` | first utterance "Your WhatsApp." — STT noise, not a sentence |
| `correction_and_conflict` | a correction ("actually the rent is fourteen thousand, not twelve"), then a second figure for an item already recorded, and "I do not know" when asked which is right |
| `estimated_income_happy_path` | income as "around forty thousand, nothing is confirmed" (certainty estimated) through plan, agreement, one goodbye and `end_call` |

Fragments needed harness support: `sim_user` may return a list for one scripted turn and
`harness._utterances` appends each element as its own user message with no reply between them,
which is how VAD delivered them on the real call. The strict alternate-turns loop could not
reproduce the shape at all.

**The suite runner** is `evals/run_suite.py`:

```
PYTHONPATH=. uv run python -m evals.run_suite              # 5 scenarios x 5 runs
PYTHONPATH=. uv run python -m evals.run_suite --runs 1     # a cheap look
PYTHONPATH=. uv run python -m evals.run_suite --all        # the four outcome fixtures too
```

Every run goes through the real system prompt and the real tool handlers over OpenAI, text only.
A rule's pass rate is the share of *runs* clean of it, not of turns: three broken turns in one
call is one bad call, and counting them separately hides a scenario that fails every time. A run
that raises counts as failing every check.

**The gate is the pooled rate across the 25 runs, not the per-scenario cell.** With five runs a
cell can only score 0, 20, 40, 60, 80 or 100, so a 95% bar on a cell silently means "never
once" — a much stricter rule than the one asked for. Cells under the bar are printed under the
table as a watch list. `gate_failures` is the exit code; `below_threshold` is the display.


## Run log

Pass rates are the share of the 25 runs (5 scenarios x 5) clean of that rule. Pass 1 was one run
per scenario, a cheap shakedown before spending the matrix.

| check | pass 1 (5 runs) | pass 2 (25) | pass 3 (25) |
|---|---|---|---|
| numbers_traceable | 80% | 96% | 92% |
| one_question_per_turn | 100% | 100% | 100% |
| banned_phrases | 80% | 84% | 100% |
| no_markdown | 100% | 100% | 100% |
| amounts_repeated | 0% | 16% | 80% |
| no_iso_dates | 100% | 100% | 100% |
| silent_before_acting | 100% | 100% | 100% |
| no_repeated_sentence | 100% | 100% | 100% |
| no_question_after_unknown | 100% | 96% | 84% |
| one_goodbye_with_the_end_call | 20% | 16% | 28% |

The two rules the owner's call was about — `one_question_per_turn` and `no_repeated_sentence` —
were already at 100% before any change here: the prompt rewrite Session B had already made
(speak once, after the result) had closed them. Everything below is what the matrix found next.

### F1 · the goodbye and the hang-up could not both happen (pass 1 and 2: 16-20%)

`end_call`'s result was "call ended, say nothing more" and the prompt said never to speak before
a tool. Those two cannot both be obeyed: the model has nowhere left to say goodbye. Every run
ended either "end_call with no goodbye" (silence, the line drops) or "goodbye without end_call"
(a farewell, then a gap the person hears as the bot waiting).

Three things were wrong and each was fixed separately:

1. `silent_before_acting` had no exemption for `end_call`, so even a model that spoke first
   would have failed. A turn whose only call is `end_call` is now exempt; a turn that also
   records something is judged normally. (`evals/checks.py`, two tests.)
2. `phrases.UNDERSTOOD` said only "understood", so nothing bound the farewell to the hang-up.
   Adding "say one goodbye and call end_call in this reply" moved it from 16% to 28% and changed
   the failure mode: the model now emits `record_understanding` and `end_call` *together* in one
   reply, so the instruction arrives after the decision, and the `end_call` result then forbids
   the speech. Half a fix, and the transcripts said why.
3. `phrases.GOODBYE` is now **"call ending, say one short goodbye now and nothing more"**. The
   result is the one place the model is certain to be listening at the moment it must speak. This
   reverses the earlier decision to make the result unspeakable, and it is safe because
   `voice.lifecycle.CallEnder` already waits for the bot to stop speaking before it ends the
   call — Session C built the grace period this depends on. If that ever changes, this constant
   is the only thing to change, as the earlier note said.

### F2 · no amount was ever read back (pass 1: 0%)

Every scenario failed `amounts_repeated`, almost always on the opening balance: the model
recorded 18,000 and said "What income do you expect?". The cause was in the result string, not
the model. `describe` said "created opening balance. in 0, out 0." — no figure — and the prompt
forbids saying a figure that is not in a result, so the model was right not to say it.

`_headline` now uses the domain's own `detail` when it is the label and the amount ("opening
balance 18,000", "rent 11,000") and ignores it when it is prose ("2 conflicts still open"). That
alone took the rule from 0% to 16%; adding "Open each reply with the amount the result names,
then ask" to the prompt took it to 80%.

### F3 · the model added two balances itself (pass 1-3: 60-80% on `fragmented_balance`)

"I have" / "20,000 in cash and" / "20,000 in bank balance." — the model said "That's 40,000
rupees available today", which is arithmetic it must never do, and `numbers_traceable` caught it.
The alternative it chose in other runs was worse: two `upsert_item` calls, and since the domain
keeps one opening balance and ignores its name, the second silently replaced the first and a
person with 40,000 was planned for as if they had 20,000.

The tool adds them now. `ToolContext.balance_total` keeps the parts of one turn and returns the
sum, sent as a correction so the domain overwrites rather than asking which figure is right;
across turns nothing is pooled, because there a second figure is a correction or a conflict and
the domain decides which. The total comes back in the result, where the model may read it.

### F4 · two rules were failing correct behaviour

- `banned_phrases` called "the credit-card minimum" an offer of credit, because the allowed forms
  were spelled with a space. Hyphens are flattened now. It also caught "affect your credit
  record" — the model's paraphrase of the engine's own "nothing reaches your credit report" —
  so "credit record", "credit history" and "credit file" joined the allowed forms. 84% -> 100%.
- `one_goodbye_with_the_end_call` counted farewell *words*, so "Goodbye, and take care." was two
  goodbyes. It counts farewell sentences now, and "You're welcome. Goodbye.Goodbye." is still two.

### F5 · `no_question_after_unknown` was both too loose and too tight (pass 3: 84%)

Reading the transcripts for this one turned up that the rule never caught the defect it was
written for. It derived the item name from everything before the dot in the field, so a bare
field like `monthly_income` — which is exactly what the live call parked before asking "What's
your monthly income?" — produced an empty subject and passed. Both field shapes are handled now,
and there is a test that replays the live turn.

It was too tight in two other ways, each of which failed a live run: it read the whole turn
rather than the question, so "I've noted the credit card is outside this window. Anything else?"
counted as asking about the credit card; and it matched on the item, so parking the rent *amount*
made "When is your rent due?" a violation. It now reads only question sentences and compares the
attribute: an amount question after a parked amount is a repeat, a date question is not.

# Cut: agent layer

Session B's slice of "the cut" (`docs/process/cut-brief.md`): every judgement about language moved
to the model, every number still from the domain. The tools, the prompt, the result strings, the
checks and the scenarios were rebuilt against the new `models.py`; the simulation matrix was rerun
against the pre-cut baseline in "Simulation phase" above.

## Simulation run log

Pass rates are the share of runs clean of that rule. The pre-cut column is pass 3 from the table
above (25 runs). `changed_value_acknowledged` is new with the cut and has no pre-cut figure: it is
the rule that replaces the conflict machinery, so before the cut there was nothing for it to
measure.

| check | pre-cut (25) | cut pass 1 (5) |
|---|---|---|
| numbers_traceable | 92% | 100% |
| changed_value_acknowledged | — | 100% |
| one_question_per_turn | 100% | 100% |
| banned_phrases | 100% | 100% |
| no_markdown | 100% | 100% |
| amounts_repeated | 80% | 40% |
| no_iso_dates | 100% | 100% |
| silent_before_acting | 100% | 100% |
| no_repeated_sentence | 100% | 100% |
| no_question_after_unknown | 84% | 60% |
| one_goodbye_with_the_end_call | 28% | 100% |

Pass 1 was one run per scenario, a cheap shakedown before spending the matrix. Every rule the cut
was judged on cleared its bar first time, including the goodbye at 28% before. Two regressions,
both read off the transcripts and both fixed before the matrix:

- **`amounts_repeated` 80% -> 40%.** Two causes. The read-back rule had been folded into another
  bullet while the prompt was being trimmed to the 620 token ceiling; pre-cut it was its own line
  and worth 64 points on its own (F2). It is its own line again. And Session A's `_FIELD_ATTRIBUTE`
  grew to report the classification flags, so a create read "recorded rent 11,000 due 18 Sep spread
  dated survival survival" — `describe` now leaves `spread`, `survival`, `flexible` and `certainty`
  out: they are how code files an item, not anything the person said, and a change to one would
  have asked them to confirm a word they never used.
- **`no_question_after_unknown` 84% -> 60%.** Two causes, both in the rule rather than the bot.
  A semicolon is not a full stop, so "the electricity amount is parked as not known; when is your
  rent due?" read as one question sentence carrying the word "amount", and the report half failed
  the asking half. Only the clause the question mark belongs to counts now. The other half was a
  real defect: the domain stopped refusing a field id that names nothing, so the model parked
  "optional_expenses" and then asked about optional expenses. `mark_unknown` validates the shape in
  this layer now (requests.md B-cut-1).

Pass 2 was the full matrix, 5 scenarios x 5 runs, 25 live calls.

| check | pre-cut (25) | cut pass 1 (5) | cut pass 2 (25) |
|---|---|---|---|
| numbers_traceable | 92% | 100% | 92% |
| changed_value_acknowledged | — | 100% | 100% |
| one_question_per_turn | 100% | 100% | 100% |
| banned_phrases | 100% | 100% | 100% |
| no_markdown | 100% | 100% | 100% |
| amounts_repeated | 80% | 40% | 68% |
| no_iso_dates | 100% | 100% | 100% |
| silent_before_acting | 100% | 100% | 100% |
| no_repeated_sentence | 100% | 100% | 100% |
| no_question_after_unknown | 84% | 60% | 92% |
| one_goodbye_with_the_end_call | 28% | 100% | 96% |

Every rule the cut was judged on cleared its bar on this pass. Two rules the suite gates on are
still under 95%, and the transcripts say why:

### F6 · the read-back went missing on the first fact of the call (`amounts_repeated` 68%)

`one_word_answers` failed it in all five runs, always on the opening balance, and the other
scenarios failed it on the same shape. The result was two lines — "recorded opening balance 6,000"
and "blocked: income" — and the model read the second as the instruction and asked the income
question. The prompt has asked for the read-back since F2 and gets most of the way; it cannot win
against a line in the result that looks like an order.

So the recording line carries the instruction now, the same lever that fixed the goodbye and the
changed value: `recorded opening balance 6,000; say this back, then ask`. One per result — a turn
that already has to settle a changed figure does not also get asked to read something back, since
a turn holds one question.

### F7 · the bot read a result line out as written

Two turns in the matrix spoke a label verbatim: "missing: electricity amount" and "timing
shortfall: 1,866.68 rupees". Nothing in the prompt said these lines were notes rather than words —
before the cut every result was a sentence, so the question never came up. The Results rule now
opens "Results are notes to you, never words to read out". It is also what produced one of the two
`no_question_after_unknown` failures: reading "missing: electricity amount" aloud put the word
"amount" in the same breath as the next question, and the rule read that as asking again.

### F8 · two more ways to park nothing (`no_question_after_unknown` 92%)

`mark_unknown` refused an unresolvable field id after pass 1, but only checked the shape, so
`essential:rent.day_of_month` — the tool's argument name rather than the field's — still passed
and parked nothing, and the model asked when the rent was due a turn later. The attribute must now
be one the domain actually has. A semicolon is also not a full stop: "the electricity amount is
parked as not known; when is your rent due?" read as one question sentence carrying the word
"amount", so only the clause the question mark belongs to counts now.

## Pass 3 · the matrix, green

| check | pre-cut (25) | pass 1 (5) | pass 2 (25) | pass 3 (25) |
|---|---|---|---|---|
| numbers_traceable | 92% | 100% | 92% | **100%** |
| changed_value_acknowledged | — | 100% | 100% | **100%** |
| one_question_per_turn | 100% | 100% | 100% | **100%** |
| banned_phrases | 100% | 100% | 100% | **100%** |
| no_markdown | 100% | 100% | 100% | **100%** |
| amounts_repeated | 80% | 40% | 68% | **96%** |
| no_iso_dates | 100% | 100% | 100% | **100%** |
| silent_before_acting | 100% | 100% | 100% | **100%** |
| no_repeated_sentence | 100% | 100% | 100% | **100%** |
| no_question_after_unknown | 84% | 60% | 92% | **100%** |
| one_goodbye_with_the_end_call | 28% | 100% | 96% | **100%** |

`PYTHONPATH=. uv run python -m evals.run_suite` exits 0: every check at or above 95% pooled over
25 live calls. 24 of the 25 runs are clean of every rule; the one that is not read back a
supporting figure instead of the amount it had just recorded, which is the one cell still under
the bar (`amounts_repeated` 80% in `correction_and_conflict`) and not the gate.

Three passes of matrix cost about **$0.90**; 1.75M input and 30k output tokens on pass 3 alone,
most of it cached prompt.

### What actually moved the numbers

Every rule that gained did so because an instruction moved out of the prompt and into the result
string the model is certainly reading at the moment it has to act — the pattern the goodbye
proved before the cut (F1) and the coordinator insisted on for the changed value. Three
instructions now ride on results: `confirm which is right before moving on` on a value that
replaced one the person had given, `say this back, then ask` on a value that was recorded, and
the existing `say one short goodbye now and nothing more`. One per turn, because a turn holds one
question. Each one is in the prompt as well; the prompt alone was worth 40-80%, the prompt plus
the result is worth 96-100%.

### After the matrix

`describe` stopped appending `missing:` to a result that is explaining the plan: it is the
gathering prompt, and ending the finalised plan with it points the model back at a question when
it should be walking through what to do. In practice `finalize_plan` only runs with no blockers
and therefore no gaps, so the matrix could not have caught it; the explain-again branch can reach
it after a change reopens a gap. One line in `describe`, one test, and the suite stayed green —
but it landed after pass 3, so no live run has exercised it.

## State of the layer

- `uv run pytest tests/agent` — **351 passed, 1 deselected** (the `llm` smoke scenario).
- `uv run ruff check ledgerline evals tests/agent` clean; `uv run lint-imports` 4 contracts kept.
- `ledgerline/agent/tools/` **867 -> 878 lines**. Not smaller: `resolve_conflict`, the restatement
  matcher and the prose assembly went (about 150 lines), and field-id validation, the flag
  handling and the three result instructions came in, with the comments that say why each exists.
- Nothing committed.

### Left, honestly

- `describe`'s `parked` argument is still passed separately from `readiness`, because `Readiness`
  carries no unknowns. It is one frozenset built in the handler; if A ever puts the unknowns on
  `Readiness` this parameter goes.
- A flag change reads "rent spread: now spread". Correct and a little clumsy; `label_for` would
  have to know that "spread" is both the attribute and its value to do better, and that is a
  domain label.
- `docs/process/luna-capabilities.md` lists prompt lines that duplicate tool-field descriptions and
  result-carried instructions. Not acted on: it arrived after the matrix, and every line it would
  cut is a line one of the three passes above paid for. It wants its own pass and its own matrix.

## Verification of the cut (session B, fresh)

Checked against `docs/process/cut-brief.md` rather than against the report above, then the report's
own numbers re-run. `uv run pytest tests/agent` → **356 passed, 1 deselected** (351 before the
five tests added below); `uv run ruff check ledgerline evals tests/agent` clean; `uv run
lint-imports` 4 contracts kept. Every count the previous section claims is true as stated.

### Correct

- **Tool surface matches the brief.** `upsert_item` (no `is_correction`), `remove_item`,
  `mark_unknown(field, not_applicable=False)`, `finalize_plan`, `record_understanding(confirmed)`,
  `end_call`. `resolve_conflict` is gone from every source file; the only surviving mentions are a
  test asserting its absence and stale fixture arguments (below).
- **A changed value carries its own instruction.** `describe._change_lines` appends
  `phrases.CONFIRM_CHANGE` to the change line, capped at one instruction per result by the `asked`
  flag. This was the risk flagged at handover — that "ask which is right" would be left to
  unprompted model behaviour, the class that ran 0-80% pre-cut while code-carried rules ran 100%.
  It is carried by the result, and the matrix agrees: `changed_value_acknowledged` 100%.
- **`test_integration_domain` runs the real domain.** Imports `state`, `engine` and `cards`
  directly; the three `Mock` hits in the file are in the cards-push spy, not in a domain call.
- **The matrix meets the brief's acceptance.** `one_question_per_turn`, `no_repeated_sentence`,
  `silent_before_acting` all 100%; `numbers_traceable` 100% against a pre-cut 92-96%;
  `changed_value_acknowledged` 100% against a 95% bar.

### Wrong — two defects in number provenance, both fixed here

Found by replaying a correction through `_sources_up_to` rather than by reading it. Both are in
`evals/provenance.py`, both defeat the retirement half of `numbers_traceable`, and both were
invisible to the existing tests for the same reason: the four retirement fixtures still use
**pre-cut result strings** (`"updated rent. in 45,000, out 12,000."`) which name only the winning
figure, where the real post-cut result names both.

1. **A superseded figure was retired and then immediately re-authorised.** `allowed -= superseded`
   ran *before* `allowed |= from_result | from_args` in the same iteration, and the change result
   is `rent: 11,000 -> 12,000` — so the losing figure came straight back in from the result that
   retired it, and stayed sayable for the rest of the call. Replayed: the assistant says "your
   rent of 11,000 rupees" two turns after the correction and `numbers_traceable` returns no
   violation. The retirement is now applied after the union.
2. **Item identity did not match the domain's (A-10b).** `_item_key` used `normalise_name` alone,
   so `essential:rent` and `essential:my rent` were two subjects where `state.items._find` sees
   one, and a correction spoken as "my rent" retired nothing. Mirrored now through the exported
   `possessive_of`: exact key first, possessive fallback second, and no retirement at all when the
   name could be either of two recorded items — the domain creates a third item there rather than
   guessing, so the checker must not retire a figure the domain kept.

Five tests, written first and failing for the right reasons: the correction against a real change
result, the turn making the change still allowed to name both, "rent" then "my rent" retiring,
"my loan" and "his loan" not retiring each other, and the ambiguous bare name retiring nothing.

### Missing, and one thing to decide

- **The prompt ceiling is enforced against an estimate, not a tokenizer.** `approx_tokens` is
  `len(text) // 4`; the prompt is 2,471 chars, hence "617 tokens". OAP's non-negotiable is to
  measure per surface with tiktoken, which is not a dependency and which this session may not add
  (orchestration rule 3). Either tiktoken goes in `pyproject.toml` as a dev dependency or the
  ceiling stays explicitly an estimate — a request, not a fix.
- **Fixture drift in `tests/agent/test_checks.py`.** Four retirement fixtures pass
  `is_correction: True`, an argument the tool no longer has, and two parking fixtures pass
  `reason="does_not_know"` / `"user_does_not_know"`, values `UnknownReason` no longer defines.
  The checks read neither field, so no behaviour is affected, but the fixtures no longer describe
  a transcript the harness could produce. They are what hid defect 1.
- **`describe`'s `missing:` suppression has no live run**, as the previous section says. The next
  matrix covers it.

### The eval phase · matrix pass 1 after the verification fixes

First matrix with the repaired `numbers_traceable`, the new sixth scenario and the new rule.
30 live runs, exit 1.

| check | cut pass 3 (25) | eval pass 1 (30) |
|---|---|---|
| numbers_traceable | 100% | 93% |
| changed_value_acknowledged | 100% | 100% |
| implausible_amount_confirmed | — | 77% |
| one_question_per_turn | 100% | 100% |
| banned_phrases | 100% | 100% |
| no_markdown | 100% | 100% |
| amounts_repeated | 96% | 80% |
| no_iso_dates | 100% | 100% |
| silent_before_acting | 100% | 100% |
| no_repeated_sentence | 100% | 100% |
| no_question_after_unknown | 100% | 100% |
| one_goodbye_with_the_end_call | 100% | 100% |

The three that moved are not three regressions. One is a real defect the repaired check can now
see, one is the new rule measuring the thing it was built to measure, and one was the rule itself
being wrong.

**`implausible_amount_confirmed` 0 out of 5 on `stt_implausible_amount`, and the result string was
the cause.** The model was told to do it: the result read `recorded rent 12; say this back, then
ask`, and it said it back — "Your rent is twelve rupees. What income will arrive between now and
the tenth of October?" — identically in all five runs, and again for the salary. It does
challenge the figure, but only after the persona volunteers the correction, one turn late every
time. So on an implausible amount the read-back instruction is now **replaced** rather than joined
by `<name> looks small, confirm it before moving on`: a turn holds one question, and "say it back"
and "check it" cannot both be it. Floors in `describe.IMPLAUSIBLE_BELOW`, stateless, no outlier
list, nothing kept between turns; `evals.checks` holds its own copy on purpose, since an eval that
imported the product's threshold could not notice the product's threshold drifting.

**`amounts_repeated` was failing correct behaviour.** A call that carries the amount again while
recording the salary *date* gets back `recorded salary date 1 Oct` — the domain reports the date,
because the date is what moved. The rule demanded the amount anyway, so the model was failed for
not speaking a figure no result offered and the prompt forbids inventing. The read-back is owed
for what the result reports, not for every argument the call happened to carry.

**`numbers_traceable` 93%: one real defect, one instrument bug.**

The real one is in `docs/process/prompt-provenance.md` under "Open failing cases":
`correction_and_conflict` turn 20 spoke a shortfall of thirteen thousand against a plan that
said `out 14,000, lowest 1,000, surplus 1,000`. The model did arithmetic and read the answer out
as plan output. It is the named failing case for the never-invent rule and it is not fixed here:
it is a prompt or result-shape question and it belongs to the luna pass.

The instrument bug was in `numbers_in`: the word pass did not stop at a full stop, so "Day thirty.
Thirty-eight thousand rupees." parsed as **68,000**. The 38,000 the person really said then counted
as never said — and since a recording tool's arguments are struck from its result when the person
did not say them, the figure disappeared from the trusted result too and the assistant was failed
for speaking a number it had been handed. It masks invented figures just as easily as it invents
violations. Clause boundaries end an amount now, which is the safe direction: the worst case is
reading "forty-five thousand, two hundred" as two figures rather than inventing a sum nobody said.

Two smaller things from the same run. Five concurrent copies of a scenario can finish inside one
second and overwrite each other's transcript — the evidence for one failing run was lost that way
— so run files get a suffix now. And three more `amounts_repeated` fixtures still carried pre-cut
result strings (`"created rent."`, no figure in it); they are post-cut strings now, which is what
made the over-strictness visible in the first place.

### Eval pass 2 · `stt_implausible_amount` only, five runs

Run narrowed to one scenario at the owner's instruction, so this measures the implausibility fix
and nothing else. `PYTHONPATH=. uv run python -m evals.run_suite stt_implausible_amount --runs 5`,
443,715 in / 7,276 out tokens, 91 s.

| check | eval pass 1 | pass 2 as run | pass 2 replayed after the two check fixes |
|---|---|---|---|
| implausible_amount_confirmed | 0% on this scenario | **100%** | 100% |
| numbers_traceable | 100% on this scenario | 40% | **100%** |
| amounts_repeated | 20% on this scenario | 80% | **100%** |

**The instruction worked, first time and in every run.** The model now asks before it accepts:
"You said rent is twelve rupees; is that correct, or did you mean twelve thousand rupees?" —
where the same model, given "recorded rent 12; say this back, then ask", had said "Your rent is
twelve rupees" in five runs out of five. One line moved from the prompt into the result, and the
rule went from 0% to 100%. That is the fourth time this lever has worked and the first time it
was predicted in advance rather than discovered.

Both remaining failures were the checks being wrong, and neither is a model defect.

**`numbers_traceable` 40%: two rules told the model opposite things.** `CONFIRM_AMOUNT` asks it
to settle a figure that looks too small, and the only useful way to ask is to offer the reading
the person probably meant — "or did you mean twelve thousand?". That twelve thousand is in no
tool result and no user turn, so the traceability rule failed it for obeying the instruction the
other rule had just given. A figure offered inside a question is now sayable, but only in a turn
whose own result carried `CONFIRM_AMOUNT` and only inside the question: offering a reading is a
question, telling somebody what they pay is a claim. Two tests pin both edges. The constant is
imported from `phrases` rather than copied, unlike the implausibility floors — this rule is
*about* the product's instruction and should follow it if the wording changes, where the floors
exist precisely to judge the product independently.

**`amounts_repeated` 80%: the pass-1 fix was scoped too widely.** It skipped the read-back when
the result did not name the amount, but read the *whole* result — and the totals line under the
recording line ("in 45,000, out 12,000, lowest 1,000 on 30 Sep") names it. So a turn recording
only the salary date still demanded the salary figure back. Only the first line counts now, which
is what `_recorded_figures` already said in its own docstring.

Replayed over the five saved transcripts with both fixes: **5 of 5 runs clean of every rule.**
Replay is not a fresh matrix — it is the same five calls — but it says the model's behaviour in
them breaks nothing, and that the two failures were in the instruments.

The transcript-collision fix earned itself immediately: two runs finished in the same second and
both survived, as `-222027.json` and `-222027-2.json`.

### AI wrong · the sentence to quote when anyone asks why the never-compute rule exists

`correction_and_conflict`, first post-cut matrix, 2026-09-12. The tool result said:

    in 0, out 14,000, lowest 1,000 on 10 October
    surplus 1,000
    provisional: shop, electricity

The bot said: *"if it doesn't, rent uses the available money and leaves a shortfall of thirteen
thousand rupees"*.

**The plan had a surplus of a thousand rupees and the person was told they were thirteen thousand
short.** Not a rounding error and not an untraceable-but-harmless figure: out 14,000 minus lowest
1,000, computed by a language model and spoken as the outcome of a financial plan, in the
direction that frightens somebody who is already worried about money. Every figure in the result
was correct. The model was not asked to compute anything. It computed anyway, because it was
asked a question — what happens if the uncertain income never arrives — that the result had no
figure for.

Two things follow, and the second is the one worth keeping.

The rule "the LLM never computes; every number it speaks came back in a tool result" is not
belt-and-braces. This is what it is for, and it held: `numbers_traceable` caught the figure
precisely because it was not in any result. The guard worked even though the prompt rule did not.

And a model asked a question its result cannot answer will answer it anyway. The fix is not a
sterner prohibition — the prompt already said never to invent, add, subtract, round or estimate,
in the hard rules, and the model did all four. The fix is to leave nothing to derive: the result
now states the shortfall even when it is zero, and says what the exclusions did to the figures
rather than naming them as a category. `surplus 1,000, shortfall 0` and `already left out of
these figures: shop, electricity`. Approved and implemented; the matrix cell that proves it is
`correction_and_conflict`, and it has not been run yet.

### `state_matches_facts` · the check the suite never had

Every other rule in `evals/checks.py` reads what the bot **said**. This one reads what it **wrote
down**, which is what the plan is built from. It exists because of a defect all eleven of the
others passed: `fragmented_balance` gives the person 20,000 in cash *and* 20,000 in the bank, said
as three fragments, and in fifteen consecutive post-cut runs the model made one balance call,
recorded 20,000, and planned the month on half their money. Nothing invented, the read-back
matched the result, no value changed — nothing for the other rules to see.

It compares the run's final state against the persona's hidden facts, which the harness now
records into every transcript so a run carries its own answer key.

**Three rounds of tuning, each measured by replaying every saved run.** The first version failed
**84%** of 283 runs and would have been noise rather than a net. What it was getting wrong is
worth keeping, because each fix is a statement about where the line sits:

| version | pass rate over 283 saved runs |
|---|---|
| compare state against the persona's notes | 16% |
| ...only for facts the person actually stated in the call | 28% |
| ...matching a figure under any name, and excusing a parked amount | **81%** |

- **Judge the conversation, not the notes.** `hidden_facts` is the persona's whole truth and the
  scripted turns deliberately hold some of it back — the "Nothing." in `one_word_answers` is the
  person declining to mention the phone EMI, not the bot losing it. A fact is owed only if its
  amount was said in a user turn.
- **The figure under another noun is the same fact.** A persona's "client payments" recorded as
  "freelance income" is the coach paraphrasing. What the person calls their money is language, and
  the cut gave language to the model; the check is about the money. Matching on name alone failed
  all 51 runs of `estimated_income_happy_path`.
- **An item on the books with no figure is not a lost fact when the person declined to give one.**

What the 19% that still fail are saying — and these read as real:

| mismatch | runs | reading |
|---|---|---|
| `fragmented_balance` opening_balance 20,000, person has 40,000 | 21 | the defect above |
| `correction_and_conflict` electricity never recorded | 12 | the conflict scenario's own shape; worth a look |
| `comfortable_surplus` opening_balance 8,000, person has 20,000 | 3 | known artifact: those files were recorded while that name held the 8,000 balance and were left byte-identical rather than relabelled |
| `fragmented_balance` credit card is 1,200, person said 3,000 | 1 | **the minimum due recorded as the amount due** — the plan pays 1,200 of a 3,000 debt |
| `one_word_answers` rent is 0.00, person said 9,000 | 2 | rent recorded as zero |

The last two are new defects that no pass rate has ever reflected. Neither is fixed here.

### The dropped half of the balance · diagnosis and fix

The transcripts say it plainly. All three fragments reach the model in one turn, and it answers
with a single call:

    [1] user: I have
    [2] user: 20,000 in cash and
    [3] user: 20,000 in bank balance.
    [4] assistant: You have 20,000 in cash; how much income will come in during the next 30 days?
         CALL upsert_item {'kind': 'balance', 'name': 'cash', 'amount': 20000}
         RESULT 'recorded opening balance 20,000; say this back, then ask'

`ToolContext.balance_total` was built to add the parts of one turn and is simply never given a
second part. The result then tells the model to speak and ask, and the turn ends.

The fix is the same lever as the other four, and it goes on the balance result because that is
the sentence the model is certainly reading at the moment it could still make the second call —
the tool loop allows up to four rounds in a turn, so an instruction arriving with the first
result is in time:

    recorded opening balance 20,000; record any other amount they named before replying,
    then say the total back and ask

This is one procedure, not two questions — "one question a turn" governs what is asked of the
*person*, and the parts must be recorded before the reply or the total read back is wrong. It
replaces the plain read-back on balance results only. Implemented with a string-level test;
**unrun**: the matrix cell that proves it is `fragmented_balance`, and `amounts_repeated` needs
watching on that cell, since the read-back now sits at the end of a longer instruction.

### Two money-wrong defects, split by era — and a correction to my own report

I reported a card recorded as 1,200 against a stated 3,000, and a rent recorded as 0.00 against a
stated 9,000, as live defects. **Both are pre-cut only.** Their transcripts still carry
`is_correction`, an argument the cut deleted; they are from 20:14 and 20:24, and the cut landed at
21:35. Neither occurs in any post-cut run. Replaying a check over every saved transcript mixes two
different products, and I should have split the eras before naming anything a live defect.

Split properly, `state_matches_facts` reads:

| era | runs | failed | pass |
|---|---|---|---|
| pre-cut | 195 | 25 | 87% |
| post-cut | 88 | 26 | 70% |

| post-cut mismatch | runs |
|---|---|
| `fragmented_balance` opening_balance 20,000, person has 40,000 | 15 |
| `correction_and_conflict` electricity never recorded | 8 |
| everything else | 1-2 each |

**The card defect is live after all, inverted.** Reading every post-cut `fragmented_balance` run:
`amount` is **3,000 in all thirteen** that reach the card — correct every time — but `min_due` is
**3,000 in four of them**, the full balance sent as the minimum. It is the mirror of the pre-cut
bug and it costs the person the same way. A minimum equal to the balance means paying the minimum
saves nothing, so `PAY_MIN_DUE` — the one cheap action the engine can offer on a card — quietly
stops existing, and somebody who could have paid 1,200 this month is planned as owing 3,000.
`state_matches_facts` could not see it: `amount_due` was right, and the check only compared that.
It compares `min_due` now, with three tests.

**This is the case where the result-carried lever does not apply.** `describe` already reads both
figures back — `recorded hdfc card amount due 3,000 minimum due 1,200; say this back, then ask` —
so in the four bad runs the string said "amount due 3,000 minimum due 3,000" and the model made
the swap with the evidence in front of it. Four for four became four for five. The fix goes where
the luna report says a WHAT belongs, the field description:

    min_due: Credit cards only, and only when the person gives it: the smaller sum the card
        will accept this month instead of the full amount. Never the same as amount -- a
        minimum equal to the whole balance is not a minimum. If they did not say one, leave
        it out.

`amount` now says "the FULL amount for this cycle" rather than "the total due", since "total due"
and "minimum due" are one word apart. A test pins the existing double read-back so nobody deletes
the second figure believing it unused.

**The rent 0.00 has no post-cut counterpart.** The nearest post-cut mismatch is one run of
`one_word_answers` recording rent as 5,000 against 9,000, and reading it the persona had drifted
from its own hidden facts — it answered "Two thousand rupees" to a question about regular
payments. That is the simulated user improvising, not the bot losing a figure. One occurrence in
fifteen; recorded, not fixed.

**The stale recordings are documented in `evals/runs/README.md`** rather than relabelled: the
three `comfortable_surplus` files from 11 September were recorded while that name held the 8,000
balance, so `state_matches_facts` is right and the pairing is stale. The same file names the
pre-cut boundary (`20260912-2135`) and the pre-ISO-date-fix recording, so any future replay number
can say which era it covers.

## Frozen for the commit phase · 12 September

Stopped on the owner's instruction. Nothing committed. Final state: `uv run pytest tests/agent`
**392 passed, 1 deselected**; whole repo **871 passed, 8 deselected**; `uv run ruff check
ledgerline evals tests/agent` clean; `uv run lint-imports` 4 contracts kept.
`ledgerline/agent/prompts/v1.md` was never edited in this session, so no container rebuild is
owed.

### Queued, unrun, waiting on a spend decision

Four matrix cells, each with its named failing case. None has been measured live.

| cell | change | named case | measure |
|---|---|---|---|
| the 13,000 | `surplus X, shortfall Y` always as a pair; `already left out of these figures:` | `correction_and_conflict` | `numbers_traceable` |
| the balance total | balance results carry "record any other amount they named before replying" | `fragmented_balance` | `state_matches_facts`, watch `amounts_repeated` |
| the card fields | `min_due` / `amount` field descriptions rewritten | `fragmented_balance` | `state_matches_facts` on `min_due` |
| the state assertion | `state_matches_facts` itself, live rather than replayed | all six | its own pooled rate |

The luna pass is not started. `docs/process/prompt-provenance.md` holds the batching decision
(C1/C2/C3/C5 in one matrix, bisect only on a regression; C6, C7, C8 and the A additions each
their own) and the one open failing case.

### Kiro review 13, held — but one finding lands on unrun work

Held per instruction, and nothing here is fixed or verified. Recording only the part a successor
needs before running the balance cell:

**F1 disputes the fix that cell is meant to prove.** My change puts an instruction on the balance
result asking the model to record the other part before replying; F1's position is that
`balance_total` is model-dependent by construction and that the components should be recorded in
code instead. The two are not alternatives at the same level — mine is cheaper and is the lever
that has worked four times out of five; F1's removes the dependency rather than nudging it, and
is the correct answer if the cell comes back under the bar. **Run the cell before choosing.** If
`state_matches_facts` still reports 20,000 against 40,000, the instruction has failed in the one
place the model was certainly reading, and that is the evidence for doing it in code. F1 also
asks for a regression that feeds the exact fragmented utterance and asserts a final opening
balance of 40,000 rather than asserting that two calls would add correctly — that test does not
exist and should, whichever fix wins.

**F2 is about a run this session already has on file.** It cites `fragmented_balance` finalizing
after recording only cash, rent and salary and reporting a 54,000 surplus. That is the same class
`state_matches_facts` was built to catch, and the check does flag those runs — but for the missing
items, not for the finalization. Readiness is Session A's file; the eval-side question, which is
mine, is whether a check should fail a run that reaches `plan_final` while categories the person
never addressed are still open. It is not written, and no pass rate reflects it.

F3 and F4 are `ledgerline/domain/` and belong to Session A.

## Review 13

Unfrozen for F1 and F2. One matrix cell served both, plus Session A's two knock-ons. Gates:
`uv run pytest tests/agent` **401 passed, 1 deselected**; `uv run ruff check` clean;
`uv run ruff format --check .` 89 files already formatted; `uv run lint-imports` 4 contracts.
Spend: two `fragmented_balance` cells, 5 runs each, about $0.14 of the $0.50 approved.

### F1 · the fragmented balance, both halves

Two defects, and the run says both were real because fixing one exposed the other.

**The code half.** `balance_total` dropped its parts whenever `state.turn` moved. That is the
commonest case there is and not an edge: VAD cuts the utterance, the model answers the cash, the
bank fragment lands in the next turn — and the parts had just been thrown away, so it replaced
the cash instead of adding to it. Parts now live for the whole call, keyed by normalised name; a
name already seen is that part again however late it comes back; `remove_item(balance)` clears
them all. No heuristic for a name that sounds like a total: if somebody restates the whole balance
under a new word the sum is spoken back and they can correct it, which is a better failure than
silently planning on half. Three tests, including the cross-turn regression.

**The result half**, queued since yesterday and now measured: the balance result asks the model to
record any other amount before replying. It works — and in the live runs the second call now
arrives in the *same* turn, so the two fixes are belt and braces rather than duplicates.

**`state_matches_facts` on `fragmented_balance`: 0% before, 100% after.** All five runs store
40,000. Every one of the fifteen post-cut runs before this stored 20,000.

**The first cell found a regression the fixes caused, which is why cells are run.** With the parts
adding, the domain reported `opening balance: 20,000 -> 40,000` and `describe` attached `confirm
which is right before moving on` — so the result asked the person to choose between half and all
of their own money. `changed_value_acknowledged` went to **0% in 5 of 5**, and the model was right
to refuse the question. A balance that moved is never a disagreement: the tool owns that
arithmetic and the figure is the sum of the parts, so there are no two competing values. Balance
changes carry `say the total back and ask` instead. Back to 100% in the second cell.

### F2 · readiness · no code gate, and why

Recorded as the reasoning, not just the outcome. `blockers` is the opening balance and the income
question and nothing else, so a call with a balance, an income and one essential is READY — which
is how `fragmented_balance-20260912-220810` finalised on cash, rent and salary and reported a
54,000 surplus with the groceries, the card and the gym never asked about.

A category-level gate in code was rejected: the cut put discovery with the model on purpose, and
"has anybody established whether there are debts" answered in code is a questionnaire wearing a
different hat. `state_matches_facts` already fails a run that finalises while items the person
actually stated are missing, which is the real failure in that run. What code knows and the model
does not is the single turn when nothing is blocking any more, so that turn gets one stateless
line: `ready to plan; if you have not yet asked whether anything else goes out this month, ask
once, then finalize_plan`. Emitted only at `Phase.READY`, never while explaining the plan.

Cost nothing: `one_question_per_turn` and `no_question_after_unknown` both 100% in the same cell.

### Session A's knock-ons

- **The longer `missing:` line.** A's `missing_fields` now lists an undated essential's due date,
  so the line the model reads grows by one item per undated essential. Watched on the same five
  runs: `one_question_per_turn` 100%, `no_question_after_unknown` 100%. No date-chasing seen; if
  it appears later the fix is the `spread` field description, not the domain.
- **The new engine warning.** `describe` passed `plan.warnings[0]` through whole, and A's string
  is a finished sentence with a full stop — "rent has no date; spread across the month." Every
  other line in a result is a compact fact behind a label, and the one time a bare label reached
  the model it was read out verbatim. The carrier changed here rather than the engine string:
  warnings are prefixed `note:` and lose a trailing stop, so the line reads as something to
  paraphrase rather than speech ready to say. Two tests.

### Open, found by this cell, not fixed

`numbers_traceable` 80%: one run spoke "paying only the minimum leaves 1,800 rupees still due",
which is 3,000 minus 1,200. Reading that run, the engine returned a plan with a **surplus of
63,500 and no actions at all** — and the model invented two actions and the remainder to go with
them. It is the 13,000 defect's family: a result that says there is nothing to do gives the model
nothing to explain, and it fills the gap. Distinct enough to be its own case, and it wants the
same treatment — the figure stated so nothing is derived, which for `PAY_MIN_DUE` means the
engine naming what stays unpaid. That is Session A's file; written up for the orchestrator rather
than fixed here.

### B-13 · a plan that needs nothing

My half of the defect the review 13 cell turned up, routed by the orchestrator and recorded in
`requests.md` under B-13. A's half is the `PAY_MIN_DUE` remainder.

`describe` now says, when `finalize_plan` comes back with no actions **and nothing unpaid**:

    no actions needed: every payment is covered in full; explain the lowest point and propose nothing

The second condition is the boundary the balance regression taught, applied before it could bite:
an instruction has to be true of the case it rides on, and "every payment is covered in full"
printed beside a list of unpaid bills is the one lie that matters — it tells somebody who is short
that they are fine. A plan with no actions because it is UNSOLVABLE gets nothing; the unpaid rows
already say what is wrong.

`test_a_clean_plan_stays_short` went from 25 words to 35, which is a real budget being spent and
is noted as such in the test. The budget exists so a result does not become a speech the model
reads out. The fifteen words bought here are the ones that stop it writing a speech of its own.

**Cell: `fragmented_balance`, five runs. Every check 100%, all five runs clean of every rule.**
`numbers_traceable` 80% -> 100%. Spend: about $0.07, $0.21 of the $0.50 approved in total.

| check | cell 2 (before) | cell 3 (after) |
|---|---|---|
| numbers_traceable | 80% | **100%** |
| state_matches_facts | 100% | 100% |
| changed_value_acknowledged | 100% | 100% |
| every other rule | 100% | 100% |

### `actions_match_plan` · zero spend

`numbers_traceable` guards the numbers; nothing guarded the advice. Written offline, replayed over
the 103 post-cut saved runs, never run against a live model.

**94% pass.** Two narrowings on the way, both from reading failures rather than from theory: 59%
when "keep", "set aside" and a bare "pay" counted as proposals — nearly all of those were correct
sentences, since "keep 11,000 available for rent by the eighteenth" describes the plan's own
timeline — then 93% with one verb family per `ActionType`, then 94% once a sentence naming any
item the plan does contain is authorised, which stopped it failing "if you don't move it, the
500-rupee streaming payment may be taken before your salary arrives" for mentioning the salary.

All six survivors read, all one shape: no actions in the plan, and the bot manufactured an action
with a consequence. The clearest is independent of the run that prompted the check —
`one_word_answers-20260912-213637` announced "your top action" and "your second action" against a
plan whose only content was a 3,600 surplus and nothing to do. So the check has caught a real
defect it was not written for, which was the bar for leaving the watch list.

Of the five runs recorded after the B-13 no-actions line landed, five are clean. The 94% covers a
period that contains the defect and not its fix.

Limit worth stating: it judges proposals that name an item. "You should hold some of that back"
names none and passes, and nothing here can see it.

Gates: tests/agent 410 passed, ruff check clean, ruff format --check clean, lint-imports 4
contracts. `REPORT.md` §2.3 and §10.5.

## Observability phase · ponytail list (carried forward, do before reporting the phase done)

- **Move `spoken_day` out of `prompt.py` into a leaf module and restore the module-scope import
  of `phrases` in `turn_block`.** The function-level import there is deliberate and commented —
  `tools.describe` imports `spoken_day` from `prompt`, so the pair deadlock at module scope, and
  two copies of a sentence that must stay identical was the worse option — but it is not the
  final shape. Agreed with the orchestrator to keep it for now and fix it in the phase's ponytail
  pass, with the census showing the cycle gone.

### Step 4 · carried figures, measured

Two scenarios, `returning_confirms_all` and `returning_changes_rent`, both hydrated the way C's
session will hydrate from the store: the items go into the state through `upsert` and are then
marked `carried`, so the plan starts blocked exactly as it will in production. The suite is eight
scenarios now.

**Both cells, 5 runs each: every check 100%, all ten runs clean of every rule.** About $0.10.

| check | returning_confirms_all | returning_changes_rent |
|---|---|---|
| carried_confirmed_before_plan | 100% | 100% |
| state_matches_facts | 100% | 100% |
| numbers_traceable | 100% | 100% |
| every other rule | 100% | 100% |

`state_matches_facts` at 100% on `returning_changes_rent` is the one worth naming: the person's
rent went up to 14,000 between calls, the carried figure was 12,000, and the recorded state ends
on 14,000 in all five runs. The carried value did not survive contact with the person saying
otherwise, which is the entire point of reading it back.

**The first cell found another two-rules-disagree case, the third of the phase.** `numbers_traceable`
failed 3 of 5 on `returning_confirms_all`, flagging 12,000, 45,000 and 3,400 — the very figures the
carried line had just instructed the coach to read back. They reach the model through the
greeting's prompt block, where there is no tool result yet to name them, so the traceability rule
saw an invented number. The figures came from the store, which is a source; the transcript now
records `carried` alongside `hidden_facts`, and `provenance.carried_numbers` authorises them. A
figure that was never carried is still not sayable, with a test for that edge.

Same shape as the implausible-amount question and the balance total before it: the result-carried
lever is strong enough that a correct instruction obeyed will fail a rule that has not been told
about it. Three times now, and each time the instruction was right and the rule was incomplete.

## Observability phase · ponytail pass

Three cuts, all applied, suite and gates green after each. 489 tests across agent, judge and
memory; ruff check and format clean repo-wide; lint-imports 7 kept 0 broken.

**`spoken_day` moved to `phrases.py`, and the function-level import is gone.** This was the named
item carried from step 4. `describe` needed `spoken_day` from `prompt`, and `prompt` needed the
carried-line constants from `phrases`, so the two formed a cycle that had to be broken with an
import inside `turn_block`. `phrases` was already the leaf — it imports nothing but
`domain.models` — so `spoken_day` belongs there and both sides now import downwards at module
scope. Net: one function moved, one comment about a cycle deleted, one import restored to where
imports go.

**One transcript renderer instead of two.** `judge.llm` and `memory.extractor` had near-identical
six-line functions turning a recording into text for a model. The contract already allows
`memory` to import `judge`, so there is one `judge.llm.transcript(recording, *, with_tools=True)`
now. The flag earns itself rather than being speculative: the judge needs tool results, because
half of what the coach says is something a result told it to say and a judge blind to results
grades the coach for obedience; the extractor must NOT see them, because tool results are full of
figures and a note carrying a figure is the one thing the extractor may never produce. Two
callers, two settings, opposite reasons.

**Six dead `ask=` kwargs deleted** from the `Unpaid` fixtures in `test_describe.py`. A removed
the field; pydantic ignored the extra key, so nothing failed and nothing would have — which is
exactly why it needed deleting rather than waiting to be noticed.

Line counts, `ledgerline/judge/` and `ledgerline/memory/` together: **562**. What went: two
duplicate renderers became one (-14), the cycle comment and its import (-7), the dead kwargs
(-6). Net about **-27** across the phase's files, against roughly 1,050 added.

Nothing else was cut. The rest of the phase is bounds and provenance — the schema limits in
`vocabulary.py`, the three code-side checks in `extractor.py`, the `applies_when` predicates —
and each of those is the reason a module exists rather than decoration on it.

### Check sixteen · `claimed_values_recorded`

From C's third live call: STT heard "my red went up to" with the amount in the next fragment, the
bot said "I've noted rent as 13,000 rupees" and called no tool. State kept 11,000, the profile
kept 11,000, and every check passed — `numbers_traceable` because the person really did say
13,000, `state_matches_facts` because no hidden fact contradicted the state.

A claim is a receipt. The person hears "noted" and stops repeating themselves, so a claim with
nothing behind it is worse than silence: silence at least leaves them trying. The rule is that a
coach sentence carrying a claim verb and a figure must have that figure in some tool call's
arguments or result by that point in the call. Verbs taken from the saved runs, not imagined.

**Replayed over all 343 saved runs: zero false positives, and the single flag is C's live call.**

| era | runs | flagged |
|---|---|---|
| pre-cut | 216 | 0 |
| post-cut | 127 | 1 — `voice-9876500042-…-001039`, C's call, "I've noted rent as 13,000 rupees" |

The first version used a two-turn window and flagged six runs for true statements — "I've already
recorded rent of eleven thousand" refers to a call made ten turns back. The window is the whole
call to date now. That is both simpler and truer: the defect is a figure recorded **nowhere**.

### The lever held, and the cell found something else

`fragmented_correction` reproduces C's call: a returning caller correcting a carried rent through
a garbled noun, with the hidden fact set so a lost correction fails `state_matches_facts` too.
Smallest lever first, per the orchestrator: the `upsert_item` docstring now says to call it
**before** telling anybody you have noted anything, and why. No code-side guard.

**5 runs: `claimed_values_recorded` 100%.** The bot recorded before it claimed, every time.

Two other cells came in under the bar and both are real:

- **`state_matches_facts` 60% — the correction landed on the wrong item.** Reading run 3: the
  persona volunteered the rent change cleanly at turn 1 and the bot recorded it correctly; the
  scripted garbled fragments then arrived as a second statement of the same thing, and the bot
  filed "My red went up to / thirteen thousand" as **an opening balance of 13,000** — a figure
  nobody gave for that field. Given an unintelligible noun it guessed the item rather than asking.
  That is a different defect from the one this work was for, and it is not fixed.
- **`carried_confirmed_before_plan` 80%** — one run planned without saying the carried figures
  back.

Scenario flaw to note: the persona answers the correction naturally before its scripted fragments
land, so the garbled version arrives as a duplicate rather than as the only statement. That makes
the misfiling easier to trigger than it would be live. Worth tightening before the number is
quoted as a rate.

### The tight scenario, and what the model actually does

`fragmented_correction` now scripts turn 1 as well, saying nothing about the rent, so the garbled
two-fragment correction is the only statement of the new figure anywhere in the call.

**5 runs: `claimed_values_recorded` 100%, `state_matches_facts` 80%** (was 60% on the loose
version, which over-triggered). `carried_confirmed_before_plan` 80% — logged below as its own
open item.

Reading all five replies to "My red went up to / thirteen thousand" is the useful part:

| run | what it did |
|---|---|
| …1915-2 | `upsert rent 13,000` — "Is your rent 13,000 rupees on the fifth, rather than 12,000?" |
| …1915 | `upsert rent 13,000` — "Your rent is thirteen thousand, not twelve thousand. Is that right?" |
| …1920 | `upsert rent 13,000` — "Is the rent 13,000 rupees on the fifth, rather than 12,000?" |
| …1921 | `upsert rent 13,000` — "Is your rent 13,000 rupees on the fifth, instead of 12,000?" |
| …1913 | `upsert balance 13,000` — "I've noted 13,000 rupees in your account." |

**Four of five already do the right thing**: they map the garbled noun onto a carried item, record
it against that item, and ask whether it is right. The fifth invents a field nobody named and
claims it. So this is not a coach that cannot handle a garbled correction — it is one that
occasionally guesses the wrong item and then states the guess as a fact.

The failing run is also exactly the shape the orchestrator's proposed lever targets: it created a
**new** item while carried items were still unconfirmed. Not implemented; the rate is reported
first, as asked.

### Open item · `carried_confirmed_before_plan` at 80%

Two separate cells have now had one run in five plan without saying the carried figures back
(`returning_confirms_all` was 100%, `fragmented_correction` 80% twice). Unrelated to the claim
work and not chased. Recorded so it is not lost.

### The new-while-carried lever, measured on ten runs

When `upsert` creates a NEW item while any carried figure is still unconfirmed, the result now
carries `new item; if they meant a carried one, say which and move it: rent 12,000, salary 45,000`.
Nothing is carried for a first-time caller, so their results stay byte-identical; three tests,
including the no-carried and the update-an-existing-item cases.

**Ten runs on the tight `fragmented_correction`: `state_matches_facts` 90%**, one run still filing
the garbled correction as an opening balance.

| cell | runs | state_matches_facts |
|---|---|---|
| loose scenario, before the lever | 5 | 60% |
| tight scenario, before the lever | 5 | 80% |
| tight scenario, with the lever | 10 | 90% |

**That is not evidence the lever worked, and it should not be written up as though it were.**
Four of five against nine of ten is one extra success; at these sample sizes the two are
indistinguishable, and the honest statement is that the failure rate is somewhere around one call
in five to one in ten and the lever has not been shown to move it. Distinguishing 80% from 90%
needs tens of runs, not ten, which is not what this defect is worth. It ships because the
instruction is true, cheap and rides a case the model was already getting right most of the time
— not because a number went up.

`carried_confirmed_before_plan` came back clean across all ten, having been 80% on two earlier
five-run cells. Same caveat in the other direction: that is not a fix either, it is the same noise
seen from the other side. It stays an open item.

One new open item from this cell: `actions_match_plan` 90%, one run naming the bike EMI in a
proposal the plan did not contain.

### Unasked-for filing flags · census, and what the number actually means

From C's fourth call: on a rent correction the model sent `survival=false` explicitly though the
person had only changed the amount, flipping a survival essential to ordinary. The domain treats
an omitted flag as unchanged, so this was stated rather than defaulted, and the store kept `true`
because `record_call` supersedes only stated fields — the two then disagree. Survival drives the
tier, so the money risk is real.

**Census over 369 saved runs, and the headline number needs its qualifier:**

| count | what it counts |
|---|---|
| 253 | an `upsert` on an item already in the call carrying `spread`, `survival` or `flexible` |
| 239 | …where the person had said nothing about how that item is filed |
| 460 | a flag re-sent for an item and flag already sent once |
| **9** | …where the re-sent value **contradicted** the earlier one |

The first number is the one to be careful with. The model volunteers these flags constantly — 239
of 253 — but almost every one repeats the value already held, which changes nothing. The harmful
case is a re-send that contradicts, and that is **nine occurrences across 369 runs**: two kinds
only, `newspaper.flexible` true to false and `electricity bill.survival` false to true. So the
behaviour is ubiquitous and the damage is rare, which is a different problem from the one 239
suggests on its own.

**Fix: the field descriptions for all three flags** now say to send them only when the person says
so that turn, and to omit them to leave things as they are; `survival` also says plainly what
sending false costs — an item already filed as survival drops down the priority order and can
leave the rent unpaid. A schema test asserts all three texts.

**Cell: `returning_changes_rent`, 5 runs, every check at or above 95%.** Four of five end with
`rent.survival` true; three re-sent `survival: true`, which is the harmless repeat, and none
contradicted. The fifth ends false — but it re-sent no flag at all: that run created a fresh rent
item rather than matching the carried one, which is the misfiling shape from §10.9 and not this
one.

As with the last lever, five runs cannot show this worked: the harmful event was already rare
enough that its absence proves nothing. It ships because the description is true and the omission
rule is what the domain already does.

## The owner's call as a scenario · the before table

`owner_call_1` reproduces the live call the owner judged "a bot, not an intelligent agent"
(`evals/runs/voice-9869101897-20260913T194053Z-20260913-194718.json`). Every scripted line is the
person's actual words from that recording, fragments and hedging intact — "I think, like, around
30,000", "I did not understand", "30 minus / 18 is not 57". What is deliberately not scripted is
everything after the arithmetic challenge, because those turns depend on what the bot says back.

**Run against the CURRENT build, 5 runs, before any redesign.** Run ids kept for the after table:

`owner_call_1-20260914-013312`, `-013402`, `-013403`, `-013404`, `-013406`.

| check | before |
|---|---|
| numbers_traceable | **60%** |
| claimed_values_recorded | **80%** |
| banned_phrases | **80%** |
| state_matches_facts | 100% |
| every other rule | 100% |

The facts land — `state_matches_facts` is clean, so the balance, the salary, the rent and the
5,000 all reach the state correctly. What fails is everything the owner actually complained about,
and it fails on the turns where the person pushes back:

- *"You're right: thirty thousand minus eighteen thousand is twelve thousand rupees; the
  fifty-seven thousand figure included your opening balance…"* — the bot concedes the challenge by
  doing the subtraction itself. Neither 12,000 nor 57,000 came from any tool result.
- *"Your recorded income is thirty thousand rupees, and your recorded spending is twenty-three
  thousand rupees, with the lowest balance…"* — 53,667 spoken as a recorded figure that was never
  recorded, which is check sixteen firing on a run that was not built for it.
- One run offered credit.

So the deterministic checks already describe the failure the owner named, without a judge: when
challenged on its own numbers, the bot computes an answer rather than reading one back. Two of the
three failing checks are the never-compute rule, which is the oldest rule in the product.

Not fixed, not touched: prompt and tools are unchanged pending the redesign brief.

# Handover · to the fresh Session B taking the redesign

Written at 27% context by the session that did the cut, the eval phase, the observability phase
and the before table. The brief is `docs/process/agent-redesign-brief.md` and it is authoritative;
this is what the brief does not say and what you would otherwise have to rediscover.

## Read first, in this order

1. `docs/process/agent-redesign-brief.md` — the work.
2. This file from "## The owner's call as a scenario" down — the before table and its run ids.
3. `docs/process/prompt-provenance.md` — every rule with the case it was added for; the last
   section lists what v2 cuts and where each case lives if it comes back.
4. `evals/REPORT.md` §10.2, §10.3, §10.7, §10.9 — the four hard-won lessons, below.
5. `docs/process/requests.md` "## B" — open items and the shapes A owes you.
6. The constraint census the orchestrator names in its message.

## Done already

`prompts/v2.md` exists: 270 tokens against a 400 ceiling (v1 was 599 against 620). The ceiling
test is per version now — `MAX_BASE_TOKENS = {"v1": 620, "v2": 400}` — so v1 keeps its budget
while v2 is held to the smaller one. Two tests pin v2's substance: the identity and the goal's
category list, and the five money rules. **Nothing else of the redesign is started.** The tool
set, coercion, results, turn block, checks split and judge criteria are all yours.

## Four things that will cost you a day each if you rediscover them

**The result-carried lever is the strongest tool in this codebase and it cuts both ways.** Nine
instructions ride on result strings today (`prompt-provenance.md` has the table). Every one moved a
check from 0-80% to 96-100% where the same rule in the prompt alone had failed. The brief deletes
most of them, which is the right call for the ones that are orders about language — but keep the
three the brief keeps, and know what you are giving up. §10.2 is the counter-example: a card's
`min_due` is read back beside its amount and the model still sent the balance as the minimum in 4
of 13 runs. **The lever works on what to do next, not on what a value means.** A misunderstanding
of a field is fixed in the field description, not in the result.

**A correct instruction, obeyed, will fail any rule that was not told about it.** Three times
(§10.7): the implausible-amount question, the balance total, the carried read-back. Each time the
instruction was right and the check was incomplete, and each looked exactly like a defect until
the transcript was opened. The rule for you: whoever adds an instruction that makes a new figure
sayable adds its provenance source in the same change. You are about to add derivation figures to
`numbers_traceable` — that is the fourth case, and it is in the brief because we now expect it.

**Five runs cannot tell 80% from 90%.** Two levers this phase shipped on numbers that could not
distinguish themselves from noise, and both are written up saying so. When the after table comes
in, say what it can and cannot support. The before table is five runs; a two-point move in it
means nothing.

**`state_matches_facts` is the check that found what eleven transcript checks could not**, because
it reads what was written down rather than what was said. When you change the tool set, its
`_FACT_GROUPS` and the `min_due` comparison need to follow, or it will silently stop covering the
new shapes.

## The before table, for the after comparison

`owner_call_1`, 5 runs, current build. Run ids: `owner_call_1-20260914-013312`, `-013402`,
`-013403`, `-013404`, `-013406`.

| check | before |
|---|---|
| numbers_traceable | 60% |
| claimed_values_recorded | 80% |
| banned_phrases | 80% |
| state_matches_facts | 100% |
| every other rule | 100% |

Every line of that scenario is the owner's actual words from
`voice-9869101897-20260913T194053Z-20260913-194718.json`, fragments and hedging intact. Do not
tidy them. Everything after the arithmetic challenge is unscripted on purpose: those turns depend
on what the bot says back, and scripting them would decide the outcome being measured.

The failures are all on the push-back turns, and `state_matches_facts` is clean — the gathering
half works, and what breaks is the explaining half. Two of the three failing checks are the
never-compute rule.

## Notes on the tool table

- **Fuzzy name matching**: the domain already matches possessives (`state.possessive_of`,
  `items._same_item`: bare names merge, two different owners do not). `evals/provenance.py`
  mirrors that rule and a comment there says why. Whatever you do for `note`, those three have to
  agree or the checks drift from the domain — that pairing has broken twice.
- **Plain date parsing**: `coercion._day` takes a day number today. "end of month", "first week of
  October", "the 7th" all need to land on `day_of_month`, and `spoken_day` in
  `agent/tools/phrases.py` is the reverse direction and already exists.
- **`show_month` replacing `finalize_plan` as a gate**: the no-actions line (`phrases.NO_ACTIONS`)
  exists because a plan with nothing to do gave the model nothing to explain and it invented two
  actions and a remainder. Whatever `show_month` returns, a month that needs nothing must still
  say so in words.

## Open items, unchased

- `carried_confirmed_before_plan` 80% on two five-run cells, clean on one ten-run cell.
- `actions_match_plan` 90% on one cell, a proposal naming an item the plan did not contain.
- `register_fit` has passed 13 of 13 including an adversarial run; the owner declined the
  falsification run, and §10.8 says to read it as unfalsified rather than as a pass.
- The full judge sweep is unspent and not worth it until a criterion can fail.
- `evals/REPORT.md` §10 is current through §10.9 and wants the after table as §10.10.

# Session B (fresh) · the redesign

## Section 5 · checks and judge — done, suite green

`uv run pytest` 1176 passed, 27 skipped. `ruff check`, `ruff format --check`, `lint-imports`
(7 contracts) clean. No model was called: this whole section is offline and cost nothing.

**The split.** `ledgerline/judge/checks/checks.py` now has nine gates (money and state) and nine
advisory rules (how the coach talks), both run on every call, both printed in the matrix table,
only the gates in the exit code (`evals/run_suite.GATE_NAMES`; `gate_failures` is the exit code and
`below_threshold` stays the report). `no_repeated_sentence` went advisory on the same test as the
rest — the brief lists it on neither side, and doubled speech is something the coach said twice,
not a figure that is wrong. Say if you want it back on the gate side.

**Two new gates.** `no_silent_turn` (a tool call, no spoken word, the person waiting) and
`no_spoken_decimals` (a figure with paise, in digits or in words). Both were among `owner_call_1`'s
four judge questions and both turned out decidable in code. Replayed over all 382 saved runs, split
at the cut as `evals/runs/README.md` requires:

| rule | pre-cut (221) | post-cut (161) | the live call |
|---|---|---|---|
| no_silent_turn | 59 turns in 50 runs | 11 turns in 9 runs | 3 turns |
| no_spoken_decimals | 17 figures in 9 runs | 5 figures in 4 runs | 2 figures |

All 22 decimal flags were read individually; every one is an engine `Decimal` spoken aloud. The 70
silences were checked structurally — tool call, no text, a user utterance before it — and **none is
followed by the coach speaking**, which is what licenses the narrow "after a user utterance" rule.
Thirty-nine of the seventy call `end_call`: a hang-up with no goodbye.

**The before table gains a row.** `owner_call_1-20260914-013403` spoke "56,833.27 rupees", so
`no_spoken_decimals` is 80% before; no baseline run has a silent turn, so `no_silent_turn` is 100%
before. Nothing else in the table moves.

**The judge.** Six criteria became four, as the brief asks: `full_month_before_planning`,
`low_point_explained`, `challenge_answered_without_computing`, `led_like_a_coach`. `applies_when`
stays in code — the two planning criteria need a final plan, `low_point_explained` needs a result
that actually named a low point (`_low_point` matches `describe`'s own "lowest …" line, and a test
pins the pairing against `_summary_lines` so it cannot silently stop applying), and the fourth
applies to every call. `judge.run` reports gates and advisory both, so nothing disappears from the
review screen; the matrix is the only place the split decides anything.

Written up as `evals/REPORT.md` §10.10. Contract note for the orchestrator and D in
`docs/process/requests.md` B-redesign-1: two sample fixtures still carry retired criterion ids.

Next, in order: the tool set (brief §2), results (§3), the turn block (§4), then `owner_call_1`
five runs on v2 with the new tools.

## Section 5, second pass · the three outcome checks and the advisory flag

Suite 1187 passed, 27 skipped; ruff and `lint-imports` clean (the new domain import — `coverage`,
`FinancialState`, `Coverage`, `ItemKind` — is inside the existing judge-to-domain contract). Still
zero spend.

**Eleven gates now.** `no_premature_plan` (a plan reached with a category never mentioned and never
ruled out, read off `state.coverage`, end-of-call state, unreadable states report nothing) and
`explains_on_request` (doubt about a figure the coach just spoke, answered without a figure from any
result; a question in reply is no defence). Replay over the 383 saved runs: `no_premature_plan` 47
pre-cut runs and **72 of 162 post-cut**; `explains_on_request` 3 turns in 2 runs, all post-cut. Both
fire on the live call — the plan with debts never discussed, and the two deflections at turns 18 and
33. Ten trigger turns in the whole corpus for `explains_on_request`, because only `owner_call_1` and
the live call contain a person who pushes back; it cannot fire where nobody doubts anything.

**The before table is now eleven rows** and the four things the redesign is aimed at are all
measurable before it starts: `no_premature_plan` **0%**, `numbers_traceable` 60%,
`claimed_values_recorded` / `banned_phrases` / `no_spoken_decimals` / `explains_on_request` 80%,
everything else 100%. (The baseline files on disk are `owner_call_1-20260914-013312`, `-013312-2`,
`-013312-3`, `-013402`, `-013403` — the handover's `-013404`/`-013406` are the `-2`/`-3` suffixes
under another name. Five runs either way.)

**`coverage_before_plan`** is the judge criterion, renamed from `full_month_before_planning` to the
orchestrator's name; same question, same `applies_when`.

**Contract, as agreed:** `RuleResult.advisory: bool = False`, true for the nine advisory rules, set
in `judge.py` from `checks.ADVISORY`. Additive; the key-set test in `tests/judge/test_models.py` is
updated. Ready for `verdict.ts` and a regenerated `verdict.sample.json`.

Written up as `evals/REPORT.md` §10.11 (the two checks and the full before table) and §10.12 (the
correction to this report's own 96-to-100 headline: four-way confound, the two strongest cells are
removed conflicts rather than placement, OpenAI's hierarchy ranks tool text lowest, n=5 per cell).

## The tools, the results, the turn block, and the after table

Suite **1291 passed**, 27 skipped; ruff, format and `lint-imports` (7 contracts) clean. Spend on
the phase so far: eight `owner_call_1` runs (three smoke, five the cell), roughly $0.12 of the
$0.30 cap.

**Two new files, v1 untouched.** `ledgerline/agent/tools/plain.py` is the six plain verbs —
`note`, `forget`, `nothing_more`, `show_month`, `what_if`, `done` — and
`ledgerline/agent/tools/facts.py` is the result string as facts. `build_tools(ctx, version="v1")`
returns the old seven and `version="v2"` the new six, so the A/B is one setting
(`prompt.turn_block` and `system_instruction` take the same argument). `handlers.py` and
`describe.py` are unchanged and go when the owner has read the after table.

**Where a wrong translation would move money, the tool asks instead of guessing.** `note` works out
that rent is a bill and a car loan is a secured EMI, but "the gym" comes back as a question naming
the four words to answer with, because filing a bill as spending drops it down the priority order.
A date it cannot pin down ("first week of October") is reported as an open date — and the amount is
still recorded. That last part is a fix from the first smoke run, where refusing the whole call over
a fuzzy date lost the owner's rent for ten turns.

**The four imperatives the brief keeps are the only ones left**: the balance in parts, an amount too
small to be real, a month that needs nothing, the goodbye. No read-back order, no "confirm which is
right", no "ask once, then finalize". The coverage fact replaced `READY_TO_PLAN`, and that is the
change with a mechanism behind the number below.

**The after table, five runs, every column replayed under today's rules:**

| check | before | after |
|---|---|---|
| no_premature_plan | **0%** | **100%** |
| numbers_traceable | **60%** | **100%** |
| claimed_values_recorded | 80% | 100% |
| no_spoken_decimals | 80% | 100% |
| explains_on_request | 80% | 100% |
| every other gate | 100% | 100% |
| one_question_per_turn (advisory) | 100% | 80% |
| one_goodbye_with_the_end_call (advisory) | 100% | 80% |

Five runs cannot tell 80% from 100%; what this supports is that nothing regressed on money or state
and that the two failures the owner named did not happen once. **Two of the five after runs never
reached a plan** — they spent the call establishing loans and cards and ran out the scenario's
26-turn budget — so `no_premature_plan` at 100% is three real passes and two abstentions, against
five of five planning prematurely before. That cost is named in the report, not buried. Written up with the caveats, the two
rule changes that moved numbers, and the run ids in `evals/REPORT.md` §10.13.

**Three things the smoke runs found and fixed**, each with its run id in the report: markdown bullet
lists (the rule came back to v2 with a named case, `prompt-provenance.md`), the lost rent above, and
`in minus out` — two runs did that subtraction out loud when challenged, because no result contained
the figure. Adding it to the month view is why the third challenge produced "the fifty-seven
thousand figure is not the result" instead.

**Two rules changed, both named in the report**: `credited` is no longer read as an offer of credit
(a salary is credited to an account), and a bare small number the person says in an arithmetic
sentence now authorises its thousand-scaled form for the coach to say — replayed over 391 runs it
changes exactly the three it was written for.

Open, for whoever picks this up: the full matrix has not been run on v2, only `owner_call_1`; the
four judge questions are for the owner to read from the transcripts; and `docs/process/requests.md`
B-redesign-2 (C: one setting switches prompt, tools and block; the v2 greeting shrinks) and
B-redesign-3 (A: a `Summary` field for in-minus-out) are open.

## The matrix, the follow-ups, and C-obs-4

Suite **1328 passed**, 27 skipped; ruff, format, `lint-imports` clean. Spend for the whole phase:
61 runs — 8 owner_call_1 before the matrix, the 40-run matrix, two five-run cells and three
`fragmented_balance` runs — roughly $0.90 at this report's own per-run figure.

**The matrix found one defect wearing eight scenarios' clothes.** `state_matches_facts` 30%, and 22
of the 28 failures read "essential groceries never recorded". Groceries WERE recorded — as everyday
spending, because `_kind_of` took the model's `kind` word over the item's name. Food filed as
discretionary is food the engine may propose cutting, which is exactly what code owning the filing
was for. The item's name wins now; `must_pay=True` also lifts spending to a bill. Re-run on
`fragmented_balance`, the groceries failure is gone in all three runs and what remains is a
different, real gap: the coach did not ask for the card's minimum. Full table and the rest of the
matrix in `evals/REPORT.md` §10.14.

**The three follow-ups from the owner's report are in** (§10.15): the derivation now reads as a line
per step with `show_month`'s description pointing at it; complete coverage says so as a fact; the
turn budget went to 36 and is ruled out as a cause. The honest result: the coverage fact did not
stop the looping, because the person in `owner_call_1` never answers the loans question at all, so
"not mentioned yet: loans or cards" comes back every turn — a standing fact the conversation cannot
satisfy is the fourth form of the ratchet this report keeps finding. The fix went in the prompt,
where knowing when enough is enough belongs, and two of five then reached a plan.

**Two figures were added to the month view because runs said them out loud**: `in minus out` (now
`Summary.net_flow`, from A) and `opening plus in is X to work with`. After both, five of five were
clean on `numbers_traceable`.

**C-obs-4 is in.** `prompt.managed_name(version, name)` derives the Langfuse name, and both
`ensure_prompt` and `managed_prompt` call it themselves rather than trusting the caller, so a
publish and a fetch cannot disagree. A name that already carries the version is left alone, so
C's own `managed_prompt_name` keeps working today and can be deleted whenever C likes. The recorded
version is now `v2@7` — ours and Langfuse's — because a bare `7` reads as a prompt version of our
own. Four tests.

**Ponytail pass done** on the three new files: a dead `_signed` helper and a dead `upsert(...,
min_due=None)` call (None means "leave it alone", so it did nothing) are gone; `item_line` lost an
argument it no longer used. 1,228 lines across `plain.py`, `facts.py` and the plain-word half of
`coercion.py`, against 1,034 in the v1 pair they replace — the extra is the translation from plain
words, which is the point of the redesign.

Still open and unowned: the unasked card minimum (`state_matches_facts` on `fragmented_balance`),
`one_goodbye_with_the_end_call` at 75% and `one_question_per_turn` at 78% across the matrix, both
advisory; `silent_before_acting` 40% on the returning-caller path; and the product judgement the
owner has to make — a coach that establishes loans and cards before planning will sometimes not
reach a plan on a call where the person wants the numbers now.

## The v1 deletion · census

Delete-only sweep after the owner read the after table. `uv run pytest` 1111 passed, 17 deselected;
ruff, format and `lint-imports` (7 contracts) clean. `tests/store` was excluded from that run and
only from that run: `ledgerline/store/__init__.py` was mid-edit in another session and its own
import was failing, nothing to do with this sweep — re-run it once that lands.

**What it cost, first.** With v1 gone the **before column of `evals/REPORT.md` §10.13 can never be
re-run**: the prompt, the tools and the result strings that produced 60% `numbers_traceable` and
0% `no_premature_plan` are deleted. The five recordings
(`owner_call_1-20260914-013312`, `-013312-2`, `-013312-3`, `-013402`, `-013403`) and the report are
the record, and replaying today's checks over those files still works because a transcript is just
JSON. What cannot be done again is producing a new v1 run to compare against.

### Files

| deleted | lines | evidence it had no caller |
|---|---|---|
| `ledgerline/agent/tools/handlers.py` | 339 | the seven v1 tools. Imported by `tools/__init__.py` (rewritten), `tests/agent/test_tools.py` (deleted) and nothing else; `voice/pipeline.py` imports `tools.build_tools`, which moved to `plain.py` under the same name and the same re-export |
| `ledgerline/agent/tools/describe.py` | 373 | the v1 result string. Imported by `handlers.py`, `tools/__init__.py`, `tests/agent/test_describe.py` (deleted), and two pairing tests in `tests/judge` now pointed at `facts.py` |
| `ledgerline/agent/prompts/v1.md` | 46 | read only through `base_prompt("v1")`; `DEFAULT_VERSION` is "v2" and no caller passes "v1" |
| `tests/agent/test_describe.py` | 896 | tested `describe.py` only |
| `tests/agent/test_tools.py` | 927 | tested the seven v1 handlers. Five tests covering surviving behaviour were moved into `test_plain.py` first, named below |
| `evals/provenance.py`, `evals/spoken_numbers.py` | 12 each | module aliases from the checks move; `grep -rn "evals.provenance\|evals.spoken_numbers"` over `*.py` returns nothing outside the shims themselves |

`evals/checks.py` is the one shim still standing, and deliberately: `tests/voice/test_recorder.py`
(Session C's) imports `from evals import checks`. One line, C's file, in `requests.md` B-sweep-1.

### Symbols

| deleted | evidence |
|---|---|
| `build_tools(ctx, version)` -> `build_tools(ctx)` | one tool set; the only caller passing a version was `voice/pipeline.py:265`, which C changed in the same sweep. Two intermediate steps kept the tree green: the parameter was accepted-and-ignored while C landed their edit |
| `prompt.turn_block(..., version=)` and its v1 body, `_plural`, `RECORDED_LINE`, `STILL_MISSING`, `PHASE`, `MAX_MISSING` | the v1 block's counts, missing list and phase word. `state_ops` left `prompt.py` entirely with them |
| `ToolContext.take_carried`, the `carried=` constructor argument, `ToolContext.forget_balance_parts` | `grep` for each over `*.py`: one hit apiece, the definition. `take_carried` was read only by `describe`'s carried line; `forget_balance_parts` was called only by v1's `remove_item` on a balance, and `forget` has no balance route — restating a part by name corrects it, which is documented on `balance_total` |
| `coercion`: `_kind`, `_debt_kind`, `_day`, `_field`, `_income_fields`, `_one_of`, `FIELD_ID`, `BARE_FIELDS`, `ATTRIBUTES`, `CERTAINTIES`, `DEBT_KINDS` | the v1 argument grammar: enums, day integers and the `kind:name.attribute` field id. Every one had exactly one occurrence outside its own module — none. `Certainty` left the imports with `_income_fields` |
| `phrases`: `UNDERSTOOD`, `READ_BACK`, `BALANCE_TOTAL`, `READY_TO_PLAN`, `NO_ACTIONS`, `NEW_WHILE_CARRIED`, `CARRIED`, `CARRIED_SETTLE`, `RECORDED`, `ALREADY`, `PARKED`, `MISSING`, `PROVISIONAL`, `NOT_APPLICABLE`, `REMOVED`, `EXPLAIN_AGAIN`, `NO_PLAN_YET`, `MORE_UNPAID`, `MAX_UNPAID_SPOKEN`, `MAX_MISSING_SPOKEN`, `MAX_ACTIONS_SPOKEN`, `CONFIRM_CHANGE`, `REFUSAL_FIELD`, `REFUSAL_DEBT_KIND` | `grep -o "phrases\.[A-Z_]*"` across `ledgerline`, `evals` and `tests` lists exactly what is still read: `GOODBYE`, `CONFIRM_AMOUNT`, `BALANCE_PARTS`, `NOTE`, `UNCHANGED`, `NOTHING_RECORDED`, `NOT_KNOWN`, `BLOCKED`, `PLAN_FINAL`, `PLAN_SHAPE`, `PROVISIONAL_UNNAMED`, `REFUSAL_PLAIN`, `REFUSAL_AS_GIVEN`, `spoken_day`. 83 lines where there were 172 |
| `evals`: `OPENING` (v1 wording), `OPENING_V2` (renamed to `OPENING`), `run_suite --prompt-version` | the flag had one possible value once `prompts/v1.md` was gone |
| `tests/agent/conftest.py`: the `StateSnapshot` fake and the `snapshot` monkeypatch | asked for by Session A, who is deleting `domain.state.StateSnapshot` and `snapshot()`. Mine were the last two references in the repo outside A's own tests; the v2 block reads `facts.coverage_lines(state)` instead, and `prompt.py` no longer imports `domain.state` at all |

**`phrases.NO_ACTIONS`, asked about by name: it is NOT reachable and it is deleted.** `facts.py`
carries the same fact under its own constant, `NOTHING_TO_DO = "nothing to do: every payment is
covered in full"` — the sentence without the order half ("explain the lowest point and propose
nothing"). The case it was written for, B-13, is covered: `test_a_month_that_needs_nothing_says_so_
in_words` in `tests/agent/test_plain.py` asserts a month with nothing to do says so.

### Tests

`test_tools.py` and `test_describe.py` went whole; five tests in them covered behaviour that
survives, and those were moved into `test_plain.py` before the files went, not rewritten:
`test_pipecat_derives_a_schema_from_every_tool` (now asserting the six plain schemas and the
`what_if` array), the two `_refused` routing tests, and the two replay-guard tests (a different
call runs, the same call runs again on a later turn).

`test_integration_domain.py` was rewritten rather than deleted: twelve tests against the plain
tools and the real domain, each keeping the case its v1 twin was written for — a changed figure
carrying both numbers, "I don't know" as an answer, no income as a fact, the card minimum above its
total refused with the state unchanged, a domain refusal reaching the model as a sentence, the
balance dead end, every line of a real result being a fact, and the identity `opening + net_flow ==
closing`. Twelve where there were twenty-six: the other fourteen tested v1 tools or duplicate what
`test_plain.py` already covers against the same real domain.

`test_prompt.py` lost the v1 prompt and v1 block sections and kept one path: 20 tests where there
were 45.

**Two pairings nearly rotted silently, and both are now tested.** `tests/judge/test_criteria.py`
reached into `describe._summary_lines` to prove `criteria._low_point` matches the product's own
line; it now reads `facts._low_point_lines`. And `changed_value_acknowledged` parses the result's
change line — v1 wrote `rent: 11,000 -> 12,000`, v2 writes `rent 11,000 before, now 12,000`, so the
check would have passed every v2 run without looking at one. `CHANGE` now matches both shapes, the
old one because the saved runs hold both eras.

### Numbers

2,058 insertions against 3,483 deletions across the sweep. `agent/tools` is 1,317 lines in five
files where it was 2,029 in seven; `prompt.py` 164 where it was 205; `phrases.py` 83 where it was
172. Everything the model actually reads — six tools, one prompt, one result builder, one block —
now exists once.

## The three-check fold

`uv run pytest` 1060 passed, 27 skipped, 18 deselected; ruff, format and `lint-imports` clean. One
test is deselected in that count and it is C's: `tests/voice/test_recorder.py::test_checks_accept_a
_recorded_voice_turn_order` calls `checks.silent_before_acting`, one of the nine deleted rules.
Everything else is green; the fix is in the report to the orchestrator.

`money_traceable`, `state_matches_call`, `speakable`, over the same ten sub-rules as private
helpers. Replayed over all 448 saved runs: folded output equals sub-rule output exactly, zero
mismatches, and that replay is a test. Violation counts by sub-rule over the corpus, for the
record: no_premature_plan 121, no_silent_turn 71, actions_match_plan 46, state_matches_facts 44,
numbers_traceable 30, no_spoken_decimals 22, no_iso_dates 7, claimed_values_recorded 3,
no_markdown 2, banned_phrases 1.

Deleted with them: the nine advisory rules, `explains_on_request`, `ADVISORY`, `run_advisory`,
`run_suite.GATE_NAMES` (every check decides the matrix now), `RuleResult.advisory`, nineteen private
helpers and fourteen orphaned constants. `checks.py` is 710 lines where it was 1,204; its test file
1,537 where it was 2,004, with 58 tests for deleted rules removed and two `no_silent_turn` cases
restored that the sweep took because a docstring named a deleted rule.

`evals/checks.py` is gone: C repointed `tests/voice/test_recorder.py` to
`ledgerline.judge.checks`, so the last shim from the checks move has no importer.

**`event_order` is gone from the harness too.** `silent_before_acting` was the only reader, so with
it deleted the harness was writing a field nothing looks at and the recorder was writing the same
field plus a `spoke_before_acting` mark. `evals/harness.py` no longer builds or writes it (the
`order` list, its accumulation and the third return value of `_agent_turn`), and the orphaned
`turn_with_order` fixture went from the check tests; C is taking the recorder's half in the same
pass, so the two recording formats stay the same shape. Evidence it had no reader:
`grep -rn "event_order" --include="*.py" ledgerline evals tests` returns only `voice/recorder.py`
and its own tests, both C's and both being removed.

**The deselected tests were swept too, because the green suite proves nothing about them.**
`tests/agent/test_harness_smoke.py` (marked `llm`, so never run offline) still looped over
`checks.run_advisory` and asserted `transcript["state"]["understanding"]` — a key that has not
existed since the cut renamed it `understood`, so the first paid run would have died on a
KeyError nobody was looking at. The advisory loop is gone, the assertion reads `understood` and
checks it is a bool with the reason why it is not asserted True (whether the person agreed is the
person's, and that scenario's `ends_when` is the action repeated back, not agreement), and the
`finalize_plan` wording in the comment above it is v2's. Proven by `--collect-only -m llm` plus a
static read, not by spending.

Then every `llm`, `voice` and `e2e`-marked file was grepped for every name deleted today. The only
hits are `mark_unknown`, `upsert` and `confirm_carried` in `tests/store/test_profile_write.py`, and
all three are the DOMAIN functions, which are untouched — it was the tools of those names that went.
`spike/` is clean. All 17 marked tests collect.

Written up as `evals/REPORT.md` §10.16, including the thing worth keeping: the fold's own argument
is `changed_value_acknowledged`, which parsed v1's change line, stopped matching when v2 changed it,
and went on reporting 100% on runs it was not looking at — and it is one of the nine deleted. A rule
per surface is a rule per way to rot silently.

## Kiro review kiro-20260914T050806Z · four findings

Suite in my areas green (`tests/agent`, `tests/judge`); ruff, format and `lint-imports` clean. The
full run is red in `tests/domain` and `tests/api` while Session A's second pass is mid-edit — the
failures move between runs and pass in isolation, and nothing of mine imports either file.

**KIRO-003 · `must_pay` no longer decides what kind of thing it is.** `_kind_of` lifted an optional
to an essential when `must_pay` was true, so a gym the person insists on sat at tier 0 — above the
rent — and, because `upsert` keys by (kind, name), the same gym ended up recorded twice, once under
each kind and counted twice in the outflow. `note`'s own contract already said what the domain
means by it: an inflexible optional. The lift is gone and the `must_pay` parameter with it; `note`
sends `flexible=False` as it always did for that branch. Two tests: the first insertion, and the
update of an item already recorded as optional, both asserting one item and no essential. The
§10.14 groceries fix does not lean on the lift and is pinned separately — the item's name wins over
the model's word, and `_kind_of("groceries", "everyday spending")` is still a bill.

**KIRO-004 · how a debt was filed is said back.** The unsecured-EMI default for a bare "loan" stays
— refusing would put a question in front of the common case — but the guess is visible now: "as a
card", "as a secured EMI", "as an EMI", "as money owed", in the `note` echo and in every debt line
of the month view. The filing is the tier and the tier is what gets paid when the money runs out, so
a wrong guess needed to be one correction away rather than invisible. Four tests, one per kind.

**KIRO-011 · `what_if` pays in full through a name the person would use.** `_find_kind` accepted
"my hdfc card" but the mutation compared normalised names exactly, so the alias matched no debt,
nothing changed on the copy, and the result still announced the change. It resolves the debt
through the domain's own `_find` now — the same identity `upsert` and `remove` use — and refuses
when nothing matches. Tested with the possessive alias against a month where the engine actually
proposes the minimum, so the delta has something to show, plus the refusal.

**One more dead thing the sweep had missed.** `tests/agent/conftest.py` still monkeypatched every
domain function with a recording fake, and `tests/agent/factories.py` built the `Plan` and `Summary`
doubles it returned — both served `test_tools.py` and `test_describe.py`, which went with the v1
tools. One test still took the `rec` fixture and did not need it (it only derives tool schemas).
`factories.py` is deleted, the `Recorder` class and the `rec` fixture with it; what is left is a
real state, the cards a handler pushed, and the params double. `grep -rn "factories\|make_plan\|
make_summary" tests/` returns nothing. Session A's warning about hand-built `Summary` fixtures
defaulting `to_work_with` to zero therefore cannot bite this layer: nothing here builds one.

**KIRO-002 · the last arithmetic leaves the agent layer.** A landed `Summary.to_work_with`, so
`_cashflow_lines` reads it and the `ponytail:` note about working out the addition is gone; `grep
-c "ponytail:" facts.py` is 0. The surplus/shortfall pair is unchanged: two presentations of one
published figure, always shown together.

## Kiro review kiro-20260914T053721Z · three findings

Whole tree **1112 passed, 31 skipped, 17 deselected**; ruff, format and `lint-imports` clean. The
fold's 448-run replay still shows zero mismatches after these result-string changes.

**F1 · an estimate is counted, and the line says so.** `item_line` gave every non-confirmed
certainty the same words — "not counted as money until it arrives" — but `_income_events` counts an
ESTIMATED income in full and leaves out only an UNCERTAIN one. So `show_month` could tell the model
an estimated salary was excluded while the cashflow and the low point three lines below it included
the money: a coach contradicting its own figures in the same breath. One wording per certainty now,
each matching what the engine does: "an estimate, counted in full", "may not arrive, left out until
it lands". Both tested against `plan.summary.total_in` from the real engine — 30,000 counted for the
estimate, 0 for the uncertain one — so the line cannot drift from the arithmetic without failing.

**F2 · the head word decides, not any word in the phrase.** `_kind_of` scanned the item before the
model's kind and returned on the first substring, so "rent from my tenant" sent as money coming in
was filed as an outflow and "salary advance loan" sent as a loan was filed as income — cashflow
direction reversed, on exactly the phrases where the model's reading is the better one. The rule is
now: the LAST word of what they called it decides when it is one of the listed words ("groceries",
"my salary", "credit card", "bike loan"); otherwise the model's `kind` decides; otherwise any listed
word in the phrase decides, as before. §10.14's measured case is untouched — "groceries" sent as
everyday spending is still a bill — and "salary advance loan" now lands as a debt by its head word
and by the model's kind agreeing, rather than by one beating the other. Tested at the coercion level
for all four phrases and through the tool for the tenant case, which must increase `total_in`.

**F4 · a date that goes away is said out loud.** `_change_lines` dropped every transition with an
empty new value, so making a dated essential spread (`due_date` cleared) or narrowing an income
range (`latest_date` cleared) reported the new state and never the removal — though the removal is
exactly what changed about when the money moves. Cleared fields now read "rent due date 5 Oct, now
none" beside the new state. Two tests: the essential going spread, which asserts both halves, and
the income range narrowing to one day.

## Kiro review kiro-20260914T082328Z · F1 done, F3 waiting on A

`tests/agent`, `tests/judge`, `tests/domain` and `tests/store` green; ruff and format clean on my
files. `tests/api` is red and mid-edit in Session C's hands (their F4 and F5), not mine.

**F1 · when the words disagree, the tool asks.** The head-word rule from Kiro 15 stays, and the
gap it left is closed: if the head word settles nothing and the phrase and the model's `kind` point
at different kinds, neither wins — `_kind_of` raises with both readings named, which is the route
the tool already had. "rent payment" sent as everyday spending would have put rent where the engine
may propose cutting it; it now asks "could be a bill or everyday spending". "rent payment" sent as a
bill files as an essential, because nothing conflicts.

Two consequences worth naming rather than burying:

- **"rent from my tenant" now asks instead of filing as income.** Kiro 15 F2 made the model's kind
  decide it; this makes it a question. That is a deliberate reversal and the right one: rent is the
  strongest essential word there is and a tenant pays it TO them, so either filing is a cashflow
  direction guessed from a substring. One question is the cheaper error. The test says so.
- **"credit card payment" sent as a bill asks rather than filing as a card.** The orchestrator
  offered either. Asking keeps the rule one sentence long — conflicts ask — where the alternative
  needs a table of which word is stronger, which is the judgement machinery the cut removed. The
  cost is one question on a phrase the model could have got right; the benefit is that no future
  word pair needs a ruling.

**F3 · done, on A's view.** `_cashflow_lines` rounds each figure with `rupees()`
independently, so opening 60,000.40 plus income 30,000.40 can read "60,000 plus 30,000 is 90,001".
`ledgerline/domain/rupees.in_rupees(summary)` landed while this was held, and `_cashflow_lines`
reads it: all eight figures are ints whose three identities hold exactly, because the three the
month is made of are rounded and the totals are derived from them. The low-point steps use the
same module's `reconciled(parts, total)` on each side of the arithmetic, so the steps reach the
figure they end on rather than each rounding where it likes.

`facts.rupees()` survives for figures that stand alone — an item's amount, a card's minimum, an
unpaid row, a what-if delta — and its docstring now says why: anything that has to ADD UP against
something else comes from `domain.rupees`. There is one rounding rule in the product again, which
is what the finding was really about; a second one in this layer would have been the same bug
wearing a different hat. Two tests with paise on both sides of the half-rupee boundary: the
cashflow line reconciles against `in_rupees`, and the low-point steps sum from the opening balance
to the low point exactly.

## Kiro review kiro-20260914T083217Z · F1 and F2

Whole tree **1148 passed, 31 skipped, 17 deselected**; ruff, format and `lint-imports` clean.

**F1 · a date somebody named has to exist, and be in the window.** `resolve_day` clamps, which is
right for "the end of September" and wrong for a day the person named: "the 31st of September" was
stored as the 30th. And the parser stripped a four-digit year before reading the day and never
checked it, so "5 October 2027" was stored as 5 October 2026. Either way money moved on a date
nobody gave. `_check_named_date` now builds the actual calendar date — the named year if they gave
one, otherwise the first occurrence of that month on or after today — refuses a day the month does
not have ("September has 30 days, so 'the 31st of September' is not a date. Ask them which day it
is.") and refuses anything outside the thirty-day window. Clamping survives only where the phrase
asks for it: "end of September" still sends day 31 and `resolve_day` still lands it on the 30th,
which is asserted rather than assumed.

**F2 · one ledger, both ends of the month.** `_low_point_lines` rounded the closing balance itself
while `_cashflow_lines` spoke the reconciled one, so with paise the same result could say "closing
0" and "closing 1". It reads A's `in_rupees_low_point(plan)` now — opening, low point, closing and
every movement as ints, its ends being the same objects the cashflow line speaks — and `whole()` is
gone from `facts.py` except inside `rupees()`, the one formatter for figures that stand alone. The
test builds a month with paise on both sides of the half-rupee boundary, asserts every "closing" in
the rendered month is the same integer, and asserts the cards' low-point closing is that integer
too, so the screen and the voice cannot drift apart either.

One test moved with it: `tests/judge/test_criteria.py`'s pairing test built a fake plan by hand and
now runs the real engine, because the line it pins is built from the ledger rather than assembled
figure by figure. It still pins what it always did — `criteria._low_point` matches the word
"lowest", which the product's own line still says.

# Handover · the agent, judge and eval layers as frozen, 14 September

Written at 23 percent context by the session that did the redesign, the v1 deletion, the check
fold and four Kiro rounds. The commit series is the orchestrator's alone; nothing below needs
doing, it is what a successor would otherwise pay a day to rediscover.

## The state of the layer

Six plain tools — `note`, `forget`, `nothing_more`, `show_month`, `what_if`, `done` — in
`agent/tools/plain.py`, bound by `build_tools(ctx)`. One prompt, `prompts/v2.md`, 331 tokens
against a 400 ceiling. One result builder, `agent/tools/facts.py`: facts and options, whole
rupees from `domain.rupees`, four surviving imperatives (a balance in parts, an amount too small
to be real, a month that needs nothing, the goodbye). One turn block: today, the window, the
coverage lines, nothing else. Three deterministic checks over ten sub-rules in
`judge/checks/checks.py`, and four judge criteria in `judge/criteria.py`. `agent/tools/coercion.py`
is the translation from what people say into what the domain takes, and it is the only place that
refuses.

## Open for the owner, not for a successor to quietly close

- **The unasked card minimum.** Two of three `fragmented_balance` runs never asked what the card's
  minimum was, so `state_matches_facts` fails against a fact the person would have given. Not a
  recording bug: the coach did not ask.
- **Loans and cards versus a person who wants the numbers now.** The coverage fact made the coach
  establish categories before planning, and in `owner_call_1` the person never answers the loans
  question — so two of five runs reached no plan at all. Which of those two the product should
  serve is a judgement, and it is the owner's.
- **Two rates that no longer have an instrument.** `one_question_per_turn` at 78% and
  `one_goodbye_with_the_end_call` at 75% on the last full matrix. Both rules were deleted in the
  fold; `led_like_a_coach` is what would catch them now, and a judge criterion is not a rate.

## The rules worth a day each

- **The result-carried lever works on what to do NEXT, not on what a value MEANS.** Nine
  instructions rode results and each moved a check from 0–80% to 96–100%. The counter-example is
  §10.2: a card's minimum was read back beside its amount and the model still sent the balance as
  the minimum in 4 of 13 runs. A misunderstanding of a field is fixed in the field description.
- **A correct instruction, obeyed, fails any rule that was not told about it.** Four times now.
  Whoever makes a figure sayable adds its provenance source in the same change — `carried_numbers`,
  `_offered_readings` and `_in_thousands` are all that rule applied after the fact.
- **Five runs cannot tell 80% from 100%.** Every table in `evals/REPORT.md` says what it can and
  cannot support; keep doing that. A two-point move in a five-run cell is noise.
- **`state_matches_facts` follows any change to the tool set**, because it reads what was written
  down rather than what was said — which is how it found a defect eleven transcript rules passed.
  `_FACT_GROUPS` reads the state, so it survived the tool rename; `provenance.RECORDING_TOOLS` and
  the arg names did not and had to be taught both sets.
- **Fuzzy name matching lives in three places and they must agree**: `state.possessive_of`,
  `items._same_item` and `checks/provenance._same_item`. That pairing has broken twice. `what_if`
  and `forget` resolve through the domain's own `_find` for the same reason.
- **A rule per surface is a rule per way to rot silently.** `changed_value_acknowledged` parsed
  v1's change line, v2 changed the wording, and it went on reporting 100% on runs it was no longer
  looking at. Two pairing tests exist because of it: `criteria._low_point` against
  `facts._low_point_lines`, and the check against `facts._change_lines`.

## `_kind_of`, in full, because four rounds shaped it

The item's **head word** decides when it is one of the listed words: "groceries", "my salary",
"credit card", "bike loan". Otherwise the model's `kind` decides. Otherwise any listed word in the
phrase decides. And when the head word settles nothing **and the phrase and the kind disagree, the
tool asks** — "'rent payment' could be a bill or everyday spending" — rather than picking a side,
because picking needs a table of which word is stronger and that table is the judgement machinery
the cut removed. `must_pay` does not decide the kind: it means an inflexible optional, and lifting
it to an essential put a gym above the rent and recorded it twice.

`_debt_kind_for` keeps its unsecured-EMI default for a bare "loan" — **the owner's choice**,
because refusing would put a question in front of the common case. What makes it safe is that the
filing is spoken back ("as an EMI", "as a card", "as a secured EMI", "as money owed"), so a wrong
guess is one correction away. Kiro has raised the default twice; it is a decision, not an oversight.

## Where the evidence is

`evals/REPORT.md` §10.13 (the redesign measured on the owner's own call, before and after), §10.14
(the full matrix and the groceries defect), §10.15 (the three follow-ups and what they cost), §10.16
(the fold). The recordings under `evals/runs` are committed and replayable — 448 of them, and the
fold's acceptance test replays over every one. The before column of §10.13 cannot be re-run: v1 is
deleted.


# Session B · the coaching frame · 14 September evening

Brief: `docs/process/coach-brief.md`. Report: `evals/REPORT.md` §10.17. Provenance rows: the last
section of `docs/process/prompt-provenance.md`. Suite green, ruff and lint-imports clean, prompt at
398 tokens. No commits.

## Changed

- `ledgerline/agent/tools/facts.py` — `_delta_lines` rewritten: `compared with the month as it
  stands:` then shape (first, when it changes), lowest point with both dates, closing, unpaid, each
  as `X as it stands, Y with this change, up/down N` off `in_rupees` / `in_rupees_low_point`, so the
  comparison and the derivation in one result agree. Sits right under `if they did this:`.
  `nothing moves` when nothing does.
- `ledgerline/agent/prompts/v2.md` — the coaching paragraph (brief §"Prompt v2"), 331 to 398 tokens;
  cuts listed in the provenance section. The Money rule is verbatim again after one cell.
- `ledgerline/agent/tools/plain.py` — `what_if` grammar: `TRAILING` ("this month", "for now"),
  `LEAD` ("pay", "keep", "move"), `SHIFT`/`SHIFT_BY` ("7 days late", "late by a week"), `DELTA`
  ("10,000 short", "2,000 higher"), verbs between item and "to/on" ("electricity moves to 15
  September"), " rupees" after an amount. A shift past the window or before today is refused with
  the landing date; past the window it suggests `'<item> is 0'`. Every refusal ends "nothing was
  tried; forget is not a trial, it drops an item for real". `forget`'s description says the same.
  `done(understood=True)` sets `plan_final` when the plan is not blocked.
- `evals/harness.py` — `MAX_TOOL_ROUNDS` 4 to 8, with the reason in the comment.
- Tests: `tests/agent/test_plain.py` (comparison lines, shape change, ledger agreement, nothing
  moves, trailing words, eleven stress phrases from the runs, out-of-window refusal, unreadable
  refusal, two-items refusal, `done` settling); `tests/agent/test_prompt.py` (the frame's lines,
  wrapped-line safe).

## Found, and where it stands

- The coach reaches for **stresses, not figures**: every `what_if` it wrote is a state edit the
  engine already answers. No engine change; the brief's condition for one was not met.
- **The harness cap was harsher than the pipeline** and produced the six `no_silent_turn` failures.
  Raised. The real cost underneath — four to seven round trips before speaking — is a latency
  question for C's filler, not a rule.
- **`forget` after a refused `what_if`** dropped an item from the real month three times. Parser,
  refusal wording and description all changed; the wording is the money instruction of this change.
- **`done` without `show_month(final=True)`** in six of seven understood runs. Fixed in `done`.
- **`low_point_explained` fell on the comfortable month** (5 of 5 to 2 of 5). Cause not separable on
  five runs: the frame's "one breath" or the refused-chain eating the turn.
- **Open for the owner**: `comfortable_surplus.max_turns: 14` was sized for a two-question call;
  every after run used 20 to 24 turns. One owner run planned with loans never discussed (§10.15's
  question). The "30,000 minus 18,000 is 12,000" phrasing — figures from a result, said as a sum.

## Not done

The final build is unmeasured: the cell that produced the table ran before the parser, the cap,
the `done` change and the Money-rule restore. Re-running both cells is about $0.25. Cap was $0.30
and roughly $0.30 was spent.

## Re-run, later the same evening

Owner approved; both cells again on the build above, `comfortable_surplus.max_turns` 14 to 24
first (noted in the scenario file). Table and excerpts appended to REPORT §10.17. Headlines: no
silent turn, 5 of 5 final plans in both scenarios, `led_like_a_coach` 5 of 5 on the owner's call,
refusals 9 of 26 (from 28 of 34). $0.24 of $0.25.

Landed from the re-run, unmeasured: six more `what_if` shapes (`BY`, `STAYS`, `LATE_AFTER`,
`RUPEE_TAG`, "instead of" trailing, "late," before a date, a bare `<item> <amount>`), each a phrase
from a run in `test_what_if_reads_the_second_cell_s_phrases`; `CREDIT_IS_ABOUT` knows "credit
impact / consequence / standing / rating", replayed over every saved run, exactly the two new turns
change.

Open, recorded: `forget` after a refused `what_if` happened once more with the "not a trial" line
in front of the model; one run said "58,000 plus 700" before its `what_if` ran; one run offered
"HDFC card, 8,000" as an example figure; two owner runs said the subtraction the engine did as a
subtraction. The premature-plan-on-debt run: once more, not chased.

## Unchanged note, same figure (queued item, done)

`facts._unchanged_line`: `unchanged <item>, same figure as before, <amount>; if they were correcting
it, ask what they said`, amount as recorded with paise kept (`rupees_exact`), balance path covered.
Test `test_a_note_that_changes_nothing_says_the_figure_and_what_to_ask` from the live two-fifty
call (turn 35 of `voice-9869101897-20260914T135556Z-20260914-140323`). Provenance paragraph at the
end of `prompt-provenance.md`. Suite green. Unmeasured; a result line, not a prompt rule.

## Demo rehearsal (frozen after this)

Two scenarios from the owner's script, `demo_call_1` and `demo_call_2` (not in SUITE), two rounds,
$0.27. Step table, the domain finding (a timing month never proposes the card minimum), the script
lines to change (step 5 correction wording, step 11 "below zero", step 15 "keep aside", a balance
line before step 18) and the best full transcript are in `evals/demo-rehearsal.md`. Fixes with
tests in `facts.py`, `plain.py`, `harness.py` listed there. Suite green; frozen.
