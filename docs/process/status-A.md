# Status A · domain

`uv run pytest tests/domain` → **342 passed in 1.24s**. `uv run ruff check ledgerline tests` clean.
`uv run lint-imports` → 3 contracts kept, 0 broken (`domain` imports nothing but pydantic and the
standard library). Nothing committed; the working tree is dirty for the owner to review.

| Module | Lines | Tests |
|---|---|---|
| `domain/models.py` | 251 | — (contract) |
| `domain/policy.py` | 160 | `tests/domain/test_policy.py` 10 |
| `domain/cards.py` | 403 | `tests/domain/test_cards.py` 43 |
| `domain/state/` | 65 + 98 + 64 + 201 + 379 + 148 + 77 = 1032 | `tests/domain/state/` 123 |
| `domain/engine/` | 15 + 267 + 70 + 239 + 274 + 187 = 1052 | `tests/domain/test_engine.py` 141 + 11 YAML fixtures |


Fixture 11 is not from research 09; it is Session B's harness case, kept as a fixture so the
spread-optional regression cannot come back.

## What is implemented

**`policy.py`** — all eight tiers carry a speakable consequence and an ask. Ranks are a
contiguous 0..7; the tier list is data, and `tier_for(policy, key)` is how the engine reads it, so
a swapped policy changes behaviour without touching the engine (proved by
`test_a_swapped_policy_changes_which_debt_goes_unpaid`). No tier text contains `loan`, `BNPL`,
`approved`, `settlement`, `guarantee`, `overdraft` or `balance transfer`.

**`state.py`** — `normalise_name`, `resolve_day`, `upsert` (create / unchanged / merge / conflict
/ correction / stale-overwrite / balance / outlier), `remove`, `resolve_conflict`
(previous / new / both), `mark_unknown`, `confirm_untouched`, `missing`, `readiness`, `snapshot`.
Also `group_inr`, `field_of`, `outlier_question` and `question_for`, which `cards.py` and the
engine reuse.

**`engine.py`** — gate, day-by-day simulation with within-day ordering, spread proration with the
remainder on the last day so the slices add back up exactly, classification, the five actions in
order, re-simulation after each, unpaid rows carrying the tier consequence and ask, and a
hypothesis property test over random small states.

**`cards.py`** — `fmt_inr`, `build_cards`, the 4 KB guard. All ten engine fixtures plus the cards
sample round-trip through `CardsMessage.model_validate_json`.

## Decisions I had to make

1. **The tier-0 reservation tension the context7 appendix flagged as unresolved.** The base
   simulation books every event, so the dip is visible and the TIMING/STRUCTURAL classification is
   honest; what is actually unpayable is decided in the `PAY_ON_DATE` pass, where the reserve is
   the survival money falling *after* that day through the end of the window. This reproduces
   scenario 2 as `TIMING` with a pre-action minimum of -5,800 on 09-29 **and** scenario 4's
   "available 8,500 after reserving 1,000 groceries" exactly. Confirmed by the orchestrator.
2. **Cut order is largest first** (research 09 §2), not the brief's "cheapest first" — changed on
   the orchestrator's instruction: fewest changes a person has to live with. Optionals the user
   marked `flexible=False` are cut last. Same three cuts in scenario 3 either way.
3. **`Summary.lowest_balance` is the final plan's lowest**, not the pre-action one. Research
   quotes the pre-action figure for scenarios 2, 5 and 10 and the post-action one for scenario 3;
   there is only one field, so it has to be the plan the user actually gets.
   `shortfall_before_actions` carries the "before" figure. Each affected fixture has a `note:`
   saying what research quoted and why the number differs. Confirmed by the orchestrator.
4. **`provisional` is true when `excluded_items` is non-empty (per the brief) or a `latest_date`
   was assumed**, which is what makes scenario 10 provisional as research 09 §5 requires.
5. **`total_out_planned` counts unpaid obligations** (they are still owed), so
   `shortfall_after_actions` is -500 in scenario 4 while `closing_balance` is 8,500. That is the
   only reading consistent with both scenario 3 and scenario 4.
6. **`ASK_LENDER` is emitted for anything moved by `PAY_ON_DATE` as well as anything left
   unpaid.** The brief says "anything still unpaid"; research §4 says "any obligation that cannot
   be paid on its due date", and scenarios 5 and 10 expect it for a debt that is paid, just late.
7. **`PAY_MIN_DUE` only fires when `net < 0`** (a structural money problem). A timing problem is
   fixed by moving dates, not by carrying interest.
8. **`group_inr` lives in `state.py` and `cards.fmt_inr` delegates to it.** The outlier and
   conflict questions have to speak the same grouping as the cards, and `cards` already imports
   `state`, so putting it the other way round would be a cycle. `cards.py` therefore imports
   `state` as well as `models`, which the HLD module table did not anticipate; it is still a
   one-directional domain-internal import and import-linter is green.
9. **`resolve_day` returns the first matching date on or after today, not strictly inside the
   window.** With a 30-day horizon every day-of-month lands inside the window anyway, and the
   engine drops out-of-window events itself, so returning `None` would only lose a real date.
10. **Card `rows` capitalise known acronyms** (`emi`, `hdfc`, `ott`, `upi`, `nach`, …) because
    `normalise_name` lowercases the stored name and "Hdfc card" reads badly on screen.
11. **The forbidden-word test covers engine-authored text only** (warnings, questions, action
    rationales and warnings, unpaid consequences and asks). Item names come out of the user's own
    mouth — someone with a car loan will say "loan" — so asserting over the whole serialised
    `PlanResult`, as research §7 scenario 12 words it, would be asserting about the user.
12. **Unpaid rows on the `plan` card carry their marker in the third column**,
    `[label, amount, "unpaid, due 5 Oct"]`, per `requests.md` D-1, so Session D's predicate
    ("third column contains `unpaid`") holds and the amount stays alone in the second column.
    Action rows are unchanged. The consequences are joined into the plan card's note, one
    sentence each.
13. **A spread item is deferred or cut whole, as one action and one timeline row.** A
    subscription prorated across the window is one thing the user stops paying; emitting one
    `DEFER_OPTIONAL` per prorated day meant twenty actions of 23.33 for a single 700 rupee item.
    Deferring collapses the slices into one event on the new date.
14. **Needless optional actions are pruned.** After the actions are chosen, each
    `DEFER_OPTIONAL` and `CUT_OPTIONAL` is tried cheapest first with the item put back where the
    user had it; if the plan is still sound without the action, the action goes. An action that
    changes nothing is noise the bot speaks aloud and the user remembers. Debt-side actions
    (`PAY_MIN_DUE`, `PAY_ON_DATE`, `ASK_LENDER`) are never pruned — they carry a consequence —
    and nothing at all is pruned while an obligation goes unpaid, because then every rupee a cut
    saves is a rupee that could have paid it. "Still sound" means lowest balance at or above zero
    with no negative days; once the plan is already in trouble the old numbers have to be matched
    exactly instead.
15. **`_first_unpayable` judges debts only.** It used to judge optionals too, which made a
    subscription slice look like an obligation that could not be met — it blocked the prune, and
    a non-flexible optional could have collected a "pay it later" action that belongs to money
    that is owed. Essentials were already always booked.
16. **`readiness().blockers` drops an essential whose amount the user declined or does not
    know — a deliberate deviation from the brief.** The brief specifies the blocker list as
    "opening balance None, open conflicts, no income, essential without amount". The last clause
    cannot survive F5: once a field leaves the question queue, a blocker on it never clears,
    `missing()` offers no question for it, the phase sticks on `gathering` with nothing left to
    ask, and `finalize_plan` refuses for the rest of the call. I reproduced that strand before
    changing anything. An amount nobody knows is recorded, excluded from the maths and shown as
    provisional, which is the honest outcome and lets the call finish. **The opening balance and
    having at least one income remain the only hard blockers** — the engine genuinely cannot
    compute without them — along with any open conflict. Approved by the orchestrator.
17. **A timeline point is a day with a non-spread event.** A prorated daily slice of groceries is
    proration, not an event; `cards.py` recognises it by the label turning up on more than two
    days. Marked with a `ponytail:` note in the code.

## Assumptions

- A credit card with no `min_due` is booked as one event at the `card_min` tier. It cannot be
  split, and the missing minimum is already surfaced as a structural gap.
- An essential with neither `spread` nor a `due_date` is spread across the window.
- `missing()` drops fields the user declined or called not applicable, and keeps the ones they
  said they do not know (still missing, just known to be).

## Not done

- `frontend/src/protocol/sample.json` is **unchanged**. `build_cards` produces the same seven card
  ids in the same order with the same statuses and the same field shape, so the structure does not
  differ and the brief says to leave it. The value differences and four things Session D needs that
  `types.ts` does not say are written up as **A-1 in `docs/process/requests.md`**.
- Scenario 12 (forbidden words) and scenario 11 (policy swap) are tests in `test_engine.py` rather
  than YAML fixtures; neither is a scenario with expected arithmetic.

## Known limitations

**Opening balance has no conflict tracking.** `FinancialState.opening_balance` is a bare
`Money | None`, so it carries no `confirmed` or `source_turn` for the six-turn conflict window to
run against; `upsert(BALANCE, ...)` overwrites silently and a user who corrects their balance
mid-call never gets asked which figure is right. Every other item kind does. Deferred by the
orchestrator, not a contract change now.

*The fix, when someone wants it:* give `opening_balance` the same two fields the items have —
a small `OpeningBalance(_Item)` model in `models.py` with an `amount: Money | None`, swapped in
for the bare `Money | None` field. `_upsert_balance` in `state.py` then reuses the same
confirmed / recent-window branch the item path already uses, and `readiness`, `missing` and
`build_plan`'s gate read `state.opening_balance.amount` instead of `state.opening_balance`.

## Review findings fixed (review `kiro-20260911T180651Z-62b9df29`)

**F1, high — completing a partial item crashed.** Verified before fixing: recording an amountless
essential and later supplying the amount raised a bare `AssertionError` out of `group_inr(None)`,
which the tool handler does not catch. A field going from unknown to known is now treated as
completion, not a contradiction: the value is set, `confirmed` goes to False, the status is
`updated` and no `Conflict` is written. Covered for income, debt, essential and optional, for
dates as well as amounts, and for an item that had already been confirmed while still partial.

**F5, medium — a field the user did not know was asked again every turn.** `missing()` now
returns only the gaps still worth asking about; `user_does_not_know` joins `user_declined` and
`not_applicable` in leaving the queue. The new `noted_unknowns()` keeps them for the `missing`
card, which renders them with `"not known"` in the third column and a note. The plan stays
provisional either way, because the amount is still `None` and therefore still in
`excluded_items`.

