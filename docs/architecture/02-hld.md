# Ledgerline: high level design

Approved 2026-09-11; sections 3 to 9 revised 2026-09-13 for the state-layer cut (`docs/process/cut-brief.md`);
sections 3, 4, 5, 7 and 9 revised 2026-09-14 for the agent-layer redesign
(`docs/process/agent-redesign-brief.md`). A voice assistant that gathers a person's next thirty days of money
by conversation, computes a plan in plain Python, and keeps the spoken numbers and the on-screen cards reading from the same
object. One Python package split by concern, one React frontend, one process, one command.

Companion docs: `01-tech-stack.md` (what and why), `03-folder-structure.md` (where), `docs/research/00-index.md`
(verified facts and every rejected alternative).

## The one rule

The LLM never computes and the engine never reads the LLM. Every number the bot speaks came back in a tool
result. Every card is derived from the same state object the tool just mutated. A correction is a state update;
speech and cards change together because neither holds its own copy.

## 1. Components

One FastAPI process. It serves the built React app, creates a Daily room on request, and runs the Pipecat
pipeline as an asyncio task in the same process. The browser and the bot both join the room. Audio and cards
ride Daily. Nothing inbound but the HTTP port.

```
browser (React + daily-js)
   │ POST /api/sessions                    │ mic audio ────────────┐
   ▼                                       ▼                       │
FastAPI ──creates room, token──▶ Daily room ◀── bot audio ─────────┤
   │ create_task(run_session)              │ app-message (cards)   │
   ▼                                       ▼                       │
pipeline: Daily in → Deepgram STT → user agg → luna → Cartesia TTS → Daily out → assistant agg
                                              │ tool calls
                                              ▼
                                    agent/tools/  ──mutate──▶ domain/state/ 
                                              ▲                     │ build_plan()
                                              │ result string       ▼
                                              └── totals ◀── domain/engine/  ──▶ domain/cards.py ──▶ urgent frame
```

Layers and the only allowed import direction: `domain` ← `agent` ← `judge` ← `memory` ← `voice` ← `api`, with `store` and `observability` beside them importing only `domain` and `config`. Inside `domain`: `models` ← `policy` ← `state` ← `engine` ← `cards`. Enforced by import-linter (seven contracts). The observability, session, memory and judge additions are designed in `04-observability-hld.md`.

| Module | Owns | May import |
|---|---|---|
| `ledgerline/config.py` | typed Settings from env, validated at boot | pydantic-settings |
| `ledgerline/domain/models.py` | `FinancialState` and item models | pydantic |
| `ledgerline/domain/state/` | upsert (overwrite, report changes), remove, mark_unknown, missing_fields, readiness (package; `names`, `items`, `unknowns`, `readiness`). Correction vs contradiction is the model's call, carried as an instruction in the tool result | models |
| `ledgerline/domain/engine/` | `build_plan`, day simulation, reserve and settle, actions (package; `events`, `simulate`, `settle`, `actions`, `plan`) | models, policy, state |
| `ledgerline/domain/policy.py` | tier order, consequences, allowed actions | nothing |
| `ledgerline/domain/cards.py` | state + plan to `CardsMessage`, 4 KB guard | models, state (for `group_inr`, so cards and spoken figures group rupees identically) |
| `ledgerline/agent/tools/` | six plain-word tools (`plain`) and result strings that state facts rather than issue orders (`facts`), over `context`, `coercion` and `phrases` | domain |
| `ledgerline/agent/prompt.py` | base prompt loader, the per-turn block (today, window, coverage), the Langfuse-managed prompt name | domain |
| `ledgerline/judge/` | the call judge: `checks/` (three deterministic checks, `money_traceable`, `state_matches_call`, `speakable`, moved from `evals/` and folded from twenty on 14 Sep), `criteria.py` (four criteria), `llm.py`, `judge.py`, `models.py` (`Verdict`, a contract). Recording in, Verdict out; never raises; see `04-observability-hld.md` section 7 | agent (`phrases`), domain, openai |
| `ledgerline/memory/` | soft-notes extractor: one structured-output call at session end, closed `NoteCategory` vocabulary, notes with amounts rejected in code | judge.checks, domain, openai |
| `ledgerline/observability/` | tracing setup (one provider, SDK-owned exporter, scope filter), attribute names, Langfuse client with a Null twin; key presence turns it on | config, langfuse, opentelemetry |
| `ledgerline/store/` | Postgres: users, slim sessions, `profile_facts` and `profile_notes` with supersession rows; `load_active` with a deadline, `record_call(loaded=)`, `hydrate`, `forget`; `NullStore` when unconfigured | domain.models, psycopg |
| `ledgerline/voice/pipeline.py` | services, aggregators, observers, `PipelineWorker` | agent, domain, pipecat |
| `ledgerline/voice/session.py` | one call: join, greet, card push, prompt refresh, disconnect, idle | pipeline, agent, pipecat |
| `ledgerline/voice/tool_trace.py` | observer beside the recorder: one `tool` span per executed function call under the current turn | observability, pipecat |
| `ledgerline/voice/transport.py` | Daily room, token, transport construction | pipecat daily utils |
| `ledgerline/api/routes.py`, `sessions.py` | `POST /api/sessions`, health, task registry | voice, fastapi |
| `ledgerline/main.py` | app factory, lifespan, static mount | api, config |
| `frontend/src/` | React app: call hook, protocol types and parse, reducer, components | react, daily-js |

