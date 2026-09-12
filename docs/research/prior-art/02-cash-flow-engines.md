# Prior art 02 - cash-flow forecasting, budgeting and debt-planning engines

Research for Ledgerline's `domain/engine.py` and `domain/policy.py`. What open-source
forecasting engines actually do day by day, and what published hardship guidance says about
which bill to pay first and how to phrase the consequence of not paying it.

## Summary

Ten most liftable findings, ranked by how much they change the engine.

1. **No published debt-advice source presents "pay it N days late" as a plan step.** CFPB, Citizens
   Advice, MoneyHelper and Australia's NDH all make *the request to the creditor* the action, and the
   late payment only the consequence branch if the request fails. Retiring `PAY_ON_DATE` was right;
   what is missing now is the consequence ladder behind `ASK_LENDER`.
2. **Consequences are graduated by how late, not by whether late.** CFPB, verbatim: "The consequences
   for paying bills late can vary depending on how late you are." Turn `Tier.consequence` from one
   string into buckets - card 0-3 days (RBI: no fee, nothing reported), 4-30, 30+; loans 1-29, 30 DPD,
   90 NPA.
3. **CFPB ranks income-protecting spend *above* housing** - the vehicle, tools and licences that keep
   the job. We have no such tier, so a gig worker's two-wheeler EMI sits below rent and can be
   proposed for deferral. Needs a `protects_income` promotion.
4. **The pro-rata offer is the one real algorithm in the advice sector**:
   `offer_i = surplus * balance_i / total`, with a token payment as the floor when the surplus is
   zero. It turns "you could ask about a part payment" into a number.
5. **Actual Budget's forecast is our exact shape** - expand schedules into dated occurrences, then
   one day loop accumulating a running balance, with `lowestBalance` as a first-class result field.
   It has no within-day ordering, which is precisely the part of our engine that has no prior art.
6. **Lift `getZeroCrossingGradientOffset`** (`max / (max - min) * 100`, null if the line never
   crosses zero) so the balance chart paints the dip without the frontend guessing.
7. **Weekend and month-length handling is a solved, named problem elsewhere.** Firefly III has four
   explicit weekend behaviours on every repetition; hledger's manual warns about day-31 rules. We
   have neither, and NACH presents on working days.
8. **Double-counting an already-posted scheduled transaction is the classic bug** - Actual shipped
   the fix twice, hledger's forecast period starts after the last real transaction to avoid it. Ours
   is the autodebit that already ran this morning against the balance the user just quoted.
9. **The Indian credit-card minimum due is a composite, not 5%** - 100% of on-card EMIs, fees, GST
   and over-limit plus a percentage of the rest, with an absolute floor. Never derive it; never imply
   the whole gap above it is discretionary.
10. **There is no Python library that does this**, so the tests are the specification: golden files
    over serialised `PlanResult` plus property tests on the simulation invariants.

---

## 1. Actual Budget - balance forecast (schedules expanded into a daily running balance)

- Repo: https://github.com/actualbudget/actual (AGPL-3.0, ~21k stars, active - `master` commits daily as of Sep 2026)
- Docs: https://actualbudget.org/docs/experimental/balance-forecast-report/
- Language: TypeScript. Money is **integer minor units** everywhere (`amount: number` in cents), never floats.

**What it is.** A local-first envelope budgeting app. Its *Balance Forecast Report* is the closest
open-source analogue to `build_plan`: it expands scheduled (recurring) transactions into simulated
future occurrences up to a forecast end date, then walks a day range accumulating a running balance
and reports the **lowest balance and the date it happens**.

### Learnings

1. **Two-stage pipeline: expand, then walk.** Recurrence rules are resolved into concrete dated
   occurrences *before* the simulation starts; the day loop knows nothing about recurrence. Ledgerline
   already does this in `_build_events` -> `_simulate`; the split is worth keeping explicit.
2. **Emit a point for every day, not only event days.** `forecastDays` is
   `dayRangeInclusive(start, end)` and the projection `.map`s over all of them, carrying
   `runningBalance` forward. Our `PlanResult.timeline` holds event rows only, which is right for a
   4 KB card, but the *chart* wants a value per day - Actual builds that as a separate derived series
   (`buildBalanceForecastChartData`) rather than fattening the model.
3. **`lowestBalance` is a first-class field of the result**, not something the UI recomputes:
   `ForecastResult = { dataPoints, lowestBalance: {date, balance, accountId, accountName},
   forecastStartDate, forecastEndDate }`. Matches our `Summary.lowest_balance` /
   `lowest_balance_date`. Note the sentinel handling: it seeds `balance: Infinity` and, if no data
   points exist, falls back to the sum of current account balances so the field is never undefined.
4. **Zero-crossing is computed, not eyeballed** -
   `packages/desktop-client/src/components/reports/reports/balanceForecastChartData.ts`:

   ```ts
   export function getZeroCrossingGradientOffset(chartData: ChartDataPoint[]) {
     const balances = chartData.map(p => p.balance);
     const minBalance = Math.min(...balances), maxBalance = Math.max(...balances);
     if (minBalance >= 0 || maxBalance <= 0) return null;   // never crosses
     return (maxBalance / (maxBalance - minBalance)) * 100; // % of the y-range that is above zero
   }
   ```

   A single number that lets the chart paint the below-zero part of the line red. Directly usable for
   the "30-day balance line with the dip day marked" in HLD 6b - the frontend can ask the engine for
   one float instead of inventing its own threshold.