**F6, medium — only money could conflict.** The recent-or-confirmed rule now covers `amount`,
`date` / `due_date`, `min_due`, debt `kind` and the opening balance. `spread`, `survival`,
`flexible`, `certainty` and `latest_date` still overwrite: they describe an item rather than
commit money to a day. A conflict reports the first offending field and applies nothing, so the
state stays internally consistent. `Conflict.values` holds the machine form (ISO dates, enum
values, grouped rupees) so `resolve_conflict` can read it back, and `Conflict.question` is the
speakable form.

**F2, high (the part in my files) — no way to record uncertain or ranged income.** `upsert` gained
`certainty: Certainty | None = None` and `latest_day_of_month: int | None = None`, income only,
ignored elsewhere. The engine already excluded `UNCERTAIN` income and assumed `latest_date`; there
is now a path to populate both.

### One thing F5 broke that the finding did not mention (deviation 16, approved)

Taking a field out of the question queue without releasing its blocker **stranded the call**:
`readiness().blockers` still held `essential:electricity.amount has no amount`, `missing()` no
longer offered a question for it, the phase stayed `gathering` with nothing to ask, and
`finalize_plan` refused forever. An essential amount the user has declined or does not know no
longer blocks — it is recorded, excluded from the maths and shown as provisional, which is the
honest outcome. The opening balance and having at least one income still block, because the engine
genuinely cannot compute without them. This is a change to the blocker list the brief specified,
so it is recorded as deliberate deviation 16 above, and in `requests.md` A-2. The orchestrator
reviewed and approved it, confirming the opening balance and at least one income as the only hard
blockers.

## Second review fixed (review `kiro-20260911T183052Z-ec6c133c`)

**F2, high — a questioned amount could be confirmed by silence.** Reproduced first: salary 45
stored, `confirm_untouched` flipped it to confirmed and `readiness().blockers` was empty, exactly
the live recording in the finding. An outlier is now persistent unresolved state in
`state.outliers`, a `Conflict`-shaped record in its own additive list. It blocks readiness, it
stops `confirm_untouched` touching that item, and it clears only through `resolve_conflict` or a
correcting `upsert`. `resolve_conflict(field, "new")` keeps the value as heard;
`"previous"` reverts to the value before it, and when there was none the amount goes back to
`None` so the field re-enters the question queue. A correction whose new value is itself an
outlier raises a fresh one. The cards' confirm badge and note are now read straight off
`state.conflicts` and `state.outliers` rather than recomputed, so the badge cannot drift from what
the bot actually asked.

It is a separate list from `state.conflicts` on purpose: a conflict makes the engine return
`BLOCKED`, and a questioned amount should not stop the plan computing — it should compute, show
the confirm badge and refuse to finalise.

**F3, high — the plan told people to pay debts late.** The engine no longer moves a lender's due
date. Only the lender can agree to that, so "pay it eleven days late" was never a plan the user
could carry out. A debt the money does not cover on its due date is now left unpaid on its own
date and produces exactly one action, `ASK_LENDER`, whose rationale names the shortfall on that
day and the first day the money exists, and whose warning is the tier consequence from policy.
Actions are ordered so a lender request is spoken before any optional change — the explanation
only covers the top two.

**F4, medium — removing an item orphaned its unresolved state.** Reproduced first. `remove()` now
drops every unknown, conflict and outlier under that normalised kind and name, and removing the
opening balance clears its conflict too.

### What F3 changed in the fixtures

Status now describes the **shape of the money**; the `unpaid` rows describe **what still needs a
lender's agreement**. They are different questions and the orchestrator settled them apart:

| Status | When |
|---|---|
| `OK` | nothing dips and nothing is unpaid |
| `TIMING` | the month balances, but a payment lands before the money does — even though it sits in `unpaid` with an `ASK_LENDER` |
| `STRUCTURAL` | more goes out than comes in, after every allowed cut |
| `UNSOLVABLE` | structural **and** something is still unpaid |

Classification reads the net of the month **as the user described it**, before any cut. An
earlier attempt read the running net inside the cut loop, which turned scenario 3 into `TIMING`
the moment the cuts closed the gap — the cut loop's variable is now separate from the one the
status reads.

So scenarios 2, 5, 10 and 11 keep `TIMING` and gain an unpaid row with an `ASK_LENDER` dated to
when the money exists; scenario 4 stays `UNSOLVABLE`. The summary card says "the money arrives
after the due date; ask the lender to move it" for `TIMING` and "even after every change, X stays
unpaid" for `UNSOLVABLE`, naming the item.

Scenario 5 also loses its 500 late fee: nothing is paid late any more, so the fee never accrues.
`total_out_planned` drops from 25,500 to 25,000 and closing rises from 20,500 to 28,000, because
the 7,000 has not left the account.

### `PAY_ON_DATE` is retired

Gone from `Policy.allowed_actions` and from every code path — the ranking table and the cards'
verb map. The `Literal` member stays in `models.py` so no other layer's typing breaks, and
`test_pay_on_date_is_retired` plus a per-scenario check keep it from coming back.

Rescheduling a non-survival essential such as rent inside the window **was considered and
rejected**: it would have kept the action type alive, but research 09 section 2 books essentials
unconditionally on purpose — the engine makes a shortfall visible rather than solving it by
moving the household's own bills around, and a landlord's date is no more the engine's to move
than a lender's.

## Third review fixed (review `kiro-20260911T205445Z-3070f642`)

All three reproduced before being touched.

**F1, high — unaffordable essentials were paid from money that did not exist.** Two bugs in one.
The reserve only protected survival money, so an early unsecured EMI could be paid with the rent;
and essentials were never judged at all, so an unaffordable rent stayed in the timeline, drove the
balance to -20,000 and produced no `Unpaid` row, no consequence and nothing to ask the landlord.

Now: the reserve is ranked. A debt gives way to **every** essential still to come, a non-survival
essential gives way to survival money, and survival gives way to nothing. And the settlement pass
runs in three rounds — debts, then the essentials the household could live without, then survival
last, so rent is given up before food. Anything the money does not reach is reported uncovered on
its own date with the consequence and the ask from policy, which for rent is the landlord and for
utilities the provider. The base simulation still books every essential, so the dip stays visible
exactly as research 09 section 2 intends; the judgement happens only in the final pass.

Uncovered rows are aggregated per item, not per event: a grocery budget prorated across thirty
days is one thing the household is short of, not thirty.

**F2, medium — a filled field kept its "not known" label.** Supplying an amount, date, card
minimum or opening balance now clears the matching `unknown`, so the chip goes and the plan stops
being provisional. Unrelated unknowns are untouched.

The survival tier's ask now reads for a food shortfall as well as a utility bill — "You could ask
family or a local shop for a few days' credit, or ask the provider to split a bill" — since
groceries became a place it can surface.

**F3, medium — a person with no income could never finish.** `mark_unknown(state, NO_INCOME,
"not_applicable")` records a confirmed absence of income and satisfies the blocker; income simply
not discussed yet still blocks. Covered both ways: a zero-income month the balance covers comes
back `OK`, and one it cannot comes back `UNSOLVABLE` naming the rent.

### What F1 changed in the fixtures

Only scenario 10. Its last five days of grocery money before the salary, 1,000 of it, are now
named as uncovered instead of shown as a -1,000 balance: lowest goes from -1,000 on 09-30 to 0 on
09-25, the five negative days become none, and closing rises from 32,000 to 33,000 because that
1,000 was never spent. The status stays `TIMING` — the month balances at +28,000, and nothing is
missing except the money arriving sooner. Scenarios 1 to 9 and 11 are untouched.

### Contract changes (authorised) and the mock snapshots

`Phase` gains `"done"` and `FinancialState` gains `call_ended: bool = False`; `readiness()`
returns `done` once `understanding.confirmed` or `call_ended`. Note this **changes an existing
value**: a confirmed understanding used to report `plan`. `scripts/dump_mock_snapshots.py` builds
four real `CardsMessage` snapshots from domain fixtures into
`frontend/src/mock/snapshots.json`, run once, with three tests keeping it honest. Both written up
in `requests.md` A-3. That JSON file is the only thing outside my ownership row I have touched,
and only because the orchestrator asked.

## D-6 · the timeline labels its lowest day

The timeline carries event days only, so a month whose low falls on a quiet day gave the chart no
point to label. `build_cards` now always emits a point for `summary.lowest_balance_date` with
`e="lowest"`, merged into that day's label when something else happens there ("rent, lowest"), and
the size guard keeps first, last and the lowest rather than guessing the low from the points it
happens to have. Regenerated `frontend/src/mock/snapshots.json`.

## Fourth review fixed (review `kiro-20260911T212350Z-164006d4`)

All four reproduced first.

**F1, high — priority only worked within a day.** A payment reserved future essentials but no
future *debts*, so with 5,000 available an informal debt due on the 15th was paid and a secured
EMI due on the 25th went unpaid. The reserve is now uniform: a payment gives way to every future
obligation that outranks it, essentials and debts alike, ranked by policy so a swapped policy
still changes the answer. Due-date feasibility is unchanged — two debts the money covers are both
paid.

**F2, high — the summary spoke from two cashflows.** `total_out_planned` added unpaid obligations
back while the timeline, lowest and closing were simulated without them; the mock implied 47,800
and closed at 52,300. Now `total_out_planned` is only what leaves the account, so
`opening + in - out_planned == closing` and `shortfall_after_actions == closing` on every fixture,
pinned by a test. What the plan cannot fund is `Summary.unpaid_total`, an additive field, shown on
the summary card as its own `unpaid` line.

**F3, medium — a corrected income kept its old range.** A correction carrying `day_of_month` and
no `latest_day_of_month` now clears `latest_date`, so the engine stops assuming the later date and
the plan stops being provisional.

**F4, medium — "I do not know" was read as "there is none".** Only `not_applicable` confirms an
absence of income now. `user_does_not_know` and `user_declined` still clear the blocker, because a
hard blocker with no question left to ask strands the call, but the plan is provisional with
`"income"` in `excluded_items` and a warning.

### What changed in the fixtures

Scenario 4 is the one worth reading. The 500 card minimum is now what goes unpaid and the 9,000
unsecured EMI is kept current — the reverse of research 09 section 7, and deliberate. A card
minimum ranks below an unsecured instalment, so paying the 500 on 25 September to leave the EMI
500 short on 5 October trades penal charges, a thirty day bureau mark and eventually the asset for
one late fee. Its note says so. Scenarios 2, 5, 10 and 11 change only in `total_out_planned`,
`shortfall_after_actions` and the new `unpaid_total`; every closing balance and lowest balance is
untouched, which is the point of the fix.

Scenario 4 also now shows `PAY_MIN_DUE` on the same card whose minimum is uncovered. That reads
oddly but both halves are true: pay only the minimum and carry the rest, and even that 500 is not
there on the day. Left as is rather than suppressed, since hiding either one hides something the
user needs.