## 2. One user turn

1. User speaks. Silero VAD plus Smart Turn decide the turn ended. Deepgram transcript enters context.
2. Luna emits zero or more tool calls, parallel allowed.
3. Each handler mutates state, calls `build_plan`, pushes one card snapshot, returns a short string with the
   recomputed totals.
4. Luna speaks using only numbers from tool results. Cartesia streams the first sentence while the second is
   still generating.
5. After the turn the per-turn block is rebuilt from state and applied via `LLMUpdateSettingsFrame`.

Latency target, not measurement: transcript final ~0.3 s, first tool call ~0.7 s, cards on screen ~1.0 s,
first audio ~1.4 s. Handlers are in-memory only; no network, no disk.

## 3. State model

```python
class FinancialState(BaseModel):
    today: date
    horizon_days: int = 30
    opening_balance: Money | None          # None blocks the plan
    incomes:    list[Income]               # name, amount, date, latest_date, certainty
    debts:      list[Debt]                 # name, kind, amount_due, min_due, due_date, autodebit, lender
    essentials: list[EssentialExpense]     # name, amount, due_date, spread, survival
    optionals:  list[OptionalExpense]      # name, amount, date, flexible
    unknowns:   list[Unknown]              # field, reason UNKNOWN | NOT_APPLICABLE  -> "still need" card
    understood: bool                       # the person said the plan made sense; any later change resets it
    plan_final: bool
    call_ended: bool
    turn: int                              # replay guard

class DebtKind(StrEnum): SECURED_EMI, UNSECURED_EMI, CREDIT_CARD, INFORMAL
Money = Decimal quantised to 0.01
```

Upsert semantics after the cut. Key is `(kind, normalised name)`; "rent" and "my rent" resolve to one item,
"my loan" and "his loan" stay two, an ambiguous bare name creates a new item rather than guessing. Upsert
**overwrites, always**, and returns `Outcome.changes`: field id to (old, new) in speakable form for every
field that moved. Whether a moved value is a correction to acknowledge or a contradiction to ask about is the
model's call, carried as an instruction on the result line ("confirm which is right before moving on"). There
is no conflict store, no outlier list and no confirmation tracking in code; those were built, measured
(forty of the first fifty-five review findings lived in them) and cut.

`Unknown` has two reasons. UNKNOWN: the person does not know; the item is left out of the maths and the plan
is provisional. NOT_APPLICABLE: the person said there is none; a confirmed absence, counts as an answer (for
income it satisfies the income blocker), never provisional. A balance can never be not applicable.

