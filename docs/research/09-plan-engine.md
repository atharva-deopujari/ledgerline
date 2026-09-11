# 09 - Deterministic 30-day plan engine

Research note for Ledgerline. Scope: the pure-Python engine that turns facts gathered by the voice agent into a testable 30-day plan. Pipecat/LLM integration is out of scope here. Date of writing: 2026-09-11; all scenario dates use a window of 2026-09-11 to 2026-10-10 (30 days inclusive).

## Decision summary

- The engine is a **pure function** `build_plan(facts: Facts, policy: Policy = DEFAULT) -> PlanResult`. No I/O, no randomness, no LLM. Corrections are handled by re-running it on the updated `Facts`; there is no incremental state to get out of sync with the cards.
- Money is `Decimal` quantised to paise; dates are `datetime.date`. The LLM never does arithmetic; it only fills `Facts` and reads `PlanResult`.
- **Day-by-day simulation** (not a monthly total) so that "salary on the 1st, EMI on the 28th" is caught. Within a day: income, then spread essentials, then dated obligations by priority tier, then optionals.
- Shortfall is classified as **TIMING** (opening + total in >= total required out, but the running balance dips below zero) or **STRUCTURAL** (total required out exceeds what is available in the window).
- Prioritisation is a **configurable ordered tier list** defaulting to: survival essentials (food, utilities) > rent > secured EMI > unsecured EMI > credit-card minimum due > informal debt > credit-card remaining balance > optional spends. Each tier carries a cited consequence string that the agent can speak.
- The only actions the engine may emit: `CUT_OPTIONAL`, `DEFER_OPTIONAL`, `PAY_MIN_DUE_INSTEAD_OF_FULL` (with an interest warning), `PAY_ON_DATE` (reorder to the first day the balance covers it), `ASK_LENDER` (due-date shift / restructuring, phrased as "you could ask"). It never emits loans, BNPL, balance transfer, card-to-EMI conversion or settlement offers.
- Unknown amounts are **excluded from the math and listed**; the plan is marked `provisional`. Uncertain income dates take the **latest** plausible date. **Conflicts block computation** and surface a question; no plan is produced until resolved.
- When it cannot be solved, the engine says so (`status = UNSOLVABLE`), lists exactly which obligations remain unpaid, with amounts and the cited consequence of not paying them.

---

## 1. Data model (Pydantic v2, `Decimal`, frozen)

```python
Money = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]

# (corrected via context7) the section title claims "frozen" but no model below declared it.
# Pydantic v2 immutability is opt-in; every model below sets `model_config = FROZEN`.
FROZEN = ConfigDict(frozen=True)

class Certainty(StrEnum):   CONFIRMED="confirmed"; ESTIMATED="estimated"; UNCERTAIN="uncertain"
class DebtKind(StrEnum):    SECURED_EMI="secured_emi"; UNSECURED_EMI="unsecured_emi"; CREDIT_CARD="credit_card"; INFORMAL="informal"

class Income(BaseModel):
    name: str                          # "salary", "freelance invoice"  -> timeline row label
    amount: Money | None               # None = unknown -> excluded, listed in unknowns
    date: date | None                  # expected credit date
    latest_date: date | None = None    # if user gave a range ("28th or 1st"); engine uses this
    certainty: Certainty = CONFIRMED   # UNCERTAIN -> excluded from base plan, shown as upside

class Debt(BaseModel):
    name: str
    kind: DebtKind
    amount_due: Money | None           # EMI amount, or card total amount due
    min_due: Money | None = None       # cards only; RBI requires it to cover interest+charges
    due_date: date | None
    late_fee: Money | None = None      # only if user stated it; never defaulted
    autodebit: bool = False            # bounce/NACH-return charges apply if it fails
    lender: str | None = None          # for ASK_LENDER wording only
    notes: str = ""                    # free text the user said ("already 1 month behind")

class EssentialExpense(BaseModel):
    name: str                          # rent, electricity, groceries, school fees
    amount: Money | None
    due_date: date | None = None       # dated (rent) ...
    spread: bool = False               # ... or spread evenly across the window (groceries)
    survival: bool = False             # food/utilities/medicine -> tier 0 (reserved first)

class OptionalExpense(BaseModel):
    name: str
    amount: Money | None
    date: date | None = None           # None -> treated as spread
    flexible: bool = True              # False = user insists (e.g. a wedding gift) -> cut last

class Unknown(BaseModel):   field: str; question: str        # "rent.amount", "What is your monthly rent?"
class Conflict(BaseModel):  field: str; values: list[str]; sources: list[str]  # both utterances kept

class Facts(BaseModel):
    today: date
    horizon_days: int = 30
    opening_balance: Money | None      # cash + bank available today
    incomes: list[Income]; debts: list[Debt]
    essentials: list[EssentialExpense]; optionals: list[OptionalExpense]
    unknowns: list[Unknown] = []; conflicts: list[Conflict] = []
```