5. **Anti-double-count guard.** Occurrences are filtered to
   `occurrence.transaction.date >= firstForecastDate`, where
   `firstForecastDate = max(forecastStartDate, today)`, while transactions dated before the start roll
   into `startingBalance`. Release notes record two bugs fixed here: "Balance Forecast double-counting
   scheduled transactions that were already posted" and "...posted split transactions"
   (https://actualbudget.org/docs/releases/). The Ledgerline equivalent: an autodebit that *already
   ran today* must not be simulated again on top of the opening balance the user quoted.
6. **Occurrence identity is `${date}:${scheduleId}`** (`countForecastScheduledOccurrences`), so the
   same schedule firing twice in a window is two occurrences but a re-render is not. Our upsert key is
   `(kind, normalised name)` with no date component - two rent payments in one 30-day window (a
   month-boundary case) would collide.

### Code pointers

| File | What to read it for |
|---|---|
| `packages/loot-core/src/server/forecast/forecast-projection.ts` | `buildAccountForecastDataPoints` (the day loop), `calculateLowestBalance`, `indexScheduleOccurrences` |
| `packages/loot-core/src/server/forecast/forecast-schedules.ts` | recurrence rule -> dated occurrences |
| `packages/desktop-client/src/components/reports/reports/balanceForecastChartData.ts` | zero crossing, lowest point, carry-forward when the visible range starts mid-series |
| `packages/desktop-client/src/hooks/usePreviewTransactions.ts` | how "upcoming" rows are merged with real ones in the ledger view |

The day loop itself, condensed:

```ts
let runningBalance = postedTransactions.startingBalance;
return forecastDays.map(day => {
  const txDelta = postedTransactions.txsByDay[day] || 0;
  const scheduleDelta = (scheduleOccurrencesByDay[day] || [])
    .reduce((sum, tx) => sum + tx.amount, 0);
  runningBalance += txDelta + scheduleDelta;
  return { date: day, balance: runningBalance, transactions: scheduleTxns };
});
```

Note what it does **not** do: there is no ordering *within* a day. Actual is a forecast, not a
decision engine, so it never has to say "the salary lands before the EMI is debited". Ledgerline's
`_KIND_ORDER` + tier + `within_day` sort key is the part that has no prior art here, and it is the
part that decides whether a day dips below zero. That is our own risk surface and needs its own tests.

---

## 2. CFPB - "Your Money, Your Goals" bill prioritisation (US federal consumer guidance)

- Toolkit: https://files.consumerfinance.gov/f/documents/cfpb_your-money-your-goals_financial-empowerment_toolkit.pdf
- Tool 5, "When cash is short: Prioritizing bills and planning spending":
  https://files.consumerfinance.gov/f/documents/cfpb_ymyg_budget-worksheet.pdf
- Booklet, "Behind on bills? Start with one step.":
  https://files.consumerfinance.gov/f/documents/bcfp_your-money-goals_behind-on-bills_booklet_print.pdf

**The published order is not the one we have.** Tool 5's focus areas, in the order printed:

| # | CFPB focus area | Examples given | Stated reason |
|---|---|---|---|
| 1 | **Protect your income** | car payment and car insurance if you need the car for work; tools, required licences | losing the means to earn removes every future payment |
| 2 | **Protect your shelter** | rent or mortgage, property taxes, condo fees, mobile home lot payments; "if possible, maintain your utilities" | "the costs of losing your home are big"; utilities "are difficult to live without, and reconnection is expensive" |
| 3 | **Pay your obligations** | child support, income taxes, student loans | legal consequences |
| 4 | **Protect your assets and health** | auto / renter's / homeowner's / health insurance premiums, co-pays, prescriptions | "not having insurance may mean you cannot drive your car, and it puts your assets ... at risk" |

The "Behind on bills?" booklet restates it as four checklist groups - *insurance I need to pay for*,
*things I need to keep or get a job*, *things I need to stay housed and keep utilities connected*,
*obligations I need to pay* - and ends with a two-column sort: **"Highest priority bills (I'll pay
these first)" / "Lowest priority bills"**. That two-bucket output, not a seven-rank list, is what an
end user is actually asked to produce.

### Learnings (all directly relevant to the "late payment as proposal" finding)

1. **Income-protecting spend outranks rent.** Our tier 0 is "survival essentials (food, utilities,
   medicine)" and tier 1 is rent; CFPB puts *the vehicle and the tools that keep the job* above both.
   In the Indian context this is the two-wheeler EMI, the petrol, the phone recharge the gig worker
   needs for the app. Today Ledgerline would classify a bike EMI as `secured_emi` (rank 2) and could
   propose deferring it under rent - the exact inversion CFPB warns against.
2. **Consequence severity is a function of *how late*, not of *whether* late.** Verbatim: "Timing
   matters. The consequences for paying bills late can vary depending on how late you are. For
   example, utility and credit card payments received within 30 days of their due dates typically
   don't affect your credit report. After 60 days, however, your credit card company may choose to
   raise the interest rate on your balances." So a consequence string should be *bucketed by days
   late*, not a single sentence per tier. `Tier.consequence` is currently one flat string.