`coverage(state)` answers, for the balance and each of the four item kinds, one of three things.
`Coverage.STATED`: they have named at least one. `Coverage.NONE`: they said there are none of these, which is
an answer and is never asked again. `Coverage.UNASKED`: nothing usable has been said yet. `none_of(state,
kind)` is how NONE is written, and it stores nothing of its own: it records one `Unknown(field=kind,
reason=NOT_APPLICABLE)`, the same mechanism the engine already honours, so there is one path and not two. "I
do not know" deliberately leaves a category UNASKED, because not knowing is not an answer. A balance is never
NONE; an empty account is a balance of zero. Coverage is derived on every read, never stored.

Derived, never stored: `missing_fields` (structural gaps as field ids, ranked: opening balance, debt due
dates and card minimums, essential amounts and dates for undated non-spread essentials, income amounts and
dates, optional amounts, debt amounts), `blockers` (opening balance; the income question until answered),
readiness (phase gathering | ready | plan | done), all totals. Carried figures from a previous call no longer
block anything: the blocker was removed on 14 September and a carried item only makes the plan provisional,
is listed with "from last call" in the result, and the model decides what to do about it.

## 4. Tools

Six direct functions, named and argued in the words a person would say. Code translates; the model never has
to reproduce a grammar. Descriptions say when to use the tool and what a value looks like.