Why each field exists (traced to an output):

| Field | Output that needs it |
|---|---|
| `Income.date` / `latest_date` / `certainty` | timeline ordering, TIMING-vs-STRUCTURAL classification, `warnings` ("assumed latest date"), `provisional` flag |
| `Debt.kind` | tier lookup in the priority policy; consequence text in `unpaid` |
| `Debt.min_due` vs `amount_due` | the `PAY_MIN_DUE_INSTEAD_OF_FULL` action and its "amount saved this month" |
| `Debt.late_fee`, `autodebit` | cost line when `PAY_ON_DATE` moves a payment past its due date; only used if the user supplied it |
| `EssentialExpense.spread` | daily proration so the running balance is realistic between paydays |
| `EssentialExpense.survival` | tier 0 reservation: the engine never lets a debt payment consume next week's food money |
| `OptionalExpense.flexible` | ordering of `CUT_OPTIONAL` candidates |
| `opening_balance` | starting point of the running balance; `None` blocks the plan (it is the single most important number) |
| `unknowns`, `conflicts` | `provisional`, `status = BLOCKED`, the "missing information" card |

Everything an LLM extracts is a *claim*; the Facts object is the agreed, confirmed subset. The agent layer owns the mapping from utterances to Facts; the engine trusts Facts.

## 2. Algorithm

Complexity is trivial: E events (typically < 40) sorted once, one pass over D = 30 days; O(E log E + D). Actions are tried greedily, each requiring a re-simulation, so worst case O(A * (E log E + D)) with A < 20. Sub-millisecond.

```text
build_plan(facts, policy):
  if facts.conflicts:               return PlanResult(status=BLOCKED, questions=conflict questions)
  if facts.opening_balance is None: return PlanResult(status=BLOCKED, questions=["opening balance"])

  window   = [today, today + horizon_days - 1]
  unknowns = facts.unknowns + every item whose amount is None   # excluded from math
  warnings = []

  events = []
  for inc in incomes with amount:
      if inc.certainty == UNCERTAIN: warnings += "excluded uncertain income X"; continue
      d = inc.latest_date or inc.date; if d != inc.date: warnings += "assumed latest date"
      if d in window: events += Event(d, INCOME, +amount, tier=None)
  for e in essentials with amount:
      if e.spread: events += 30 daily Events of amount/30 (paise-rounded, remainder on last day)
      else if e.due_date in window: events += Event(due_date, ESSENTIAL, -amount, tier=0 if survival else 1)
  for debt in debts with amount and due_date in window:
      events += Event(due_date, DEBT, -amount_due, tier=policy.tier(debt.kind, part="full"))
      # cards are split into two events: min_due (tier 4) and (amount_due - min_due) (tier 6)
  for o in optionals with amount: events += Event(o.date or spread, OPTIONAL, -amount, tier=7)

  sim = simulate(events, opening_balance, policy)           # see below
  total_in, total_out = sums over events; net = opening + total_in - total_out
  if sim.min_balance >= 0:            status = OK
  elif net >= 0:                      status = TIMING       # money exists, dates do not line up
  else:                               status = STRUCTURAL   # more out than in, dates aside

  actions = []
  if status != OK:
      # 1. optionals: defer flexible ones past the first negative day (TIMING) or cut them (STRUCTURAL),
      #    largest first, until the simulation is non-negative or none remain
      # 2. cards: switch full -> min_due (largest saving first); attach interest warning
      # 3. still negative: for each obligation that falls on a negative day, PAY_ON_DATE = first later
      #    day in window where balance covers it; if none, it becomes UNPAID
      # 4. every dated debt that cannot be paid on time gets an ASK_LENDER suggestion
      after each step: re-simulate; stop as soon as min_balance >= 0
  final = simulate(events after actions)
  status = UNSOLVABLE if final.unpaid else status
  return PlanResult(...)

simulate(events, opening, policy):
  balance = opening; reserved = sum of tier-0 spread amounts not yet booked
  for day in window:
      todays = sorted(events on day, key=(kind_order, tier, due_date, -amount))
        # kind_order: INCOME(0) < ESSENTIAL(1) < DEBT(2) < OPTIONAL(3)
      for ev in todays:
          if ev is INCOME: balance += ev.amount
          else:
              available = balance - reserved_after(ev)   # survival money for the rest of the window
              if available >= ev.amount or ev.tier <= 1: balance -= ev.amount   # essentials always booked
              else: ev.unpaid = True                       # recorded, not paid; consequence text attached
          rows += TimelineRow(day, ev.label, ±amount, balance, flags)
      track min_balance and its day; negative_days
```