## Fifth review fixed (review `kiro-20260911T213837Z-9c6a049f`)

All four reproduced first.

**F2, high — "around 45,000" was spoken as exact.** `Certainty.ESTIMATED` fell straight through
into a full-amount event with no marker anywhere. It is still counted in full, because it is the
user's own figure and `provisional` keeps its narrower meaning of "something left out of the
maths", but the plan now warns "salary is an estimate, around 45,000; the plan moves with it", the
card shows `~45,000`, and the card carries "~ marks an amount you said is approximate." A conflict
or outlier question still wins the note slot when there is one.

**F3, high — a goodbye was rendered as agreement.** `phase == "done"` was set by `call_ended` as
well as by a confirmed understanding, so someone who said goodbye without agreeing got a screen
saying the plan was confirmed. `done` now comes only from `Understanding(confirmed=True)`, and the
new additive `CardsMessage.ended` carries the separate fact that the call is over.

**F4, medium — finalising ignored most of what was missing.** `finalize_plan` reads
`readiness().blockers`, which covered only the opening balance, conflicts, outliers, absence of
income and essentials without amounts. A debt with no due date, a card with no minimum, an income
with no date or an optional with no amount was dropped from the maths and the plan went final
anyway. Every `missing()` entry is now a blocker, phrased "<field> is not known yet". Nothing
strands, because `missing()` already drops what the user has answered; the opening balance keeps
its own blocker, since `missing()` drops it once declined and the engine cannot compute without it.

**F6, medium — an adverse month was badged "ok".** The summary card is now `blocked` when the plan
is blocked, `warn` whenever `plan.status != "OK"`, else `provisional` or `ok`. An adverse status
outranks provisionality; the `?` markers and the note keep that visible separately.

### One contract file I did not touch

`frontend/src/protocol/sample.json` says the summary card is `"provisional"`; on an equivalent
state the engine now emits `"warn"`. That file is Session D's, so the divergence is written up in
`requests.md` A-5 and the test documents it rather than asserting the stale value. Card ids, order
and phase still match.

## Prior-art residual bugs (`docs/research/prior-art/04-slot-filling-state-conflicts.md`)

Both reproduced first.

**A confirmed understanding never reset.** Nothing cleared `state.understanding`, so after the
person agreed, any later correction recomputed the plan while the phase stayed `done` and the
screen kept saying "Plan confirmed." about a plan they had never heard. A single `_unsettle`
helper now clears it from every mutation that actually changes something — `upsert` created,
updated and newly-conflicted, `remove`, `resolve_conflict`, and the first `mark_unknown` of a
field. A `noop` or `unchanged` outcome leaves it alone. A newly raised conflict clears it too: the
plan is in doubt from that moment. `plan_final` stays `True` on purpose, so the card keeps showing
while they correct and the engine recomputes it live.

**A date range could run backwards.** `upsert(..., day_of_month=5, latest_day_of_month=1)` stored
`date = 5 Oct` and `latest_date = 1 Oct`. Worse than it reads: the engine's pessimistic
`latest_date or date` then picked the **earlier** day while still warning that it had assumed the
latest, so it was optimistic exactly where it promised not to be. A range is now stored earliest
first however it arrives, and a one-day range becomes a plain date with `latest_date = None`.

One thing that fell out of it: widening a date the user had already given into a range looked like
a date contradiction and raised a conflict, because the earlier bound becoming the stored date is
a material field change. That normalisation is ours, not theirs, so it no longer raises one.

## Sixth review fixed (review `kiro-20260912T061037Z-e848fe14`)

All three reproduced first.

**F1, medium — a correction left its conflict standing.** With `is_correction` the conflict branch
is skipped and the new value written, but the reconciliation after it only cleared unknowns and
outliers. "Eleven thousand", "twelve thousand", "actually thirteen" left the item at 13,000 with
readiness still blocked by a question about two numbers that were both wrong. A new value for a
disputed field now clears that field's conflict, on items and on the opening balance, whether the
correction matches one of the two old figures or neither. Another field's conflict is untouched.

**F2, medium — changing what an unknown means was treated as no change.** `mark_unknown` on an
existing record overwrote the reason and returned `"unchanged"` without unsettling. For the
`income` field that flips the plan from a confirmed zero income to provisional-with-income-excluded
while a confirmed `Understanding` survived and the phase stayed `done`. An identical reason is
still a no-op; a different one returns `"updated"` and clears the agreement.

**F4, medium — a hopeless obligation held cash hostage.** The reserve was computed once from every
original obligation and reused through all three settle passes, so an obligation that was itself
dropped as unaffordable went on reserving money away from one that was affordable. With 5,000 on
hand, an informal debt of 5,000 due on the 15th and a secured EMI of 10,000 due on the 25th, both
came back unpaid and the 5,000 sat idle.

The reserve is now recomputed after every drop, and the whole settlement iterates to a fixed
point: settle, take the result as the set of obligations nobody can pay, settle again with those
excluded from the reserve, stop when the answer repeats. The circularity is real — what is
hopeless depends on the reserve and the reserve depends on what is hopeless — so it is solved by
iteration rather than by ordering. The informal debt is now paid, the EMI is uncovered with its
`ASK_LENDER`, and the closing balance is 0 rather than 5,000.

Two things that bit while building it, both now pinned by tests. A first attempt iterated on the
*dropped set* instead of the reserve and oscillated: round one dropped both, round two dropped
neither, round three dropped both again. And excluding an obligation from the reserve initially
removed its tier from the lookup table as well, so it reserved nothing at all and the priority
order inverted — `ignore` now drops an obligation from what gets reserved, never from the set of
tiers that need a table.

**No fixture moved.** Every closing balance, status and unpaid list is unchanged across all
eleven, scenario 4 included; the snapshots regenerate byte-identical.

## Seventh review fixed (review `kiro-20260912T070010Z-7bc8fe3c`)

All three reproduced first.

**F1, high — a partial income stranded the call.** `missing()` derived an income *date* gap but
never an income *amount* gap, while `readiness()` blocked on "no income recorded" until some
income had an amount. Since the per-turn block shows `missing()` questions and not blocker text,
"salary comes on the first" left the phase at `gathering` with nothing for the model to ask.
`missing()` now carries the amount gap, and `income_answer()` treats `mark_unknown` on a specific
income's amount exactly as it treats the blanket `NO_INCOME` field: "I do not know what I earn"
answers the question as fully as "there is no income". `user_does_not_know` and `user_declined`
clear the blocker and leave the plan provisional with that income excluded and a warning naming
it; `not_applicable` is a confirmed absence and is not provisional.

**F2, high — an unknown left the old fact in the maths.** `mark_unknown` only appended an
`Unknown`. Two live consequences: retracting a known 1,200 electricity bill left the engine
spending 1,200 while the card said it was not known, and answering an open 11,000-versus-12,000
conflict with "I do not know" recorded the unknown while the conflict went on blocking readiness
and re-asking the same question, breaking the never-ask-again promise twice over. A `_retract`
helper now blanks the value and drops the conflict and outlier on that field. The opening balance
is blanked the same way and keeps its hard blocker, since the engine cannot simulate a month
without it; a debt's `kind` is not blankable and is left alone.

**F4, medium — a card minimum could exceed its total.** Total 5,000 with a minimum of 10,000
booked 10,000, twice the debt. `upsert` now raises `ValueError` with a speakable corrective
whichever of the two arrives second, storing nothing, so the tool layer returns a refusal and
pushes no cards. A minimum equal to the total is allowed. As a belt, the engine books no more than
the card is owed if such a pair ever reaches it and warns that it did.

**No fixture moved.** Every status and closing balance is unchanged across all eleven; snapshots
regenerate byte-identical.

## Eighth review fixed (review `kiro-20260912T074342Z-a7068109`)

**F2, medium — a spread shortfall was described two incompatible ways.** When a later slice of an
already-uncovered item was dropped, `_settle` added to the running amount but left `short` at the
first slice's figure. Groceries of 6,000 with 1,000 on hand aggregated to 5,000 uncovered while the
spoken line said "you are 200 short for groceries" — one day's slice, against a row reporting
5,000.

An obligation now knows how many events it spans and what the whole item came to, and the two
cases are phrased differently. A single-day obligation is unchanged: "On 14 September you are
24,000 short for auto emi." A multi-day one names when it starts running short and how much of the
whole is uncovered: "From 16 September there is not enough for groceries; 5,000 of 6,000 is not
covered this month." `short` still accumulates across slices, capped at what is actually
uncovered, so nothing reading it can claim more is short than is owed.

The phrasing deliberately does not agree with the item's name — "there is not enough for
groceries" rather than "groceries runs short" — because names come from the user and half of them
are plural.

**No fixture moved**, and the snapshots regenerate byte-identical: the only uncovered item in them
is a single-day EMI.

## Ninth review fixed (review `kiro-20260912T082624Z-1869b2b9`)

Both reproduced first.

**F1, high — the plan recommended new borrowing.** My fault, and it had been there since the
fifth review: the survival tier's ask read "You could ask family or a local shop for a few days'
credit". A shopkeeper's tab and a few days from family are new borrowing as surely as a loan is,
and the engine puts `tier.ask` verbatim into every uncovered item's rationale, so an uncovered
grocery budget had the bot recommending it. It now reads "You could ask the provider for a few
more days or to split the bill, and buy only what you need until the money lands." Every other
tier was checked and is clean.

The regression test is semantic, because a word list cannot express this rule: "ask the lender" is
talking to a creditor the person already has, and "reported to the credit bureaus" is a
consequence rather than an offer. `tests/domain/conftest.py` bans phrases that *propose getting
money* and allows `credit` only as `credit bureau`, `credit report`, `credit card` or
`credit score`. It runs over the whole engine-authored recommendation for an uncovered item in
each of the six reachable tiers, and over every scenario's complete spoken output.

**F2, high — the spoken shortfall included money reserved for other things.** `short` was
`amount - (balance - reserve)`, so a 4,000 EMI was described as "20,000 short" where the 20,000
was future rent and groceries. Two different questions are now answered separately: how far the
balance itself falls short on the day, and what paying the item would leave the obligations it is
being held for. A payment the balance cannot cover says "On 14 September you are 6,800 short for
auto emi"; one the balance covers but the reserve protects says "On 25 September paying the 3,000
personal emi would leave you 18,000 short for groceries and rent later in the month". The
multi-slice wording from the eighth review is untouched.

One correction along the way: the reserve figure has to be measured against what is left *after*
paying, not against the payment. Measured the wrong way, scenario 4's 500 card minimum claimed
26,500 rather than 500.

**No fixture moved**; snapshots regenerate byte-identical, since the cards carry amounts and
consequences rather than rationales.

