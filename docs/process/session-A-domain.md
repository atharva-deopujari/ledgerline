# Session A · domain

Read `docs/process/00-orchestration.md` first. You own `ledgerline/domain/state.py`, `engine.py`, `policy.py`,
`cards.py` and `tests/domain/**`. `models.py` is the contract; read it, do not change it.

Research to read before coding: `docs/research/09-plan-engine.md` (algorithm, tiers, the ten scenarios with
corrected arithmetic in its context7 appendix), `docs/research/10-state-and-tools.md` sections 1 to 3 (upsert and
conflict semantics), `docs/architecture/02-hld.md` sections 3, 5, 6.

Everything here is pure Python. No Pipecat, no OpenAI, no I/O. `uv run lint-imports` must stay green.

## Order of work, TDD each step

### 1. `policy.py`
Fill `consequence` and `ask` for each tier from research 09 section 3 (late fees, penal interest, 30+ DPD bureau
reporting, repossession for secured, card interest on unpaid balance). Speakable, one sentence each, no numbers
the user did not give except the labelled "typical" interest note already in the model.
Test: every tier has non-empty consequence and ask; ranks are 0..7 contiguous.

### 2. `state.py`
Tests first in `tests/domain/test_state.py`, then implement, in this order:
- `normalise_name`: "The Rent" == "rent", "HDFC credit card" == "hdfc credit card", trailing punctuation dropped.
- `resolve_day`: today 2026-09-11, day 5 -> 2026-10-05; day 15 -> 2026-09-15; day 11 -> 2026-09-11; day 31 in a
  30-day September -> clamp to last day of that month; None -> None.
- `upsert` create: new income "salary" 42000 day 1 -> created, confirmed False, source_turn = state.turn,
  date 2026-10-01.
- `upsert` unchanged: same call again -> unchanged.
- `upsert` conflict: rent 11000 at turn 2, rent 12000 at turn 4 without is_correction -> status conflict, state
  still holds 11000, a Conflict appended with both values and a speakable question.
- `upsert` correction: same but is_correction True -> updated, value 12000, no conflict.
- `upsert` outside window: rent 11000 at turn 2 confirmed, rent 12000 at turn 20 -> conflict (confirmed value
  always conflicts). rent unconfirmed at turn 2, new value at turn 10 (beyond 6 turns) -> updated, no conflict.
- `upsert` balance kind sets `opening_balance`, name ignored.
- `upsert` outlier: rent 12 -> created but outlier True with question; salary 500 -> outlier.
- `upsert` debt requires debt_kind; card without min_due leaves it None (structural gap later).
- `remove`: existing -> removed; missing -> noop.
- `resolve_conflict` previous / new / both. `both` produces "rent 1" and "rent 2".
- `mark_unknown` appends once; second call same field does not duplicate.
- `confirm_untouched`: items with source_turn < turn-1 flip to confirmed; returns count.
- `missing`: opening balance first; debt without due_date; debt (card) without min_due; essential without amount;
  income without date; merged with state.unknowns; no duplicates; excludes fields the user declined.
- `readiness`: phases per docstring; `blockers` = opening balance None, open conflicts, no income, essential
  without amount. `score` = 1 - blockers/4 clamped.
- `snapshot` counts.

### 3. `engine.py`
Fixtures: one YAML per scenario in `tests/domain/fixtures/` with `facts` and `expected` (status, total_in,
total_out_required, lowest_balance, lowest_balance_date, actions types, unpaid names). Take the ten scenarios
from research 09 section 7 **using the corrected numbers in its context7 appendix for scenarios 2 and 10**.
Write `tests/domain/test_engine.py` parametrised over the fixtures. Then implement:
- gate (BLOCKED on conflicts or missing opening balance, `questions` filled)
- day loop with within-day ordering; spread items as amount / horizon_days per day, quantised, remainder on
  the last day so the total is exact
- uncertain income excluded; `latest_date` used when set
- classification OK / TIMING / STRUCTURAL
- actions in order: DEFER_OPTIONAL (TIMING: move flexible optionals to the first day balance recovers),
  CUT_OPTIONAL (STRUCTURAL: drop flexible optionals, cheapest first until net >= 0 or none left), PAY_MIN_DUE
  (cards: pay min_due on due date, add warning), PAY_ON_DATE (move a dated obligation to the first later day in
  window where balance covers it, flag "deferred"), ASK_LENDER (emit for anything still unpaid, phrased "you could
  ask")
- re-simulate after each action; UNSOLVABLE when anything remains unpaid, with `Unpaid` rows carrying the tier
  consequence from policy
- `provisional` True whenever `excluded_items` is non-empty
Also a hypothesis test: for random small states, total_out_planned <= total_out_required, timeline balances are
consistent (each row balance == previous + amount), and build_plan never raises.

### 4. `cards.py`
Tests in `tests/domain/test_cards.py`:
- `fmt_inr`: 42000 -> "42,000"; 1250000 -> "12,50,000"; 4200.50 -> "4,200.50"; 0 -> "0".
- `build_cards` on the sample state used in `frontend/src/protocol/sample.json` produces a message that
  round-trips through `CardsMessage.model_validate_json` and matches that file's card ids and statuses.
- provisional items render value with a trailing " ?" and the card status "confirm" when any conflict or outlier
  touches it; "blocked" on summary when plan status is BLOCKED; "final" on plan card when state.plan_final.
- timeline points: first day, every event day, last day; balance in whole rupees.
- size guard: build a state with 40 items and assert the serialised message is under 4096 bytes and the summary
  note mentions truncation.
- After the tests pass, dump the sample message to `frontend/src/protocol/sample.json` **only if it differs in
  structure**; if it does, write the diff in `docs/process/requests.md` for Session D instead of editing the file.

## Done when
`uv run pytest tests/domain` green, `uv run ruff check ledgerline/domain tests/domain` clean,
`uv run lint-imports` green. Write `docs/process/status-A.md`.