Two deliberate choices. First, essentials are always booked even if they push the balance negative: the engine does not "solve" a shortfall by starving the household; it makes the negative visible. Second, the tier-0 reservation means a debt on the 5th cannot be paid with money the family needs to eat on the 8th.

## 3. Prioritisation policy (default, configurable)

```python
DEFAULT_TIERS = [
  Tier(0, "survival essentials", consequence="no food / utilities disconnected, reconnection fees"),
  Tier(1, "rent",                consequence="late fee, eviction risk, landlord dispute"),
  Tier(2, "secured EMI",         consequence="penal charges; 30 DPD reported to bureaus; 90 DPD = NPA; asset repossession under contract (vehicle) or SARFAESI 60-day notice (property)"),
  Tier(3, "unsecured EMI",       consequence="bounce charge Rs 300-1,200 + NACH return fee; penal charges ~2-4%/month on overdue; 30 DPD bureau reporting"),
  Tier(4, "credit card min due", consequence="late fee Rs 100-1,300 by slab if > 3 days past due; reported past due to bureaus; interest 3.5-3.75%/month continues"),
  Tier(5, "informal debt",       consequence="no fee or bureau impact; relationship cost; often renegotiable"),
  Tier(6, "credit card balance above min", consequence="revolving interest ~42-45% p.a. on the carried amount; interest-free period lost"),
  Tier(7, "optional spends",     consequence="none"),
]
```

Grounding for the ordering, so it is defensible:

- **Housing and utilities first** is the standard consumer-protection guidance: CFPB's "Prioritizing bills" tool lists housing (eviction) and utilities (disconnection, reconnection fees) ahead of credit cards, and notes that a car payment matters because "you risk possible repossession of your car" and losing the means to earn.
- **Secured above unsecured**: default on a secured loan can cost the asset. An account is NPA after 90 days overdue; for mortgaged property the lender then serves a 60-day SARFAESI s.13(2) demand notice before taking possession. Vehicle repossession follows the contract's notice clause (RBI does not fix days) and typically starts after repeated missed EMIs, not one. Unsecured EMIs carry fees and bureau damage but no asset loss.
- **Unsecured EMI above card minimum**: a missed EMI is usually a NACH bounce, costing Rs 300-1,200 lender charge plus a bank return fee, then penal charges of roughly 2-4% per month on the overdue amount. Since RBI's 2023 "Fair Lending Practice - Penal Charges" circular (effective 1 Apr 2024) penalties must be flat "penal charges", not added to the interest rate, and cannot be capitalised. Missing an EMI is reported as 30 DPD after a month, and one 30+ DPD entry is commonly cited as costing 50-100 points.
- **Card minimum due is the cheapest thing to protect**: under RBI's Credit Card Directions 2022, para 9(b)(v), an issuer may report the account past due to a credit bureau or levy late fees only when it is past due for **more than three days**; so paying at least the minimum by due date (or within three days) avoids both the fee slab (SBI: Rs 100 up to Rs 500 due, rising to Rs 1,200 above Rs 50,000; HDFC up to Rs 1,300; ICICI up to Rs 800) and the bureau entry. Para 9(b)(ii) requires the minimum due to be set so there is no negative amortisation.
- **Card balance above minimum below everything except optionals**: carrying the balance costs 3.5-3.75% per month (42-45% p.a.), and interest accrues from transaction date once the interest-free period is lost. That is expensive, but it is the only line where "pay less" is a lender-sanctioned option with no fee or bureau hit. RBI para 9(b)(iii) mandates the statement warning that paying only the minimum stretches repayment over "months / years with consequential compounded interest"; the engine emits the same warning with the user's own numbers (interest on carried balance at a stated or user-supplied rate; if no rate is known it says "your card charges roughly 3.5% a month; check your statement").
- **Informal debt** sits below the card minimum by default because it has no fee or bureau consequence; users can raise it (`Policy(informal_tier=2)`) if the relationship matters more.

The tier list is data, not code; tests run the same scenarios with a swapped policy to prove the engine honours it.

## 4. Allowed and disallowed recommendations

