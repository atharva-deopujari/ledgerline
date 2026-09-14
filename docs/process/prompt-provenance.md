# Prompt rule provenance

One row per rule. A rule earns its tokens by naming the scenario and check that would fail without
it. **A rule with no named case is a cut candidate** (OAP Step 0b: a rule re-enters only with a
named failing case).

**Read the first two tables as history, not as the product.** They are the v1 prompt and the v1
result strings, and both were deleted on 14 September once the after table was read: there is no
`prompts/v1.md`, no `agent/tools/handlers.py` and no `agent/tools/describe.py` any more, and the
nine result-carried instructions are down to four. The rows stay because the CASES stay — every
one of them is a real failure that really happened, and a rule may only come back by naming one.
What is live today is the last three sections: what v2 cut, what came back with a case, and what
the deletion retired.

Scenario ids are the `evals/scenarios/*.yaml` names run by `evals/run_suite.py`; checks are the
rule names in `ledgerline/judge/checks/checks.py`. "live call 3" is
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

## Result-carried instructions (v1 · deleted 14 September)

Not prompt rules, but rules all the same, and the ledger was misleading without them. Nine
instructions rode on v1's result strings, and across every matrix a rule carried by a result has
held where the same rule in the prompt alone sat between 0% and 80%. One per result, because a
turn holds one question.

| Instruction | Case that fails without it | Check | Added | Status |
|---|---|---|---|---|
| `say one short goodbye now and nothing more` | live call 3 turn 22 (goodbye, no `end_call`) and turn 24 ("Goodbye.Goodbye."); 16-28% before it | `one_goodbye_with_the_end_call` | 2026-09-12 | 100% |
| `confirm which is right before moving on` | the cut removed the conflict machinery; a changed figure had nothing to make the model ask | `changed_value_acknowledged` | 2026-09-12 | 100% |
| `say this back, then ask` | the model recorded a figure and went straight to its next question in a third of calls | `amounts_repeated` | 2026-09-12 | 80% -> 96% |
| `<name> looks small, confirm it before moving on` | `stt_implausible_amount` — "recorded rent 12; say this back, then ask" produced "Your rent is twelve rupees" in 5 of 5 | `implausible_amount_confirmed` | 2026-09-12 | 0% -> 100% |
| `record any other amount they named before replying, then say the total back and ask` | `fragmented_balance` — one balance call, 20,000 stored where the person has 40,000, 15 post-cut runs | `state_matches_facts` | 2026-09-12 | 0% -> **100%** |
| `say the total back and ask` (balance changes only) | with `confirm which is right` on a balance the result asked the person to choose between half and all of their own money; `changed_value_acknowledged` 0% in 5 of 5 | `changed_value_acknowledged` | 2026-09-13 | 0% -> **100%** |
| `ready to plan; if you have not yet asked whether anything else goes out this month, ask once, then finalize_plan` | `fragmented_balance-20260912-220810` — finalised on cash, rent and salary, 54,000 surplus, groceries/card/gym never asked about (review 13 F2) | `state_matches_facts`; watch `one_question_per_turn`, `no_question_after_unknown` | 2026-09-13 | 100%, no rule cost |
| `no actions needed: every payment is covered in full; explain the lowest point and propose nothing` | `fragmented_balance-20260913-003557` — plan came back with a 63,500 surplus and no actions, and the model invented two actions plus "paying only the minimum leaves 1,800 rupees still due" (B-13) | `numbers_traceable` | 2026-09-13 | 80% -> **100%** |

| `carried from last call: <each figure>; say each back, then ask whether all still hold, confirm or change each before the plan` | `returning_confirms_all` — the domain blocks the plan until carried figures are confirmed, and `confirm_carried(all)` clears that in one call, so nothing in code can tell whether the person was ever told what they agreed to | `carried_confirmed_before_plan` | 2026-09-13 | 100% on both returning cells |

