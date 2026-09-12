# Prior art: what other people built, and what we take from it

Researched 2026-09-12 by six parallel agents against live repos and docs, after the HLD was approved and
the first end-to-end build existed. Purpose: stop reinventing solved problems, and check our design choices
against what others learned the hard way. Each report ends with an "Ideas to adopt in Ledgerline" checklist
sized S/M/L with the files touched. This file ranks across all six.

## Reports

| # | File | Angle | Words | Closest prior art |
|---|---|---|---|---|
| 01 | `01-pipecat-daily-voice-agents.md` | Pipecat and Daily bots that call tools and drive a browser | 5.5k | pipecat `examples/`, Gradient Bang, RTVI, voice-ui-kit |
| 02 | `02-cash-flow-engines.md` | Cash-flow forecasting, debt priority orders, edge cases | 6.9k | Actual Budget forecast, Firefly III, hledger, CFPB, StepChange |
| 03 | `03-generative-ui-cards.md` | Live cards during a conversation, protocol and presentation | 5.0k | AG-UI, A2UI, Vercel AI SDK, Terraform plan |
| 03a | `03a-tool-results-carrying-ui.md` | Tool results that carry UI (input to 03) | 1.4k | MCP-UI, OpenAI Apps SDK, Adaptive Cards |
| 04 | `04-slot-filling-state-conflicts.md` | Structured gathering, corrections, conflicts, unknowns | 5.8k | Dialogflow CX, Rasa forms, Guardrails, LiveKit survey, Instructor |
| 05 | `05-agent-evals-regression.md` | Simulated users, judges, pass^k, regression | 8.7k | tau2-bench, Pipecat Evals, LiveKit testing, agentevals |
| 06 | `06-finance-coaching-agents.md` | Finance coaching agents and counsellor domain knowledge | 6.6k | StepChange, MaPS, RBI Master Direction, motivational interviewing |

## Three things the survey settled

1. **Our core shape has no open-source equivalent and does not need one.** No Python library does a
   day-by-day cash simulation with within-day priority ordering (02). No open-source intake agent has
   conflict or unknown semantics as complete as `domain/state.py` (04). No voice starter ships a card
   surface, a motion policy or a mock-feed browser test (03). Where we are ahead, the tests are the
   specification.
2. **Full snapshot plus monotonic version is the consensus, not a shortcut.** AG-UI, Adaptive Cards, the
   Apps SDK and MCP-UI all replace wholesale; deltas appear only on channels that guarantee order, and Daily
   app-message does not (03, 03a). Keep it. The one missing leg is resync for a late or desynced browser.
3. **The domain knowledge is in regulator and charity publications, not repos.** GitHub finance coaches
   are the anti-pattern catalogue: model does arithmetic, US ratios leak in, one instructs the agent to
   suggest refinancing (06). StepChange, CFPB, MaPS and RBI give us the priority principle, the consequence
   register and the three Indian clocks.

## Top adoptions, ranked across reports

Effort S under an hour, M an afternoon, L a day. "Finding" cites the static review ids it answers.