Allowed action types (the `Action.type` enum):

| Type | When emitted | Fields |
|---|---|---|
| `CUT_OPTIONAL` | STRUCTURAL shortfall | name, amount_saved, rationale |
| `DEFER_OPTIONAL` | TIMING shortfall | name, amount, from_date, to_date (first day the balance recovers) |
| `PAY_MIN_DUE_INSTEAD_OF_FULL` | shortfall persists after optionals | card, pay=min_due, carried=amount_due-min_due, warning with interest estimate |
| `PAY_ON_DATE` | a dated obligation falls on a negative day but a later in-window day covers it | debt, due_date, pay_on, days_late, late_fee (if known), note that > 3 days (card) / ~30 days (loan) risks bureau reporting |
| `ASK_LENDER` | any obligation that cannot be paid on its due date | debt, ask="whether the due date can move to after {payday}" or "whether a part-payment or restructuring is possible"; always prefixed "You could ask" |

Never emitted, enforced by the enum and a test that asserts no other strings appear: new loan, BNPL, overdraft, balance transfer, card-to-EMI conversion, gold loan, "settlement", "the lender will agree", "approved". The engine also never invents a late fee or interest rate: if `late_fee` is None it says "late fee as per your card's schedule" and does not add a number to the timeline.

**Unsolvable path.** After all allowed actions the simulation still has unpaid obligations. Output then contains: `status=UNSOLVABLE`; `unpaid=[Unpaid(name, amount, due_date, tier, consequence)]` ordered by tier; `summary.shortfall_after_actions` (a negative Decimal); a spoken-form sentence template: "Even after cutting {n} optional expenses and paying only the minimum on {card}, you are short by {x} on {date}. The plan leaves {debt} of {amount} unpaid; the likely consequence is {consequence}. You could ask {lender} about {ask}." No hedged promises. The closing balance shown is what remains after protecting essentials, so the user sees the real money they have to negotiate with.

## 5. Handling uncertainty

- **Unknown amount** (`amount=None`): excluded from all sums; appended to `unknowns` with the question to ask; `provisional=True`; summary carries `excluded_items` so the card can say "surplus 33,000 *before rent*". Never substitute an average.
- **Uncertain income date**: use `latest_date` (pessimistic). If the user gives no range, ask; if they refuse, treat as `UNCERTAIN` and exclude. Flag in `warnings`. An optional `upside` sub-summary re-runs with the early date so the agent can say "if it lands on the 28th instead, the dip disappears".
- **Uncertain income at all** (`certainty=UNCERTAIN`, e.g. a freelance invoice "that may or may not come"): excluded from the base plan, shown as upside. Product rules forbid presenting guesses as facts; a plan that depends on money that may not arrive is a guess.
- **Conflicting numbers**: recommendation is **block, do not compute**. Computing both scenarios sounds helpful but doubles every card, and the agent is one question away from resolving it ("Earlier you said 50,000 and just now 45,000 - which is right?"). `status=BLOCKED` with `questions` populated; cards show the last consistent plan greyed out. The exception: if the conflict is on an *optional* expense the engine proceeds with the smaller value and lists the conflict, because optionals never change the status.
- **Corrections**: not special. The agent layer replaces the value in `Facts` and re-runs. Idempotence of `build_plan` is a test.

## 6. Output shape

```python
class TimelineRow(BaseModel):  date: date; label: str; kind: Literal["income","essential","debt","optional","fee"]; amount: Decimal; balance: Decimal; flags: list[str]  # ["unpaid","deferred","min_due","late"]
class Summary(BaseModel):
    opening_balance: Decimal; total_in: Decimal; total_out_required: Decimal; total_out_planned: Decimal
    shortfall_before_actions: Decimal; shortfall_after_actions: Decimal      # positive = surplus
    lowest_balance: Decimal; lowest_balance_date: date; negative_days: list[date]; closing_balance: Decimal
class Action(BaseModel):  type: ActionType; target: str; amount: Decimal | None; date_from: date | None; date_to: date | None; rationale: str; warning: str | None
class Unpaid(BaseModel):  name: str; amount: Decimal; due_date: date; tier: int; consequence: str; ask: str
class PlanResult(BaseModel):
    status: Literal["OK","TIMING","STRUCTURAL","UNSOLVABLE","BLOCKED"]
    provisional: bool; timeline: list[TimelineRow]; summary: Summary
    actions: list[Action]; unpaid: list[Unpaid]; warnings: list[str]; unknowns: list[Unknown]; questions: list[str]
    excluded_items: list[str]; policy_version: str
```

