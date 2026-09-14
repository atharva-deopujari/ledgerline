# Ledgerline: observability, sessions, memory and the call judge

Proposed 2026-09-13, awaiting the owner's approval. Extends `02-hld.md`; nothing in sections 1 to 9 of
that document changes. Four additions, one design: every call becomes a **session** that is persisted,
traced end to end in Langfuse, judged when it ends, and remembered for the person's next call.

Research behind the choices: `docs/research/12-observability.md` (to be filed from the 13 Sep survey: Pipecat
OpenTelemetry surface, Langfuse OTLP ingestion and its limits, five voice observability platforms compared,
memory libraries rejected, persistence patterns). The Langfuse agent skill is installed at
`.claude/skills/langfuse/` and its instrumentation checklist is the acceptance bar for section 3.

## 0. The rules that carry over

- **The model never computes.** Nothing here adds a number the model could speak that did not come back in a
  tool result. Carried facts from a previous call are tool results too.
- **Code owns what must be correct; the model owns what needs understanding.** Code owns: which facts carry
  over, that they are provisional until confirmed, what blocks the plan, what the judge's deterministic
  checks say, the arithmetic in every score. The model owns: how to ask whether last month's rent still
  holds, and the judge model owns the intent criteria (was the explanation comprehensible) that no
  deterministic check can answer.
- **Observability never touches the call path.** Every write to Langfuse or Postgres is fire-and-forget or
  bounded by a timeout, never awaited on the turn path, never able to raise into the pipeline. Unconfigured
  means off: no keys, no database, and the product behaves exactly as today.
- **Instructions ride in the tool result.** The memory line the model reads is a result string, not a
  prompt rule.

## 1. Components after the change

```
browser ── POST /api/sessions {phone} ──▶ FastAPI ──▶ store.sessions.create
   │                                                │ create_task(run_session)
   │  Daily audio + cards (unchanged)               ▼
   │                                    pipeline (unchanged) ── OTel spans ──▶ Langfuse (OTLP/HTTP)
   │                                                │ tool calls ──▶ voice/tool_trace ─┘ (tool spans)
   │                                                │ recorder ──▶ evals/runs/*.json (unchanged)
   │                                                ▼
   │                                    run_session fills a CallRecord as the call runs
   │                                                │ (passed in, not returned: the common end is a cancel)
   │                                    api/aftercall (own task, slot already freed)
   │                                      ├─ store.sessions.end (trace id, recording path)
   │                                      ├─ store.profile.record_call  (diff, supersede)
   │                                      ├─ memory.extract(recording, notes) ──▶ store.notes (one LLM call)
   │                                      ├─ judge.run(recording) ──▶ recording file, Langfuse scores (one LLM call)
   │                                      └─ verdict held in process: pending -> ready
   └── GET /api/sessions/{id}/verdict (poll after `ended`) ◀───────────┘
```

Next call from the same phone: `store.profile.load_active` (hard timeout, None on expiry) hydrates the
new `FinancialState` with **carried** items before the greeting; the first tool result names them.

## 2. Packages and import direction

Four new packages, all above `domain`, none importing `voice`:

```
ledgerline/
  observability/          # OpenTelemetry + Langfuse client. Imports: opentelemetry, langfuse, config
    tracing.py            # setup(settings): TracerProvider, OTLP HTTP exporter, resource; idempotent; no-op without keys
    attributes.py         # StrEnum of every span attribute name we set (langfuse.*, ledgerline.*)
    langfuse.py           # LangfuseClient protocol + real + Null: scores, prompt fetch/create, trace url
  store/                  # Postgres persistence. Imports: psycopg, domain.models
    db.py                 # pool, schema apply at boot, NullStore when DATABASE_URL empty
    schema.sql            # CREATE TABLE IF NOT EXISTS, the only schema source
    models.py             # SessionRow, ProfileFact (pydantic, Decimal as text)
    sessions.py           # create, end (a slim row: who, when, trace id, recording path; turns live in Langfuse and the recording)
    profile.py            # load_active(phone, timeout) -> list[ProfileFact] | None; record_call; forget
  judge/                  # Recording in, Verdict out. Imports: openai, domain, judge.checks
    checks/               # MOVED from evals/: checks.py, spoken_numbers.py, provenance.py (evals/ keeps shims)
    criteria.py           # intent criteria: id, question, applies_when; the list the judge model answers
    llm.py                # one structured-output call; three-valued per criterion with a quoted turn
    judge.py              # run(recording) -> Verdict: deterministic first, then llm; never raises
    models.py             # Verdict, CriterionResult, Outcome = PASS | FAIL | NOT_APPLICABLE
  memory/                 # Recording + existing notes in, notes out. Imports: openai, domain, judge.checks (amount parser)
    vocabulary.py         # NoteCategory StrEnum; the structured-output schema
    extractor.py          # one call, bounded; never raises; rejects notes with amounts
    models.py             # Note, ExtractedNotes
  voice/
    tool_trace.py         # observer: one `tool` span per executed function call, under the current turn
  api/
    aftercall.py          # the post-call task described above
    routes.py             # POST body gains phone; GET /sessions/{id}/verdict; DELETE /users/{phone}
```

