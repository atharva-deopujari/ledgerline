# Prompt rule provenance

One row per rule in `ledgerline/agent/prompts/v1.md`. A rule earns its tokens by naming the
scenario and check that would fail without it. **A rule with no named case is a cut candidate**
(OAP Step 0b: a rule re-enters only with a named failing case).

Scenario ids are the `evals/scenarios/*.yaml` names run by `evals/run_suite.py`; checks are the
rule names in `evals/checks.py`. "live call 3" is
`evals/runs/voice-2ac2a01f28e9-20260912-141347.json`, the owner's third call.

**Status of this file**: seeded 2026-09-12 from `status-B.md`'s documented failure history while
the post-cut prompt was still being written, so the rule text is as of that moment. Rows marked
*unverified* have no case on record yet — they are the input to the luna second pass, not a
verdict. Filled in as each cut lands.

| Rule (abridged) | Case that fails without it | Check | Added | Status |
|---|---|---|---|---|
| Never invent, add, subtract, round or estimate | `fragmented_balance` — model summed two balances into "that's 40,000 rupees available today" (F3); and `correction_and_conflict` turn 20, "leaves a shortfall of thirteen thousand rupees" where the plan said out 14,000, lowest 1,000, surplus 1,000 (2026-09-12) | `numbers_traceable` | 2026-09-11 | keep — still failing, see below |
| Never add two amounts, even two balances: one call each | none — code adds them (`ctx.balance_total`), so the rule is unenforceable and contradicted | — | 2026-09-11 | **cut candidate (C6)** |
| Never approved / guaranteed / eligible, no new borrowing or settlement, no skipping a payment without its consequence | no model failure on record; `banned_phrases` misses were check bugs, fixed in F4 | `banned_phrases` | 2026-09-11 | **rewrite as identity (A3)** |
| Never claim an action is done, or mention cards or the system | none — DONE-gating held on luna with zero lines; "cards"/"system" appear in no result, so naming them primes them | — | 2026-09-11 | **cut candidate (C4)** |
| Results are notes to you (the `missing:` / `blocked:` / `parked` legend) | none — legend duplicates the strings themselves; self-describing once R2 lands | — | 2026-09-11 | **cut candidate (§8)** |
| Say figures as people say them, say "rupees", not a symbol | voice rule code cannot carry; TTS reads a symbol wrong | — | 2026-09-11 | keep (A4) |
| Start every reply with the figure on the result's first line | every scenario failed `amounts_repeated` at 0%; result fix took it to 16%, this line to 80% (F2) | `amounts_repeated` | 2026-09-12 | keep |
| Say dates as day and month, never as digits | ISO dates leaked into speech before the fix; five violations in `comfortable_surplus-20260911-214731` | `no_iso_dates` | 2026-09-11 | keep |
| If a result tells you what to say, do it next | licenses the whole result-carried-instruction mechanism (R4): rules in results held 100% where prompt-only rules sat at 0-80% | `one_goodbye_with_the_end_call`, `changed_value_acknowledged` | 2026-09-11 | keep |
| If a figure is not in a result, do not say it | the no-invented-numbers floor; the reason `_headline` had to carry the amount at all (F2) | `numbers_traceable` | 2026-09-11 | keep |
| One or two short sentences, exactly one question | live call 3 turns 5, 8, 14, 16 — four questions in one turn | `one_question_per_turn` | 2026-09-11 | keep |
| No lists, no markdown | markdown in every V0 transcript; a named luna failure category | `no_markdown` | 2026-09-11 | keep |
| Talk like a person: use contractions | none of its own; reclassified as a register rule, so it lives or dies with A1's register check | none — needs the A1 check | 2026-09-11 | **folded into A1; cut if A1 has no check** |
| Call the tool first, say nothing before it; speak once after the result | live call 3 — every tool turn produced two spoken segments, each with its own question | `silent_before_acting`, `no_repeated_sentence` | 2026-09-12 | keep |
| upsert_item for every fact, even partial; remove_item when it ends | none — `upsert_item`'s docstring already says it | — | 2026-09-11 | **cut candidate (C2)** |
| If a value differs from one recorded and they did not call it a correction, ask which is right | duplicate of `phrases.CONFIRM_CHANGE`, which rides the result line (`describe.py:119`) | `changed_value_acknowledged` | 2026-09-12 | **cut candidate (C7) — only while the carrier rides** |
| If an amount sounds implausible, confirm it once | `stt_implausible_amount` — "My rent is 12." and "Salary forty-five.", the thousand dropped by STT | `implausible_amount_confirmed` | 2026-09-12 | keep — case built 2026-09-12, baseline pending |
| Ask about missing fields in the given order, one at a time | live call 3 turn 16 — four questions at once after "Nothing" | `one_question_per_turn`, `no_question_after_unknown` | 2026-09-12 | keep |
| …and never ask again about what you marked unknown | duplicate of `phrases.PARKED` ("parked, do not ask again: "), which states it per turn | `no_question_after_unknown` | 2026-09-12 | **cut candidate (C3)** |
| Income certainty uncertain; earliest day_of_month, latest latest_day_of_month | none — verbatim duplicate of the `certainty` and `latest_day_of_month` field descriptions | — | 2026-09-12 | **cut candidate (C1)** |
| When nothing blocks it and they agree, finalize_plan | measured indirectly: every scenario reaching a plan. Cut it and rerun — if the happy paths still reach `plan_final`, the line goes | `plan_reached` via `state.plan_final` in the run record | 2026-09-11 | **cut candidate — decide by experiment** |
| Explain the top two actions with the result's numbers and consequences | review F3 — the final result withheld consequences; a closing surplus read as "you are fine" next to deferrals | `numbers_traceable` | 2026-09-11 | keep |
| Ask once if it makes sense; never ask them to repeat it back | quotes the unwanted output, which primes it (Step 6b); state the wanted one instead | — | 2026-09-11 | **reword (C8)** |
| A yes is understanding: record_understanding confirmed true | none — acceptance-in-any-shape is luna's strongest measured default (pass^5) | — | 2026-09-11 | **cut candidate (C5)** |
| Say one goodbye and call end_call in the same reply; never twice | live call 3 turn 22 (goodbye, no `end_call`) and turn 24 ("Goodbye.Goodbye."); matrix passes 1-2 at 16-20% | `one_goodbye_with_the_end_call` | 2026-09-12 | keep |