## Maintainability refactor (behaviour-preserving)

**Phase 1 — string unions became `StrEnum`s.** `PlanStatus`, `ActionType`, `RowKind`, `Phase`,
`UnknownReason`, `OutcomeStatus` in `models.py`; `CardId`, `CardStatus` in `cards.py`; `TierKey` in
`policy.py`. `StrEnum` members *are* `str`, so JSON, equality, dict keys and the TypeScript
contract are unchanged; raw string comparisons across the domain now use the members. Written up
for the other sessions as `requests.md` A-9, with two deviations: `OutcomeStatus` needs a seventh
member, `RESOLVED`, which the brief omitted and `resolve_conflict` returns, and `mark_unknown`'s
`reason` is annotated with the enum rather than its narrower `Literal`.

**Phase 2 — `state.py` (857 lines) and `engine.py` (879) became packages**, each re-exporting the
same public API. `state/`: `names` the vocabulary, `core` what every part needs, `conflicts`
contradictions and doubts, `items` recording what the person says, `unknowns` what is not known,
`readiness` how far the call has got. `engine/`: `events`, `simulate`, `settle`, `actions`, `plan`.
`upsert` (181 lines) is now six named steps — proposal, create, material changes, conflict, apply,
reconcile; `_build_events` (145) is one builder per kind over a small collector; `build_plan` is a
short orchestration over `_blocked`, `_shape_of_the_month`, `_propose_changes`, `_final_status`
and `_summarise`. Tests moved to mirror `state/`, unchanged in content.

### Verifying it really was behaviour-preserving

Tests alone were not enough to trust, so each split was checked by walking the old file against the
new package with an AST diff: every top-level unit compared by normalised dump, and for the three
decomposed functions every statement compared by multiset, so a dropped side effect could not hide
behind a green suite. Both package splits came out exactly equal — 45 units for state, 35 for
engine, nothing missing, added or changed. For the decomposed functions every difference was
enumerated and accounted for.

That was worth doing. The walk-equivalent check on `upsert` caught a defect I had just introduced:
a helper I added passed `state.turn` where the original passed `existing.source_turn`, which differ
whenever nothing actually changed, and the whole suite stayed green. Reading `plan.py` and
`items.py` closely also turned up three raw strings that phase 1's sweep had missed, including a
bare `"STRUCTURAL"` sitting beside four enum members.

`tests/domain` is 342 passed throughout, and `frontend/src/mock/snapshots.json` regenerates
byte-identical against a copy taken before the refactor started.

## Resolved since the first pass

- **Needless optional actions** (the open question from the previous round): the prune pass is
  built on the orchestrator's instruction. Session B's scenario now returns the EMI move alone
  with the subscription left exactly where the user put it — 22 actions at the first report, 3
  after the spread-item aggregation, 2 now. Fixtures 1 to 10 are untouched by it; fixture 11 is
  Session B's own case and changed on purpose, and its note says why.

## Cut: tests and snapshots

**342 before, 303 after.** `uv run pytest tests/domain` green; `uv run ruff check ledgerline tests
scripts` clean; `uv run lint-imports` 4 contracts kept, 0 broken.

| file | tests |
|---|---|
| `tests/domain/test_engine.py` | 141 |
| `tests/domain/test_cards.py` | 39 |
| `tests/domain/state/test_items.py` | 42 |
| `tests/domain/state/test_unknowns.py` | 33 |
| `tests/domain/state/test_names.py` | 25 |
| `tests/domain/state/test_readiness.py` | 13 |
| `tests/domain/test_policy.py` | 10 |

`ledgerline/domain/state/` is **560 lines** across five files (`items` 255, `names` 103, `unknowns`
99, `readiness` 54, `__init__` 49). Nothing was shrunk for the number's sake.

### Pruned by hand, not by regex

The first attempt deleted by pattern and took working tests with it, so `test_engine.py` and
`test_cards.py` came back intact from the pre-cut tarball and `tests/domain/state/` was restored
from it as well. Every test function was then read and decided on its own: delete if the cut
deleted its subject, adapt if the subject survived in a new shape.

**Deleted: 59 test functions.** `state/test_conflicts.py` went whole (49) -- conflict detection,
outlier detection, `resolve_conflict`, the confirm-on-resolve rules. Four more went with
`confirm_untouched` and `Readiness.score`, four with the "confirm" card badge
(`test_an_outlier_makes_its_card_need_confirming`, `test_a_conflict_makes_its_card_need_confirming`,
`test_the_confirm_badge_comes_from_recorded_state_not_a_recomputation`,
`test_doubt_outranks_the_estimate_note_on_the_same_card`), and two were duplicates once the
"declined" reason folded into `NOT_APPLICABLE`. One test was *rescued* out of `test_conflicts.py`:
the card minimum larger than the total bill is still refused, so it now lives in `test_items.py`.

**Adapted: about 69.** Mechanically: `plan.questions` -> `plan.blockers` (field ids),
`readiness().missing` -> `missing_fields` (field ids, not `Unknown` objects),
`noted_unknowns(state)` -> the `UNKNOWN`-reason entries of `state.unknowns`, `"user_does_not_know"`
-> `UnknownReason.UNKNOWN`, `"user_declined"` -> `UnknownReason.NOT_APPLICABLE`,
`Understanding(confirmed=True)` -> `understood = True`, blocker prose (`"opening_balance is not
set"`) -> the bare field id. Substantively: every test that used a conflict fixture to reach a card
or a phase now uses a plain overwrite, and the `agreed` fixture is a plan the person understood
rather than an `Understanding` object.

**Kept as they were: every arithmetic test.** All 141 in `test_engine.py`, including `test_scenario`
over the 11 fixtures, the hypothesis invariants, the priority and reserve tests, the borrowing-
language ban and the shortfall wording. Five needed one line each (`plan.questions` out of the
spoken-text helpers, `is_correction=True` off one upsert, the two income-reason tests).

**New: 16.** `label_for` (7 cases: it is a label, carries no "?" and no full stop) and `spoken`
(5 cases) in `test_names.py`; `Outcome.changes` in `test_items.py` -- an overwrite reports
`("11,000", "12,000")`, a first value reports `("", "12,000")`, only fields that actually moved are
reported, an opening balance reports its own move, a second value simply overwrites with no
blocking state; `mark_unknown` in `test_unknowns.py` -- `UNKNOWN` is the default reason, blanks the
value, excludes it from the maths and marks the plan provisional, `NOT_APPLICABLE` on the blanket
`income` field satisfies the income blocker with `total_in == 0` and no provisionality. "Any change
after `understood` resets it" is a five-case parametrisation over create, overwrite, balance
overwrite, remove and `mark_unknown`, with its mirror image: a change that changes nothing leaves
the agreement standing.

### Fixtures

Ten of the eleven were already plain facts and are untouched. `07-conflicting-salary.yaml` existed
only to prove a conflict blocks the plan, and there is no conflict gate any more; rather than lose
the only BLOCKED scenario it became `07-blocked-no-opening-balance.yaml` -- the same shape of
assertion against the gate that survived, with `blockers: ["opening_balance"]` where `questions`
used to be. `test_cards.py`'s summary-badge table points at the new name.

### Snapshots

`scripts/dump_mock_snapshots.py`: `gathering()` relied on a conflicting salary plus an outlier rent
of 12 rupees. It is now a plain state -- rent 12,000, a salary restated from 42,000 to 45,000 (which
simply overwrites), and an electricity bill not yet given, so the "Still need" card is still on
screen, which was the point of that frame. `done()` sets `understood = True` instead of building an
`Understanding`. Regenerated: four snapshots, 863 / 860 / 1571 / 1570 bytes, all well under the
4 KB app-message limit, no `confirm` status anywhere. The stale file was the reason
`test_the_mock_snapshots_are_real_cards_messages` could not even parse.

### Three places the code looked wrong from inside the tests

Reported, not fixed -- the shapes are frozen and other sessions are building on them.

1. **A flag-only edit is applied but never reported** (`state/items.py`). `Outcome.changes` is built
   from `_FIELD_ATTRIBUTE`, which covers amount, date, due date, minimum due and debt kind.
   `spread`, `survival`, `flexible` and `certainty` are written to the item and then fall out of the
   report, so the status comes back `UNCHANGED` and `_unsettle` never runs. Two consequences: the
   model is not told, and a plan the person agreed to keeps saying "agreed" after the maths behind
   it moved. `certainty=UNCERTAIN` is the sharp case -- it takes an income out of the base plan
   entirely and reports nothing. Pinned by
   `test_a_flag_only_edit_is_written_but_not_reported`, which asserts today's behaviour and says in
   its docstring that it should fail the day this is fixed.
2. **`NOT_APPLICABLE` only means "there is none" for income** (`engine/events.py`). The income path
   reads the reason and treats it as a confirmed zero; the essential, debt and optional paths only
   look at `amount is None`, so "there is no electricity bill" plans exactly like "I do not know the
   electricity bill" -- excluded from the maths and the whole plan marked provisional. Same
   arithmetic either way, different thing for the person to hear. Pinned by
   `test_an_essential_that_does_not_apply_is_still_excluded_and_provisional`.
3. **"blockers" means two different things in two models.** `PlanResult.blockers` is only ever
   `["opening_balance"]`; `Readiness.blockers` is the balance, the income question and then every
   structural gap, so it is `missing_fields` plus at most two entries and the two lists are empty
   together. Harmless while both are field ids, but a reader of `models.py` would expect
   `Readiness.blockers` to be the short list and `missing_fields` the long one.

   Smaller: `mark_unknown("opening_balance", NOT_APPLICABLE)` blanks the balance and keeps the
   blocker, so there is no way to say "there is no account" -- correct for the engine, but it means
   `NOT_APPLICABLE` is silently not an answer for that one field. And `cards._item_card` still has
   `note: str | None = None` followed by `if note is None and estimated_any`, a conditional left
   over from the conflict note that can now never be false.

## The three reported defects, fixed (plus two the orchestrator added)

**303 -> 315 tests**, `uv run pytest tests/domain` green; `uv run ruff check ledgerline tests
scripts` clean; `uv run lint-imports` 4 kept, 0 broken; `snapshots.json` regenerates
**byte-identical** (863 / 860 / 1571 / 1570), so nothing the reviewer sees moved.

| file | before | after |
|---|---|---|
| `tests/domain/test_engine.py` | 141 | 141 |
| `tests/domain/test_cards.py` | 39 | 40 |
| `tests/domain/state/test_items.py` | 42 | 46 |
| `tests/domain/state/test_unknowns.py` | 33 | 36 |
| `tests/domain/state/test_names.py` | 25 | 26 |
| `tests/domain/state/test_readiness.py` | 13 | 16 |
| `tests/domain/test_policy.py` | 10 | 10 |