Import-linter contracts (seven, from four):

```
layers: api -> voice -> memory -> judge -> agent -> domain
domain is pure: also forbids langfuse, opentelemetry, psycopg
agent never imports pipecat: also forbids langfuse, psycopg, opentelemetry
domain internal layers: unchanged
judge and memory are pure of infra: forbid pipecat, fastapi, psycopg, langfuse (they return values; the caller persists)
store imports only domain models and psycopg; observability imports only config and domain: each forbids agent, judge, memory, voice, api and the other
```

The judge sits *above* the agent, not beside it, because that is what is true: it reads the agent's output.
`checks.py` imports `phrases.CONFIRM_AMOUNT` from the agent so the rule that recognises a settled amount follows
the product's wording if it changes, while the implausibility floors are deliberately *copied* into the checks
so an eval can never inherit a drifting threshold. Imported where drift would be a defect, copied where
inheritance would be one (B-obs-1 in `requests.md`). Memory sits above the judge because the extractor uses
the judge's amount parser to reject notes that carry figures.

`evals/` stays the paid harness. `evals/checks.py` becomes `from ledgerline.judge.checks import *` so the
harness, the replay scripts and `evals/REPORT.md` keep their names; `tests/evals` moves with the code to
`tests/judge/checks`.

## 3. Tracing (Langfuse over OpenTelemetry)

**Source of spans.** Pipecat 1.9 emits `conversation` -> `turn` -> `stt_*`, `llm_*`, `tts_*` with TTFB,
character counts, `gen_ai.usage.*` tokens and `turn.was_interrupted`, once `PipelineWorker` gets
`enable_tracing=True` (turn tracking defaults on in 1.9.0; both are passed explicitly). Our build already sets
`enable_metrics` and `enable_usage_metrics`.

**One provider, one exporter, owned by the SDK.** Spike S3 (`docs/process/spike-findings.md`) found two silent
failures in the first draft of this section: a Langfuse client with tracing disabled drops every score, and a
tracing-enabled client adds its span processor to whatever provider it finds, so an OTLP exporter of our own
would export every span twice. So `observability/tracing.py` builds the `TracerProvider` with the resource
attributes, registers it as the global provider, and hands it to `Langfuse(tracer_provider=provider)`; the SDK
owns the OTLP/HTTP exporter, auth, environment, masking and flush. Pipecat's `setup_tracing()` is not called (it
would register a second provider that OpenTelemetry drops with a warning). Pipecat's decorators and
`TurnTraceObserver` write through the global provider. Langfuse accepts OTLP over HTTP only; the SDK does the
right thing, a hand-built gRPC exporter would fail silently.

**Turn context is public API.** `PipelineWorker.turn_trace_observer.get_current_turn_context()` returns the
current turn's span context, and `get_turn_context(1)` survives the pipeline, so the trace id `aftercall` needs
for scoring is `format(ctx.trace_id, "032x")` with no lookup.