Each card maps to one field (`summary` -> shortfall/surplus card; `timeline` -> upcoming payments; `actions` -> proposed actions; `unknowns` + `questions` -> missing info; `unpaid` -> the honest "cannot be solved" card). The spoken explanation is produced by the LLM from the same `PlanResult` JSON, with the rule that it may only quote numbers present in it; a regex test over transcripts checks every rupee figure spoken exists in the result.

## 7. Test plan (pytest scenarios)

Common assumptions: `today=2026-09-11`, groceries are a spread survival essential of 6,000 (200/day), amounts in rupees. "Closing" = balance on 2026-10-10.

| # | Scenario | Inputs (key) | Expected |
|---|---|---|---|
| 1 | Comfortable surplus | opening 25,000; salary 60,000 on 10-01; rent 15,000 on 10-05; PL EMI 5,000 on 10-03; card 12,000 (min 1,500) on 09-20; OTT 500 on 09-15; dining 3,000 on 09-25 | `OK`; total_in 60,000; required out 41,500; surplus 43,500 closing; lowest 5,500 on 09-30; actions [] |
| 2 | Timing shortfall fixed by deferring | opening 6,000; festival shopping 5,000 flexible on 09-20; PL EMI 3,000 on 09-25; salary 50,000 on 09-30; rent 15,000 on 10-01 | **(corrected: arithmetic)** before: first negative day 09-20 at -1,000, but min is **-5,800 on 09-29** (the 200/day grocery spread keeps draining and the 3,000 EMI lands 09-25); net **+27,000** per §2's `net = opening + total_in - total_out` (6,000 + 50,000 - 29,000) — the previously stated +21,000 omitted the opening balance; -> `TIMING`; one `DEFER_OPTIONAL` 5,000 to 10-01 is **not sufficient alone** (lowest still **-800 on 09-29**), so a `PAY_ON_DATE` moving the 3,000 EMI to 09-30 is also required; closing 27,000 |
| 3 | Structural shortfall fixed by cuts | opening 2,000; salary 40,000 on 09-15; utilities 2,000 on 09-20; card 10,000 (min 500) on 09-25; rent 15,000 + PL EMI 9,000 on 10-05; optionals dining 3,000, gym 2,000, OTT 800 | required 47,800 vs available 42,000 -> `STRUCTURAL`, shortfall_before -5,800; actions = CUT dining, CUT gym, CUT OTT (descending); shortfall_after 0; card paid in full; closing 0; lowest 0 on 10-10 |
| 4 | Unsolvable | as 3 but salary 30,000 | after 3 cuts (5,800) and `PAY_MIN_DUE` on card (saves 9,500) still -500; PL EMI 9,000 on 10-05 `unpaid` (available 8,500 after reserving 1,000 groceries); `status=UNSOLVABLE`; `ASK_LENDER` for PL; closing 8,500; warning on carried card balance 9,500 |
| 5 | Salary after EMI date | opening 1,000; auto-loan EMI 7,000 on 09-14 (late_fee 500 stated); salary 45,000 on 09-16; rent 12,000 on 10-01 | `TIMING`; negative_days [09-14, 09-15], min -7,000; `PAY_ON_DATE` EMI -> 09-16, days_late 2, fee 500 added as a `fee` row; `ASK_LENDER` due-date shift; closing 20,500 |
| 6 | Missing amount | opening 5,000; salary 40,000 on 09-30; rent amount None on 10-01; PL EMI 6,000 on 10-05 | `provisional=True`; unknowns contains "rent.amount"; excluded_items ["rent"]; surplus 33,000 shown; status computed on known items only (`OK`) but card copy says "before rent" |
| 7 | Conflicting salary | conflicts=[salary.amount: 50,000 vs 45,000] | `status=BLOCKED`; timeline []; questions has one entry naming both values; no actions |
| 8 | Correction changes result | run scenario 3, then re-run with salary 46,000 | second run: `OK`, actions [], shortfall_before +200; results differ only in fields touched; running the same facts twice gives byte-identical JSON |
| 9 | Zero debts | opening 10,000; salary 30,000 on 10-01; rent 10,000 on 10-05; optional 2,000 on 09-20 | `OK`; lowest 4,000 on 09-30; closing 22,000; no debt rows; no `PAY_MIN_DUE` possible |
| 10 | All income uncertain | opening 3,000; salary 50,000 date range 09-28..10-01; PL EMI 4,000 on 09-20; rent 15,000 on 10-01 | uses 10-01; warning "assumed latest date"; `provisional=True`; `TIMING` with **(corrected: arithmetic)** first negative day 09-20 at -3,000 and min **-5,000 on 09-30** (grocery spread deepens the dip until salary lands 10-01); `ASK_LENDER` for EMI; upside summary shows dip is unchanged (salary still after 09-20) |
| 11 | Policy swap | scenario 4 with `Policy(informal_tier=2)` and an extra informal debt | informal debt paid before PL EMI; proves tiers are data |
| 12 | Forbidden words | every scenario | serialised `PlanResult` contains none of {"loan", "BNPL", "approved", "settlement", "guarantee"} outside `unknowns/questions` |