### 1. A flag-only edit is now reported (`state/items.py`)

`_FIELD_ATTRIBUTE` gained the five attributes `upsert` wrote and then forgot: `spread`,
`survival`, `flexible`, `certainty`, `latest_date`. Every attribute `upsert` can write is now in
it, so "every written field that differs is in `Outcome.changes`" is true by construction rather
than by a list somebody has to remember to extend.

A boolean says nothing out loud, so each flag has the two words it is spoken as -- `_FLAG_WORDS`:
spread `dated -> spread`, survival `ordinary -> survival`, flexible `flexible -> fixed`. Certainty
speaks itself (`confirmed -> uncertain`), dates through the existing `spoken`.

Consequences: the status is `UPDATED`, `_unsettle` runs, and a plan the person agreed to stops
saying "agreed" the moment the maths behind it moves. The sharp case from the report --
`certainty=UNCERTAIN` taking an income out of the base plan in silence -- is
`test_an_income_turning_uncertain_is_reported`. Both pinned tests were flipped
(`test_a_flag_only_edit_is_reported_and_unsettles_the_plan`,
`test_upsert_merges_a_non_monetary_field`), and four more added, including the mirror image: a
flag restated the same way still reports `UNCHANGED` and leaves the agreement standing.

### 2. NOT_APPLICABLE means "there is none" for every kind (`engine/events.py`, `cards.py`)

**Excluded, not removed.** `mark_unknown` marks a *field*, not an item: `debt:hdfc card.due_date`
NOT_APPLICABLE says the card has no due date, and deleting the debt over it would throw away money
the person owes. So the item stays in the state and the engine reads the reason on its **amount**
field: NOT_APPLICABLE means skip it silently -- no `excluded_items` entry, no warning, no
provisionality -- exactly as the income path already did. UNKNOWN keeps the old behaviour.

One helper, `_amount_answer(state, kind, name)`, now serves all four builders; it replaced the
`recorded` dict the income path had built for itself.

The card followed: `?` on a card means "left out of the maths, so this plan is incomplete", which
is the one thing a confirmed absence does not mean. An item whose amount is NOT_APPLICABLE now
reads `none` instead of `amount?`, so nobody is asked again on every screen.

### 3. "blockers" means one thing now (`state/readiness.py`, `engine/plan.py`, `models.py`)

`state.blockers(state)` is the single predicate: the opening balance, and the income question while
it has no answer at all. `readiness()` calls it and appends the structural gaps; `_blocked()` calls
it and returns exactly it. The two models cannot drift because there is one function.

Documented in `models.py` (comments only, no shape change -- it is the orchestrator's file, and he
approved this):

    Readiness.blockers == PlanResult.blockers + [f for f in missing_fields if f not in PlanResult.blockers]

The dedup is real: `opening_balance` is both a blocker and a gap worth listing on the "Still need"
card, and it is named once.

**This changes engine behaviour**: `build_plan` used to compute a plan for a household with no
income at all, which states something the person never said. It is now `BLOCKED` on `income` until
they give a figure, say there is none, or say they do not know (UNKNOWN still plans, provisionally
-- the orchestrator confirmed that reading). Seventeen engine tests built states with no income to
isolate the priority arithmetic; rather than edit seventeen dicts, `state_from` says it for them
("no income" was always what they meant), and the hypothesis strategy does the same when its draw
produces no income amount.

Smaller, same round: `mark_unknown("opening_balance", NOT_APPLICABLE)` now raises
`ValueError("a balance cannot be not applicable; if there is nothing in the account, record it as
zero")` -- Session B's handler already has a branch for exactly this refusal. And `cards._item_card`
lost the `if note is None and estimated_any` conditional that could never be false.

### 4 and 5, from the orchestrator

**Possessives are meaning, not noise** (`state/names.py`). `normalise_name` stripped `my`, `our`,
`his`, `her`, `their` along with the articles, so "my loan" and "his loan" were one key and
recording the second overwrote the first -- two people's debts merged into one. Articles stay
stripped (transcription noise); possessives stay in the name. `normalise_name("my rent!")` is now
`"my rent"`.

Policy and engine sentences (consequences, rationales, warnings) stay where they are: that is
domain knowledge the model must not invent, on the correct side of the line.

### 6. A possessive only tells two items apart when both names have one (`state/names.py`, `items.py`)

The round's last item, after B filed `B-cut-2` against 5 above: keeping possessives in the name
fixed one money error and opened another. "Rent is eleven thousand", then "my rent is twelve
thousand", is how people restate an item on a call, and two rows named `rent` and `my rent` count
the rent twice in the outflow.

`_find` now tries the exact normalised name first, and only on a miss applies `_same_item`: the
same bare name, and not two *different* owners. "rent" and "my rent" are one item either way
round; "my loan" and "his loan" stay two people's debts. A name that could be either of two stored
items matches neither -- which one they meant is a question about language, and the model gets a
`CREATED` it can ask about rather than a silent merge.

Field ids follow the stored name, so an upsert that reaches `rent` through "my rent" still reports
`essential:rent.amount` and the unknowns, the cards and the model go on naming one field. `remove`
inherits it through the same `_find`. Five tests, including the two that must never merge:
`test_two_peoples_loans_stay_two_debts` and `test_a_bare_name_that_could_be_either_loan_merges_with_neither`.

`possessive_of` is exported from `state.__all__` so `evals/provenance.py` can key item identity
by the same rule (`possessive_of(normalise_name(name))[1]`) rather than by `normalise_name` alone,
which would see "rent" and "my rent" as two subjects where the state sees one.

**325 tests green**, ruff clean, 4 contracts kept, snapshots byte-identical.

### 7. A field id has to name a real field (`state/unknowns.py`)

From B-cut-1 and B's F8: after the cut `_retract` returned quietly when a field id had no `kind:`
prefix, so `mark_unknown(state, "optional_expenses")` succeeded and the state grew an `Unknown`
that named nothing. The maths ignored it, the card showed a row the person could not place, the
model learned that inventing a field id works -- and it then asked about optional expenses a turn
after parking them. `essential:rent.day_of_month`, the tool's argument name rather than the
field's, parked nothing the same way.

`mark_unknown` now validates before it writes. A field id is either one of the two bare ids
(`opening_balance`, `income`) or `kind:name.attribute` with a real kind and an attribute that kind
actually has. The attribute set is read off the pydantic model (`_SPEC`), with the money field
spelled as field ids spell it (`amount`, not `amount_due`), so a field added to an item is askable
the same day. `balance:` is refused: the balance is the bare id. An unknown item **name** stays
legal -- the person may say they do not know a bill nobody has recorded yet.

Three corrective messages, each self-sufficient so the agent layer can pass them through as
written:

    optional_expenses is not a field id; name it as kind:name.attribute, like
    essential:rent.amount, or as the bare field opening_balance or income
    expenses is not a kind of item; use income, debt, essential or optional, or the bare field
    opening_balance for the money in the account
    day_of_month is not a field on essential items; use one of: amount, due_date, spread, survival

B's handler-side validation stays exactly where it is, per the orchestrator: belt and braces. One
consequence for it, worth knowing: its `"ItemKind" in str(refusal)` branch (which swaps in
`phrases.REFUSAL_FIELD`) will now rarely fire, because the domain no longer lets a bad kind reach
the raw enum error -- and the message it replaced that one with is already in mine.

23 tests: 9 well-formed ids accepted, 12 refused, 2 on the wording.

**348 tests green**, ruff clean, 4 contracts kept, snapshots byte-identical.

## Frozen for the commit phase — held findings against domain files

Tree frozen by the owner at **348 tests green** (`tests/domain`), ruff clean, lint-imports 4 kept
0 broken, `frontend/src/mock/snapshots.json` byte-identical. Nothing below is fixed; it is written
down so the next session does not have to rediscover it. Kiro review 13
(`kiro-20260912T171543Z-30afe763`) is held, not dispatched; three of its four findings are in my
files and I checked them by hand rather than take them on trust.

**F4 is real, and it is mine.** Confirmed by running it, not by reading:

    upsert(essential "rent"); mark_unknown("essential:rent.amount")
    remove(essential, "my rent")
    -> item gone, unknowns still ['essential:rent.amount'], Outcome.field "essential:my rent.amount"

`remove` resolves the item through the possessive-aware `_find` (A-10b) but then builds its
cleanup prefix and its returned field id from the name it was *asked* with. So removing `rent` as
"my rent" drops the item and leaves its unknown behind, and the "Still need" card goes on showing
a field of an item that no longer exists. `upsert` already has the fix — it rewrites `key` to
`normalise_name(existing.name)` after `_find` — and `remove` needs the same two lines, plus a test
each way round ("rent" removed as "my rent", "my rent" removed as "rent"). It is a defect I
introduced with A-10b and did not carry through to the second caller of `_find`.

**F3 is real in its sharper half.** `_essential_events` prorates when `spread or due_date is
None`, and `missing_fields` never asks for an essential's due date, so an undated rent is spread
across thirty days with no provisional mark. For an essential the person simply has not dated yet,
that is the old and deliberate fallback. What is not defensible is the other path the finding
names: `mark_unknown("essential:rent.due_date", UNKNOWN)` blanks the date and the plan then treats
the rent as evenly spread — an explicit "I do not know" turning into a concrete daily schedule,
where every other UNKNOWN excludes the item and marks the plan provisional. That inconsistency is
worth fixing; whether an undated-and-never-asked rent should block is a design call for the owner.

**F2 is a judgement call, not a defect.** `blockers()` cannot know a person has debts until
somebody asks; the cut put "what to ask next" with the model on purpose. If the owner wants code
to hold the gate, the domain-side lever is a category answer — `mark_unknown("debt",
NOT_APPLICABLE)` alongside the existing blanket `income` — so "are there any loans?" has to be
answered before `finalize_plan`, exactly as the income question is. That is a contract change
(`models.py`, the tools, the prompt), not a domain patch.

**F1 is `ledgerline/agent/tools/context.py`, not mine.**

## Review 13

Unfrozen for two items after the commit at `a4b4d15`. **348 -> 358 tests**, `uv run pytest
tests/domain` green, `ruff check` clean, `ruff format --check` 89 files already formatted,
`lint-imports` 4 kept 0 broken, `frontend/src/mock/snapshots.json` **byte-identical** (863 / 860 /
1571 / 1570), so the frontend session has nothing to pick up.

### F4 - `remove` keyed its cleanup on the name it was asked with

Mine, introduced with A-10b: `_find` became possessive-aware, so removing `rent` as "my rent"
found and deleted the item while the unknowns cleanup looked for `essential:my rent.*` and the
returned field id said the same. The unknown survived its item, and the "Still need" card went on
showing a field of an essential that no longer existed.