## Missing rows

Two additions from `luna-capabilities.md` have a named case but no rule yet:

| Proposed rule | Case | Check | Source |
|---|---|---|---|
| Match their words and pace, never their register | register mirroring is a named luna failure category; no scenario forces it yet | none — needs a scenario. "Use contractions" is folded in here | A1 |
| End with a question they can answer any way they like; never name the word you want back | "Please reply *yes* to confirm" in 7/10 V0 previews — the one prompt line the v0 battery earned | none — needs a check | A2 |

Both need a scenario or check built before the rule can be justified, or they join the
*unverified* rows on arrival.

## Commissioned 2026-09-12

- **`stt_implausible_amount`** — BUILT. A scenario where STT drops the thousand: "My rent is 12."
  and "Salary forty-five.", corrected by the persona only when the coach asks. Pairs with
  **`implausible_amount_confirmed`**, also built: an `upsert_item` recording an amount under a
  per-kind floor must be queried in the same turn, by a question that names the item and asks
  whether the figure is right. Naming the value is deliberately NOT enough — saying "twelve rupees
  for rent" out loud is the failure. Asking instead of recording raises nothing, since no wrong
  figure reached the state. Floors: income 500, essential 200, debt 200; no floor on `optional`
  (a 40 rupee subscription is real) or `balance` (a person with 40 rupees is exactly who this call
  is for). Independent of the 100-rupee trace floor, which answers a different question.
  Note the carrier problem: a first-time implausible figure is a CREATED, and `CONFIRM_CHANGE`
  only rides a change (old -> new), so nothing in the result instructs the model. That makes this
  rule prompt-only, the 0-80% class. If the check misses its gate, the fix is a result-carried
  instruction on an implausible CREATED, not prompt wording.
- **Decide "when nothing blocks it, finalize_plan" by experiment**: cut the line, rerun the matrix,
  keep it only if a happy path stops reaching `plan_final`.


## Open failing cases

A rule with a case that is still failing is not a cut candidate; it is a rule that is not working
yet. One so far.

- **Never invent, add, subtract, round or estimate** — `correction_and_conflict`, first post-cut
  matrix (2026-09-12). The bot said "rent uses the available money and leaves a shortfall of
  thirteen thousand rupees" where `finalize_plan` had returned `out 14,000, lowest 1,000,
  surplus 1,000`. Thirteen thousand is in no tool result and no user turn: the model subtracted
  and spoke the answer as plan output, in the one place a wrong figure costs the person money.
  The repaired `numbers_traceable` caught it; before the repair it would very likely have passed,
  because the retirement half was inert and the invention half never sees a figure the model
  derived from two it was given. Not yet fixed — it is a prompt or result-shape question and it
  belongs to the luna pass, where it is the named case that keeps this rule off the cut list.
