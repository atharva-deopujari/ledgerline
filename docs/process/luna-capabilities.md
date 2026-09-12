# What luna does by default, and what Ledgerline still tells it

Sources (read in full): two internal prompt-engineering guides for this model family (**LPD**, a
prompt-design guide, and **OAP**, a prompt-optimisation procedure) and the two measured QA reports OAP
points at (**V0**, a baseline battery, and **LR**, a prompt-rewrite comparison). None of the four is in
this repository; the numbers quoted below are theirs.

**Caveat.** Every luna number below was measured at `reasoning_effort=low` (LR "Rig", V0 "Setup");
Ledgerline runs luna at `effort="none"` (`voice/pipeline.py:172,181`). Treat "luna does this anyway"
as a hypothesis to verify with OAP Step 8's pass^5, not a licence to delete blind.

## 1. What the skills say luna does well without being told

| Capability | Evidence |
|---|---|
| Acceptance in any shape — bare "yes", "ok thank you", "haan" all execute the pending action | V0 K1 5/5, K2 5/5; LR `gratitude_yes` pass^5. OAP Step 0b lists gratitude-as-acceptance as holding with **zero dedicated lines** |
| Mid-flow correction / repair — "nahi 5 din kar do" re-previews with new values, no loop | V0 K7 2/2; LR `date_tweak` pass^2 |
| Not claiming an action is done before the tool says so (DONE-gating) | OAP Step 0b: "data-boundary, invented-links, gratitude-as-acceptance, DONE-gating all held with zero dedicated lines, carried by identity + tool surfaces" |
| Not inventing values; refusing to compute when the fact is absent; asking instead of guessing on a vague window | V0 headline "zero unsafe failures in ~35 runs", K8 refused to compute; LR `invented_window` "failed 3 prompt rounds on 4.1-mini; holds on Luna" |
| Following instructions carried in a **tool result** at the moment it acts; copying an injected value verbatim | OAP Step 4; LR `duration_only` pass^3 ("injected today-default copied, never invented") |
| Acting on a single positive statement — no bookend, no repetition | LR: "the 4.1-mini era bookend was NOT needed on Luna"; OAP Step 0b "Identity beats prohibition" (one identity line replaced three RULE-walls) |

## 2. What it still does badly, or needs an explicit constraint for

- **Register mirroring is a named failure category** — luna accommodates the caller's register
  (slang, anger, "beta") unless one *invariance* meta-rule splits language from register (Step 0b).
  One line covers the whole class; never patch per token.
- **Boxing the user into a reply word** — "Please reply *yes* to confirm" in 7/10 previews, the
  **single prompt line luna earned** in the whole v0 battery (V0 Finding A1).
- **Markdown leaks into speech** — every V0 transcript is full of `*2 September*`.
- **It copies its tools' framing and tense verbatim** — a future pause was spoken as "is paused"
  because the DONE text did. Fix the tool string, not the prompt (Step 0b).
- **A prohibition that quotes the unwanted output plants it** (Step 6b); a worked example that
  transforms a value teaches transformation. Old defensive rules cause failures, not just cost —
  exact-date rules produced "which year?" interrogation (Step 0b).
- **Single green runs prove nothing** — ~61% compliance at one attempt vs <25% at eight (OAP Step
  8b, arXiv 2406.12045). Read the state, never the reply.

## 3. The prompt-design rules they recommend

1. **Six surfaces, not one** (OAP "The six surfaces"): prompt=POLICY, docstring=MECHANICS, field
   description=PER-ARG MECHANICS, tool response=FACTS + runtime routing, injected context=DATA whose
   *shape* teaches behaviour, middleware=the physically impossible.
2. **Law 1 — relocation saves nothing** (schemas ride in every call); only deleting a duplicate
   saves tokens. **Law 2 — one fact, one place**, owner chosen by type.
3. **Subtract before you relocate** (Step 0b): leaner prompts measured +10–15% quality and 41–66%
   fewer tokens; a rule re-enters only with a named failing case (rule→case provenance). Length:
   4.1-mini era ≈1.5k instruction tokens, **luna ≈1k for the same invariants**.
4. **Identity, not prohibition** — write who the agent is; luna derives the don'ts.
6. **One worked example per dangerous flow; zero deliberate repetition on luna** — bookends are
   "waste or worse" (OAP "Judgment calls"). Quoting user inputs is safe; quoting model outputs
   primes them (Step 6b).