3. **A missed payment is framed as a conversation to have, before it happens.** Verbatim: "If you
   have to miss a payment, try calling your creditors to tell them why. You may be able to make
   short-term arrangements. For example, if you are in good standing with your creditors, they may be
   willing to forgive the occasional fee." This is precisely `ASK_LENDER`, and CFPB puts it *ahead of*
   the act of paying late - the call is the action, the late payment is the outcome if the call fails.
4. **Permanent fix framed separately from this month's fix**: "If you find you're often late with a
   particular bill, negotiate a new due date to better line it up with the dates you receive income or
   benefits." A distinct, structural `ASK_LENDER` variant (move the due date permanently) versus the
   one-off (give me ten days this month). We collapse both into one action type.
5. **Rotation as an explicit strategy**: "One strategy is to rotate the bills you pay each month.
   While not ideal, this can prevent you from losing your car or house..." Honest about being second
   best. Useful tone model for `UNSOLVABLE` copy.

---

## 3. Citizens Advice (UK) - priority vs non-priority debts

- https://www.citizensadvice.org.uk/debt-and-money/help-with-debt/dealing-with-your-debts/work-out-which-debts-to-deal-with-first/
- https://www.citizensadvice.org.uk/debt-and-money/help-with-debt/dealing-with-your-debts/making-a-plan-to-pay-your-debts/

**Priority debts, in the order published, each with its stated consequence:**

| # | Debt | Consequence as written |
|---|---|---|
| 1 | Rent arrears | "your landlord might evict you from your home if you don't pay" |
| 2 | Mortgage or secured loan arrears | "your bank or building society might evict you and take your home" |
| 3 | Council tax arrears | "you could go to prison" (if you have the money and refuse) |
| 4 | Gas or electricity | supplier "might cut off your gas or electricity" |
| 5 | Phone or internet (only if essential) | supplier "can cut off your phone or internet" |
| 6 | TV licence | "you could be fined by the magistrate's court" |
| 7 | Court fines | "you could be sent to prison if you have the money but choose not to pay" |
| 8 | Overpaid tax credits | HMRC "can take the money from your wages" or "use bailiffs to take your property" |
| 9 | Hire purchase / conditional sale (essential goods only) | creditor "could take back the goods you bought" |
| 10 | Income tax, National Insurance, VAT | HMRC can take from wages or use bailiffs |
| 11 | Unpaid child maintenance | CMS can "take the money from your wages or bank accounts" |

**Non-priority:** credit cards, store cards, catalogues, **unsecured loans**, water bills, benefit
overpayments, parking tickets, **money owed to family and friends**.

### Learnings

1. **The rule that generates the list is a single legal test**, not a preference: a debt is priority
   if non-payment lets the creditor *take your home, take your goods, cut off an essential supply, or
   imprison you*. Everything else is non-priority. That test is portable to India and is a much better
   thing to encode in `policy.py` than a hand-ranked list - it explains itself when the bot is asked
   "why is my personal loan below my rent?".
2. **Unsecured personal loans are non-priority. Ours is tier 3, above the card minimum.** Citizens
   Advice would put a personal loan EMI and a credit card in the *same* bucket. Our split is
   defensible on Indian grounds (NACH bounce fees + s.138-adjacent pressure make an unsecured EMI
   genuinely more expensive to miss than a card minimum), but the deviation should be written down in
   `policy.py` as a comment with this citation, because a reviewer who knows UK debt advice will
   flag it.
3. **"Money owed to family and friends" is explicitly non-priority** - same call we made (tier 5,
   below the card minimum) and the same reasoning: no fee, no legal consequence. Good, cite it.
4. **Consequence phrasing is uniformly conditional**: "might evict", "can cut off", "could take back".
   Never "you will be evicted", never "the lender will agree". Our `Tier.consequence` strings mostly
   follow this; `"the lender can eventually move to take back the asset"` is the right register.

---

## 4. hledger `--forecast` and periodic transaction rules

- https://hledger.org/hledger.html#forecasting , https://github.com/simonmichael/hledger (GPL-3.0,
  ~2.7k stars, active)

**What it is.** Plain-text accounting. A periodic rule is written with `~` and a period expression;
`--forecast` expands it into ordinary transactions that flow through every report unchanged:

```
~ monthly  set budget goals    ; 2+ spaces before the description
    (expenses:rent)      $1000
    (expenses:food)       $500
```

### Learnings

1. **Forecast rows are ordinary rows.** A generated transaction is indistinguishable from a real one
   downstream - same register, same balance report, same auto-posting rules (`=`). Ledgerline already
   mixes planned and actual rows in one `timeline` with `flags`; hledger validates that choice, and
   its `flags`-free approach is the warning: without a marker on the row you cannot tell the user
   which numbers are facts and which are projections. **Keep the flag.**
2. **The default forecast period starts *after the latest real transaction*, not today.** This is
   hledger's double-count guard and it is the same problem Actual fixed twice. Stated in the manual as
   a caveat: do not include both a real and a forecast version of the same transaction or balances
   inflate.
3. **Month-length is called out as a known trap.** The manual warns that rules anchored to a day like
   the 31st behave unexpectedly in shorter months. Ledgerline's `upsert_item(day_of_month=31)` resolves
   a day number to a date - "the 31st" in a 30-day month and "the 30th" in February are real inputs
   from a real user and need a documented rule (clamp to last day is the conventional answer).
