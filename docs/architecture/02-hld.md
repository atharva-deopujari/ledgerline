# Ledgerline: high level design

Approved 2026-09-11. A voice assistant that gathers a person's next thirty days of money by conversation,
computes a plan in plain Python, and keeps the spoken numbers and the on-screen cards reading from the same
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
                                    agent/tools.py ──mutate──▶ domain/state.py
                                              ▲                     │ build_plan()
                                              │ result string       ▼
                                              └── totals ◀── domain/engine.py ──▶ domain/cards.py ──▶ urgent frame
```

Layers and the only allowed import direction: `domain` ← `agent` ← `voice` ← `api`. Enforced by import-linter.

| Module | Owns | May import |
|---|---|---|
| `ledgerline/config.py` | typed Settings from env, validated at boot | pydantic-settings |
| `ledgerline/domain/models.py` | `FinancialState` and item models | pydantic |
| `ledgerline/domain/state.py` | upsert, remove, conflict, unknown, missing, readiness | models |
| `ledgerline/domain/engine.py` | `build_plan`, day simulation, classify, actions | models, policy |
| `ledgerline/domain/policy.py` | tier order, consequences, allowed actions | nothing |
| `ledgerline/domain/cards.py` | state + plan to `CardsMessage`, 4 KB guard | models |
| `ledgerline/agent/tools.py` | six handlers, result strings | domain |
| `ledgerline/agent/prompt.py` | base prompt loader, per-turn missing block | domain |
| `ledgerline/voice/pipeline.py` | services, aggregators, observers, `PipelineWorker` | agent, domain, pipecat |
| `ledgerline/voice/session.py` | one call: join, greet, card push, prompt refresh, disconnect, idle | pipeline, agent, pipecat |
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
5. After the turn the "still missing" block is rebuilt from state and applied via `LLMUpdateSettingsFrame`.

Latency target, not measurement: transcript final ~0.3 s, first tool call ~0.7 s, cards on screen ~1.0 s,
first audio ~1.4 s. Handlers are in-memory only; no network, no disk.

## 3. State model

```python
class FinancialState(BaseModel):
    today: date
    horizon_days: int = 30
    opening_balance: Money | None          # None blocks the plan
    incomes:    list[Income]               # name, amount, date, latest_date, certainty, confirmed
    debts:      list[Debt]                 # name, kind, amount_due, min_due, due_date, autodebit, lender, confirmed
    essentials: list[EssentialExpense]     # name, amount, due_date | spread, survival, confirmed
    optionals:  list[OptionalExpense]      # name, amount, date | spread, flexible, confirmed
    unknowns:   list[Unknown]              # field, question, reason      -> "missing info" card
    conflicts:  list[Conflict]             # field, values[], sources[]   -> blocks plan, badge on card
    understanding: Understanding | None    # confirmed, restated_actions[], gaps[]
    turn: int