7. **Docstrings say WHEN** ("Use when…" + cross-tool disambiguation); **field descriptions say WHAT
   value**, plus "if missing or ambiguous, ask — never guess" (Step 3, LPD "Where Instructions
   Belong"). A prompt full of "use tool X when Y" is a tool manual, not a policy document.
8. **Tool results ROUTE on failure** ("already paused — use extend_pause instead"), stay fact-only
   and neutral, and prefer an actionable STATUS over a validator raise (Step 4).
9. **Injected context: semantic over raw** — `Is paused: True` forces inference; the rendered
   meaning *is* the answer (Step 5).
10. **A stuck behaviour is a placement or priming bug, not a wording bug**; never write a third
    prohibition for the same behaviour (OAP Non-negotiables).
11. **Authorisation lives in code, keyed on tool identity**; a model-set `confirmed=true` is a
    *request*, verified against an artifact the tool emitted (Step 2b; arXiv 2512.00332: models
    comply with an asserted-but-never-granted authorisation ~36% of the time).

## 4. Ledgerline: lines to cut (luna does it anyway, or another surface owns it)

| # | Line in `prompts/v1.md` | Why | Cite | Size |
|---|---|---|---|---|
| C1 | "If income may not come, set certainty uncertain. Over a range give the earliest day_of_month, the latest latest_day_of_month." | Verbatim duplicate of the `certainty` and `latest_day_of_month` field descriptions in `handlers.py`. Pure REMOVE-SCHEMA | OAP Step 2, Law 2 | S — `prompts/v1.md` |
| C2 | "upsert_item for every fact, even partial; remove_item when it ends." | The docstring already says "Call this the moment the person states or changes anything… even when you only have part of it" | OAP Step 2 REMOVE-SCHEMA | S — `prompts/v1.md` |
| C3 | "…call mark_unknown and **never ask again**" | `phrases.PARKED` = "parked, do not ask again: " already states it as a fact, per turn | OAP Step 2 REMOVE-ALERT | S — `prompts/v1.md` |
| C4 | "Never claim an action is done, or mention cards or the system." | DONE-gating held with zero lines; "cards"/"system" are nouns the model never sees in a result, so naming them is pure priming | Step 0b; Step 6b | S — `prompts/v1.md` |
| C5 | "A yes is understanding: record_understanding, confirmed true." | Acceptance-in-any-shape is luna's strongest measured default (pass^5); the `confirmed` field description already defines true vs false | V0 K2; LR `gratitude_yes` | S — `prompts/v1.md` |
| C6 | "Never add two amounts, even two balances: one call each" | Two balances are added **by code** (`handlers.py` `ctx.balance_total`), so the rule is both unenforceable-by-model and contradicted | OAP Step 2 REMOVE-CODE | S — `prompts/v1.md` |
| C7 | "If a value differs from one already recorded and they did not call it a correction, ask which is right" | Exact twin of `phrases.CONFIRM_CHANGE`, which rides the result line. Correction-vs-contradiction is the luna default (V0 K7) | Law 2; Step 0b | M — `prompts/v1.md`; gate on `changed_value_acknowledged` ≥95% at 5x (cut-brief Acceptance) |
| C8 | "Never ask them to repeat it back." | Quotes the unwanted output; state the wanted one ("ask once, in your own words") | OAP Step 6b | S — `prompts/v1.md` |

Net: `# Hard rules` collapses from 3 prohibitions to ~1 identity sentence; `# Behaviour` loses 3 of
6 bullets. Measure with tiktoken per surface, never estimate (OAP Non-negotiables).

## 5. Lines to add or reword

- **A1 (S, `prompts/v1.md`) — register invariance, one line.** Missing entirely, and it is the named
  luna failure category on a call where people are frightened about money: "Match their words and
  pace, never their register: the same calm coach whether they joke, swear or panic." (Step 0b.)
- **A2 (S, `prompts/v1.md`) — natural close**, the one line v0 earned: "End with a question they can
  answer any way they like; never name the word you want back." (V0 Finding A1.)
- **A3 (M, `prompts/v1.md`) — turn the Hard rules into identity.** Replace "never suggest new
  borrowing or a settlement / never say approved, guaranteed, eligible" with "You work only with
  money they already have and bills they already owe; every action you name comes from a plan
  result." Restore a negative only against a named failing case (Step 0b provenance).
- **A4 (M, `prompts/v1.md`) — keep untouched:** "no markdown", "one question a turn", "say rupees,
  not a symbol", "never read a date as digits", "if a figure is not in a result, do not say it".
  OAP Step 2 survivors (never-invent-values, voice rules code cannot carry), and markdown has a
  failing case in every V0 transcript.

## 6. Tool docstring / schema changes (`ledgerline/agent/tools/handlers.py`)

- **T1 (S) — `mark_unknown.field`.** The code comment admits "the model invents field names here
  more than anywhere else"; per Step 3 the fix is the field description, not the prompt:
  "Copy a field id exactly as a result printed it on a `missing:` or `blocked:` line, or
  `opening_balance`. Never compose one; if none matches, ask the person instead."
- **T2 (S) — `finalize_plan` refusal should route** (Step 4: a dead end self-corrects in one hop):
  "blocked: opening balance — ask for it, then call finalize_plan again", not bare `blocked:`.
- **T3 (S) — `end_call.reason`** is stored for replay and never used: schema tokens every call, plus
  an invitation to narrate. Drop it, or make it a one-word enum.
- **T4 (M) — `record_understanding.confirmed` is a model-set verdict flag** (Step 2b test 2). Code
  does verify an artifact (`plan_final`, `last_plan`) — more than most — but not that the question
  was asked this turn. Accept and document, or gate on `PLAN_FINAL` being the previous result.
- **T5 (S) — cross-tool disambiguation**, Step 3's strongest placement against a wrong tool pick:
  `remove_item` "NEVER use to correct a figure — upsert_item overwrites"; `mark_unknown` "NEVER use
  for a figure you merely find implausible".

## 7. Result-string shape (`ledgerline/agent/tools/describe.py`, `phrases.py`)

- **R1 (S) — `missing:` is appended to the plan-final and explain-again results**: `told(None, plan,
  actions=True)` still runs `_missing_line`, so the turn explaining the plan ends with a gathering
  prompt. Suppress `missing:` when `actions=True` (Step 5 "hunt duplication").
- **R2 (M) — semantic over raw for the blocked/parked pair.** Two lines (`blocked: opening balance`,
  `parked, do not ask again: opening balance`) leave the consequence to inference. Render the
  meaning: "blocked: opening balance — they declined it, so the plan stays provisional; don't
  ask again." (Step 5.)
- **R3 (M) — tense and state belong in the string.** `provisional: <items>` does not say what
  provisional *does* to the figures, and the model relays its tools' framing verbatim (Step 0b).
- **R4 (keep, with a note) — the instruction-inside-a-fact-line** (`CONFIRM_CHANGE`, `READ_BACK`,
  `UNDERSTOOD`, `GOODBYE`). OAP Step 4 wants guards fact-only, but `phrases.py` records that rules
  in results held 100% where prompt-only rules sat at 0–80%; that local evidence wins — luna follows
  result-carried instructions. So delete the **prompt** twin (C7), not the result one, and keep "If
  a result tells you what to say, do it next" — it licenses the whole mechanism.
- **R5 (S) — one instruction per result.** `_change_lines` caps at one via `asked`; confirm
  `UNDERSTOOD`+`GOODBYE` cannot both land in a turn, or "one goodbye" is fighting itself.

## 8. What in Ledgerline still constrains what luna handles inherently

- **`turn_block` re-states what results already carry.** `Recorded: N incomes…`, `Still missing: …`
  and `Phase: …` are injected every turn while `describe()` prints `missing:` and the plan status in
  the same turn's result — the task-briefing-rendered-twice bug of OAP Step 5, with "ask about
  missing fields in the given order" now anchored to two lists. **M — `agent/prompt.py`:** keep one
  (the turn block survives a turn with no tool call), drop the other. Not both.
- **The prompt teaches the result format** ("Results are notes to you… `missing:` what to ask next,
  `blocked:` the blocker, `parked` never ask again"). Once R2 lands the strings are self-describing
  and this legend is the next thing to delete (Law 2, Step 5).
- **`reasoning_effort="none"` is the largest live constraint on luna's inherent judgement** — the
  cut-brief hands the model correction-vs-contradiction and implausibility detection, exactly the
  reasoning-shaped calls. Before cutting C7, run the 5x5 matrix at effort none *and* low and compare
  `changed_value_acknowledged`; if none is worse, that prompt line is paying for the effort setting.
- **No rule→case provenance file exists**, which OAP Step 0b requires of every surviving rule.
  **S — `docs/process/`:** one table, rule → scenario id in `run_suite.py`, written as the cuts land.