**What Pipecat does not emit, and we add.** The Chat Completions path emits no span per executed tool call
(verified in `service_decorators.py`; only the Gemini Live and OpenAI Realtime paths do). `voice/tool_trace.py`
is a `BaseObserver` like the recorder: on `FunctionCallInProgressFrame` it opens a span named after the tool
(`upsert_item`, `finalize_plan`, ...), typed `tool` via `langfuse.observation.type`, input = arguments, and
on `FunctionCallResultFrame` sets output = the result string and ends it. Parent = the current turn span
(spike S1 below settles how that context is obtained). This is what makes the Langfuse tree read as the
best-practices page asks: generation, then the tool it requested, as siblings under the turn.

**Trace identity and grouping.** One call = one trace; Langfuse's own Pipecat guide says so and says not to
invent a session per call. We set on the conversation span through `additional_span_attributes`:

| attribute | value | why |
|---|---|---|
| `langfuse.trace.name` | `coach-call` | stable, filterable; never the uuid |
| `user.id` | the phone | per-person cost and quality, memory debugging |
| `session.id` | our call id (phone plus UTC stamp) for voice, matrix run id for simulation | one Langfuse session is one call, its root input the whole transcript as chat messages, written once at teardown because the span exists only after Pipecat's conversation span has closed, so every turn reads in the Sessions view (owner's ruling of 14 Sep, replacing the phone, which had merged calls hours apart); a person's calls group under `user.id` |
| `langfuse.environment` | `production` / `development` / `simulation` | keeps sim traces out of production dashboards |
| `langfuse.trace.tags` | `prompt:v<N>`, `tts:cartesia`, `llm_api:chat`, `source:voice` | immutable dimensions known at start |

Trace input and output are runtime values the conversation span cannot take, so the recorder opens one span of
its own (`call`) and sets `langfuse.trace.input` (first user utterance) and `langfuse.trace.output` (the plan
summary line, or the reason the call ended) on it. Langfuse treats that span as a second application root, so
it repeats the conversation attributes (name, user, session, tags) or the trace reads back unnamed.