class DebtKind(StrEnum): SECURED_EMI, UNSECURED_EMI, CREDIT_CARD, INFORMAL
Money = Decimal quantised to 0.01
```

Upsert semantics. Key is `(kind, normalised name)`. New name creates with `confirmed=false`. Same name and
same amount is a no-op. Same name and a new amount, when the previous was confirmed or within the last six
turns, creates a conflict and keeps both values. Same name with `is_correction=true` overwrites without a
conflict.

Derived, never stored: structural gaps (debt without due date, income without date, essential without
amount), readiness (balance known, no conflicts, at least one income, no essential without amount), all totals.

## 4. Tools

Six direct functions. The model learns one habit: every fact becomes an `upsert_item`.

| Tool | Arguments | Handler does | Returns |
|---|---|---|---|
| `upsert_item` | `kind` income/debt/essential/optional/balance, `name`, `amount?`, `day_of_month?`, `debt_kind?`, `min_due?`, `spread?`, `is_correction` | normalise, upsert or conflict, resolve day to date, run engine, push cards | status, item, totals, outlier or conflict question |
| `remove_item` | `kind`, `name` | drop, run engine, push cards | status, totals |
| `resolve_conflict` | `field`, `chosen` previous/new/both | collapse, confirm, run engine, push cards | status, open conflicts |
| `mark_unknown` | `field`, `reason` | record so it is not re-asked; plan provisional | status, remaining missing |
| `finalize_plan` | none | refuse with blockers, else mark final and push final card | blocked + blockers, or top actions, shortfall, unpaid |
| `record_understanding` | `confirmed`, `restated_actions[]` | compare to plan actions, store gaps | gaps or understood |

Every handler: mutate, `build_plan`, push cards through an injected callback, `result_callback(describe(...))`.
Set `function_call_timeout_secs=5`. Never await the network inside a handler.

## 5. Plan engine

Pure function `build_plan(state, policy) -> PlanResult`. Day-by-day simulation, `Decimal`.

1. Gate: conflicts or missing opening balance return `BLOCKED` with a question.
2. Simulate 30 days. Within a day: income, spread essentials, dated items by tier, optionals. Unknown amounts
   are excluded and listed; uncertain income takes its latest date.
3. Classify: min balance ≥ 0 is `OK`; net ≥ 0 but a dip is `TIMING`; net < 0 is `STRUCTURAL`.
4. Apply actions by tier, re-simulate: `DEFER_OPTIONAL`, `CUT_OPTIONAL`, `PAY_MIN_DUE` (with interest warning),
   `PAY_ON_DATE`, `ASK_LENDER` ("you could ask"). Never a new loan, BNPL, settlement or promise.
5. Anything still unpaid makes the status `UNSOLVABLE` with the unpaid list and a consequence per item.

Priority tiers, configurable in `policy.py`: 0 survival essentials, 1 rent, 2 secured EMI, 3 unsecured EMI,
4 card minimum due, 5 informal debt, 6 card remaining, 7 optionals. Paid in that order, cut in reverse.

`PlanResult`: status, provisional, timeline rows, summary (in, out, lowest balance and date, closing), actions
with rationale and warning, unpaid with consequence, warnings, questions.

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

Fixed base (~450 tokens): role and English only; hard rules (no invented numbers, no approval promises, no
settlement offers, no new loans, never claim an action is done); speak only figures returned by tools, repeat a
newly recorded figure once; short sentences, one question per turn, no lists, "4,200 rupees" never "₹"; record
facts immediately, ask about one missing thing at a time, mark what the user does not know, ask which value is
right when a conflict is returned; when ready and the user agrees call `finalize_plan`, explain the top two
actions, ask the user to say them back, call `record_understanding`.

Per-turn block, rebuilt and applied with `LLMUpdateSettingsFrame`: today and window end, compact state
summary from the engine, up to five missing items ordered by how much they block the plan, provisional
outliers and open conflicts, phase hint.

## 8. Call lifecycle

Start click (mic permission, user gesture unlocks audio) → `POST /api/sessions` (room `exp` 1 h, two tokens,
`create_task(run_session)`) → both join (`on_first_participant_joined`) → greeting via developer message →
turns (tools, cards, prompt deltas; idle 10 s "still there?", idle 300 s cancel) → End or leave
(`on_client_disconnected`, cancel worker) → cleanup (task removed, room ejects at `exp`; no DELETE, Daily only
allows it 24 h after expiry).

Failure paths: missing env var fails at boot naming the variable; bot exception logs and cancels the task and
the browser shows "call ended"; user never joins, idle timeout cancels at 300 s.

## 9. Testing

Three layers. Unit: engine scenarios as fixtures, state upsert and conflict, cards size guard; free,
milliseconds. Text harness: OpenAI plus the real tool handlers, no audio, simulated user with hidden facts and
one scripted correction and conflict; rule checks (numbers traceable to tool results, one question per turn, no
banned phrases) gate, LLM judge scores what rules cannot, N=5 pass rate. Voice smoke: manual checklist, ~5 min
of Cartesia each. The eval suite adds scenario YAML, cassettes, a report per prompt version, and one documented
failure with before and after pass rates.

## 10. Build order

| Phase | Deliverable | Done when | Hours |
|---|---|---|---|
| 0 Spike | throwaway pipeline: Daily + Deepgram + luna + Cartesia, one tool, one app-message | reply heard, message seen in console, four VERIFY items settled | 2-3 |
| 1 Engine + state | `domain/`, 10 scenario tests | pytest green including scenarios 2 and 10 corrected | 6 |
| 2 Tools + harness | `agent/`, text harness driving luna | scripted conversation with correction and conflict ends in a finalized plan | 6 |
| 3 Voice + cards | `voice/`, `domain/cards.py`, `api/`, React frontend | the one journey works by voice, cards update on correction | 9 |
| 4 Docker + docs | two-stage Dockerfile, compose, .env.example, README, import-linter | fresh clone, one command, works at localhost:7860 | 3 |
| 5 Eval suite | scenarios, sim user, judge, report, one failure story | eval report in docs with before and after | 8 |
| 6 Polish | demo video, what works / does not / next | released | 4 |

## 11. Decisions, approved 2026-09-11

1. Package layout `ledgerline/` with `domain`, `agent`, `voice`, `api`; one-way imports enforced; React + Vite +
   TypeScript frontend built into the same image.
2. Six tools; `get_state_summary` cut.
3. Five item kinds: income, debt, essential, optional, balance.
4. Conflicts block the plan rather than computing both scenarios.
5. Full-snapshot cards with monotonic version, not diffs.
6. Parallel tool calls on; idempotent upsert makes it safe.
7. Spike first, then engine.
8. Eval suite after the Docker phase, not interleaved.
9. Screen as in 6b; consume four RTVI messages instead of ignoring them.

Items to verify in the spike: turn-end strategy (Smart Turn vs timeout), generic vs Daily-specific urgent
frame, Responses vs Chat LLM service, strict mode through direct functions, `en-IN` on Nova-3, room DELETE
timing.