4. **The period expression is the whole recurrence DSL.** Worth noting only to say we do not need it:
   inside a fixed 30-day window every recurring item fires at most twice, so "day of month, clamped"
   plus an explicit second occurrence covers it. No rrule dependency.

Beancount's forecasting plugins (`fava.plugins.forecast`, and the `beancount.plugins.forecast` example
in https://github.com/beancount/beancount) do the same thing with a `#forecast` tag and a
`dateutil.rrule` expansion - same shape, same conclusion.

---

## 5. Firefly III - bills vs recurring transactions, and weekend handling

- https://github.com/firefly-iii/firefly-iii (AGPL-3.0, ~19k stars, active)
- https://docs.firefly-iii.org/explanation/financial-concepts/recurring/ ,
  https://www.mintlify.com/firefly-iii/firefly-iii/api/recurring-transactions

**What it is.** Self-hosted personal finance manager. Two separate concepts we should not conflate:

- a **bill** is an *expectation* - "something around Rs 12,000 arrives around the 5th, match a real
  transaction to it"; it has a min/max amount range and a date range, and it can be *not paid yet*;
- a **recurring transaction** is an *instruction* - it actually creates a transaction on a schedule.

### Learnings

1. **Bills carry an amount *range*, not a number** (`amount_min` / `amount_max`), because the user
   genuinely does not know whether the electricity bill is 1,800 or 2,400. Ledgerline models an unknown
   amount as `None` and excludes the item entirely. A range would let the engine say "the dip is
   somewhere between -800 and -1,400" instead of "surplus 33,000 *before rent*" - a strictly better
   answer to the same question, and it composes with a worst-case simulation.
2. **Weekend handling is a first-class field on a repetition** (`repetitions[].weekend` in the API),
   with four behaviours: *do nothing / create anyway*, *skip this occurrence*, *move to the previous
   Friday*, *move to the next Monday*. See also issue
   https://github.com/firefly-iii/firefly-iii/issues/2043 ("Next expected transaction not listed on a
   weekend"). We have no concept of this at all. In India it matters in both directions: **NACH
   auto-debit presentations run on working days, so an EMI dated Sunday is presented the next working
   day**, while salary credits often land *early* when the 1st is a Sunday. That is a one-day shift in
   both the dip date and whether the dip happens.
3. **`skip` (fire every n-th occurrence) is separate from the frequency**, which keeps "every second
   Friday" out of the frequency enum. Not needed at a 30-day horizon, noted for completeness.
4. **A repetition has a `moment`** (day of month / nth-day-of-month / weekday) rather than a resolved
   date, and resolution happens at query time against a range. Same split as Actual: rules in, dates
   out, then simulate.

---

## 6. Business Debtline / MoneyHelper / the Standard Financial Statement - the pro-rata offer

- https://www.businessdebtline.org/dealing-with-your-debts/your-non-priority-debts/ and
  https://businessdebtline.org/guides/your-non-priority-debts-ew/
- https://www.moneyhelper.org.uk/en/everyday-money/credit/how-to-prioritise-your-debts
- Worked example: https://www.solihullcommunityhousing.org.uk/images/stories/fleximedia/askmat-calculating-a-prorata-offer.pdf
- The Standard Financial Statement itself: https://sfs.moneyadviserinetwork.co.uk/

**This is the one real *algorithm* in published debt advice**, and we do not implement it.

The UK debt-advice sequence is: (1) essential living costs, benchmarked against the **SFS spending
guidelines** ("trigger figures" - category caps above which the adviser must justify the figure);
(2) priority debts; (3) whatever is left - "Box E, money for credit debts" on the SFS - is split
across all non-priority creditors **pro rata by balance**:

```
offer_to_creditor_i = available_surplus * (balance_i / total_non_priority_balance)
```

and the check is that the offers sum back to Box E. If the surplus is zero or negative, the published
answer is a **token payment of GBP 1 per month per creditor** - deliberately not zero, because a token
payment keeps the account in an arrangement and demonstrates engagement rather than silence.

### Learnings

1. **Partial payment is the normal case, not a failure mode.** Ledgerline pays a tier in full or
   leaves it `unpaid`; for anything except a NACH-presented EMI (which genuinely is indivisible) the
   advice sector's default is a proportional part payment. `ASK_LENDER` already says "whether a part
   payment ... is possible" but the engine never computes what that part payment would be. Computing
   `surplus * balance_i / total` turns a vague ask into a concrete, speakable number: "you could offer
   them 1,400 of the 5,000 this month."
2. **The token payment is the honest floor.** Our `UNSOLVABLE` status currently lists unpaid items with
   a consequence and stops. A token-payment analogue - "pay something, tell them the date you can pay
   the rest" - is a strictly better terminal state and costs one string.
3. **A benchmarked essentials floor exists and is a published number.** The SFS spending guidelines
   cap what counts as reasonable per category per household size. Ledgerline has no floor at all: a
   user who says groceries are 200/day is believed, and the engine will happily plan them to zero if
   they are not marked `survival`. A "this looks below any plausible living cost" warning is the
   defensible version of that, not a hard cap (Indian figures would need an Indian source - see
   open question below).