| Tool | Arguments | What it does | Returns |
|---|---|---|---|
| `note` | `item` (their plain name), `amount?`, `when?` ("7th", "end of month", "spread over the month"), `kind?`, `might_not_arrive?`, `minimum_due?`, `must_pay?` | write down anything they say about a figure, a date or a bill, even partial. The item's own name decides the filing and `kind` only settles what the name leaves open; a balance in parts is one call per part and the tool adds them | the fact as recorded, old beside new when a value moved, then the coverage lines |
| `forget` | `item` | drop something that no longer applies | dropped line, then coverage |
| `nothing_more` | `of?` (a category) or `about?` (one item's detail) | record that there is no more of a category, or that a detail will not be answered; it stops being a gap and is never asked again | none line, then coverage |
| `show_month` | `final?` | look at the whole month; callable at any point, not a gate. `final=true` marks the plan final on their screen | coverage, every item with its figures, cashflow, the lowest point a step per line, everything they could do with what each costs, what is unpaid, what is left out and by how much |
| `what_if` | `changes` (plain edits: "skip gym", "pay the card in full", "move rent to the 10th") | rerun the engine over a copy | the same picture, plus what moved |
| `done` | `understood`, `reason?` | end the call; the goodbye is the model's own words | one line |

Every tool: coerce, one domain call, `build_plan`, push one snapshot through an injected callback, return
`facts(...)`: facts and options, one per line, every number from the domain, no orders except the three that
protect money (echo a figure just given, show old beside new when a value changed, confirm an amount that
looks implausibly small). A refusal routes in plain words and never lectures: "Nothing called 'gym' is on the
books. On the books: rent, salary, groceries." `function_call_timeout_secs=5`. Never await the network inside
a tool. An identical call repeated within a turn is answered from a replay cache.

The rule-shaped v1 set (`upsert_item`, `remove_item`, `mark_unknown`, `confirm_carried`, `finalize_plan`,
`record_understanding`, `end_call`) and its result strings were removed on 14 September once the after table
had been read. There is one tool set.

## 5. Plan engine

Pure function `build_plan(state, policy) -> PlanResult`. Day-by-day simulation, `Decimal`.

1. Gate: a missing opening balance, or an income question nobody has answered, returns `BLOCKED` with the blocking field ids.
2. Simulate 30 days. Within a day: income, spread essentials, dated items by tier, optionals. Unknown amounts
   are excluded and listed; uncertain income takes its latest date.
3. Classify: min balance ≥ 0 is `OK`; net ≥ 0 but a dip is `TIMING`; net < 0 is `STRUCTURAL`.
4. Apply actions by tier, re-simulate: `DEFER_OPTIONAL`, `CUT_OPTIONAL`, `PAY_MIN_DUE` (with interest warning),
   `ASK_LENDER` ("ask the lender to move it"). `PAY_ON_DATE` is retired. Never a new loan, BNPL, settlement or promise. A pay-minimum action carries the remainder still due; an essential prorated for lack of a date carries a warning naming the assumption.
5. Anything still unpaid makes the status `UNSOLVABLE` with the unpaid list and a consequence per item.

Priority tiers, configurable in `policy.py`: 0 survival essentials, 1 rent, 2 secured EMI, 3 unsecured EMI,
4 card minimum due, 5 informal debt, 6 card remaining, 7 optionals. Paid in that order, cut in reverse.

An essential with no date, or one marked spread, is prorated across the window in **whole rupees**:
`amount / days` rounded down to the rupee for every day but the last, and the last day carries
`amount - per_day * (days - 1)`, so the slices sum back to exactly the amount, paise included, and every
figure is one a person could say aloud. Optionals with no date are prorated the same way. A deferral
collapses a spread optional back to one event, so no action ever speaks thirty small moves.

`LowPoint` is the arithmetic behind the lowest balance, built from the same post-action events and the same
simulation that filled the summary, so nothing is recomputed: `date`, `balance`, `opening_balance`,
`before` (rows landing on or before the low day), `after` (rows arriving later), `closing_balance`. Each row
is one label with a signed amount, and a spread item collapses to one running total with the last day it
counts. Two identities hold by construction and are pinned by tests:
`opening_balance + sum(before) == balance` and `balance + sum(after) == closing_balance`. That is what lets
the result read the derivation out a step per line instead of asserting a figure.

`Summary.net_flow` is `total_in - total_out_planned`, computed once in the engine, so the three figures on
the spoken cashflow line always reconcile and the agent layer never works the difference out itself.

`PlanResult`: status, provisional, timeline rows, summary (in, out, net flow, lowest balance and date,
closing), the low point with its rows, actions with rationale, warning and remainder, unpaid with
consequence, warnings, blockers (field ids).

## 6. Cards protocol

One message type after every state change, full snapshot, monotonic version. Browser reconciles DOM by card id.

```json
{ "type": "cards", "v": 7, "phase": "gathering", "focus": "essentials", "cards": [
  { "id": "income",     "title": "Income",        "status": "ok",          "rows": [["Salary", "42,000", "1 Oct"]] },
  { "id": "essentials", "title": "Essentials",    "status": "confirm",     "rows": [["Rent", "12 ?", "5 Oct"]] },
  { "id": "missing",    "title": "Still need",    "status": "warn",        "rows": [["Opening balance", "", ""]] },
  { "id": "summary",    "title": "This month",    "status": "provisional", "kv": { "in": "42,000", "out": "25,400", "lowest": "-1,800 on 5 Oct" } },
  { "id": "actions",    "title": "Proposed",      "status": "provisional", "rows": [["Defer", "Streaming 1,200", "to 6 Oct"]] }
] }
```

Cards: `income`, `debts`, `essentials`, `optionals`, `missing`, `summary`, `timeline` (event days only),
`actions`, `plan` (after `finalize_plan`). Hard limit 4 KB per Daily app-message: short keys, integer rupees,
size guard in code. Sent as `OutputTransportMessageUrgentFrame` so cards land before speech finishes.

The browser also consumes four of Pipecat's default RTVI messages: `bot-transcription` for the question
headline, `bot-started-speaking`, `bot-stopped-speaking`, `user-started-speaking` for the state pill. Other
RTVI traffic is dropped. `phase` is gathering, ready, plan or confirm, computed from readiness, never from a
fixed order. `focus` names the card the last tool call touched.

## 6b. Screen

Phone width first. Reading order kept from the reference demo we studied: question as headline, one focus
card with key-value rows filling live, speaking pill, mic and end. Changed on purpose: every card stays on
screen collapsed so a correction visibly ripples; provisional values carry `?` and a confirm badge; "still
need" chips; a 30-day balance line with the dip day marked; timing vs structural stated in words; actions carry
their cost; the confirm phase asks the user to restate the plan; the phase strip reflects readiness, not a
questionnaire.

Components: `PhaseStrip`, `QuestionHeadline`, `FocusCard`, `CardStack`, `MissingChips`, `Timeline`,
`PlanPanel`, `VoiceBar`, `ErrorBanner`.

## 7. Prompt

Fixed base `agent/prompts/v2.md`, about 330 tokens measured with tiktoken `o200k_base` and held under a
400-token ceiling in the test suite. Identity and goal, not a list of prohibitions, in four short parts:

- **Who you are**: a calm, experienced money coach on a voice call, helping one person get through their next
  thirty days. You have done this for years. English only.
- **What you are here to do**: understand their month before saying anything about it, what comes in and when,
  everything that must go out, what they spend day to day, anything owed or overdue, anything unusual. Ask
  what a coach would ask, in whatever order the conversation takes. When you know enough, look at the month
  with the tools and explain it plainly, then agree what to do. If they will not answer something, say what
  you will do without it and move on.
- **Money**: every figure you say came back from a tool, never your own arithmetic, not even a subtraction and
  not even when someone challenges you and you can see they are right; asked why a figure is what it is, read
  them the derivation the tool gave you; record before you say you have noted it; the plan moves only money
  they already have, and nothing is ever approved, guaranteed or eligible.
- **How you sound**: short spoken sentences, no lists or headings, figures as people say them with "rupees",
  dates as day and month.

Cut in the redesign, each with its failing case marked superseded by the goal in
`docs/process/prompt-provenance.md`: one question per turn, start every reply with the figure, ask the missing
fields in the given order, the scripted close, a yes is understanding, the goodbye script, the result legend,
and the schema rules the tool descriptions already carry. The rule-shaped v1 prompt, 599 tokens under its own
620 ceiling, was removed on 14 September with the v1 tools; `Settings.prompt_version` survives as a name and a
record, deriving the Langfuse prompt name and landing on the recording as `v2@N`.

Every rule has a named failing case in `docs/process/prompt-provenance.md` or is marked a cut candidate.
Rules that also ride in a tool result held at 96 to 100 percent in the matrix; prompt-only rules at 0 to 80.

Per-turn block, rebuilt after every user turn and applied with `LLMUpdateSettingsFrame`: today and the window
end as day and month, then the coverage lines, `recorded: ...`, `none: ...`, and either `not mentioned yet:
...` or, when nothing is left unasked, a line saying so; then anything carried from the last call and any soft
notes. No missing list, no counts, no phase word. What to ask next, and in what order, is the model's.

## 8. Call lifecycle

Start click (mic permission, user gesture unlocks audio) → `POST /api/sessions` (slot reserved before the
first await; private room, `exp` 1 h, eject at expiry; owner token for the bot, guest token for the browser;
`create_task(run_session)`) → browser joins with a 20 s timeout, a 45 s join watchdog frees the slot if it
never does → greeting via developer message on client-ready → turns (tool calls, one snapshot each, prompt
block refreshed on every user turn end; a one-word filler covers the tool round trip; idle 25 s "still
there?", pipeline idle 300 s cancels) → end: `end_call` asks to hang up and the call ends only after the bot
has stopped speaking (6 s grace), or the browser leaves and the worker is cancelled → teardown in shielded
steps: recording written first, worker cancelled, room deleted (verified working immediately, 10 s bound).

Turn end has one judge: Pipecat's LLM turn-completion protocol with domain hints appended (a turn ending in a
function word or a bare amount is incomplete; short answers are complete), Smart Turn deferred to it.

Failure paths: missing env var fails at boot naming every missing variable; a second Start gets 409; a
browser that cannot play audio ends the call and says so; late events from a replaced call object are
ignored; a bot exception logs, writes the recording and cancels the task.

## 9. Testing

Four layers. Unit (free, seconds): engine scenario fixtures, state operations, cards including the 4 KB
guard and a byte-identical check against the generated mock snapshots; agent tools, result strings and the
prompt ceiling; voice and api with fakes that carry the real latency and errors. Browser: vitest over parser,
reducer, call lifecycle and components; Playwright runs over the mock feed. Simulation (paid,
opt in): `evals/run_suite.py` runs the voice-shaped scenarios five times each through the real prompt and
tools against a simulated person; every run is recorded under `evals/runs` and every check can be replayed.

**Three deterministic checks**, since 14 September, where there were twenty. Each folds the sub-rules it
grew from, and a violation's detail opens with the sub-rule that raised it, so nothing detected was lost, only
the score count: `money_traceable` (every figure spoken came from a tool result or the person's own words, in
whole rupees, the only other licence being a reading offered as a question under `CONFIRM_AMOUNT`; and every
"I've noted X" has a tool call behind it; folds `numbers_traceable`, `claimed_values_recorded`,
`no_spoken_decimals`), `state_matches_call` (what was recorded and planned matches what the person said and
what the call covered; folds `state_matches_facts`, `actions_match_plan`, `no_premature_plan`) and
`speakable` (voice-safe output: no borrowing offered, no ISO dates, no markdown, no silent turn; folds
`banned_phrases`, `no_iso_dates`, `no_markdown`, `no_silent_turn`). The nine advisory rules about form
(question count, goodbye shape, repeated sentences, acknowledging a change) were deleted rather than folded:
the judge's `led_like_a_coach` is the instrument for that intent, and one of them,
`changed_value_acknowledged`, had been passing every v2 run without matching a line of it. The fold was
accepted by replaying all 448 saved runs and finding the folded output identical to the sub-rules' output,
violation for violation (`evals/REPORT.md` section 10.16). The split into code and judge follows section 10.6
of that report: pointed at four runs with known money defects, the judge caught one and the deterministic
layer three, so money and state stay in code and form goes to the judge.

The end-of-call judge asks four criteria about expertise, each with a predicate in code deciding whether it
applies at all: `coverage_before_plan` (was the whole month established before planning, judged on what the
coach asked, not on whether the person had an answer), `low_point_explained` (was the lowest point explained
in plain words from the tool's own figures), `challenge_answered_without_computing` (was a doubted figure
settled from the tools rather than the coach's own arithmetic), `led_like_a_coach` (did it read as somebody
who does this for a living, or as a form worked through regardless of the answers). Voice: headless runs with a fake participant and the owner's live calls,
recorded in the same shape. `evals/REPORT.md` holds every pass table in run order and every finding with
its before and after.

## 10. Build order

| Phase | Deliverable | Done when | Hours |
|---|---|---|---|
| 0 Spike | throwaway pipeline: Daily + Deepgram + luna + Cartesia, one tool, one app-message | reply heard, message seen in console, four VERIFY items settled | 2-3 |
| 1 Engine + state | `domain/`, 10 scenario tests | pytest green including scenarios 2 and 10 corrected | 6 |
| 2 Tools + harness | `agent/`, text harness driving luna | scripted conversation with correction and conflict ends in a finalized plan | 6 |
| 3 Voice + cards | `voice/`, `domain/cards.py`, `api/`, React frontend | the one journey works by voice, cards update on correction | 9 |
| 4 Docker + docs | two-stage Dockerfile, compose, .env.example, README, import-linter | fresh clone, one command, works at localhost:7860 | 3 |
| 5 Eval suite | scenarios, sim user, judge, report, one failure with fix and evidence | eval report in docs with before and after | 8 |
| 6 Polish | demo video, what works / does not / next | released | 4 |

## 11. Decisions, approved 2026-09-11

1. Package layout `ledgerline/` with `domain`, `agent`, `voice`, `api`; one-way imports enforced; React + Vite +
   TypeScript frontend built into the same image.
2. Six tools; `get_state_summary` cut.
3. Five item kinds: income, debt, essential, optional, balance.
4. Conflicts block the plan rather than computing both scenarios. *Superseded 12 Sep by the cut: no conflict store; a changed value is reported and the model asks.*
5. Full-snapshot cards with monotonic version, not diffs.
6. Parallel tool calls on; idempotent upsert makes it safe.
7. Spike first, then engine.
8. Eval suite after the Docker phase, not interleaved.
9. Screen as in 6b; consume four RTVI messages instead of ignoring them.

Items to verify in the spike: turn-end strategy (Smart Turn vs timeout), generic vs Daily-specific urgent
frame, Responses vs Chat LLM service, strict mode through direct functions, `en-IN` on Nova-3, room DELETE
timing.