| `new item; if they meant a carried one, say which and move it: <each>` | `fragmented_correction` — "My red went up to / thirteen thousand" filed as an opening balance nobody named, then stated as a fact; 80% before | `state_matches_facts` | 2026-09-14 | see the ten-run cell |
| `call this BEFORE you say you have noted anything` (upsert_item docstring, not a result) | C's third live call — "I've noted rent as 13,000 rupees" with no tool call at all | `claimed_values_recorded` | 2026-09-14 | 100% on 5 runs |

The counter-example belongs beside them: a card's `min_due` is read back next to its amount and
always has been, and the model still sent the full balance as the minimum in 4 of 13 post-cut
runs. The lever works on **what to do next**, not on **what a value means**. That one went to the
field description.

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


## Superseded by the goal · prompt v2, 14 September

`prompts/v2.md` is 270 tokens against a 400 ceiling, where v1 was 599 against 620. The rules below
are gone from it. Each one was added against a real failing case and each case is still real; what
changed is that the brief replaces them with a goal the model can reason from, on the evidence that
55 of the 109 constraints in the census were about language, order and tone and 54 had no recorded
failing case at all. Recorded here so that if a case comes back, the line that closed it is one
lookup away rather than a rediscovery.

| Rule cut from v2 | The case it was added for | Where to find it |
|---|---|---|
| One or two short sentences, exactly one question | live call 3, four questions in one turn | `one_question_per_turn` — instrument retired 14 Sep, rule already cut from v2 |
| Start every reply with the figure on the result's first line | F2, `amounts_repeated` 0% then 80% | `amounts_repeated` — instrument retired 14 Sep, rule already cut from v2 |
| Ask about missing fields in the given order, one at a time | live call 3 turn 16 | superseded by the goal's "in whatever order the conversation takes" |
| …and never ask again about what you marked unknown | duplicate of `phrases.PARKED` | C3, already a cut candidate |
| Ask once if that and what happens if they skip it make sense | the scripted close | the brief calls it a script; V0 Finding A1 warned against steering |
| A yes is understanding | luna's strongest measured default (pass^5) | C5, already a cut candidate |
| Say one goodbye and call end_call in the same reply | live call 3 turns 22 and 24; 16-28% before the fix | `one_goodbye_with_the_end_call` — instrument retired 14 Sep; the goodbye is the model's own in v2, asked for by `phrases.GOODBYE` |
| Results are notes to you (the `missing:`/`blocked:`/`parked` legend) | F7, a label read out verbatim | superseded: v2 results are facts, not orders |
| upsert_item for every fact; income certainty and ranges | duplicates of field descriptions | C1, C2 |
| Never claim an action is done, or mention cards or the system | none on record | C4 |
| If a value differs and they did not call it a correction, ask which is right | the cut removed the conflict machinery | C7; the result still shows old and new |
| If an amount sounds implausible, confirm it once | `stt_implausible_amount`, 0% then 100% | `implausible_amount_confirmed` — instrument retired 14 Sep; `phrases.CONFIRM_AMOUNT` still rides the result, because a twelve-rupee rent is money |