Each row becomes a `pytest.mark.parametrize` case with a `Facts` fixture and asserts on `status`, `summary`, `actions` types/amounts, and the exact `lowest_balance_date`. Decimal arithmetic makes the expected numbers exact, not approximate.

## 8. Reference implementations to borrow from

- **Actual Budget - Schedules + Balance Forecast report.** Exactly our shape: scheduled transactions are "expanded into simulated occurrences up to the forecast end date", then a per-day running balance is computed from a starting balance. Borrow the expansion step and the daily-loop; ignore its budget-plan mode.
- **Beancount `forecast` plugin / fava.plugins.forecast.** Recurring-transaction expansion into future dated entries; a clean example of treating projections as ordinary events in the same ledger, which is why our timeline mixes actual and planned rows.
- **Firefly III recurring transactions and bills.** Useful separation of "a bill I expect" from "a transaction that happened"; our `Debt.due_date` vs `TimelineRow.flags=["unpaid"]` mirrors it.
- **CFPB "Prioritizing bills" worksheet.** The consequence-per-bill table is the model for the `Tier.consequence` strings.
- Not used: envelope/YNAB-style budgeting (allocation, not cash-flow timing) and debt snowball/avalanche (multi-month payoff ordering; irrelevant inside a single 30-day window where every due amount is fixed).

## Open questions

1. Should the horizon be a fixed 30 days or "today to next payday + 1"? Fixed 30 matches the product rules; a payday-aligned view is a card, not an engine change.
2. Partial EMI payments: NACH is all-or-nothing, so the engine treats EMIs as indivisible. Do we expose `allow_partial=True` for lenders who accept manual part-payment?
3. Card-to-EMI conversion is offered by issuers on existing balances. It is not a new loan strictly, but it is a new credit contract with fees; recommended: disallowed, mention only as "something you could ask your issuer about" inside `ASK_LENDER`.
4. Interest estimate on the carried card balance: use the user's stated monthly rate, or a labelled "typical 3.5%/month" figure? Product rules say do not invent numbers; proposal is to use the stated rate when given, otherwise words only.
5. Where should the "3-day card grace" live: in the engine (`PAY_ON_DATE` up to 3 days late on a card is flagged low-risk) or only in the consequence text?

## Sources

- RBI, Fair Lending Practice - Penal Charges in Loan Accounts (18 Aug 2023, effective 1 Apr 2024): summarised at https://vinodkothari.com/2023/08/faqs-on-penal-charges-in-loan-accounts/ and https://www.azbpartners.com/bank/penal-charges-the-new-regime/
- RBI Master Direction - Credit Card and Debit Card Issuance and Conduct Directions, 2022 (paras 9(b)(ii), 9(b)(iii), 9(b)(v)): https://www.rbi.org.in/Scripts/BS_ViewMasDirections.aspx?id=12300 ; commentary https://www.scconline.com/blog/post/2022/04/30/rbi-introduces-master-directions-rbi-credit-card-and-debit-card-issuance-and-conduct-directions-2022/
- Bank-wise late fee slabs and monthly interest (SBI, HDFC, ICICI): https://rupeewisdom.com/credit-card-late-payment-charges-india/ ; https://freed.care/blog/credit-card-late-payment-charges-banks-compared ; https://www.bankbazaar.com/credit-card/minimum-amount-due-hdfc-credit-card.html
- Minimum-due trap illustrations: https://www.debtzen.in/credit-card-minimum-payment-trap-india ; https://freed.care/blog/credit-card-minimum-payment-calculator
- EMI bounce and penal charges: https://www.tatacapital.com/blog/personal-use-loan/what-are-personal-loan-emi-bounce-charges/ ; https://www.au.bank.in/blogs/personal-loan-emi-bounce-charges
- DPD reporting and score impact: https://www.paisabazaar.com/cibil/days-past-due-dpd-cibil-report/ ; https://www.iifl.com/blogs/credit-score/what-happens-if-you-miss-an-emi-step-by-step-impact ; https://www.bajajhousingfinance.in/resources/impact-of-late-payment-on-cibil-score
- NPA at 90 days, SARFAESI 60-day notice, vehicle repossession: https://vakilsearch.com/article/recover-money-under-sarfaesi-act/ ; https://www.dealplexus.com/blog/sarfaesi-act-explained-when-banks-can-seize-property-and-how-to-respond ; https://www.business-standard.com/finance/personal-finance/missed-car-loan-emi-know-when-lenders-can-repossess-your-vehicle-126062501228_1.html ; https://righttoinformation.wiki/vehicle-repossession-rights-rbi-india
- CFPB, Your Money Your Goals - Prioritizing bills tool: https://files.consumerfinance.gov/f/documents/cfpb_your-money-your-goals_prioritizing-bills_tool.pdf ; https://www.consumerfinance.gov/archive/blog/behind-bills-three-steps-help-you-make-tough-choices-tight-moments/
- Actual Budget Balance Forecast report and Schedules: https://actualbudget.org/docs/experimental/balance-forecast-report/ ; https://actualbudget.org/docs/schedules/
- Beancount forecast plugin: https://beancount.io/docs/Tips/forecast-plugin
- Firefly III recurring transactions: https://docs.firefly-iii.org/explanation/financial-concepts/recurring/