`remove` now takes `stored = normalise_name(existing.name)` after `_find` and uses it for both the
prefix and `field_of`, which is exactly what `upsert` has done since A-10b; the fix is carrying it
through to the second caller of `_find`. Three tests: both directions ("rent" removed as
"my rent", "my rent" removed as "rent"), and a miss still reports the name as asked, since there
is no stored name to report.

### F3 - an undated essential stays counted, and the assumption is said out loud

Kiro asked for the opposite: exclude an undated essential and mark the plan provisional. The
orchestrator ruled against it and the ruling is right -- excluding rent from the maths because
nobody has dated it takes real money out of a survival plan and shows a surplus that is not there.
A mis-timed 12,000 is a worse plan; a missing 12,000 is a wrong one. So the money stays counted and
prorated, and the guess stops being silent:

- **`missing_fields` gained `essential:<name>.due_date`** for an essential that has an amount, is
  not `spread`, and has no date -- after the amount gap (a date for a bill nobody has priced is the
  wrong question) and before the income date gaps. A spread essential has no date by nature and is
  never listed. `answered()` already drops it once the person says they do not know, so it is asked
  exactly once.
- **The engine names it**: prorating an essential because its date is None, rather than because
  `spread` is True, appends "<name> has no date; spread across the month." The plan states its own
  assumption and the model can say it. Both routes are covered -- never asked, and
  `mark_unknown("essential:rent.due_date")`, which blanks a date the person no longer stands
  behind.

Seven tests. No fixture moved: all eleven date every non-spread essential, which is why this went
unnoticed. One existing test changed on purpose --
`test_readiness_and_the_plan_reconcile_once_a_field_is_filled` filled electricity's amount and
expected no blockers; the date is now the one question left, so it fills that too and then expects
none.

F1 is `agent/tools/context.py` and F2 is a contract question (a category answer such as
`mark_unknown("debt", NOT_APPLICABLE)`), neither dispatched to me.

### B's cell - what is left after the minimum

**358 -> 361 tests.** Snapshots byte-identical again: the mock plan state has no credit card, so
no PAY_MIN_DUE row exists in any of the four frames.

**The item's premise was off, and the record should say so.** The engine already carried the
remainder: `_pay_min_due` builds its action from the card's "rest" event, which *is*
`amount_due - min_due`, and the rationale read "Pay only the minimum due on hdfc card this month
and carry 1,800." for a 3,000 card with a 1,200 minimum. The model did not derive 1,800; it
reworded a figure the result had given it, which is why provenance passed. Confirmed by running a
plan, not by reading the code.

The orchestrator checked B's failing run after I said so: that run had **no actions at all**, and
the model invented both the pay-minimum action and its arithmetic from card figures it had read
back earlier. So the fix for the named run is B's (a result that says "no actions needed" in words
the model can use), not mine.

What my change does close is a real and separate gap: the remainder was spoken but **nowhere on
screen**. The card row read `Pay min | HDFC card 1,200 | ""`, so the screen and the voice
disagreed about what paying the minimum leaves behind.

- `Action.remainder: Money | None = None` in `models.py` -- additive, default None, orchestrator
  authorised. The engine computes it; `types.ts` does not move, since cards render it in the third
  cell of the row they already have.
- `_pay_min_due` sets it and words it: "Pay only the minimum due on hdfc card this month; 1,800 is
  still due after the minimum." The model now has the sentence rather than the subtraction.
- `cards._action_rows` puts `1,800 still due` in the third cell -- the same cell that carries
  "to 25 Sep" on a deferral, which a minimum payment never has.

Three tests: the 3,000 / 1,200 action text, the card row, and the guard that a minimum equal to
the whole balance leaves no remainder to state (with the state-layer refusal of a minimum larger
than the bill still holding). `tests/agent` run read-only afterwards: 405 passed, 1 deselected --
only saved eval transcripts carry the old "and carry 1,800" wording, and those are artifacts.

## Observability phase: store (phase 2) and carried facts (phase 3)

**361 -> 416 tests.** `tests/domain` 390, `tests/store` 26 (23 of them `db`, against the compose
container; they skip with a message naming the compose command when `DATABASE_URL` is unset, so a
fresh clone is green either way). Whole suite `uv run pytest`: 991 passed, 23 skipped. ruff check
and format clean on my files, `lint-imports` green. **Snapshots byte-identical** (863 / 860 /
1571 / 1570): no mock state holds a carried item, so nothing the frontend renders moved.

### `ledgerline/store/` — what it is and what it refuses to be

`schema.sql` is the only schema source, applied at boot every boot, every statement
`IF NOT EXISTS`. Four tables as the HLD lists them. Money is `text` holding the Decimal's own
string: `numeric` would be correct too, but every driver between here and it is one float
coercion away from losing a paisa.

Two shapes I decided and the orchestrator accepted. `sessions.phone` is **nullable**, so `forget`
detaches the row rather than deleting it and the call stays countable while nothing about it
points at the person. `forget` deletes **notes as well as facts**: the notes are the softer half
of the same personal data, and a forget button that leaves them is a lie.

`load_active` returns `None` on timeout or error and `[]` when nothing is remembered. Different
answers, and every caller has to keep them apart -- which is also why `record_call` takes
`loaded:`. If the memory was not read this call (`None`), an item's absence from the final state
says nothing about whether the person still has it, so **nothing is tombstoned**. Without that
distinction one slow database would quietly delete every fact the person did not happen to repeat.

`record_call` is the diff: unchanged is no row and only `last_confirmed_at` moves; changed or new
inserts and stamps the old row's `superseded_by`; an ended item or a `NOT_APPLICABLE` field gets a
tombstone row with no value, and `load_active` skips tombstones because a tombstone exists so that
nothing carries. A flag sitting at its model default is not written at all -- "the rent is not
spread" is not something anybody said.

`hydrate(today, facts)` rebuilds a `FinancialState` with every item `carried`. The parsing is
pydantic's: the values come back as text and the models already know which field is a Decimal, a
date, a flag or an enum, so there is no parser table to keep in step.

### Domain: a fact from last month is provisional until the person says otherwise

`_Item.carried` is set only by the loader and cleared by any `upsert` of that item -- restating a
figure is confirming it, even when the figure has not moved, because what made it provisional was
that nobody had mentioned it this call. `confirm_carried(names | all)` is the other way through,
and it refuses a name nobody carried: the blocker exists so a plan is never built on unconfirmed
figures, and a mistyped name must not be able to clear it. Confirming an income resets its
certainty to CONFIRMED -- "may or may not come" was about last month.

The blocker goes in `Readiness.blockers`, **not** `PlanResult.blockers`: the engine keeps counting
carried money, because a survival plan with the rent missing is a wrong plan, and reports
`provisional` instead. `finalize_plan` refuses meanwhile. The documented identity now reads
`Readiness.blockers == PlanResult.blockers + ["carried"] + missing_fields`.

The carry policy is a table beside the tiers, because it is the same kind of thing. Everything
recurring carries. Two do not: the opening balance changes daily, and a credit card's statement
balance changed the day it was printed -- but an EMI is the same figure every month, so
`carries(DEBT, "amount", debt_kind=...)` is True for an EMI and False for a card.

### Ponytail review of my own diff

Three cuts, all applied, `ledgerline/store` 747 -> 736 lines:

- **Two copies of the bounded read.** `profile.load_active` and `notes.load_active` each had the
  same timeout wrapper around the same shape of query. One `read_within(pool, sql, args, timeout,
  what)` now serves both, and each loader is two lines.
- **`except (TimeoutError, Exception)`** with a `noqa` explaining itself. `TimeoutError` is an
  `Exception`; the tuple said nothing the first entry did not, and a dead database, a timeout and
  an unreadable row are all the same answer to the caller.
- **Two lookup tables for one mapping.** A dict and its inverse for the single field whose name
  differs between the field ids and the models. Two one-line functions replace both.

One cut I tried and reverted: collapsing the field-name mapping to a single kind-free pair. Only
a debt spells its money field `amount_due`, so the inverse direction has to know the kind, and the
tests said so immediately -- an income came back from the database with no amount at all.

Not cut, deliberately: the `Store` protocol and the `PostgresStore` delegation to `sessions.py`,
`profile.py` and `notes.py`. The protocol has two real implementations, and the alternative to the
delegation is one 500-line `db.py`.

### The fifth snapshot frame

`returning`, first in the file, agreed with ledgerline-D by name and composition before
regenerating. **618 / 863 / 860 / 1571 / 1570** — the four existing frames are unchanged in
content; only their `v` shifts by one, because the version is the frame's position in the journey
and a returning caller's first screen comes before gathering.

It is the state the profile loader hands over before the greeting: salary 45,000 on the 1st and
rent 12,000 on the 5th, both carried, so both cards read `carried` with the note; no opening
balance, because it never carries; `missing` naming the balance; `summary` blocked on it. D uses
it as the fixture for the carried rendering and for a screenshot, and deliberately does not replay
it in `MOCK_SCRIPT` -- the scripted demo stays a first-time caller from gathering to done, since a
returning caller's opening is a different call rather than a step in this one.

`test_the_mock_snapshots_are_real_cards_messages` now asserts the five-name list, that a frame's
phase may differ from its name where the name says more (`returning` is still `gathering`), and
that this frame keeps showing two carried cards with the note and a blocked summary -- so the
fixture cannot quietly lose the thing it exists to show.

**No card names the `carried` blocker in words, and that is settled.** `Readiness.blockers`
carries it, but the cards render `missing_fields`, which is structural gaps only, so on screen
"carried" is said by the status word and the note alone. Taken to the orchestrator rather than
decided quietly, because a row on the "Still need" card would mix a readiness blocker into a list
of missing fields: ruled against, no contract change. The card lists gaps; the two cards it
applies to already say it.

### Ponytail review of the domain half

Run at the owner's instruction, over the other half of this phase's diff: the `carried` flag,
`confirm_carried`, the carry policy, the cards status word, the fifth frame and its test. Three
cuts, all applied, suite green at 390 domain and 26 store, snapshot bytes unchanged
(618 / 863 / 860 / 1571 / 1570).

- **The snapshot script kept two dicts keyed by the same five names** -- `SNAPSHOTS` of builders
  and `FOCUS` of card ids. One table of `(builder, focus)` replaces both: **26 added lines -> 20**.
  Not only shorter, but the shape that cannot go wrong the way I nearly did -- adding `returning`
  to one dict and not the other is a `KeyError` at the end of a run, and I wrote exactly that bug
  for a minute before the script told me.
- **`getattr(item, "carried", False)` in `cards._item_card`.** A defensive read of a field that
  lives on `_Item`, so every item model has it. `item.carried`. The default was hiding the
  contract rather than guarding anything.
