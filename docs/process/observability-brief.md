# Brief: observability, sessions, memory, judge

Design: `docs/architecture/04-observability-hld.md`. This file is the work split, the order, the acceptance
line per phase, and the estimate. Nothing starts until the owner approves; each phase is approved on its own
and lands as its own commit set.

Rules as ever: failing test first; fakes carry the real latency and the real errors; no worker edits another
worker's files, contract changes go through `requests.md`; every result-string or prompt change is measured
on the matrix, not read; nobody commits; no attribution anywhere. Delegate bounded work (the checks move, the
schema tests, the replay of the judge over `evals/runs`) to Opus subagents.

Two rules the owner added on approval. **Reinvent nothing that exists**: the recorder already sees every
frame the tool-span observer needs, `SessionRegistry` already owns the task lifecycle, `describe` already
carries result lines, `checks.py` is the deterministic judge, `?mock=1` is the routing trick, the Langfuse
SDK is the prompt cache. Before writing a module, name the existing thing it extends. **Ponytail review at
the end**: when a session's phase is done and green, it runs `/ponytail-review` over its own diff and records
what it deleted or simplified in its status ledger before reporting done.

## Ownership

| Package or area | Owner |
|---|---|
| `ledgerline/observability/`, `ledgerline/voice/tool_trace.py`, tracing wiring in `pipeline.py`, `session.py`, `main.py`; spikes S1 to S4 | **C** |
| `ledgerline/store/` (schema, slim sessions, profile), `tests/store` | **A** (typed facts and the supersession diff are domain-adjacent; A is idle) |
| Domain: `_Item.carried`, blocker `carried`, `confirm_carried`, engine provisional rule, cards status word, snapshots | **A** |
| `ledgerline/judge/` (checks move with shims, criteria, llm, judge), `tests/judge`, `evals/harness.py` tracing, judge replay over `evals/runs`, `REPORT.md` addendum | **B** |
| `confirm_carried` tool, `describe` carried line, prompt fetch via Langfuse in `agent/prompt.py`, provenance rows, memory and judge scenarios; `ledgerline/memory/` extractor (one call at session end, closed vocabulary, amount rejection), `tests/memory` | **B** |
| `ledgerline/api/aftercall.py`, routes (`POST` body with phone, `GET verdict`, `DELETE user`, `GET review/users`), `SessionRegistry` post-call task, phone validation | **C** |
| Frontend: phone on the start screen, forget, verdict panel and poll, the user memory page, `protocol/` verdict and review types with samples, e2e | **D** |
| `pyproject.toml` deps and six import-linter contracts, `docker-compose.yml` postgres service, CI service container, `.env.example`, README, `03-folder-structure.md`, `02-hld.md` module table, `docs/README.md` reading order, `docs/research/12-observability.md` | **orchestrator** |

## Phases, in order

### Phase 0: spikes (C, half a day)

S1 turn-span parent, S2 trace id capture, S3 single provider, S4 unit count. Headless runs with
`TTS_PROVIDER=deepgram`, three runs cap. Findings to `docs/process/spike-findings.md`. Blocks phase 1 only
on S1 and S2; the fallbacks in the HLD are acceptable outcomes.

### Phase 1: tracing to Langfuse (C, B, orchestrator; one day)

- Orchestrator: deps `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`, `langfuse` (v4, exact pin);
  contracts; `.env.example`.
- C: `observability/tracing.py`, `attributes.py`, `langfuse.py` with `Null` twins; `tool_trace.py`;
  `enable_turn_tracking`; conversation attributes; trace input and output from the recorder; in-memory
  exporter test for one recorded call.
- B: harness root span per simulation run, `langfuse.environment=simulation`, session id = run id.
- Acceptance: one live call and one 5-run cell visible in Langfuse; tree reads turn, generation, tool as
  siblings; the Langfuse skill's baseline table (model, tokens, names, hierarchy, types, no secrets, trace
  input and output) audited against a fetched trace and every gap closed; whole suite green with no keys set.

### Phase 2: sessions in Postgres (A, C, D, orchestrator; one day)

- Orchestrator: `postgres:17` in compose with a volume, CI service container, `DATABASE_URL`.
- A: `store/` with `schema.sql` (users, slim sessions, profile_facts), `db.py` (pool, apply schema,
  `NullStore`), `sessions.py`, `models.py`; `tests/store` marked `db`; `NullStore` tests.