---

## Context7 cross-check (2026-09-11)

This report is stdlib + Pydantic only, so context7's reach here is narrow. Pydantic v2 syntax in §1 and §6 was checked against context7; the `Decimal`/`datetime` semantics and **all Indian consumer-credit domain claims in §3 (RBI penal-charges circular, RBI Credit Card Directions 2022 paras 9(b)(ii)/(iii)/(v), DPD bureau reporting, NPA at 90 days, SARFAESI 60-day notice, bank late-fee slabs, CFPB prioritisation)** are **NOT COVERED by context7** — they are not library claims and have been left exactly as written, with their own source list intact. The 10 test scenarios in §7 were recomputed by hand/script instead.

### Libraries resolved

| Library | Context7 ID | Version info |
|---|---|---|
| Pydantic | `/pydantic/pydantic` | unversioned (main branch, v2 docs), 1397 snippets, reputation High |
| Pydantic (docs site, cross-check) | `/websites/pydantic_dev_validation` | unversioned, 2805 snippets |
| Python stdlib (`decimal`, `datetime`) | — | **no context7 entry**; `Decimal.quantize` semantics NOT COVERED |

### Claims table

| # | Claim (§) | Verdict | Evidence |
|---|---|---|---|
| 1 | `Money = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]` (§1) | **VERIFIED** | Two separate docs pages confirm both halves: "Apply type constraints such as gt, max_length, max_digits, and decimal_places… `precise_decimal: Decimal = Field(max_digits=5, decimal_places=2)`" and "Create a reusable constrained type using `typing.Annotated` and `Field`… `PositiveInt = Annotated[int, Field(gt=0)]`" |
| 2 | `max_digits` + `decimal_places` together bound the whole part (relevant to the 12/2 choice = max ₹9,999,999,999.99) (§1) | **VERIFIED** | `decimal_whole_digits` error: "Raised when the number of digits before the decimal point exceeds max_digits minus decimal_places when both constraints are specified" |
| 3 | Models are **frozen** (§1 title) | **CONTRADICTED** (omission) | Frozen is opt-in and must be declared: "Configure a model to be immutable by setting `frozen=True` in `model_config`… `model_config = ConfigDict(frozen=True)`". No model in §1 declared it. Corrected inline. |
| 4 | Frozen models are safe for the "re-run `build_plan` on updated `Facts`" design (§ Decision summary, §5) | **VERIFIED with caveat** | "Reassigning model attributes raises a `ValidationError`, though **nested mutable objects such as dicts can still be modified in place**." The `list[...]` fields on `Facts` remain mutable under `frozen=True`; byte-identical-JSON idempotence (scenario 8) depends on nothing mutating them in place. |
| 5 | `unknowns: list[Unknown] = []` / `conflicts: list[Conflict] = []` mutable defaults (§1) | **VERIFIED** (valid v2) | Pydantic deep-copies mutable defaults per instance; no `default_factory` needed. Not a dataclass-style shared-default bug. |
| 6 | Output models in §6 (`TimelineRow`, `Summary`, `Action`, `Unpaid`, `PlanResult`) use plain `BaseModel` + `Literal[...]` unions | **VERIFIED** | Standard Pydantic v2; nothing in the shapes conflicts with current docs. No `model_validator` is actually used anywhere in the report, so there was nothing to check there. |
| 7 | `Decimal` "quantised to paise", remainder-on-last-day spread rounding (§ Decision summary, §2) | **NOT COVERED** | No Python-stdlib entry in context7. `Decimal.quantize` semantics unverified here; the report's approach (quantise each daily slice, push the remainder to the final day) is arithmetically sound but should be pinned with an explicit `ROUND_HALF_UP` context in code. |
| 8 | All §3 domain claims (RBI, DPD, SARFAESI, CFPB, bank fee slabs) | **NOT COVERED** | Not library claims. Untouched, per scope. |