4. **Priority is a legal test, restated.** MoneyHelper's ordering is the Citizens Advice one: home,
   fuel, essential services, court-enforceable obligations; credit cards and unsecured loans last.

---

## 7. Australia - National Debt Helpline and the ASIC hardship variation

- https://ndh.org.au/debt-solutions/prioritise-your-debts/
- https://moneysmart.gov.au/managing-debt/financial-hardship ,
  https://www.asic.gov.au/for-consumers/loans-and-credit-cards/hardship-threshold/

Same ordering (essential living expenses, then housing and utilities, then everything else), but with
one thing the UK and US material does not make explicit and which **matters more to us than the
ordering does**:

> "When you ask for help, your lender **must consider** you for financial hardship assistance" - the
> lender assesses and responds within a statutory window; a hardship variation is framed as a
> *temporary* arrangement "while you get back on your feet".

### Learnings

1. **`ASK_LENDER` is a process with a defined counterparty obligation, not a wish.** The reason a
   debt-advice tool can put "ask your lender" in a plan and call it an action is that the request has a
   defined outcome path: you make it, they must consider it, you get an answer. Phrasing that carries
   the process ("ask them for a hardship arrangement - they have to consider it and come back to you")
   is far stronger than "you could ask", and it is the answer to the reviewer finding: **the plan's
   action is the request, the late payment is only what happens if the request fails.**
2. **Temporary is stated up front.** Every one of these sources frames a variation as time-boxed. Our
   `ASK_LENDER.rationale` names a date the money arrives, which is the right shape - it is implicitly a
   time-boxed ask. Say it out loud.
3. **"Hardship" is a named status the user can claim**, which is what makes the conversation possible.
   The Indian equivalent is thinner (RBI Fair Practices Code obliges a grievance process, and the
   2023 penal-charges circular constrains what can be charged, but there is no s.72-style statutory
   hardship variation), so our copy must not over-promise: "you can ask" is accurate for India where
   "they must agree" would not be.

---

## 8. India specifics the engine gets wrong - credit card minimum due