- C: `POST /api/sessions` accepts `{phone}`, validates it, derives `session_id = phone + UTC timestamp`;
  `run_session` returns `CallRecord`; `SessionRegistry` spawns `aftercall`, which ends the session row with the
  trace id and recording path; the slot is released before it runs.
- D: phone field on the start screen (the only field), sent in the body; remembered in `localStorage` for the
  next visit.
- Acceptance: a call produces one `users` row and one `sessions` row; the recording filename, the row and the
  Langfuse trace carry the same id; `docker compose up` with the database down still takes a call; `db` tests
  green in CI.

### Phase 3: profile memory (A, B, C, D; two days, includes matrix runs)

- A domain: `_Item.carried`, cleared by `upsert`; blocker `carried`; `confirm_carried(names | all)`; engine
  keeps carried items counted and the plan provisional; cards status word; snapshots regenerated once.
- A store: `profile.py` with `load_active(timeout)` returning `None` on expiry, `record_call` diff and
  supersession with tombstones, `forget`; `notes.py` with the same shape; fixture-driven tests including
  "same value, no new row".
- B memory: `ledgerline/memory/` extractor; `ledgerline-notes` prompt; replay over ten saved runs and read
  every note against the transcript before it is allowed to write; the turn-block line.
- C: hydrate the state and notes before the greeting; `aftercall` runs the extractor; `DELETE /api/users/{phone}`;
  `GET /api/review/users/{phone}`.
- B: `confirm_carried` tool; the `carried from last call:` result line on the first result and the greeting
  turn block; provenance rows; two scenarios (returning caller confirms all; returning caller changes rent) and
  a `carried_confirmed_before_plan` check; 5-run cells until the gates hold.
- D: forget button; `carried` status rendering; the `/review/users/{phone}` memory page with history and trace links.
- Acceptance: second call from the same phone opens with the carried line; `finalize_plan` refuses until
  confirmed; `state_matches_facts` 100% on both scenarios; a first-time caller's prompt and results byte-identical
  to today.

### Phase 4: prompt in Langfuse (B, orchestrator; half a day)

- B: `ensure_prompt` at boot from `v1.md`, fetch by label with fallback, Langfuse version into
  `prompt_version`; `PROMPT_SOURCE=file` keeps today's path; the ceiling test unchanged on the file.
- Acceptance: the prompt appears in Langfuse with label `production`; a live call's tag names its version;
  Langfuse unreachable means the file is used and one warning is logged.

### Phase 5: the judge (B, C, D; two days, includes calibration)

- B: move `checks.py`, `spoken_numbers.py`, `provenance.py` into `ledgerline/judge/checks/` with shims in
  `evals/` (tests move, not rewritten; a subagent does the mechanical part); `criteria.py`, `llm.py`,
  `judge.py`, `models.py`; `ledgerline-judge` prompt; replay over `evals/runs` and read verdicts against
  `REPORT.md` dispositions; addendum with the confusion table.
- C: `aftercall` runs the judge, appends the verdict to the recording file, pushes scores; `GET /api/sessions/{id}/verdict` with
  `202` while pending; a failing judge leaves status `failed`.
- D: "reviewing this call" line on `ended`, poll, verdict panel, trace link; `VerdictMessage` type and sample
  from the Python side; e2e with a mocked endpoint.
- Acceptance: a live call shows its verdict on screen within twenty seconds of ending; scores visible on the
  trace in Langfuse; the intent judge's agreement with the human dispositions is in the report before any
  criterion is called a gate.

## Estimate

Roughly seven working days of session time; with A, B, C, D in parallel and the orchestrator verifying, about
three calendar days of the owner's time, dominated by phase 3 and phase 5 matrix runs and by live calls.
Spend: Langfuse Hobby free; OpenAI for judge and extractor calls about $0.03 a call and about $0.60 for the replay over the
saved runs; matrix cells as today (about $0.07 per 5-run cell).

## Not in scope, said plainly

Audio replay, per-word STT timing, Redis, a login, alembic, managed Langfuse evaluators, memory extracted from
prose, any new engine action. Each has a line in the HLD saying why and what would change the answer.