Counts: 5 VERIFIED (one with caveat), 1 CONTRADICTED, 2 NOT COVERED (library/stdlib), plus the entire §3 domain block explicitly out of scope.

### Scenario arithmetic re-check (§7)

Each scenario was recomputed from its stated inputs over the window 2026-09-11 → 2026-10-10 (30 days), with the common assumption of groceries as a 6,000 spread survival essential at 200/day, and §2's within-day ordering (income → essentials → debts → optionals).

| # | Totals / status | Lowest balance & date | Verdict |
|---|---|---|---|
| 1 | in 60,000; required out 41,500; closing 43,500 | 5,500 on 09-30 | **VERIFIED** (exact) |
| 2 | closing 27,000 ✓, but `net` and both minima wrong | claimed -1,000 on 09-20 / 0 on 09-25 → actual **-5,800 on 09-29** / **-800 on 09-29** | **CONTRADICTED (arithmetic)** |
| 3 | required 47,800 vs available 42,000; shortfall -5,800; cuts 3,000+2,000+800 = 5,800; closing 0 | 0 on 10-10 | **VERIFIED** (exact) |
| 4 | -15,800 → -10,000 after cuts → -500 after min-due (saves 9,500); closing 8,500 | reservation math checks: on 10-05 balance 9,500, reserve 1,000 → available 8,500 < 9,000 EMI → unpaid | **VERIFIED** (exact, including the reservation step) |
| 5 | closing 20,500 (46,000 in − 25,500 out incl. 500 fee); days_late 2 | -7,000, negative days [09-14, 09-15] | **VERIFIED** (exact) |
| 6 | known out 12,000; surplus/closing 33,000; `OK` | 1,200 on 09-29 (never negative) | **VERIFIED** (exact) |
| 7 | BLOCKED, no arithmetic | — | n/a |
| 8 | available 48,000 − required 47,800 = +200; `OK` | 200 on 10-10 | **VERIFIED** (exact) |
| 9 | in 30,000; out 18,000; closing 22,000 | 4,000 on 09-30 | **VERIFIED** (exact) |
| 10 | net +28,000 → `TIMING` correct | claimed -3,000 on 09-20 → actual **-5,000 on 09-30** | **CONTRADICTED (arithmetic)** |
| 11–12 | no arithmetic | — | n/a |

Both errors are the same mistake: the minimum was read off the day of the large event and the report stopped there, ignoring the 200/day grocery spread that keeps pulling the balance down until the next income lands. Scenarios 2 and 10 have been corrected inline and marked *(corrected: arithmetic)*.

Scenario 2 also exposes a **design tension worth resolving before implementation** (not corrected, since it is a spec question, not arithmetic): under §2's tier-0 reservation rule, the 3,000 EMI on 09-25 sees `available = 3,000 − 3,000 reserved groceries = 0` and would be marked `unpaid`, which makes the scenario `UNSOLVABLE` rather than `TIMING`. Either the reservation should look ahead only to the next income date rather than to the end of the window, or scenario 2's expectation needs restating.

### Corrections applied

1. **§1** — added `FROZEN = ConfigDict(frozen=True)` with a note that Pydantic v2 immutability is opt-in and none of the models declared it, marked *(corrected via context7)*.
2. **§7 scenario 2** — `min -1,000 on 09-20` → **-5,800 on 09-29**; `net +21,000` → **+27,000** (§2 defines `net = opening + total_in − total_out`); `after: lowest 0 on 09-25` → **-800 on 09-29**, with the note that the deferral alone no longer clears the dip. Marked *(corrected: arithmetic)*.
3. **§7 scenario 10** — `min -3,000 on 09-20` → first negative day 09-20 at -3,000, **min -5,000 on 09-30**. Marked *(corrected: arithmetic)*.

Nothing else was changed. §3's grounding, §4's action enum, §5's uncertainty rules, §8's reference implementations and the source list are untouched.