| # | Adoption | Effort | Files | Report | Finding |
|---|---|---|---|---|---|
| 1 | Consequence ladder by lateness, not binary. Card: 0-3 days nothing (RBI 9(b)(v)), 4-30 fee, 30+ bureau. Loan: 1-29 fee, 30 DPD mark, 90 NPA. Secured adds asset risk on the agreement's notice period. Every `ASK_LENDER` and every late suggestion carries the bucket text. | M | `policy.py`, `engine.py`, tests | 02, 06 | F3 |
| 2 | Intent-level policy criteria judged by LLM replace the banned-substring list. First criterion carries the carve-out: naming an existing debt is required behaviour. Deterministic checks keep gating; intent criteria are diagnostics. | S | `evals/checks.py`, `evals/judge*` | 05 | F8 |
| 3 | Outliers become persistent `INVALID` state that blocks finalisation until confirmed or corrected (Dialogflow status, Guardrails `filter` + block). Clear only by explicit resolution. | S | `state.py`, `readiness()`, tests | 04 | F2 |
| 4 | `remove()` cascades: drop unknowns, conflicts and outliers for that kind/name, invalidate `plan_final` and `understanding`. | S | `state.py`, tests | 04 | F4 |
| 5 | Row-level diff highlight: keep previous snapshot in the reducer, flash only rows whose text changed, so a correction ripples income to summary to dip day to action. No count-up on money. | S | `frontend/src/state/*`, `CardStack` | 03 | demo value |
| 6 | Terraform plan vocabulary on the final panel: future-tense count line, per-row verb, "nothing here has happened yet", consequence on the row that causes it. Proposed vs unpaid emitted structurally from `cards.py`, not sniffed from prose. | S | `cards.py`, `PlanPanel.tsx`, mock | 03 | F6, F7 |
| 7 | Summary reflection instead of teach-back: bot recaps, user confirms or corrects. Panel text and prompt say the same thing. | S | `prompts/v1.md`, `PlanPanel.tsx` | 06 | F6 |
| 8 | Judge verdict becomes three-valued yes / no / continue, plus the clause "do not fault a reply for something the criterion does not ask of it". | S | `evals/judge*` | 05 | judge false negatives |
| 9 | Report pass^k (`comb(c,k)/comb(n,k)`) alongside pass rate; exclude infrastructure errors from metrics. | S | `evals/report*` | 05 | eval phase |
| 10 | Structured termination: simulated user ends with a tool call carrying success and reason, third token for out-of-scope, replacing the `[END]` sentinel. | S | `evals/sim_user*` | 05 | harness stalls |
| 11 | Income-protecting spend tier above rent (CFPB): vehicle, tools, licences that keep the job. `protects_income` flag on debts and essentials. | M | `models.py`, `policy.py`, `tools.py` | 02 | plan realism |
| 12 | Pro-rata offer behind `ASK_LENDER`: `offer_i = surplus * balance_i / total`, token payment as floor. Turns "you could ask" into a number. | M | `engine.py`, tests | 02 | plan realism |
| 13 | Arrears: "behind on anything, and since when?" asked early. Changes amount owed and which clock applies. New optional field, missing-block entry. | M | `models.py`, `state.py`, `prompt.py` | 06 | model gap |
| 14 | Resync: browser can request the current snapshot on join or version gap. One handler, one message type. | S | `session.py`, `useDailyCall.ts` | 03 | late joiner |
| 15 | `aria-live="polite"` on the focused card only; `prefers-reduced-motion` rule; missing fields rendered present-but-empty, never hidden. | S | frontend CSS, `MissingChips` | 03, 03a | accessibility |
| 16 | Weekend and month-length rules: named behaviour for due dates that land on a non-working day (NACH presents on working days), day-31 clamp. | M | `engine.py`, tests | 02 | edge cases |
| 17 | Already-posted autodebit guard: an autodebit dated today that ran before the quoted balance must not be simulated again. | S | `engine.py`, tests | 02 | double count |
| 18 | Six residual state bugs from 04: `upsert()` never clears the `Unknown` it just filled; conflict path returns before applying the non-conflicting half of a multi-field update; `latest_day_of_month` can drift below `day_of_month`; `describe()` has no zero-action clause; card push not exception-isolated; `remove()` leaves `plan_final`. | S each | `state.py`, `tools.py`, tests | 04 | earlier F1, F4 |
| 19 | Voice-realism guidelines in the simulated user: spoken numerals, disfluency, "forty-two hundred", "1.2 lakh"; STT regression fixtures use the STT's literal output ("rent is 42 100"), not audio. | S | `evals/scenarios/*`, sim prompt | 05 | STT outliers |
| 20 | Golden files over serialised `PlanResult` plus property tests on simulation invariants (balance never jumps without an event, sum of events equals closing minus opening). | M | `tests/domain/` | 02 | engine trust |

## Corrections to earlier research docs

- `07-frontend.md` and HLD section 6 name `bot-transcription` for the question headline. RTVI deprecated it
  in favour of `bot-output` with a `spoken` flag (Pipecat 0.0.95, client-js 1.5.0). See 01 section 4.
- `11-testing-evals.md` says Pipecat Evals cannot inject hidden facts. It now has a persona simulation mode
  (`persona.py`, `simulation*.py`). Keeping our own harness is still right, for a narrower reason: we need
  the real tool handlers in the loop. See 05 section 2.
- `05-llm-openai.md` and HLD section 7: the "still missing" block must go through
  `LLMUpdateSettingsFrame(system_instruction=...)` and never as a context message, or the
  `previous_response_id` prefix match breaks every turn. See 01 section 2.
- `09-plan-engine.md` tier list: no debt-advice source presents "pay N days late" as a plan step. The
  request to the creditor is the action; the late payment is the consequence branch. `PAY_ON_DATE`
  retirement confirmed. See 02 "Priority orders in the wild".

## Choices prior art validated, no change needed

- Handler-side enum validation and generic `upsert_item` over per-entity tools (01, 04).
- Conflicts block the plan and keep both values: MultiWOZ 2.1 re-annotation changed 32% of state labels,
  the empirical case against latest-write-wins (04).
- `Unknown(field, reason)` with never-ask-again reasons is the fix for the Rasa form loop (04).
- Phase derived from readiness, not a state machine; Parlant journeys reach the same conclusion (04).
- Engine-derived cards off the model's critical path; Gradient Bang runs a whole second LLM to get the
  same separation (01).
- Dropping the rote teach-back for a recap-and-confirm; motivational interviewing calls it summary
  reflection (06).