**Four things live ingestion taught that no unit test did** (`docs/process/spike-findings.md`, "What four live
calls taught us about Langfuse ingestion"): the SDK's default export filter keeps a span only if it comes from
the Langfuse tracer, carries a `gen_ai.*` attribute or a known instrumentor scope, so Pipecat's conversation,
turn and our tool spans were silently dropped until `should_export_span` also accepted the `pipecat` and
`ledgerline` scopes; an observer sees a frame once per processor hop, so one tool call is one span keyed by
`tool_call_id` for the life of the call, never reopened by a late hop; SDK 4.15.2 has neither `update_trace`
nor `start_as_current_span`, and a fake that answers to a method the real class lacks hides that, so a test
asserts the SDK methods we call exist on the real class; the attribute names are `user.id` and `session.id`,
not `langfuse.user.id` and `langfuse.session.id`, and a wrong name exports silently with the field empty.

**Known limits, accepted.** STT and TTS arrive as plain spans, not generations, so Langfuse computes no cost
for them (open issue since Dec 2025). LLM cost computes from `gen_ai.*` and the model name. The JSON recording
stays the record of tool calls and final state; Langfuse is the viewer, not the archive. Hobby retention is
30 days; recordings and Postgres are permanent.

**Simulation runs trace too.** `evals/harness.py` opens its own root span per run with the same attributes
and `langfuse.environment=simulation`, so a matrix cell is one Langfuse session of five traces, and the judge
scores land beside the deterministic checks.

## 4. Sessions in Postgres

Nothing Langfuse already holds is stored twice. Langfuse has every turn, every tool call with its result
(section 3), latency, tokens and the scores; the JSON recording on disk is the permanent transcript. Postgres
holds only what needs a query by our own keys at call start, and one slim row that ties the three together.

One container in compose, `postgres:17`, one database, schema applied at boot from `schema.sql` with
`CREATE TABLE IF NOT EXISTS` (no migration tool until a second schema version exists; the upgrade path is
`alembic`, noted in the file). Driver `psycopg[binary,pool]` 3.x, async, plain SQL, no ORM.

```sql
users          (phone text pk, created_at timestamptz, forgotten_at timestamptz)
sessions       (id text pk, phone text fk null, started_at, ended_at, ended_by text, prompt_version text,
                langfuse_trace_id text, recording_path text)   -- phone nullable so forget can detach the row
profile_facts  (id bigserial pk, phone text fk, kind text, name text, field text, value text,
                certainty text, source_session_id text fk, recorded_at, last_confirmed_at,
                superseded_by bigint null)
profile_notes  (id bigserial pk, phone text fk, category text, text text, evidence_session_id text fk,
                evidence_turn int, recorded_at, superseded_by bigint null)
```

Money is `text` holding the `Decimal` string, never `numeric` coerced through a float. `sessions.create` at
`POST /api/sessions` is the one write on the request path and is bounded (500 ms) and non-fatal: a database
outage degrades to today's behaviour with a logged warning. Everything else is written by `aftercall`.

`NullStore` implements the same protocol and is what tests, CI without a service container, and an
unconfigured deployment get. Store tests marked `db` run against a real Postgres (CI service container).

## 5. Profile memory

**What is remembered.** Exactly the facts the person stated through tools: kind, name, field, value,
certainty. Nothing extracted from the transcript by a model. The design reviewed on 13 Sep (a production
chat agent's memory pipeline) confirmed the two things worth copying and the one thing not to: copy
supersession rows and a closed typed vocabulary, do not copy an extraction model over prose when facts are
already structured.

**Write path.** `store.profile.record_call(user_id, session_id, final_state)`: for each item field in the
final state, compare with the active fact (same kind, name, field, `superseded_by IS NULL`); unchanged
means no row; changed or new inserts a row and stamps the old one's `superseded_by`. Removed items and
`NOT_APPLICABLE` marks supersede with a tombstone value. History stays: rent 11,000 then 12,000 is two rows.
Deterministic, one transaction, tested against fixtures.

**Read path.** At session start, `load_active(user_id, timeout=0.2)` returns the active facts or `None` on
timeout or error; `None` means the call proceeds with an empty state and a warning, never a delay the person
can hear. Facts hydrate the new `FinancialState` as items with a new flag:

- `_Item.carried: bool = False` (domain, additive). Set only by the loader; **cleared by any `upsert` of
  that item**, same value or new. Cards show a carried item with a `carried` status word.
- **Readiness blocker `carried`** while any item is carried and unconfirmed: `finalize_plan` refuses with
  `blocked: carried` and names them. Code owns that a plan is never built on unconfirmed last-month figures.
- New state operation `confirm_carried(names | all)` and tool of the same name, for "everything is the
  same as last time". A person who confirms all in one breath does not get asked six times.
- Engine: carried items count in the maths (a survival plan with rent missing is a wrong plan), and the
  plan is `provisional` while any remain, as it is for `UNKNOWN` today.

**The instruction rides in the result.** The first tool result of the call (and the greeting's turn block)
carries: `carried from last call: rent 12,000 on the 5th, salary 45,000 on the 1st; confirm or change each
before the plan`. Nothing in the base prompt mentions memory, so a first-time caller's prompt is unchanged.

**Staleness, three mechanisms, all code.**

1. *Carry policy per field* (`policy.py`, a table beside the tiers). Opening balance never carries: it changes
   daily and is always asked fresh. Debt `amount_due` (a card balance) never carries: it changes monthly and a
   wrong figure loses money, so it comes back through `missing:` and is asked. Income certainty resets to
   `CONFIRMED` on confirmation: "may not come" was about last month. Everything recurring carries: income
   amount and days, essential amount, due date and spread, debt minimum, EMI, due date and kind, optional
   amount, date and flexibility.
2. *Age* (`load_active`). Only facts whose `recorded_at` or `last_confirmed_at` is within
   `PROFILE_MAX_AGE_DAYS` (default 60, one cycle plus slack) reach a call. Older rows stay as history.
   `confirm_carried` refreshes `last_confirmed_at`; `upsert` inserts a new row.
3. *Untouched means unrefreshed* (`record_call`). Only items the person touched this call, by statement or by
   confirmation, are written. A carried item never confirmed, say because the call ended early, keeps its old
   timestamps and ages out on its own. No sweep, no timer.

*Blanket confirmation is allowed but never silent.* `confirm_carried(all)` exists for "everything is the same",
but the result line that introduces carried facts lists each by name and figure and instructs the model to
say them back before asking whether all still hold. The person hears the finished loan named and objects.
Cards show the same items with a `carried` status word. `remove_item` writes a tombstone row, so a fact the
person ended never carries again inside the age window.

**Soft notes, the one place a model writes memory.** Facts cover figures. What they miss is what the person
said in words: a job that may end, a parent's medical bills, "the gym is my health", "salary is often late",
"do not suggest asking my lender". One extractor call runs in `aftercall` over the whole transcript, once per
call, beside the judge. Bounded on every side, because this is where invented memory would come from:

- *Closed vocabulary.* Categories `circumstance | pattern | preference | goal | constraint` as a `StrEnum`
  compiled into the structured-output schema, so an invalid category is unrepresentable.
- *Shape.* `{category, text (under 120 chars), evidence_turn (must exist), supersedes (small index into the
  existing notes passed in, never an id)}`, at most eight per call. The existing active notes are passed in
  so the model can say which one a new note replaces; code stamps `superseded_by`.
- *No figures.* A note carrying a money amount is rejected in code (the `spoken_numbers` parser already reads
  amounts out of text). Every number the bot may speak still comes from a tool result.
- *Storage and age.* `profile_notes(id, phone, category, text, evidence_session_id, evidence_turn,
  recorded_at, superseded_by)`, same supersession and `PROFILE_MAX_AGE_DAYS` rules as facts.
- *Read path.* Loaded with the facts at call start (`load_active` answers `None` when the store could not be
  read in time and `[]` for a first-time caller; the two are different and `NullStore` always answers `[]`); rendered in the turn block as `about them, from earlier
  calls (untrusted, never evidence for a figure): ...`, present only when notes exist. The extractor prompt is
  a third Langfuse prompt, `ledgerline-notes`.
- *Package.* `ledgerline/memory/` (recording and existing notes in, notes out; imports openai and domain
  only, like `judge/`); `store/notes.py` persists.

**Two implementation notes from phase 2.** `CallRecord` is passed into `run_session` and filled in as the call
runs, not returned: the ordinary way a call ends is the browser leaving, which cancels the task, and a return
value would be lost exactly when the record matters. And two calls from one phone inside the same second share a
`session_id`; nobody outside a test can start, end and restart a call in a second, and the alternatives were a
longer id or a varying suffix, so the collision is accepted and the test that used to assert distinct ids says so.

**Identity.** The start screen asks for a phone number and nothing else. `user_id` is the phone (digits only,
validated in code at the API boundary: ten digits, or an E.164 string, refused otherwise). `session_id` is the
phone followed by a UTC timestamp, `9876543210-20260913T141502Z`, so a recording filename, a Postgres row and a
Langfuse trace all read as one call of one person. The phone reaches Langfuse as `langfuse.user.id` and as
trace metadata; this is personal data in a third-party tool, acceptable for a private demo and said plainly in
the README, and the place to hash it if that ever changes is the one function that derives `user_id`.

**Forget.** `DELETE /api/users/{phone}` sets `forgotten_at`, deletes `profile_facts` and `profile_notes` (the softer half of
the same personal data; leaving them would make the button a lie), and keeps sessions with the phone nulled so
the row stays countable while nothing about it points at the person. One button on the start screen. Day one, because the design we reviewed had no user-level
delete and that is a gap worth not inheriting.

## 6. Prompt management

`agent/prompts/v1.md` stays in the repository as the **source of truth and the fallback**; the prompt
ceiling test keeps measuring the file. At boot, `observability.langfuse.ensure_prompt("ledgerline-coach",
file_text)` creates a Langfuse text prompt with label `production` if none exists, or a new version if the
file text differs from the current `production` version (commit message = git sha). At call start the prompt
is fetched by label with the SDK cache (60 s, stale-while-revalidate) and `fallback=file_text`, so a Langfuse
outage costs nothing. The Langfuse version number becomes `prompt_version` in the recording, the Postgres
session row, and the `prompt:v<N>` tag, so any trace, run or verdict names the prompt that produced it.

The per-turn block (`turn_block(state)`) is computed, not templated: Langfuse has no conditionals, and the
block is state, not prompt. It stays in code and is appended after `compile()`.

The judge's criteria prompt is a second Langfuse prompt, `ledgerline-judge`, same mechanism. Redis is not
used: the SDK's in-process cache already covers a single instance and the prompt changes rarely.

## 7. The call judge

**When.** In `aftercall`, after the recording is on disk and the Daily room is deleted, in its own task so
the single call slot is free within a second of the call ending. Typical duration: deterministic checks
under 100 ms, the intent judge 5 to 15 s.

**Two layers, one Verdict.**

1. *Deterministic*: `judge.checks.run_checks(recording)` and `run_advisory`, the fourteen rules that gate the
   matrix today (`numbers_traceable`, `state_matches_facts`, `actions_match_plan`, ...). Pass or fail per rule
   with the violating sentence. Same code as the evals; that is why it moves into the package.
2. *Intent*: one structured-output call to the judge model (`JUDGE_MODEL`, default a different model from
   the coach so the writer does not grade itself) over the transcript, tool calls and final plan, answering
   each criterion in `criteria.py` with `PASS | FAIL | NOT_APPLICABLE`, a one-line reason, and the turn index
   it rests on. Criteria come from `evals/REPORT.md` section 9: explanation comprehensible, two actions the
   right two given the plan, register fit for someone worried about money, close left them free to answer
   any way, questions purposeful rather than a checklist, corrections handled without friction. Each has an
   `applies_when` predicate in code so `NOT_APPLICABLE` is decided by code where it can be (no plan means the
   explanation criteria do not apply) and by the model only where it must.

**Three-valued on purpose.** A criterion inapplicable in 28 of 30 runs is measured on two; the verdict and the
matrix table both show the not-applicable count.

**Where it lands.** Three places, none of them a new table. The verdict is appended to the call's JSON
recording (so `evals/runs` carries the judge's view beside the deterministic checks, replayable later); it
becomes Langfuse scores on the call's trace, one per criterion (`BOOLEAN` for deterministic rules,
`CATEGORICAL` pass/fail/not_applicable for intent, `NUMERIC` 0 to 1 for the summary), normalised in code,
never in the judge prompt; and it is held in process for `GET /api/sessions/{id}/verdict`, which the screen
polls. A restart between call end and the poll loses only the in-process copy; the file and the scores remain.
Score names are stable identifiers and are treated as an API.

**Wire shape** (`GET /api/sessions/{id}/verdict`, mirrored in `frontend/src/protocol/verdict.ts`, sample
generated from the Python side):

```
Verdict {
  session_id: str
  status: "pending" | "ready" | "failed"
  summary: float | null                    # 0 to 1, computed in code from the two layers
  deterministic: [{ rule: str, passed: bool, detail: str | null }]
  intent: [{ criterion: str, outcome: "pass" | "fail" | "not_applicable", reason: str, turn: int | null }]
  judge_model: str | null
  trace_url: str | null
}
```

**Calibration before trust.** The judge is a new instrument and the repo's rule holds: a check that has not
caught a real defect is a test of nothing. Before the intent judge gates anything, it is replayed over the
saved runs in `evals/runs` and its verdicts read against the human dispositions in `evals/REPORT.md`; a
judge being wrong is itself a finding and goes in the report. Until then its scores are advisory.

**Screen.** When `ended` arrives, the board shows a quiet "reviewing this call" line and polls the verdict
endpoint every two seconds, up to sixty. The verdict panel lists deterministic rules with pass/fail, intent
criteria with their three states and the quoted turn, the summary score, and a link to the Langfuse trace
when `LANGFUSE_PROJECT_ID` is set. Demo-facing; the person on a real call would never see it.

## 7b. Review screen

Langfuse is the review screen for calls: traces, turns, tool calls with results, latency, tokens, scores,
sessions per phone. Nothing of that is rebuilt. What Langfuse cannot show is a person's memory, so one page:

- `/review/users/{phone}`: active profile facts as a ledger; below, the history with superseded values struck
  and dated; the person's calls listed with a link to each Langfuse trace; the forget button.

Reached by path without a router dependency (a small `useRoute` on `location.pathname`, the same trick as
`?mock=1`; FastAPI's static catch-all already serves the app for any path). Backend:
`GET /api/review/users/{phone}` over `store`, one pydantic response model mirrored in
`frontend/src/protocol/review.ts` with a sample generated from the Python side as `sample.json` is today.
No authentication: a demo instrument on a private deployment, said plainly in the README.

## 8. Configuration

All optional; empty means off.

```
LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_BASE_URL   # tracing, prompts, scores
LANGFUSE_PROJECT_ID                                            # only for the trace link on screen
LANGFUSE_ENVIRONMENT=development                               # production | development | simulation
DATABASE_URL=postgresql://ledgerline:ledgerline@postgres:5432/ledgerline
JUDGE_MODEL=<model id>                                         # empty disables the intent layer only
NOTES_MODEL=<model id>                                         # empty disables the soft-notes extractor
PROMPT_SOURCE=langfuse                                         # or file
PROFILE_MAX_AGE_DAYS=60                                        # older facts stay history, never carried
ENABLE_TRACING is replaced by the presence of the Langfuse keys; Redis is not used
```

## 9. Testing

- Unit: `NullLangfuse`, `NullStore`, `FakeJudgeModel` behind protocols; fakes carry real latency (an
  `asyncio.sleep` matching the timeout they guard) and the real error types.
- Store: `tests/store` marked `db`, run in CI against a `postgres:17` service container; schema idempotency,
  supersession, forget, timeout returns `None`, phone validation at the boundary.
- Tracing: an in-memory OTel exporter asserts span names, types, parents and the attribute set for one
  recorded call; no network.
- Judge: deterministic layer keeps its fixtures; intent layer has a fake model returning a fixed verdict, and
  one `llm`-marked test with the real model on one saved run.
- Domain: `carried` flag, blocker, `confirm_carried`, cards status word, snapshots regenerated once.
- Frontend: reducer and panel tests on a `verdict` sample fixture; e2e journey extended with a mocked verdict
  endpoint.
- Aftercall: the slot is free before the judge runs; a judge exception leaves a `failed` verdict, never a
  missing one; the verdict lands in the recording file.

## 10. Spikes before build

Spikes S1 to S3 were answered on 13 Sep by reading the installed source (see `spike-findings.md`); S4 rides with
the first live call.

- **S1** Parent context for tool spans: how `TurnTraceObserver` exposes the current turn span in Pipecat 1.9
  (context provider, or a private attribute), and whether an observer can open a child span under it. Fallback:
  tool spans as children of the conversation span with a `turn` attribute.
- **S2** Trace id capture: the conversation span's OTel trace id must be known to score by `trace_id`. Read it
  from the same context as S1, else set our own `langfuse.trace.id`-compatible id if Langfuse honours one on
  OTLP, else look the trace up by `metadata.session_id` after the fact (30 requests a minute is enough).
- **S3** One `TracerProvider`: the Langfuse Python SDK v4 is OTel-based; confirm it does not install a
  second provider when used for scores and prompts only (`tracing_enabled=False`), or use the REST client.
- **S4** Hobby budget: one real call, count units in the Langfuse usage view, confirm the estimate of about
  120 per 30-turn call.

## 11. Decisions proposed

| Decision | Chosen | Rejected |
|---|---|---|
| Observability home | Langfuse Cloud Hobby over OTLP; same tool as the chat agents | Arize, Coval, Cekura, Bluejay (audio replay not needed yet); Roark (pins Pipecat below 1.0); self-host (four containers for a demo) |
| Tool visibility | own `tool` spans from an observer | monkeypatching Pipecat decorators; waiting for upstream |
| Judge placement | own code at call end, scores pushed | Langfuse managed trace-level evaluators (deprecated in v4; one call is one trace) |
| Prompt store | Langfuse prompt with the file as source and fallback | Postgres prompt table plus Redis |
| Memory | Postgres facts from tool calls, supersession rows; one bounded extractor call per call for soft notes only | mem0, Zep, Letta (re-derive structure from prose); vector store; extracting figures from prose |
| Persistence | Postgres, row per turn, written after the call | JSONB blob per call; Redis; writes on the turn path |
| Identity | phone typed at start; session id = phone + timestamp | browser uuid; login with OTP (the upgrade path) |
| Store scope | users, slim sessions, profile facts | turns and verdict tables (Langfuse and the recording already hold them) |
| Review screen | one page for a person's memory, Langfuse for everything else | rebuilding a sessions and turns viewer |