Sources: RBI Master Direction on Credit Card and Debit Card Issuance and Conduct, 2022
(https://www.rbi.org.in/Scripts/BS_ViewMasDirections.aspx?id=12300), paras 9(b)(ii), 9(b)(iii),
9(b)(v); issuer schedules summarised at
https://www.bankbazaar.com/credit-card/minimum-amount-due-hdfc-credit-card.html and
https://www.bankbazaar.com/credit-card/minimum-amount-due-icici-credit-card.html .

**The minimum amount due is not 5% of the outstanding.** The published formulae are composites:

| Issuer | Minimum amount due |
|---|---|
| HDFC | 5% of total outstanding **or Rs 200, whichever is higher**, **plus** any EMI instalments and any unpaid dues carried from previous statements |
| ICICI | typically 5% of the outstanding, plus EMIs and past dues |
| SBI Card (revised, reported effective Jul 2025) | **100%** of any EMI due + GST + fees + interest + any over-limit amount, **plus 2%** of the remaining balance |

### Learnings

1. **Never derive `min_due` from `amount_due`.** Ledgerline's `Debt` carries `min_due` as a user-stated
   field, which is correct - the research doc's "~5% of outstanding" shorthand must not become a
   default. If the user does not know it, it is an `Unknown`, not a 5% guess. (Confirm no
   `amount_due * 0.05` fallback exists anywhere.)
2. **`amount_due - min_due` is not the carried amount, and not all of it is deferrable.** The EMI,
   fee, GST and over-limit components inside the minimum are non-negotiable; the split the engine makes
   into `part="min"` / `part="rest"` is right in shape, but the `PAY_MIN_DUE` warning should say the
   carried amount is "the rest of the bill", not imply the whole gap is discretionary.
3. **There is a floor** (HDFC Rs 200). A tiny outstanding does not produce a tiny minimum. Worth a
   sanity check on absurd `min_due` values (`min_due > amount_due`, `min_due <= 0`).
4. **The three-day rule is the strongest lever we have and it is already in `policy.py`.** RBI para
   9(b)(v): late fees and adverse bureau reporting only where the payment is past due for **more than
   three days**. That converts the card tier's late-payment consequence from a cliff into a
   three-day window, and it is the one place where "pay it two days late" is a *genuinely* safe
   proposal with a citable basis. Currently that nuance lives only in the consequence string; the
   engine cannot use it.
5. **Para 9(b)(iii)** requires the issuer's own statement to carry the negative-amortisation warning
   ("paying only the minimum stretches repayment over months/years with compounded interest"). Our
   `PAY_MIN_DUE.warning` says the same thing in the user's own numbers - good, and now citable as
   *matching the regulator's required disclosure* rather than being our editorial choice.

---

## 9. The negative result: there is no Python library for this

Searches across GitHub (`cashflow forecast`, `debt payoff`, `bill prioritisation`, `snowball
avalanche`, language:python) return calculators, notebooks and ML time-series demos - nothing that
models dated obligations against a running balance with a priority policy. The debt snowball /
avalanche family (undebt.it clones, `debt-payoff` style packages) optimises a **multi-month payoff
ordering** with a fixed monthly surplus; inside a single 30-day window with fixed due amounts it has
nothing to say, which is what research doc 09 already concluded. Firefly III, Actual and hledger all
forecast but none of them decide. The prioritisation logic exists only as prose in the consumer-advice
sources above.

Practical consequence: **the tier engine has no reference implementation to diff against, so the
tests are the specification.** That raises the value of the golden-file approach (below) considerably.

---

## Priority orders in the wild, side by side

Reading down each column is that source's published order, first paid at the top.

| Rank | Ledgerline `policy.py` | Citizens Advice / MoneyHelper (UK) | CFPB Tool 5 (US) | National Debt Helpline (AU) |
|---|---|---|---|---|
| 1 | survival essentials (food, utilities, medicine) | *(essential living costs assumed before the debt list)* | **protect your income** - car payment + insurance, tools, licences | essential living expenses |
| 2 | rent | rent arrears | **protect your shelter** - rent/mortgage, property tax, then utilities | housing |
| 3 | secured EMI | mortgage / secured loan arrears | pay your obligations - child support, taxes, student loans | utilities |
| 4 | unsecured EMI | council tax (prison) | protect assets and health - insurance premiums, prescriptions, co-pays | secured debts |
| 5 | credit card minimum | gas / electricity (disconnection) | *(everything else: "other loans and credit cards", lowest priority column)* | fines and court orders |
| 6 | informal debt | phone / internet if essential | | unsecured debts |
| 7 | rest of the credit card bill | TV licence, court fines, tax, child maintenance, HP on essential goods | | |
| 8 | optional spending | **non-priority:** credit cards, store cards, unsecured loans, water, parking, **money owed to family and friends** | | |

**Where we agree with everyone.** Survival/essential living costs first; housing immediately after;
credit-card balance and discretionary spending last; informal debt to family and friends has no legal
consequence. All four orders are generated by the same underlying rule - *rank by the severity and
irreversibility of the consequence, not by the size of the debt or the interest rate*. That rule, not
the list, is what should be written at the top of `policy.py`.

**Where we differ, and whether the difference survives scrutiny.**

| Difference | Our position | Verdict |
|---|---|---|
| CFPB puts **income-protecting spend above housing** | we have no such tier; a two-wheeler EMI is `secured_emi` (rank 2), below rent | **change needed.** For a gig worker the vehicle *is* the income. Needs either a `protects_income` flag that promotes an item, or an explicit tier 1. |
| UK classes **unsecured personal loans as non-priority**, level with credit cards | we rank unsecured EMI (3) above card minimum (4) | **defensible, document it.** Indian grounds: a missed NACH presentation costs a lender bounce charge plus a bank return fee (commonly quoted Rs 300-1,200 combined) and penal charges, where a card minimum paid within three days costs nothing (RBI 2022 para 9(b)(v)). Put that reasoning and the citation in `policy.py`. |
| UK/AU rank **court fines and tax above unsecured credit** | we have no tier for statutory dues at all | **gap.** Indian analogues a user may mention: advance tax, a court-ordered maintenance payment, a challan. Today they would land as an "essential" with no consequence text. |
| Everyone makes **utilities a near-top priority in its own right** | utilities are folded into `survival` alongside food and medicine | **acceptable but lossy.** Reconnection cost and the disconnection notice period are utility-specific consequences; food has neither. The consequence string is already doing double duty for two different failure modes. |
| **Informal debt** below the card minimum | tier 5 | **agrees with Citizens Advice** (money owed to family/friends is explicitly non-priority). Cite it. |

**The finding that matters most for the reviewer note.** None of the four sources presents "pay it N
days late" as a plan step. All four present the *conversation* as the step:

- CFPB: "If you have to miss a payment, try calling your creditors to tell them why. You may be able
  to make short-term arrangements."
- CFPB again, for the structural case: "negotiate a new due date to better line it up with the dates
  you receive income."
- AU/ASIC: ask for a hardship variation - "your lender **must consider** you".
- UK: make a pro-rata offer in writing; if there is nothing, offer a token payment.

The late payment is never the action; it is the *consequence branch* if the ask fails, and it is
always stated with what it costs. `policy.py` has since retired `PAY_ON_DATE` from `allowed_actions`
with the comment *"only a lender can move a due date, so the engine asks rather than reschedules"* -
that is exactly the right call and the four sources above are the evidence for it. What is still
missing is the *ladder*: an `ASK_LENDER` should carry what happens at 0-3 days, at 30 days, at 60-90
days, because CFPB explicitly says the consequence depends on how late you are.

---

## Edge cases we do not handle yet

| # | Edge case | Where it bites | Evidence / precedent | Severity |
|---|---|---|---|---|
| 1 | **Weekend and holiday due dates.** NACH presentations run on working days, so an EMI dated a Sunday debits the next working day; salary credited "on the 1st" often lands on the preceding working day | `_build_events` resolves a day number to a calendar date with no calendar awareness; shifts the dip date and can erase or create a dip | Firefly III `repetitions[].weekend` has four explicit behaviours; issue #2043 | **High** |
| 2 | **Month length / day 31.** "the 31st" in a 30-day month, "the 30th" in February | `upsert_item(day_of_month=...)` -> date resolution | hledger manual warns about exactly this for periodic rules | **High** |
| 3 | **An autodebit that already ran today.** The user quotes a balance that already reflects it, then names the debt; the engine debits it again | opening balance vs `_build_events` | Actual fixed this twice ("double-counting scheduled transactions that were already posted") | **High** |
| 4 | **Autodebit bounce fee.** A NACH presentation on a day with insufficient funds is not a no-op: it costs a lender charge *and* a bank return fee, and may re-present | `_Event.late_fee` exists but nothing generates a bounce fee when a dated debt lands on a negative day | RBI penal-charges circular (18 Aug 2023, effective 1 Apr 2024) restricts these to flat "penal charges", not rate add-ons | **High** - this is the difference between a dip and a spiral |
| 5 | **Minimum due composition.** `min_due` includes 100% of on-card EMIs, fees, GST and over-limit, plus a % of the rest, with an absolute floor (HDFC Rs 200); `amount_due - min_due` is not discretionary | `_pay_min_due` splits `part="min"` / `part="rest"` and phrases the remainder as a choice | HDFC / ICICI / SBI Card published formulae | Medium |
| 6 | **Grace / cure windows.** RBI 2022 para 9(b)(v): a card is only reportable and fee-chargeable past **three days**. Loans are generally reported at 30 DPD | consequence strings mention it, engine cannot act on it | RBI Master Direction 2022 | Medium |
| 7 | **Partial payments.** The advice-sector default is pro rata (`surplus * balance_i / total`), plus the GBP 1 token payment floor. We pay in full or mark unpaid | `_settle_debts` | Business Debtline non-priority guide | Medium |
| 8 | **Two occurrences of one item in a 30-day window.** Rent on the 5th, window starting the 3rd, ends the 2nd of the month after next - or any twice-monthly item. Our upsert key is `(kind, normalised name)` with no date | `state.upsert` collides; the second occurrence overwrites the first | Actual keys occurrences `${date}:${scheduleId}` | Medium |
| 9 | **Amount ranges.** "the electricity bill is somewhere between 1,800 and 2,400". Modelled as `None` and excluded entirely | `models.py`, `_build_events` | Firefly III bills carry `amount_min` / `amount_max` | Medium |
| 10 | **Income arriving early.** We take `latest_date` (pessimistically) and the research doc proposes an `upside` re-run, but nothing implements it | `_build_events` | standard best/worst-case practice | Low |
| 11 | **Statutory dues** (tax, maintenance, fines, challans) have no tier | `policy.py` | UK and AU both rank these above unsecured credit | Low |
| 12 | **Implausibly low essentials.** No floor, so a user who under-reports groceries gets a plan that cannot be lived | nothing checks it | SFS spending guidelines / trigger figures | Low |
| 13 | **A negative or zero opening balance** (already overdrawn, or an overdraft) | gate only checks `None` | - | Low |
| 14 | **Timezone / "today".** `state.today` is supplied; a call that crosses midnight IST silently re-bases every date on the next `build_plan` | `_window` | - | Low |

---

## Ideas to adopt in Ledgerline

Effort: **S** under an hour, **M** half a day, **L** a day or more.

- [ ] **S - Write the generating rule at the top of `policy.py`**: "tiers rank by severity and
      irreversibility of consequence, not by amount or interest rate", with the Citizens Advice legal
      test (can the creditor take your home, take your goods, cut off an essential supply, or
      imprison you?) and its URL. Makes the ordering explainable when the bot is challenged.
      *Files: `policy.py`.*
- [ ] **S - Cite the deviations.** Comment in `policy.py` recording that UK guidance puts unsecured
      loans level with credit cards and why we do not (NACH bounce cost vs the RBI three-day card
      window), and that informal debt below the card minimum matches Citizens Advice.
      *Files: `policy.py`.*
- [ ] **S - Confirm no 5%-of-outstanding fallback for `min_due` anywhere**, and add a validator for
      `0 < min_due <= amount_due`; unknown minimum stays an `Unknown`.
      *Files: `models.py`, `tests/`.*
- [ ] **M - Graduate `Tier.consequence` into a by-lateness ladder.** Replace the single string with
      `consequences: list[LateBucket(days_from, days_to, text)]` - card: 0-3 "no fee, nothing
      reported", 4-30 "late fee and a past-due mark", 30+ "reported 30 DPD"; loans: 1-29 "penal
      charges and a bounce fee", 30+ "30 DPD on your credit report", 90+ "the account is classified
      NPA". CFPB states plainly that consequences depend on how late you are; RBI gives us the exact
      card boundary. Directly answers the reviewer finding about weak consequence warnings.
      *Files: `policy.py`, `engine.py` (`_settle_debts` picks a bucket from `earliest - due_date`),
      `models.py`, `tests/`.*
- [ ] **M - Split `ASK_LENDER` into two shapes**: `ASK_ONE_OFF` ("give me until the 30th this month")
      and `ASK_DUE_DATE_CHANGE` ("move my due date permanently to just after payday"). CFPB names them
      as separate remedies and the second is the only fix for a recurring `TIMING` shortfall. Emit the
      second whenever the same debt would dip the balance every month.
      *Files: `policy.py` (new `ActionType`), `engine.py`, `models.py`, `tests/`.*
- [ ] **M - State the counterparty obligation in the ask.** Rewrite `Tier.ask` from "you could ask" to
      a request with a shape: what to ask for, that it is temporary, and that a written request gets a
      response. Keeps the no-promises rule (we never say they will agree) while making the action feel
      like an action rather than a shrug.
      *Files: `policy.py`.*
- [ ] **M - Add a bounce-fee event.** When a dated debt with `autodebit=True` falls on a day the
      balance cannot cover, emit a `kind="fee"` row immediately after it (we already have
      `within_day` ordering for exactly this) using a user-stated fee, or no number and words only if
      unknown. Without it the engine under-states the cost of a missed EMI by the one number the user
      will actually see on their statement.
      *Files: `engine.py`, `models.py`, `policy.py`, `tests/`.*
- [ ] **M - Weekend/holiday shift on date resolution.** One helper: `resolve_due(day_of_month,
      month, kind) -> date`, clamping day 31 to the last day of the month and shifting per kind -
      auto-debited obligations forward to the next working day, salary credits back to the previous
      working day. Start with weekends only; a holiday list is a later `policy.py` constant.
      *Files: `state.py` (date resolution) or a new `domain/calendar.py`, `policy.py`, `tests/`.*
- [ ] **M - A pro-rata part-payment number on every `ASK_LENDER`.** Compute
      `surplus * amount_i / total_unpaid` and put it in the rationale: "you could offer them 1,400 of
      the 5,000 this month". Turns the weakest action in the list into a concrete proposal, and it is
      the standard published method.
      *Files: `engine.py`, `models.py` (`Action.part_payment: Decimal | None`), `tests/`.*
- [ ] **M - A `protects_income` flag on essentials and debts** that promotes the item to rank 0 in
      `_tier_key`. The commute, the work phone, the bike EMI. CFPB ranks this above shelter; for an
      Indian gig worker it is the whole plan. Ask for it in the prompt when a debt is a two-wheeler or
      a vehicle loan.
      *Files: `models.py`, `policy.py`, `engine.py`, `prompt.py`, `tests/`.*
- [ ] **S - Emit the zero-crossing offset in `Summary`.** One float, straight from Actual's
      `getZeroCrossingGradientOffset`: `null` if the line never crosses zero, else
      `max / (max - min) * 100`. The 30-day balance line then paints the negative stretch without the
      frontend inventing a threshold.
      *Files: `engine.py`, `models.py`, `frontend/src/components/Timeline.tsx`.*
- [ ] **S - Guard against re-simulating an autodebit that already ran.** If a debt's due date is
      `state.today` and `autodebit=True`, ask once ("has that already gone out?") and honour the
      answer; the engine should not silently double-count against a balance the user just read off
      their banking app. Actual shipped this bug twice.
      *Files: `engine.py`, `models.py` (`Debt.already_paid: bool`), `prompt.py`, `tests/`.*
- [ ] **M - Golden files for the ten reference scenarios.** Serialise `PlanResult` to JSON and diff
      against a committed file, rather than asserting field by field. There is no reference
      implementation in the world to diff the tier engine against, so the goldens *are* the
      specification, and they catch the phrasing regressions that field assertions miss (a
      consequence string quietly becoming a promise). `build_plan` is already required to be
      idempotent and byte-identical across runs - that is the precondition and it is already a test.
      *Files: `tests/domain/test_engine_scenarios.py`, `tests/golden/*.json`.*
- [ ] **M - Property tests over the simulation.** Hypothesis, with the invariants the sources imply:
      closing balance always equals `opening + sum(income) - sum(paid)`; applying actions never lowers
      `lowest_balance` (already encoded in `_no_worse`); no action ever moves a debt's date; spread
      slices always sum exactly to the original amount (the remainder-on-last-day trick in `_spread`
      is exactly the kind of thing a property test is for); the serialised result never contains a
      forbidden word.
      *Files: `tests/domain/test_engine_properties.py`.*
- [ ] **L - Amount ranges instead of `None`.** `Money | Range | None`, worst case drives the plan and
      best case drives an `upside` summary. Firefly III's bills show the shape. Deferred: it touches
      every sum in the engine and every card, and `None` + `Unknown` is honest in the meantime.
      *Files: `models.py`, `engine.py`, `cards.py`, `state.py`, `tests/`.*
- [ ] **L - Occurrence identity with a date component.** Key events `(kind, name, date)` so an item
      can fire twice inside one window, as Actual does with `${date}:${scheduleId}`. Deferred: it
      changes the upsert contract the LLM has learned, and twice-in-thirty-days is rare.
      *Files: `state.py`, `models.py`, `tests/`.*

### Open questions this research did not settle

1. **Is there an Indian equivalent of the SFS spending guidelines** - a published, citable minimum
   reasonable living cost by household size? Nothing authoritative surfaced. Without one, the
   "implausibly low essentials" check has to be a soft warning with no number attached.
2. **Typical NACH return charges.** Widely quoted as Rs 300-1,200 lender-side plus a bank return fee,
   but the citable primary source is each bank's schedule of charges, not a regulation. Keep to
   "there is usually a bounce charge from both the lender and your bank" unless the user states one.
3. **Should the three-day card window become engine behaviour** (a card minimum landing 1-3 days after
   its due date is flagged low-risk rather than unpaid), or stay in the consequence text? Research doc
   09 left this open too. The by-lateness consequence ladder above is the cheaper half of it and can
   ship first.