- **`CARRIED_FIELDS.get(kind, frozenset())` in `policy.carries`.** The dict holds every member of
  `ItemKind`, so the default could never fire; it only meant that a kind added later would
  silently stop carrying instead of raising. `CARRIED_FIELDS[kind]` -- a new kind is now a loud
  failure, which is what a money policy should be.

**Nothing else came out, and that is the honest reading rather than a clean bill.** The domain half
was written after the store pass, so the habits the first review taught were already in it: no
second copy of the carry rule, no wrapper layer, no defensive branch for a case the models make
impossible.

Two candidates I looked at and left. `CARRIED_FIELDS` could collapse to "everything carries except
the opening balance and a card's amount", two lines instead of a seven-line table -- but the table
is not that rule: a debt's `late_fee`, `autodebit` and `lender` are deliberately absent, and a
whitelist that must be extended to carry something new fails the safe way, while a blacklist that
must be extended to stop something carrying fails towards a stale figure in a plan. And
`test_confirming_the_carried_items_takes_the_word_off_the_card` is close to a mirror of the test
above it -- but deleting a passing regression test to make a diff look leaner is the wrong trade
in a product about money, and the ponytail rule is to cut code, not coverage.

**`Unpaid.ask` removed** (owner's trim, approved contract change): written by `_ask_actions` and
read by no production code -- the ask text reaches the model through the ASK_LENDER rationale,
which uses `tier.ask` directly. It was read by four of my own tests, so those moved to where the
guarantee belongs: `test_policy.py` already sweeps every tier's `ask` for borrowing language at its
source, and the one test that checked a landlord was named now asserts it on the action's
rationale, which is where the person actually hears it. 416 green, snapshots byte-identical,
whole suite 1044 passed. `tests/agent/test_describe.py` still constructs `Unpaid(ask=...)` and is
unaffected -- pydantic ignores the extra -- so nothing of B's needed touching.

**Two reads for the review endpoint** (C-obs-3): `calls_for(phone)` returns the person's calls
newest first -- the order the page reads them in, and empty for a forgotten person, since forget
nulls the phone rather than deleting the row. `history_all(phone)` returns every row ever recorded
for the phone, oldest first, superseded rows and tombstones included: `history()` can only be
reached from a fact that is still active, so an item the person has since ended is invisible to
it, which is exactly the history someone opens the page to read. Both on the protocol, both `[]`
on `NullStore`, four `db` tests. `tests/store` 26 -> 30, 420 with domain; whole suite 1073 passed.

## Redesign: the model gets the conversation back, code keeps the money

Four additions after the live call. **420 -> 431 tests** (domain 401, store 30); whole suite 1145
passed, 27 skipped; ruff and format clean; 7 contracts kept. **No fixture moved** by the whole-rupee change -- every spread amount in the eleven fixtures divides by thirty, which
is why the paise never showed up there and did show up on a real call.

### `PlanResult.low_point`: the arithmetic behind the lowest balance

The live caller asked why the low point was 57,166 when thirty thousand minus eighteen was twelve,
and the answer was nowhere in the result, so the model could only invent a step or change the
subject. `LowPoint` carries the opening balance, everything that lands on or before the low day,
what arrives after it and when, and the closing balance. A spread item is one running total to
that day rather than thirty lines, because thirty lines is not an explanation.

Worked example, the same shape as the call that prompted it:

    low 30 Sep 8,000 | opening 30,000 | closing 51,000
      before  20 Sep  rent       -18,000
      before  30 Sep  groceries   -4,000  (spread, so far)
      after    1 Oct  salary     +45,000
      after   10 Oct  groceries   -2,000  (spread, the rest)

Two identities hold by construction, since the rows are the events the simulation booked rather
than a second calculation agreeing with the first: `opening + sum(before) == balance` and
`balance + sum(after) == closing`. Both are asserted.

### Whole rupees

`_spread` allocates whole rupees a day and puts the remainder -- including any paise the person's
own figure carried -- on the last day. 6,500 over thirty days is 216 a day and 84 on the last. The
total is still exactly what they said; no daily balance, low point or total carries paise any
more. One consequence worth knowing: an amount smaller than the window lands entirely on the last
day rather than as a third of a rupee a day, which is the same remainder rule and reads better.

### Coverage, and `none_of(kind)`

Kiro's F2, which I argued was a judgement call rather than a defect, is now a defect with
evidence: two `mark_unknown` rounds on the live call failed to record "no loans", so nothing in
the state could tell "they have no debts" from "nobody has asked". `none_of(state, kind)` records
it -- through the same blanket mechanism the income answer has always used, an `Unknown` on the
bare kind name with reason NOT_APPLICABLE, so there is one way to say "there are none of these"
rather than two. `coverage(state)` answers STATED / NONE / UNASKED for the four kinds and the
balance.

What exists outranks what was said: a person who said "no subscriptions" and then remembered the
gym has optional spending. And "I do not know" leaves a category UNASKED, because coverage answers
what there is to plan with; that they were asked and could not say is in `state.unknowns`, which
is where a question is decided. Cards gained a `None` row for a kind settled that way -- an empty
screen cannot distinguish a fact from an unasked question.

### Readiness is money-only again

The `carried` blocker is gone. The model is told what was carried and decides whether to ask; code
keeps the flag, so the cards still say `carried` and `record_call` still knows what nobody
refreshed, and the plan is still provisional while any remain. `missing_fields` stays a list of
facts and its docstring no longer claims an order -- what to ask next is the model's judgement
about the conversation it is having.

### Snapshots: both shapes folded into the frames that already existed

D asked for the new shapes inside the existing five frames rather than a sixth, so the frame list
is unchanged and only bytes moved. **Every frame moved**, because `low_point` rides on the message
rather than on a card:

| frame | before | after | why |
|---|---|---|---|
| returning | 618 | 635 | `low_point: null` -- blocked, nothing to explain yet |
| gathering | 863 | 1307 | a `debts` card reading `None`, plus the derivation |
| ready | 860 | 1272 | the derivation |
| plan | 1571 | 1983 | the derivation |
| done | 1570 | 1982 | the derivation |

`CardsMessage.low_point` is a `LowPointView`: the low day, its balance, the opening and closing
balances, and `before` / `after` lines of `{d, label, amt, spread}` in whole rupees, like the
timeline. The same two identities hold on the wire as in the domain, and the snapshot test asserts
them on the plan and done frames.

**The 4 KB limit bites here, and the fix keeps the arithmetic.** Forty items make forty lines, and
`test_forty_items_still_fit_in_one_daily_app_message` went to 4,391 bytes the moment the
derivation shipped. `_fit` now trims the low point first, before the timeline: it keeps the four
largest movements -- the ones that explain the number -- and carries the rest as one line, "29
smaller items", with their exact total, so `opening + before == b` and `b + after == closing`
survive the truncation. A test asserts both identities on the crowded state after fitting.

### The store tests had their own database all along, they just did not use it

A live call lost its `users` row mid-call and `record_call` failed on the foreign key, because
`tests/store/conftest.py` truncated the same database the running container was using. My fixture,
my defect: destructive tests pointed at whatever `DATABASE_URL` happened to say.

They now run against `<name>_test` on the same server -- derived from `DATABASE_URL` by swapping
the database name, or `TEST_DATABASE_URL` if it is set -- created on demand through a maintenance
connection (autocommit, quoted identifier: `CREATE DATABASE` takes neither a transaction nor a
parameter). `guard()` refuses outright to truncate a database whose name does not end in `_test`,
and four tests cover the derivation, the already-a-test-name case, query parameters surviving the
swap, and the refusal itself -- none of them needing a database, so they run on a fresh clone too.

`tests/store` 30 -> 34, 438 with domain; whole suite 1175 passed. Verified by hand afterwards:
`ledgerline` still holds the live call's rows and `ledgerline_test` is the one the suite empties.

### `sample.json` has a generator now, and it had drifted further than anyone thought

`frontend/src/protocol/sample.json` is the one message the frontend parses against, and nothing
wrote it -- tests only read it -- so it drifted from `build_cards` for days without a single
failure. `scripts/dump_sample.py` builds it from `sample_state` the way `dump_mock_snapshots.py`
builds the mock journey, and `test_the_sample_message_is_what_the_generator_writes` compares the
committed file byte for byte, so drift now fails the suite instead of waiting for someone to read
the file.

What the drift had accumulated, all of it now corrected: a `note` from **before the cut**
("Rent came through as 12. Did you mean 12,000?" -- the conflict machinery has not existed for
days), a summary note in wording the engine no longer produces, and a timeline whose balances and
event days were simply wrong (3,000 where the engine says 2,800; a low point of -1,800 on 5 Oct
where it is 0 on 25 Sep). 3,572 bytes, one `low_point`, seven cards. Domain 404 -> 405.

### `Summary.net_flow`: the subtraction leaves the agent layer

B's `facts._cashflow_lines` was computing `total_in - total_out_planned` itself, with a `ponytail:`
comment saying it belonged in `Summary`. It does, and it is there now. The figure exists because
two v2 runs did that subtraction **out loud** when challenged, which is the one rule this product
has; a result that does not answer "my salary is thirty, rent and spending are eighteen, so where
is fifty-seven from?" gets the question answered anyway.

It is the month's own flow and says nothing about what was already in the account -- the invariant
that pins it is `closing_balance == opening_balance + net_flow`, asserted, along with
`net_flow == total_in - total_out_planned` over all eleven fixtures and its sign matching which
way the month runs.

**Additive with a default**, and that mattered more than it looks: as a required field it broke
145 tests across three other layers at once, every one of them a fixture that builds a `Summary`
by hand. The engine always computes it. Domain 405 -> 417; whole suite 1309 passed.

Not rounded to whole rupees on purpose, despite the instruction: it is exactly the subtraction of
two figures that are already whole, and forcing a round would make the three stop reconciling the
moment somebody states paise -- a figure the model speaks that does not add up against the two
beside it is worse than a paisa.

**Snapshots and sample unchanged** (635 / 1307 / 1272 / 1983 / 1982 and 3,572 bytes): the cards
carry `in`, `out` and `lowest`, and nothing asked for this on the summary card, so no frame moved.

## Cleanup sweep: the census

Two passes over `domain/**`, `store/**`, `scripts/**` and their tests -- one before B deleted the
v1 agent layer, one after, because v1 was the only caller of some of this. Method: an AST walk
listing every def, class, model field and module constant in those trees, each name grepped across
`ledgerline`, `tests`, `evals` and `scripts` (excluding `evals/runs`, which are artefacts), minus
its own definition line; every survivor of that filter then read by hand, because the narrow grep
lies in both directions -- it missed the four `_is_*` predicates in `settle.py`, which are passed
as callables and never called by name, and it flagged `NullStore`'s no-op parameters, which exist
to satisfy the protocol.

**Gates after both passes:** `tests/domain` 415, `tests/store` 34, 449 mine; ruff and format clean;
7 contracts kept; `db` tests against `ledgerline_test`. **`snapshots.json` and `sample.json`
byte-identical throughout** -- 635 / 1307 / 1272 / 1983 / 1982 and 3,572 -- checked after every
removal, which is the proof that none of this was load-bearing.

### Removed, with the evidence

| symbol | where | evidence it had no caller |
|---|---|---|
| `TIERS_BY_KEY` | `policy.py` | zero references anywhere, tests included; `tier_for()` does that lookup |
| `_Event.late_fee` | `engine/events.py` | assigned at two sites, read at none: a write-only field |
| `Debt.late_fee` | `models.py` | its only consumer was the above; no tool sets it, and the one fixture carrying `late_fee: 500` had it ignored by the engine |
| `Debt.autodebit` | `models.py` | read nowhere (the "autodebit" in `voice/pipeline.py` is an STT vocabulary word) |
| `_Event.within_day` | `engine/events.py` | always 0, so its term in `sort_key` could never order anything; the comment described fee events, which do not exist |
| `RowKind.FEE` | `models.py` | never constructed; existed only as an entry in `_KIND_ORDER` |
| `ActionType.PAY_ON_DATE` | `models.py` | never produced; referenced only by tests asserting it is never produced |
| `store.get_session` + `sessions.get` | `store/db.py`, `store/sessions.py` | no production caller; five test call sites, all observing a row they had just written |
| `StateSnapshot`, `snapshot()` | `state/readiness.py` | dead once v1 went: the last consumers were `tests/agent/conftest.py`'s fake, which B removed; `coverage()` replaced the counts it carried |
| `income_is_answered`, `PROFILE_TIMEOUT_SECS`, `PostgresStore`, `Store` (exports only) | `state/__init__.py`, `store/__init__.py` | the functions stay and are used inside their packages; nothing imported them **through** the front door -- `main.py` takes `open_store` from `store.db` |
| `resolve_day(..., horizon_days)` | `state/names.py` | the parameter the body never read; its own docstring said the horizon is not consulted, and both callers were passing `state.horizon_days` into nothing |
| `_value(..., provisional)` | `cards.py` | the caller computed `provisional = amount is None`, and the function returns `"amount?"` for that case before reaching the `" ?"` suffix, so the suffix was unreachable |
| `_item_card(..., absent=frozenset())` | `cards.py` | a default nobody took |

### Tests that went with the code, and one that got stronger

`test_snapshot_counts` and `test_snapshot_missing_only_lists_what_is_still_worth_asking` tested
deleted code and went. `test_pay_on_date_is_retired` likewise. `test_nothing_is_ever_told_to_pay_late`
became `test_every_action_is_one_the_policy_allows`: it asserts every action is in
`allowed_actions`, which is a stronger claim than naming the one member that no longer exists. The
five `get_session` assertions survive against a `session_row()` helper in `tests/store/conftest.py`
that reads the row through the pool -- the assertion was never about the method.

### Kept, deliberately

- **`simulate`'s `lowest if lowest is not None else opening`.** Unreachable with any real
  `horizon_days`, reachable at zero, and there it is the difference between a `None` low point and
  a crash. A boundary, not dead code.
- **`_summary_card`'s `if plan.blockers else None`.** Unreachable from the engine, which never
  produces a BLOCKED plan with no blockers, but reachable from a hand-built `PlanResult` in another
  layer's fixture, where removing it turns a `None` note into an `IndexError`.
- **`Coverage`'s missing fourth state and `coverage` on the wire** -- the orchestrator's standing
  instruction: a design decision, not dead code.

## Kiro review 14 (`kiro-20260914T050806Z-72a1d136`): seven findings

**449 -> 479 tests** (domain 440, store 39), ruff and format clean, 7 contracts kept, db tests
against `ledgerline_test`. **Snapshots and sample byte-identical** -- 635 / 1307 / 1272 / 1983 /
1982 and 3,572 -- including the two findings that were expected to move them; see 007 and 012.

**KIRO-008 · the age window was documented and never wired.** `open_store(dsn, *,
profile_max_age_days=PROFILE_MAX_AGE_DAYS)` stores it on `PostgresStore` and passes it to both the
facts and the notes reads. Keyword with a default, so C can wire `Settings` whenever. Two db
tests: a fact aged past the window leaves `load_active` and stays in `history_all`, and a store
opened with a narrower window forgets a fact the default still carries.

**KIRO-006 · a correction back to a default was never persisted.** `_stated` dropped every value
equal to its model default, which is right for a flag nobody mentioned and wrong for one the
person just corrected: "do not cut the gym" sets `flexible` back to True, the row stayed
non-default, and the next call hydrated the correction away. `record_call` already had `loaded`,
so the rule is now: a default is a stated fact when the profile remembers a value for that field.
Two db tests, both directions, one of them round-tripped through `hydrate`.

**KIRO-002 · `Summary.to_work_with`** = `opening_balance + total_in`, the second figure the agent
layer was computing for itself. Additive with a default, like `net_flow`. Asserted over all eleven
fixtures alongside it, with the identity that ties them: `closing == to_work_with - out_planned`.

**KIRO-009 · a configured database that is down took the product with it.** `open_store` let a
failed `pool.open` or `apply_schema` raise straight out of the FastAPI lifespan, so a Postgres
outage meant no calls at all rather than calls without memory. It now closes the half-opened pool,
logs the degradation once, and returns `NullStore`. Tested against an unreachable DSN.

**KIRO-012 · the card invented an action the plan did not contain.** Every TIMING plan printed
"ask the lender to move it", including one whose only action is deferring a subscription. The note
is derived from the actions now: the lender is named when there is an `ASK_LENDER` or an unpaid
debt, otherwise "the money arrives after it is needed; moving what can move covers it". The
orchestrator's cited example turned out to produce an `ASK_LENDER` after all, so the test uses a
state I built for the purpose -- a dip closed by deferring one subscription, no debts at all.
**No snapshot moved**: every TIMING frame in the mock and the sample has an unpaid debt, which is
why nobody noticed.

**KIRO-005 · a dated essential went on being prorated.** `spread` stayed True when the person gave
a date, because an unmentioned flag is filtered out, so the engine kept slicing rent across thirty
days after they had put it on the 5th. A date and "spread" contradict each other and whichever was
just said wins: dating a spread item clears the flag, calling an item spread clears the date. Only
on an item that already exists -- there is nothing to contradict on a first mention, and the
create path was reporting a meaningless `spread: ("", "dated")` change until I gated it. Five state
tests, one of them asserting the timeline shows a single dated event rather than thirty slices.

**KIRO-007 · the wire's low point could fail its own arithmetic.** Rounding the balance, the
opening, the closing and every movement independently leaves up to a rupee of residual: 0.40
opening plus 0.40 income rounds to 0 + 0 with a closing of 1, and the page checking
`opening + before == b` tells the person their plan does not add up when it adds up perfectly. It
is rounded as one ledger now -- totals rounded, then the residual placed on the largest movement,
deterministically, because a rupee is least visible against the biggest figure and the alternative
is a visible contradiction. A parametrised case for the exact example plus a hypothesis property
over 150 quantised-paise states.

### Kiro 16 F3 · one rounding rule, and the arithmetic survives it

`facts.rupees()` rounded every `Summary` figure on its own, so "opening 60,000 plus in 30,000 is
90,001" was a thing the coach could say about 60,000.40 and 30,000.40 -- and the person would be
right to distrust everything after it.

`ledgerline/domain/rupees.py` is now the single answer to "what does this look like in rupees":
`whole()` (half a rupee away from zero, as everywhere else), `reconciled(parts, total)` (the
residual on the largest part, deterministically), and `in_rupees(summary) -> Rupees`, a frozen
model. The three figures a month is made of are rounded -- opening, in, out planned -- and every
total is **derived** from them, so `to_work_with == opening + in`, `closing == to_work_with - out`
and `net_flow == in - out` hold exactly on the integers. `shortfall_after_actions` is the closing
balance by another name and is derived too, so the two cannot disagree; `unpaid_total` is rounded
on its own, being outside the cashflow on purpose.

The trade is a derived total sitting up to half a rupee per rounded part from the exact figure --
one rupee on a two-part total, one and a half on three. A rupee nobody can see against a spoken
sum that visibly does not add up is not a close call.

`cards._reconciled` now calls `rupees.reconciled` rather than carrying its own copy of the same
rule from Kiro-14 007, which is what "one rounding rule" has to mean. **Snapshots and sample
byte-identical** (635 / 1307 / 1272 / 1983 / 1982 and 3,572): the cards already reconciled, and
this only moved where the rule lives. Domain 440 -> 449, 488 with the store; 7 contracts kept.

Two test expectations of mine were wrong before the code was: the drift bound (half a rupee per
rounded part, not one overall) and `whole(-0.50)`, which is -1 because ROUND_HALF_UP rounds away
from zero. Both corrected against what the rule actually does.

### Kiro 17 F3 and F2 · spread the residual, and one ledger for the whole month

**F3.** `reconciled` put the entire residual on one part: four movements of 100.49 against a total
of 402 rendered as [102, 100, 100, 100], so a row was spoken two rupees from what it actually was
-- and the docstring claiming "up to a rupee" was simply false. It is the largest-remainder method
now: a rupee at a time to the parts that lost the most to rounding, ties by position, so every part
stays within one rupee of its own value and the sum is still exact. The residual can never exceed
the number of parts (half a rupee each, plus half for the total), so one adjustment each is always
enough. Four parametrised cases including the review's, and a property over 200 lists of up to
twelve paise-valued parts asserting both halves: the sum matches and no part drifts more than a
rupee.

**F2.** The same result could say "closing 0" in the cashflow and "closing 1" in the low point,
because one was derived from the rounded parts and the other was `whole()` of the exact Decimal.
`rupees.in_rupees_low_point(plan) -> LowPointLedger` is the one projection now: `opening` and
`closing` are the summary view's own figures, and the movements are reconciled to those endpoints,
so `opening + before == b` and `b + after == closing` hold exactly against the same numbers the
voice speaks. `cards._low_point` rounds nothing itself any more -- it shapes that ledger for the
wire -- so the screen and the voice cannot disagree.

One case the finding did not mention and the property found: when the low day **is** the end of the
month there are no `after` rows, so a residual between an independently rounded `b` and the
summary's derived closing would have nowhere to go. The balance takes the closing figure directly
in that case, which is the same number by definition; the mirror case, a low point on day one with
no `before` rows, takes the opening.

Domain 449 -> 458, 497 with the store; whole suite green; **snapshots and sample byte-identical**
(635 / 1307 / 1272 / 1983 / 1982 and 3,572); 7 contracts kept.
