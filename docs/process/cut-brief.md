# The cut: move judgement about language to the model, keep correctness in code

Decided by the owner on 12 Sep evening after reading `models.py`: the state layer re-implements judgement
the model already has (is this a correction, does that amount sound wrong, is the person done, what to ask
next and how). Forty of fifty-five review findings were in that machinery; almost none in the arithmetic.
Backup of the pre-cut tree: `~/Desktop/Personal/backups/ledgerline-pre-cut-20260912-2051.tgz`.

## The line

- Code owns what must be **correct**: money, dates, priority, what is missing, what blocks the plan, the
  numbers the bot speaks. Unchanged: engine, policy, cards, Decimal, number traceability.
- The model owns what needs **understanding**: correction vs contradiction, implausible amounts, what to
  ask next and its wording, whether the person has understood, when a sentence is finished.
- Test for each component: "if this goes wrong, does the person lose money or trust?" Yes: code. No, and
  it is about language: model.

## Contract after the cut (`ledgerline/domain/models.py`, orchestrator-owned, Session A implements)

Removed:
- `_Item.confirmed`, `_Item.source_turn`, `confirm_untouched()`, the conflict window constant.
- `Conflict` model; `FinancialState.conflicts`, `.outliers`, `.opening_balance_turn`, `.opening_balance_confirmed`.
- `Understanding` model; `FinancialState.understanding`.
- `OutcomeStatus.CONFLICT`, `.RESOLVED`; `UnknownReason.STRUCTURAL`, `.USER_DECLINED`; `Unknown.question`.
- `Phase.CONFIRM`; `Readiness.score`; `PlanResult.questions` (prose).
- `state.resolve_conflict`, `_record_outlier`, `outlier_question`, `question_for` (prose), `income_answer`,
  `noted_unknowns` (fold into `missing` with the reason), `upsert(is_correction=...)`.

Kept as is: `Certainty` (a fact the person stated), `DebtKind`, `ItemKind`, item fields, `notes`, `turn`
(replay guard), `plan_final`, `call_ended`, everything under "plan output", `_unsettle` behaviour
(any change after the person understood resets `understood`; the plan they agreed to no longer exists).

Added / changed:
- `FinancialState.understood: bool = False`.
- `Unknown(field: str, reason: UnknownReason)` with `UnknownReason = UNKNOWN | NOT_APPLICABLE`.
  UNKNOWN: excluded from the maths, plan provisional, card shows "not known". NOT_APPLICABLE: the person
  says there is none (used for income: "no money coming in"); satisfies the income blocker.
- `Outcome.changes: dict[str, tuple[str, str]]`: field id -> (old, new) in speakable form, for every field
  the call actually changed. `upsert` OVERWRITES, always, and reports what changed. The model reads
  "rent: 11,000 -> 12,000" and decides whether to confirm. No blocking state for disagreements.
- `PlanResult.blockers: list[str]` of field ids (e.g. `opening_balance`, `income`) when BLOCKED.
- `Readiness(phase, blockers: list[str], missing: list[Unknown])`; `missing` = structural gaps as field ids
  with reason UNKNOWN? No: structural gaps are plain field ids in `missing_fields: list[str]`, and
  `unknowns` stay on the state. Final shape: `Readiness(phase, blockers: list[str], missing_fields: list[str])`.
- `Phase = GATHERING | READY | PLAN | DONE`. DONE iff `understood`.
- `CardStatus` loses `CONFIRM`. Cards: `missing` card lists missing fields with deterministic labels
  (`label_for(field) -> "electricity amount"`), unknowns marked "not known"; no conflict notes; the "~"
  estimate marker stays (a fact); the "?" provisional marker stays (excluded from the maths).
- `label_for(field)` replaces `question_for`: a label, not a sentence.

## Per layer

**A (domain).** Implement the contract above. `state/` shrinks: `items.py` (upsert overwrite + changes,
remove), `unknowns.py` (mark_unknown, missing_fields), `readiness.py`, `names.py`. Delete `conflicts.py`.
Engine: `questions` -> `blockers` (ids). Cards as above. Regenerate `snapshots.json`; fixtures that relied
on conflicts become plain overwrite fixtures. Tests: delete the machinery's tests with the machinery; keep
every arithmetic and cards test. Report line counts before and after and the test count.

**B (agent), fresh agent after A lands.** Tools: `upsert_item` (no `is_correction`), `remove_item`,
`mark_unknown(field, not_applicable: bool)`, `finalize_plan`, `record_understanding(confirmed: bool)`,
`end_call`. Delete `resolve_conflict`. `describe()` returns compact facts, one per line, numbers from
the domain, no prose templates: e.g. `rent: 11,000 -> 12,000` / `missing: electricity amount, salary date` /
`in 45,000, out 27,700, lowest 2,000 on 30 Sep` / `blocked: opening_balance`. `phrases.py` shrinks to labels.
Prompt gains: "If a value you record differs from one already recorded and the person did not say they are
correcting it, ask which is right before moving on." / "If an amount sounds implausible for the item,
confirm it once." / "Ask about missing fields in the order given, one at a time; if they do not know, call
mark_unknown and never ask again." / the existing silent-tool and one-goodbye rules. Keep the killed
agent's scenarios and `run_suite.py`; rerun the 5x5 matrix after the cut; the pre-cut table in
`status-B.md` "Simulation phase" is the baseline.

**C (voice).** Remove the `confirm_untouched` call in `session.py`. Nothing else expected.

**D (frontend).** `Phase` loses `confirm`, `CardStatus` loses `confirm` (types, parse, css, PhaseStrip
steps). `sample.json` statuses updated by the orchestrator from A's regenerated snapshots.

**Orchestrator.** `types.ts`, `sample.json`, HLD module table, folder-structure doc, this brief's
before/after numbers.

## Acceptance

Domain, agent, voice, api, frontend tests green; snapshots regenerated; simulation matrix rerun with the
same five scenarios: `one_question_per_turn`, `no_repeated_sentence`, `silent_before_acting` stay at 100%;
`numbers_traceable` at or above the pre-cut 92-96%; a new check `changed_value_acknowledged` (a changed
amount is either confirmed by a question or named in the reply) at or above 95%. Line count of
`ledgerline/domain/state/` under 400 (from about 1000). One live call after.