**Kept in v2, and why each survives a 250-token budget:** every figure comes from a tool and you
never work one out "not even a subtraction, not even when someone challenges you and you can see
they are right" — that sentence is the owner's call verbatim, where conceding a correct challenge
was exactly when the bot computed; read them the derivation when asked why; record before you say
you have noted it (`claimed_values_recorded`, C's third call); never suggest new borrowing and
never say approved or guaranteed (`banned_phrases`, and one `owner_call_1` run offered credit);
the voice rules, which code cannot carry.

## Added back to v2, each with the run that failed without it · 14 September

The redesign cut a rule only where nothing failed without it. Two came back on the first v2 runs,
and one line was reworded on measured vendor guidance rather than on a failure here.

| rule (v2) | the failing case | the check |
|---|---|---|
| "Short spoken sentences, spoken not written: no lists, no bullets, no headings" | `owner_call_1-20260914-021734`, turns 30 and 42: "walk me through" answered with a markdown bullet list, twice in one run | `no_markdown`, a gate |
| "usually one question at a time — two only when they belong together" | not a failure here: every voice vendor recommends it (Vapi, Retell, LiveKit), and `one_question_per_turn` is advisory now, so the harness cannot push it back off | `one_question_per_turn`, advisory |

The second row is the one place a rule in v2 rests on outside evidence rather than on a run of our
own. What was cut with it is the part no vendor recommends and the census could not source: the
**fixed order** and the word *exactly*. `docs/research/13-agent-design.md` is the citation.

**And one result line that is neither a rule nor an order.** `in minus out 12,000` was added to
the month view after two v2 runs did that subtraction out loud when challenged — "thirty minus
eighteen is twelve" — which is the one thing this product forbids. The figure is the commonest
question a person asks about their own month, and no result contained it. Nothing was said to the
model about it; the answer was simply put where it would be read. Three runs later the same
challenge produced "the fifty-seven thousand figure is not the result", with every figure from a
result. This is the mechanism the repo keeps rediscovering, stated as plainly as it goes:
**a model asked a question its results cannot answer will answer it anyway.**


## Retired by the v1 deletion · 14 September

The rules below are gone because the code that carried them is gone, not because the case stopped
being real. Nothing replaced them except the goal in v2 and the four instructions `facts.py` still
carries.

| rule | where it lived | what carries the case now |
|---|---|---|
| `say this back, then ask` | `describe._asked_back` | nothing: the result states what was recorded and the model decides whether to read it back |
| `confirm which is right before moving on` | `describe._change_lines` | the line itself — "rent 11,000 before, now 12,000" — and the model's judgement about correction versus contradiction |
| `say the total back and ask` (balance) | `phrases.BALANCE_TOTAL` | `phrases.BALANCE_PARTS`, which survives: a half-counted balance is money lost |
| `ready to plan; ask once, then finalize_plan` | `phrases.READY_TO_PLAN` | the coverage fact, which says what has not come up instead of when to stop |
| `no actions needed … propose nothing` | `phrases.NO_ACTIONS` | `facts.NOTHING_TO_DO`, same sentence without the order: "nothing to do: every payment is covered in full" |
| `new item; if they meant a carried one …` | `phrases.NEW_WHILE_CARRIED` | nothing; carried items are listed as facts and the model decides |
| `carried … say each back, then ask whether all still hold` | `phrases.CARRIED_SETTLE` | the turn block's `From their last call:` line, a fact with no instruction attached |
| `understood, say one goodbye and call end_call in this reply` | `phrases.UNDERSTOOD` | `phrases.GOODBYE`, which survives on `done` |
| `parked, do not ask again` / `missing:` / `blocked:` legend | `phrases.PARKED`, `MISSING` | the coverage lines and `phrases.BLOCKED` |

The measured pass rates those instructions bought are in `evals/REPORT.md` and stay quotable; what
cannot be re-run is the v1 column of §10.13, because the build that produced it no longer exists.


## Instruments retired with the three-check fold · 14 September

Nine advisory rules and `explains_on_request` were deleted when the twenty deterministic checks
folded into three (`evals/REPORT.md` §10.16). Where a row above cites one as its instrument, the
row now says so: **instrument retired 14 Sep, rule already cut from v2**. The cases stay real and
the rules stay cut; what is gone is the measurement, because how the coach talks is
`led_like_a_coach`'s question now — a criterion a model answers, which a harness cannot ratchet.

The one that earned its deletion by failing quietly: `changed_value_acknowledged` read v1's
`rent: 11,000 -> 12,000`, v2 writes `rent 11,000 before, now 12,000`, and the rule went on
reporting 100% on runs it was no longer looking at.
