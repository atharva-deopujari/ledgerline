# Ledgerline evaluation report — before and after the 12–13 September changes

Scope: the voice finance planner as it behaved on the evening of 12 September 2026, and as it
behaves after the prompt rewrite, the result-string rework, the pipeline turn-completion change,
the domain cut and the repairs to the evaluation instruments themselves.

Everything here is reproducible from files in this repository: the scenario definitions in
`evals/scenarios/`, the deterministic checks in `evals/checks.py`, and 283 saved harness
transcripts plus 26 saved live-call recordings in `evals/runs/`. Where a number in this report
differs from the number written down at the time, both are given and the difference is explained.

---

## 1. What is being evaluated, and why

### 1.1 The product

Ledgerline is a voice agent that runs one 30-minute-of-someone's-life conversation: a person on a
phone call says what money they have, what is coming in, and what is going out over the next 30
days. At the end the agent explains a plan — the two most important things to do, with the
consequence of not doing each — and hangs up. The audience is people who are short of money and
frightened of it, so the product's promises are narrow and negative: it never proposes new
borrowing, never says anything is approved or guaranteed, and never proposes skipping a payment
without naming what happens.

The system has three layers relevant here:

| Layer | Owns | Files |
|---|---|---|
| Domain | Money, dates, priority, what is missing, what blocks the plan | `ledgerline/domain/` |
| Agent | The tools, the system prompt, the strings tool results return | `ledgerline/agent/` |
| Voice | STT, turn completion, the LLM service, TTS, call lifecycle | `ledgerline/voice/` |

### 1.2 The one hard rule

**The model never computes. Every number the agent speaks must trace to a tool result or to
something the person said.**

This is not a style preference. The agent is talking to somebody about whether their rent will
clear, and a figure the model derived by subtracting two other figures is a figure nobody checked.
The rule is enforced in three places at once: the prompt says "if a figure is not in a result, do
not say it"; the tool results carry every figure the model is allowed to speak; and
`numbers_traceable` in `evals/checks.py` fails any run in which the assistant speaks a figure of
100 or more that came from neither a tool result nor a recent user utterance.

The rule has a second half that is easy to miss and hard to implement: **retirement**. Once the
person corrects their rent from 11,000 to 12,000, the losing figure has to stop being sayable.
Without retirement the spoken call can contradict the card on screen beside it and still pass.

### 1.3 What a "run" and a "pass rate" are here

A **run** is one complete simulated call: a scenario's persona talks to the real system prompt
through the real tool handlers over the real model, text only, until the call ends or the turn
budget runs out. `evals/harness.py` drives it; there is no audio and no Pipecat pipeline, but the
prompt, the tool schemas and the handler bodies are exactly the ones the voice bot runs, so a
behaviour observed here is a real behaviour of the agent layer.

A **pass rate for a check** is *the share of runs that were entirely clean of that check*, not the
share of turns. This is deliberate and it is the single most important measurement decision in the
suite:

> Three broken turns in one call is one bad call, and counting them separately hides a scenario
> that fails every time. — `evals/run_suite.py`

A run that raises an exception counts as breaking **every** check: a call that did not happen is
not a call that passed (`RunResult.broke`).

### 1.4 Why the pooled rate is the gate, not the per-scenario cell

The suite runs 6 scenarios × 5 runs. A per-scenario cell over 5 runs can only take the values 0,
20, 40, 60, 80 or 100. Applying a 95% bar to such a cell therefore silently means "never once in
five" — a far stricter rule than the one intended, and one that would make the gate hostage to a
single unlucky sample in a single persona.

So the exit code comes from `gate_failures()`, which pools all 30 runs per check; `below_threshold()`
computes the per-scenario cells too, and they are printed under the table as a watch list. Pooled
over 30, a 95% bar means what it says: at most one bad call in twenty.

This has a cost, stated here so it is not discovered later: pooling hides a rule that fails
*systematically in one persona* behind four personas that never trigger it. That is exactly what
happened with `amounts_repeated` and `one_word_answers` (F6 below), and the watch list is what
surfaced it. The watch list is not decorative.

---

## 2. The evaluation apparatus

### 2.1 The harness — `evals/harness.py`

A plain OpenAI Responses loop, 256 lines. Per turn it calls the model with
`prompt_mod.system_instruction(state, "v1")`, executes any tool calls the model asks for against
the real handlers bound to a real `FinancialState`, and appends the results. Up to
`MAX_TOOL_ROUNDS = 4` tool rounds per turn. `reasoning={"effort": "none"}`, matching the voice
pipeline.

Three details matter for reading the results:

- **Tool schemas are derived the same way the bot derives them.** `to_openai_tools` builds each
  schema through Pipecat's `DirectFunctionWrapper(fn).to_function_schema()`, so there is one source
  of truth for the harness and the live bot.
- **`event_order`** records what the model emitted, in order, across every round of the turn
  (`message`, `function_call`). This is the evidence `silent_before_acting` reads; without it the
  turn text is a single concatenated string and speaking-before-acting is invisible. That
  invisibility is precisely why the defect reached a live call (§3).
- **Only `end_call` ends a call.** Agreement is not the end: the model still owes a goodbye.
  `GOODBYE_GRACE_TURNS = 2` is how long the harness waits after `understood` before giving up on
  the farewell — which is how a missing goodbye becomes a measured failure rather than a silent
  truncation.

`today` is pinned to 2026-09-11 so date arithmetic is deterministic across runs.

### 2.2 The simulated user — `evals/sim_user.py`

A persona prompt holding hidden facts (balance, incomes, debts, essentials, optionals, free-text
notes), instructed to answer one thing at a time, never to volunteer the list, never to invent a
number not in the facts, and to say goodbye back when the coach says goodbye. It runs on the same
model at `effort="none"`.

Scenario `scripted_behaviours` override the persona on named turns. A scripted `say` may be a
**list**, and that is the single most important feature of this harness:

```python
def _utterances(said: str | list[str]) -> list[str]:
    """Voice does not wait for a full sentence: VAD cuts on every pause, so "I have" /
    "20,000 in cash and" / "20,000 in bank balance." reached the model as three consecutive
    user messages with no reply between them."""
```

Each element becomes its own user message with no assistant reply between them. A strict
alternate-turns loop cannot reproduce that shape at all, and that shape is what broke the live
call. Fragment support is the reason the simulation is worth running.

### 2.3 The deterministic checks — `evals/checks.py`

Fourteen checks gate a run. One paragraph each.

**`numbers_traceable`** — every figure of 100 or more the assistant speaks must be in
`_sources_up_to(turns, i)`: the union of every number the person has said, every number in a tool
result, and every number in a tool call's arguments — minus retirements, minus laundering. Failure
looks like `not in any tool result: [13000]` on a turn where the model subtracted two figures it
was given and read the answer out.

**`changed_value_acknowledged`** — when a tool result reports a value moving (`rent: 12,000 ->
14,000`), the same turn must either name the new value out loud or ask a settling question that
names the item ("which", "right", "correct", "sure", "or is it", "did you mean"). Failure is
silence: the card now says 14,000, the person still believes 12,000, and nobody said anything. This
is the rule that replaced the deleted conflict machinery.

**`implausible_amount_confirmed`** — an `upsert_item` recording an amount below a per-kind floor
(`income` 500, `essential` 200, `debt` 200) must be queried in the same turn by a question naming
the item. Naming the value is deliberately *not* enough: saying "your rent is twelve rupees" out
loud **is** the failure. No floor on `optional` (a 40-rupee subscription is real) or `balance` (a
person with 40 rupees is exactly who this call is for). Failure looks like `rent 12`.

**`actions_match_plan`** — added 13 September, §10.5. Every action the assistant proposes in a
turn that explains a final plan must be an action the engine proposed. It reads only sentences
carrying a proposal verb — one family per `ActionType`: defer, cut, pay only part, ask the lender
— and asks whether the item named in one appears in the `finalize_plan` result. Deliberately not
"keep", "set aside" or a bare "pay": telling somebody to have the rent ready on the eighteenth
describes the plan's own timeline. A sentence naming any item the plan does contain is
authorised, so an explanation that also mentions the salary in passing is not punished. Failure
looks like `phone emi: your top action is to pay the phone emi of two thousand rupees` in a run
whose plan had no actions at all.

**`one_question_per_turn`** — more than one `?` in an assistant turn. Failure is the live call's
four-question turn.

**`banned_phrases`** — proposing new money, promising an outcome, or claiming to have acted.
Pattern list plus a `_loose_credit` predicate: the word "credit" not followed by bureau / report /
card / score / record / history / file is an offer of credit. Hyphens are flattened first.

**`no_markdown`** — any of `* # ` | _` or a leading `- `/`+ ` in spoken text. Markdown leaking into
speech is a named default failure of this model family.

**`amounts_repeated`** — every amount an `upsert_item` records is spoken near the call that records
it (window: previous assistant turn through the next two). The expected figure is what the result's
**first line** reports, not what the arguments carried — a call that re-sends the amount while
recording a *date* gets back `recorded salary date 1 Oct`, and demanding the figure would be
demanding speech no result offered.

**`no_iso_dates`** — `2026-10-10` in spoken text. TTS reads it one digit at a time; the per-turn
prompt block is where the model picks the habit up.

**`silent_before_acting`** — `message` appearing in `event_order` before the first `function_call`.
A turn whose only call is `end_call` is exempt and must be: its result is the instruction to say
goodbye, so a model that never speaks before a tool could never say goodbye. A turn that also
records something is judged normally.

**`no_repeated_sentence`** — the same sentence twice in one assistant turn. This is what doubled
speech sounds like from the other end of the line.

**`no_question_after_unknown`** — never ask again about a field just parked with `mark_unknown`.
Compares the *attribute*: parking the rent amount does not park the rent, so "when is it due?" is
still a fair question. Only question clauses count, split at the semicolon.

**`one_goodbye_with_the_end_call`** — exactly one farewell **sentence**, in the same turn as
`end_call`. Three distinct failures: `end_call with no goodbye` (the line just drops),
`goodbye without end_call` (a farewell, then a gap), and `2 farewells` ("Goodbye.Goodbye.").

`ADVISORY` is currently empty: nothing is reported-but-not-gating.

### 2.4 The provenance model — `evals/provenance.py`

`_sources_up_to(turns, index)` builds the allowed set by walking every turn up to and including the
one being judged:

1. **User turns** contribute every number in them, permanently.
2. **Tool results** are trusted — the engine computed them, and nobody says a closing balance out
   loud unprompted.
3. **Tool arguments are not trusted** for the three recording tools (`upsert_item`, `remove_item`,
   `mark_unknown`). An invented amount would otherwise launder itself in two steps: in as an
   argument, out inside the result string, and from there authorised. So any argument number the
   person did not say in the current or previous utterance (`RECENT_USER_TURNS = 2`) is struck from
   that call's result as well as from its arguments.
4. **Retirement**: `_supersede` records this call's amount for its item and returns the figure it
   replaced. A superseded figure is removed from the allowed set **from the turn after** the one
   that replaced it — the turn making the change may still name both, because "not eleven thousand
   then, twelve thousand" is how a person hears that a correction landed.
5. **Re-authorisation**: if the person later says the retired figure again, that utterance puts it
   back.

**Identity** has to match the domain's or retirement silently does nothing. `_item_key` normalises
through the domain's own `normalise_name`; `_same_item` mirrors the domain's possessive rule via
the exported `possessive_of`, so "rent" and "my rent" are one item while "my loan" and "his loan"
are two people's debts; `_stored_key` tries the exact key first and falls back to the possessive
match **only when exactly one recorded item matches** — an ambiguous bare name retires nothing,
because the domain creates a third item there rather than guessing, and the checker must not retire
a figure the domain kept.

One narrow licence exists, `_offered_readings`: in a turn whose own result carried
`phrases.CONFIRM_AMOUNT`, a figure inside a **question** is sayable. The reason is in §5.5.

### 2.5 The number-word parser — `evals/spoken_numbers.py`

`numbers_in(text)` returns every number in a string across three notations: digits with separators,
shorthand (`12k`, `1.5 lakh`, `2 crore`), and words. ISO dates are stripped first — an ISO date is
one token, not three numbers.

The word pass is one left-to-right accumulation with two rules that matter:

- **Scale ordering.** A scale at or above the one already used **starts a new amount**: "forty-five
  thousand and twelve thousand" is two figures, not 57,000. A smaller scale continues the current
  one: "one thousand and two hundred" is 1,200. Folding same-or-larger scales together would hand
  the assistant a sum nobody said — the parser would invent the very thing it exists to detect.
- **Clause boundaries end an amount.** `. , ; : ! ?` and newline close the accumulator. Without
  this the pass ran straight through the full stop in "Day thirty. Thirty-eight thousand rupees."
  and reported **68,000**. See §6.4: this bug both manufactured violations and masked real ones.

`TRACE_FLOOR = 100`: amounts smaller than this are days of the month or counts, not money, and are
ignored when tracing.

### 2.6 The six scenarios

| Scenario | What it forces | Persona |
|---|---|---|
| `fragmented_balance` | "I have" / "20,000 in cash and" / "20,000 in bank balance." as three consecutive user turns, then the rent the same way | Meera, thinks out loud and pauses mid-sentence |
| `one_word_answers` | "Nothing." to "what is your next income or expense", then "September." where a day was asked for, then "Nothing." and "Yes." | Sanjay, cab driver, single words, dislikes long calls |
| `garbage_opener` | First utterance "Your WhatsApp." — STT noise, not a sentence | Farah, polite, distracted at first |
| `correction_and_conflict` | An explicit correction ("actually the rent is fourteen thousand, not twelve"), then a *second* figure for an already-recorded item with no correction language, then "I do not know" when asked which is right | Deepak, changes his mind while talking |
| `estimated_income_happy_path` | Income as "around forty thousand, nothing is confirmed" → certainty estimated, through plan, agreement, one goodbye and `end_call` | Anita, freelance, gives round figures |
| `stt_implausible_amount` | STT drops the thousand twice: "My rent is 12." and "Salary forty-five."; the persona corrects **only when asked** | Farida, speaks quickly and trails off |

Every one of the first five was modelled on a defect heard on the live call of §3, not on a tidy
transcript. `stt_implausible_amount` was commissioned later, on 12 September, to build a case for a
prompt rule that had none (`docs/process/prompt-provenance.md`, "Commissioned 2026-09-12").

Four older scenarios remain in `evals/scenarios/` (`comfortable_surplus`, `timing_shortfall`,
`timing_emi_before_salary`, `structural_shortfall_correction`). They are engine-outcome fixtures,
not speech fixtures; `--all` runs them.

### 2.7 Cost

Measured over the 283 saved harness transcripts that carry usage data, at the posted
`gpt-5.6-luna` rate of $0.20 per million input and $1.20 per million output tokens
(`.env.example`):

| | Input tokens | Output tokens | Cost |
|---|---|---|---|
| All 283 saved runs | 19,376,957 | 354,788 | **$4.30** |
| Per run, mean | 68,470 | 1,254 | **$0.015** |
| One 30-run matrix (6 × 5) | ~2.05M | ~38k | **~$0.46** |
| `stt_implausible_amount` × 5 (measured) | 443,715 | 7,276 | **$0.10**, 91 s |

Most input is cached prompt. The whole evaluation programme documented in this report cost under
five dollars of model time, which is the argument for running the matrix before every live call
rather than after.

---

## 3. The motivating evidence: the live call of 12 September, 19:40 IST

`evals/runs/voice-2ac2a01f28e9-20260912-141347.json` (stamped UTC; 19:43 IST). 25 turns,
`plan_final: true`, `ended_by: "bot"`, `llm_warnings: {"previous_response_not_found": 1,
"drain_failed": 1}`. The owner's word for it was "disastrous".

Read as a person heard it, four defect classes appear, and every one of them is a design decision
rather than a model failure.

### 3.1 Every tool turn produced two spoken segments, each with its own question

The prompt at the time said to acknowledge first, then act. The pipeline therefore had two chances
to speak per tool turn, and took both.

```text
[turn 5] assistant:
  "Okay, twenty thousand rupees in cash and twenty thousand rupees in your bank balance.
   What else would you like to tell me?What’s your next income or expense?"
  → upsert_item {kind: balance, name: cash, amount: 20000}        = "created opening balance. in 0, out 0."
  → upsert_item {kind: balance, name: bank balance, amount: 20000} = "unchanged opening balance. in 0, out 0."
```

```text
[turn 8] assistant:
  "Okay, your rent is eleven thousand rupees. Is it due on a particular day each month?What day is the rent due?"
```

```text
[turn 14] assistant:
  "Okay, your rent is due on the eighteenth of September. What’s the next income or expense?What’s the next income or expense?"
```

Turn 14 is the literal doubled question: the same sentence twice, no separator, because the segment
spoken before the tool call and the segment spoken after the result were both generated and both
sent to TTS.

### 3.2 The four-question turn

```text
[turn 16] user: "Nothing."
[turn 16] assistant:
  "Okay, there’s no other income or expense to record. What’s your monthly income?
   You said there’s nothing else to add. Do you have any income during the next 30 days?
   What’s the next thing you’d like to tell me?
   Are you still there? There’s no rush."
  → mark_unknown {field: "monthly_income", reason: "user_does_not_know"}
      = "'' is not a valid ItemKind. Fix that argument and call the tool again."
  → mark_unknown {field: "income", reason: "user_does_not_know"}
      = "created income. in 0, out 11,000. provisional."
```

Four questions in one breath, and the third of them — "What's your monthly income?" — is asked
*immediately after* parking the income as unknown. The last sentence is the idle nudge, which was
firing at 10 seconds and landed inside the same turn. This one turn seeded three separate checks:
`one_question_per_turn`, `no_question_after_unknown`, and the `_parked_subject` handling of a bare
field id like `monthly_income`.

### 3.3 The fragment sequence

```text
[turn 2] user: "I have"
[turn 3] user: "20,000 in cash and"
[turn 4] user: "20,000 in bank balance."
```

```text
[turn  9] user: "It is"
[turn 10] user: "on"
[turn 11] user: "September."
[turn 12] assistant: "Which day of September is the rent due?"
[turn 13] user: "September 18."
```

One intended sentence arrived as three user turns. Each fragment ended a user turn, each
interrupted the bot mid-sentence, and each interruption broke the Responses API chain.

### 3.4 The 7.5-second retry

```json
[turn 5] "timings": {"vad_stop_at": "...14:11:01Z", "first_token": 7.176, "first_audio": 7.496}
```

7.5 seconds of dead air after the person stopped speaking, against a median of 1.3–2.4 s on the
other turns in the same call. Cause: the interruption invalidated `previous_response_id`, the
Responses API returned `previous_response_not_found`, and the retry paid for the whole call again.
The recording carries `previous_response_not_found: 1` for this call; an earlier 24-turn call
produced five.

### 3.5 The double goodbye

```text
[turn 22] assistant:
  "The second action is to avoid committing the remaining nine thousand rupees until income is
   known... Does that action and consequence make sense?Thanks for speaking with me. Take care."
  → record_understanding {confirmed: true} = "understood. in 0, out 11,000. provisional."

[turn 23] user: "Thank you."

[turn 24] assistant: "You’re welcome. Goodbye.Goodbye."
  → end_call {reason: "user thanked and call is complete"} = "say one short goodbye sentence, then stop"
```

Turn 22 is a farewell with no `end_call` — the call kept running. Turn 24 is two farewells in one
turn, because the model said goodbye and then the tool result told it to say goodbye. Both halves
of `one_goodbye_with_the_end_call` are in this one exchange.

### 3.6 What the text harness had said beforehand

Nothing. The acknowledge-then-act rule had been added after the *first* live call as a latency win,
and a paid harness run confirmed the model honoured it. The harness concatenated a turn's spoken
segments into one string, so two questions in two segments read as one string containing two
question marks — and no check was reading question counts yet. Only a person listening heard it.
This is the origin of `event_order` and of `silent_before_acting`.

---

## 4. The changes

Grouped by surface. The organising principle, decided on the evening of 12 September after the
owner read `ledgerline/domain/models.py`:

> **Code owns correctness, the model owns understanding.**
>
> Code owns what must be **correct**: money, dates, priority, what is missing, what blocks the
> plan, the numbers the bot speaks. The model owns what needs **understanding**: correction vs
> contradiction, implausible amounts, what to ask next and its wording, whether the person has
> understood, when a sentence is finished. Test per component: "if this goes wrong, does the person
> lose money or trust?" Yes: code. No, and it is about language: model.
> — `docs/process/cut-brief.md`

### 4.1 Prompt (`ledgerline/agent/prompts/v1.md`)

| Change | Why |
|---|---|
| **Acknowledge-then-act removed**, replaced by "When you need a tool, call it first and say nothing at all before it. Speak once, after the result." | §3.1 — two spoken segments per tool turn |
| **One goodbye rule**: "say one goodbye and call end_call in the same reply. Never say goodbye twice." | §3.5 |
| **Comprehension question reworded**: "ask once if that and what happens if they skip it make sense. Never ask them to repeat it back." | The earlier design had the person recite the plan back; patronising out loud |
| **Read-back added and later restored to its own line**: "Start every reply with the figure on the result's first line, when it has one, then ask." | F2 — no amount was ever read back |
| **Results legend added**: "Results are notes to you, never words to read out" | F7 — the bot read `missing: electricity amount` aloud verbatim |
| **Ordering rule added**: "Ask about missing fields in the given order, one at a time" | §3.2 — four questions at once |
| **Implausibility rule added**: "If an amount sounds implausible, confirm it once." | The cut deleted the outlier machinery that used to do this |
| **Changed-value rule added**: "If a value differs from one already recorded and they did not call it a correction, ask which is right before moving on." | The cut deleted the conflict machinery |

The prompt is 2,471 characters. The ceiling is enforced against `approx_tokens = len(text) // 4`
("617 tokens") — an estimate, not a tokenizer, and recorded as such in `docs/process/status-B.md`.

### 4.2 Tool results as compact facts, with instructions riding on them

Before the cut, every tool result was a prose sentence: `"created opening balance. in 0, out 0."`
After it, results are facts, one per line, every number straight from the domain:

```text
recorded opening balance 20,000; say this back, then ask
blocked: income
```

```text
rent: 12,000 -> 14,000; confirm which is right before moving on
blocked: income
```

```text
recorded rent 12; rent looks small, confirm it before moving on
blocked: income
```

```text
call ending, say one short goodbye now and nothing more
```

The four instruction constants live in `ledgerline/agent/tools/phrases.py`: `READ_BACK`,
`CONFIRM_CHANGE`, `CONFIRM_AMOUNT`, `GOODBYE`/`UNDERSTOOD`. **At most one instruction rides on a
result**, capped by the `asked` flag in `describe._change_lines`, because a turn holds one question.
On an implausible amount, `CONFIRM_AMOUNT` **replaces** `READ_BACK` rather than joining it: "say it
back" and "check it" cannot both be the single question.

`describe()` also stopped reporting how code files an item — `spread`, `survival`, `flexible` and
`certainty` are classification flags, not anything the person said, and a create was reading
"recorded rent 11,000 due 18 Sep spread dated survival survival" — and stopped appending `missing:`
to a result that is explaining a finalised plan.

### 4.3 Pipeline (`ledgerline/voice/`)

| Change | Detail |
|---|---|
| **Filler acknowledgement** | `voice/filler.py` speaks one rotating word ("Okay.", "Got it.", "Noted.") on the **first tool call of a turn**, so first audio stays fast now that the model is silent before acting. Never for `end_call` — the model owns the goodbye |
| **LLM turn completion with hints** | Our own word-list gate (`voice/turn_gate.py`, `voice/turn_completeness.py`) is **deleted**. The chain is Pipecat's documented pairing: `deferred(TurnAnalyzerUserTurnStopStrategy(...))` + `LLMTurnCompletionUserTurnStopStrategy(config=...)`, with `TURN_COMPLETION_HINTS` appended to `UserTurnCompletionConfig().completion_instructions` |
| **Chat Completions as default** | `settings.llm_api`. Responses loses its chain on every interruption; that is the 7.5 s of §3.4 |
| **Idle nudge 25 s** | Was 10 s, and fired into the middle of the four-question turn |
| **Compose volume for `evals/runs`** | The live recording of §3 was trapped inside the container and had to be copied out by hand |

The turn-completion change is the one with the best-documented reasoning. Three fixes were tried
and were wrong:

1. Raising Smart Turn's `stop_secs` to 3.0 s — no effect. `SmartTurnParams.stop_secs` only bounds an
   INCOMPLETE verdict, and Smart Turn classifies `"I have"` as COMPLETE.
2. A linguistic gate in Pipecat's deferred slot — `looks_complete("I have")` is `False` and unit
   tested, and it still made no difference live.
3. Filtering the LLM's own completion frames so ours would win — works as designed, and the live run
   was **worse**: the mixin's marker text leaked into speech (`"0 rupees. How much money do you have
   right now..."`). Reverted in full.

A frame-level trace of one call found the actual cause:

```text
UserTurnInferenceCompletedFrame from=OpenAILLMService#0   x4
UserTurnInferenceCompletedFrame from=TurnCompletionGate#0 x1
```

`ExternalUserTurnCompletionStopStrategy` finalises on **any** frame of that type, so the model was
ending four turns to our gate's one. `"I have"` never got a gate release at all. Two judges of the
same question; the fix was to configure the model's judge rather than add ours. Result on the
hesitant script: **3 bot responses for 3 intended utterances**, against 4–5 with our gate at 2.5 s
and 5 at 4.0 s.

### 4.4 The domain cut

Deleted from `ledgerline/domain/models.py` and `state/`:

- `_Item.confirmed`, `_Item.source_turn`, `confirm_untouched()`, the conflict-window constant
- the `Conflict` model; `FinancialState.conflicts`, `.outliers`, `.opening_balance_turn`,
  `.opening_balance_confirmed`
- the `Understanding` model and its fuzzy restatement matcher
- `OutcomeStatus.CONFLICT`/`.RESOLVED`; `UnknownReason.STRUCTURAL`/`.USER_DECLINED`;
  `Unknown.question`; `Phase.CONFIRM`; `Readiness.score`; `PlanResult.questions` (prose)
- `state.resolve_conflict`, `_record_outlier`, `outlier_question`, `question_for`, `income_answer`,
  `upsert(is_correction=...)`, and the `resolve_conflict` tool

Added: `FinancialState.understood: bool`; a two-value `UnknownReason` (`UNKNOWN` |
`NOT_APPLICABLE`); `Outcome.changes: dict[str, tuple[str, str]]` so `upsert` **always overwrites**
and reports what moved; `PlanResult.blockers: list[str]`; `label_for(field)` in place of
`question_for(field)` — a label, not a sentence.

Unchanged: the engine, the policy, the cards, `Decimal` throughout, and number traceability. The
justification is arithmetic: roughly **forty of fifty-five** accumulated review findings lived in
the deleted machinery, and almost none in the arithmetic. `state/` went from about 1,000 lines to
560 (the 400-line target was not met; what remains is field mapping and date arithmetic).
`ledgerline/agent/tools/` went 867 → 878 lines — not smaller, because `resolve_conflict`, the
restatement matcher and the prose assembly went (~150 lines) and field-id validation, flag handling
and the three result instructions came in.

### 4.5 The evaluation instruments themselves

Five of the changes in this period were to the measuring apparatus, not the product. They are listed
here because a report that mixes them in with product fixes is lying about what improved.

| # | Defect in the instrument | Effect | Fix |
|---|---|---|---|
| I1 | **Retirement re-authorised the figure it had just retired.** `allowed -= superseded` ran *before* `allowed \|= from_result \| from_args` in the same iteration, and the post-cut change result names **both** figures (`rent: 11,000 -> 12,000`) | The losing figure came straight back in from the result that retired it and stayed sayable for the rest of the call. Replayed: the assistant says "your rent of 11,000 rupees" two turns after the correction and `numbers_traceable` returns **no violation** | Retire *after* the union (`evals/provenance.py`) |
| I2 | **Item identity did not match the domain's.** `_item_key` used `normalise_name` alone, so `essential:rent` and `essential:my rent` were two subjects where the domain's `_find` sees one | A correction spoken as "my rent" retired nothing | Mirror the domain through the exported `possessive_of`: exact key first, possessive fallback second, nothing retired on an ambiguous bare name |
| I3 | **The word parser ran through full stops.** "Day thirty. Thirty-eight thousand rupees." parsed as **68,000** | The 38,000 the person really said counted as never said; since a recording tool's arguments are struck from its result when the person did not say them, the figure vanished from the trusted result too, and the assistant was failed for speaking a number it had been handed. It masks invented figures as easily as it invents violations | Clause boundaries close an amount (`evals/spoken_numbers.py`) |
| I4 | **Concurrent filename collision.** Five copies of a scenario can finish inside one second and overwrite each other's transcript | The evidence for one failing run was lost exactly when it was wanted | `-2`, `-3` … suffixes in `harness.run_scenario`. It earned itself immediately: `stt_implausible_amount-20260912-222027.json` and `-222027-2.json` both survive |
| I5 | **Checks failing correct behaviour** — four separate cases | See §6 | See §6 |

Both provenance defects were invisible to the existing tests for the same reason: the four
retirement fixtures in `tests/agent/test_checks.py` still used **pre-cut result strings**
(`"updated rent. in 45,000, out 12,000."`), which name only the winning figure, where the real
post-cut result names both. The bug was found by replaying a correction through `_sources_up_to`,
not by reading the code.

---

## 5. Results

### 5.1 Every matrix pass, in order

All dates 12 September 2026; times are the wall-clock stamps of the saved transcripts in
`evals/runs/`, which is how each pass was identified.

#### Pre-cut simulation matrix, passes 1–3

| check | pass 1 (5 runs, 19:57) | pass 2 (25 runs, 20:03) | pass 3 (25 runs, 20:14) |
|---|---|---|---|
| numbers_traceable | 80% | 96% | 92% |
| one_question_per_turn | 100% | 100% | 100% |
| banned_phrases | 80% | 84% | 100% |
| no_markdown | 100% | 100% | 100% |
| amounts_repeated | 0% | 16% | 80% |
| no_iso_dates | 100% | 100% | 100% |
| silent_before_acting | 100% | 100% | 100% |
| no_repeated_sentence | 100% | 100% | 100% |
| no_question_after_unknown | 100% | 96% | 84% |
| one_goodbye_with_the_end_call | 20% | 16% | 28% |

The two rules the live call was *about* — `one_question_per_turn` and `no_repeated_sentence` — were
already at 100% before any change in this phase: the prompt rewrite (speak once, after the result)
had closed them before the matrix ever ran. Everything else in this table is what the matrix found
that nobody was looking for.

#### Post-cut matrix, passes 1–3

`changed_value_acknowledged` is new with the cut and has no pre-cut figure: it is the rule that
replaces the conflict machinery, so before the cut there was nothing for it to measure.

| check | pre-cut (25) | cut pass 1 (5, 21:21) | cut pass 2 (25, 21:27) | cut pass 3 (25, 21:35) |
|---|---|---|---|---|
| numbers_traceable | 92% | 100% | 92% | **100%** |
| changed_value_acknowledged | — | 100% | 100% | **100%** |
| one_question_per_turn | 100% | 100% | 100% | **100%** |
| banned_phrases | 100% | 100% | 100% | **100%** |
| no_markdown | 100% | 100% | 100% | **100%** |
| amounts_repeated | 80% | 40% | 68% | **96%** |
| no_iso_dates | 100% | 100% | 100% | **100%** |
| silent_before_acting | 100% | 100% | 100% | **100%** |
| no_repeated_sentence | 100% | 100% | 100% | **100%** |
| no_question_after_unknown | 84% | 60% | 92% | **100%** |
| one_goodbye_with_the_end_call | 28% | 100% | 96% | **100%** |

Pass 3 exits 0. 24 of the 25 runs are clean of every rule; the one that is not read back a
supporting figure instead of the amount it had just recorded (`amounts_repeated` 80% in
`correction_and_conflict`) — a watch-list cell, not the gate.

#### Eval-phase matrix, after the provenance repairs and the sixth scenario

30 runs, 6 scenarios × 5. Exit 1.

| check | cut pass 3 (25) | eval pass 1 (30, 21:54) |
|---|---|---|
| numbers_traceable | 100% | 93% |
| changed_value_acknowledged | 100% | 100% |
| implausible_amount_confirmed | — | **77%** |
| one_question_per_turn | 100% | 100% |
| banned_phrases | 100% | 100% |
| no_markdown | 100% | 100% |
| amounts_repeated | 96% | 80% |
| no_iso_dates | 100% | 100% |
| silent_before_acting | 100% | 100% |
| no_repeated_sentence | 100% | 100% |
| no_question_after_unknown | 100% | 100% |
| one_goodbye_with_the_end_call | 100% | 100% |

The three rates that moved are not three regressions: one is a real defect the **repaired** check
can now see (§6.1), one is the new rule measuring exactly the thing it was built to measure (§5.5),
and one was the rule itself being wrong (§6.5).

#### Eval pass 2 — `stt_implausible_amount` only, 5 runs, 22:20

`PYTHONPATH=. uv run python -m evals.run_suite stt_implausible_amount --runs 5`, 443,715 in /
7,276 out tokens, 91 s.

| check | eval pass 1 (this scenario) | pass 2 as run | pass 2 replayed after two check fixes |
|---|---|---|---|
| implausible_amount_confirmed | 0% | **100%** | 100% |
| numbers_traceable | 100% | 40% | **100%** |
| amounts_repeated | 20% | 80% | **100%** |

5 of 5 runs clean of every rule on replay. Replay is not a fresh matrix — it is the same five calls
— but it says the model's behaviour in them breaks nothing, and that both failures were in the
instruments.

### 5.2 Consolidated before/after, one row per check

Computed by **replaying today's `evals/checks.py` over every saved transcript of each pass**. This
is a different measurement from the as-run tables above, and the difference is the point: where the
replayed number is higher than the as-run number, the gap is the instrument that was wrong at the
time.

| check | pre-cut pass 1 (n=5) | pre-cut pass 2 (n=24) | pre-cut pass 3 (n=24) | cut pass 1 (n=5) | cut passes 2–3 (n=48) | eval pass 1 (n=29) | 22:08 matrix (n=29) | eval pass 2 (n=5) |
|---|---|---|---|---|---|---|---|---|
| numbers_traceable | 80% | 95% | 95% | 100% | 97% | 96% | **100%** | **100%** |
| changed_value_acknowledged | 100% | 100% | 100% | 100% | 100% | 100% | **100%** | **100%** |
| implausible_amount_confirmed | 100%¹ | 95%¹ | 91%¹ | 100%¹ | 100%¹ | 79% | **96%** | **100%** |
| one_question_per_turn | 100% | 100% | 100% | 100% | 100% | 100% | **100%** | **100%** |
| banned_phrases | 100% | 100% | 100% | 100% | 100% | 100% | **100%** | **100%** |
| no_markdown | 100% | 100% | 100% | 100% | 100% | 100% | **100%** | **100%** |
| amounts_repeated | 0% | 16% | 79% | 60% | 83% | 100% | **100%** | **100%** |
| no_iso_dates | 100% | 100% | 100% | 100% | 100% | 100% | **100%** | **100%** |
| silent_before_acting | 100% | 100% | 100% | 100% | 100% | 100% | **100%** | **100%** |
| no_repeated_sentence | 100% | 100% | 100% | 100% | 100% | 100% | **100%** | **100%** |
| no_question_after_unknown | 100% | 100% | 100% | 100% | 95% | 100% | **100%** | **100%** |
| one_goodbye_with_the_end_call | 20% | 16% | 37% | 100% | 100% | 100% | **100%** | **100%** |

¹ The scenario that exercises implausibility did not exist yet; these cells are incidental small
amounts recorded in other personas, not a measurement of the behaviour.

Three comparisons are worth reading closely.

- **`banned_phrases`**: as-run 84% on pre-cut pass 2, **100%** on replay. The whole difference is
  the check: `"the credit-card minimum"` was read as an offer of credit because the allowed forms
  were spelled with a space, and `"affect your credit record"` — the model's paraphrase of the
  engine's own "nothing reaches your credit report" — was not in the allowed list. The bot never
  offered anybody credit.
- **`no_question_after_unknown`**: as-run 96% / 84% on pre-cut passes 2 and 3, **100%** on replay.
  Same cause, twice: reading the whole turn instead of only the question clauses, and matching on
  the item instead of the attribute.
- **`one_goodbye_with_the_end_call`**: as-run 28% on pre-cut pass 3, **37%** on replay. Here the
  gap is smaller and in the same direction, from counting farewell *sentences* rather than farewell
  *words* — `"Goodbye, and take care."` had been counted as two goodbyes. The remaining 63% is real.

### 5.3 Per-scenario notes

- **`fragmented_balance`** — cleanly reproduces what VAD did on the live call, and it caught the
  worst arithmetic defect in the programme (F3, §6.2). Its current status is the most serious open
  finding in this report (§6.7): the model no longer invents 40,000, but it now records 20,000 and
  drops the other half of the person's money, and no check sees it.
- **`one_word_answers`** — the hardest scenario for `amounts_repeated`. It failed the read-back in
  **all five** runs of the post-cut matrix, always on the opening balance: the result was two lines,
  `recorded opening balance 6,000` and `blocked: income`, and the model read the second as the
  instruction. Pooled, that was 68%; the watch list is what identified the scenario.
- **`garbage_opener`** — the easiest of the six. "Your WhatsApp." is handled correctly and has been
  since the first pass; it is retained as a regression guard, not as a source of findings.
- **`correction_and_conflict`** — the richest. It carries the only rule the project has with a
  *named failing case that is still failing*: turn 20 of `correction_and_conflict-20260912-215702`
  (§6.1). It is also the scenario that produces the residual `amounts_repeated` cell at 80%.
- **`estimated_income_happy_path`** — the end-to-end guard. It is the scenario that proves the
  goodbye works, and it is where `certainty: uncertain` is exercised.
- **`stt_implausible_amount`** — commissioned to give a prompt rule a case. It immediately produced
  the cleanest single result in the programme: 0% → 100% from one instruction moved out of the
  prompt and into a result string, in five runs out of five.

### 5.4 The same situation, before and after

**The goodbye.**

Before — `fragmented_balance-20260912-195809.json`, turns 26–27. The model says nothing at all; the
line simply drops.

```text
[26] assistant: ''
     → record_understanding {confirmed: true}  = 'understood. in 45,000, out 21,500.'
     → end_call {reason: "plan agreed and understood"} = 'call ended, say nothing more'
[27] user: ''
```

After — `fragmented_balance-20260912-220836.json`, turns 26–27:

```text
[26] assistant: 'Goodbye.'
     → record_understanding {confirmed: true} = 'understood, say one goodbye and call end_call in this reply'
     → end_call {reason: "plan understood"}   = 'call ending, say one short goodbye now and nothing more'
[27] user: 'Goodbye.'
```

The difference is two constants in `phrases.py`. `end_call`'s result used to say "call ended, say
nothing more", which cannot be obeyed at the same time as "say goodbye": the model had nowhere left
to speak.

**The read-back.**

Before — `fragmented_balance-20260912-195809.json`, turn 4. The opening balance is recorded and the
result contains no figure, so the model — correctly, under the never-invent rule — does not say one:

```text
[4] assistant: 'That’s 40,000 rupees available today; what income do you expect between 11 September and 10 October?'
     → upsert_item {kind: balance, amount: 40000} = 'created opening balance. in 0, out 0.'
```

After — `correction_and_conflict-20260912-215702.json`, turn 2:

```text
[2] assistant: 'You have fifteen thousand rupees in your account today. What income do you expect before the tenth of October?'
     → upsert_item {kind: balance, name: "account today", amount: 15000}
        = 'recorded opening balance 15,000; say this back, then ask
           blocked: income'
```

The result now names the figure *and* tells the model what to do with it.

**The changed value.**

After — `correction_and_conflict-20260912-215702.json`. First the explicit correction (turns 5–8),
then the unannounced second figure (turns 11–14). The model treats them differently:

```text
[5] user: 'Actually, the rent is fourteen thousand, not twelve.'
[6] assistant: 'Is your rent fourteen thousand rupees?'
     → upsert_item {kind: essential, name: rent, amount: 14000}
        = 'rent: 12,000 -> 14,000; confirm which is right before moving on
           blocked: income'
[7] user: 'Yes, my rent is fourteen thousand rupees.'
[8] assistant: 'Your rent is fourteen thousand rupees. What income do you expect before the tenth of October?'
```

```text
[11] user: 'The electricity is three thousand.'
[12] assistant: 'Is your electricity bill three thousand rupees?'
     → upsert_item {kind: essential, name: electricity, amount: 3000}
        = 'electricity: 2,000 -> 3,000; confirm which is right before moving on
           blocked: income'
[13] user: 'I do not know.'
[14] assistant: 'You don’t know the electricity amount. What income do you expect before the tenth of October?'
     → mark_unknown {field: "essential:electricity.amount", not_applicable: false}
        = 'not known: electricity amount
           blocked: income'
```

The person does not know which figure is right, the model parks the field, and it never asks again.
Before the cut this whole exchange was a `Conflict` object, a conflict window, a `resolve_conflict`
tool and a code-written question. It is now one line in a result string and a check.

**The implausible amount.**

Before — every one of the five `stt_implausible_amount` runs in eval pass 1, identically. The result
said `recorded rent 12; say this back, then ask`, and the model obediently said it back:

```text
[4] assistant: 'Your rent is twelve rupees. What income will arrive between now and the tenth of October?'
```

After — `stt_implausible_amount-20260912-222049.json`, turns 4 and 8, with `CONFIRM_AMOUNT`
replacing `READ_BACK`:

```text
[3] user: 'My rent is 12.'
[4] assistant: 'You said rent is twelve rupees; is that correct, or did you mean twelve thousand rupees?'
     → upsert_item {kind: essential, name: rent, amount: 12}
        = 'recorded rent 12; rent looks small, confirm it before moving on
           blocked: income'
[5] user: 'Twelve thousand, sorry. Twelve thousand rupees.'
[6] assistant: 'I’ve recorded rent as twelve thousand rupees. What income do you expect during the next thirty days?'
     → upsert_item {kind: essential, name: rent, amount: 12000}
        = 'rent: 12 -> 12,000; confirm which is right before moving on
           blocked: income'
```

```text
[7] user: 'Salary forty-five.'
[8] assistant: 'You said your salary is forty-five rupees; is that correct, or did you mean forty-five thousand rupees?'
     → upsert_item {kind: income, name: salary, amount: 45}
        = 'recorded salary 45; salary looks small, confirm it before moving on
           ...'
```

Five runs out of five, both figures, first time.

### 5.5 The lever that actually moved the numbers

Every rule that gained did so the same way: an instruction moved out of the prompt and into the
**tool result string the model is certainly reading at the moment it has to act**.

| Instruction | Carrier | Before | After |
|---|---|---|---|
| `say one short goodbye now and nothing more` | `phrases.GOODBYE` on `end_call`'s result | 16–28% | 96–100% |
| `say this back, then ask` | `phrases.READ_BACK` on a recording line | 68–80% | 96–100% |
| `confirm which is right before moving on` | `phrases.CONFIRM_CHANGE` on a change line | (nothing existed) | 100% first time |
| `<name> looks small, confirm it before moving on` | `phrases.CONFIRM_AMOUNT`, **replacing** the read-back | 0% | 100% |

Each of these is *also* in the prompt. The prompt alone was worth 40–80%; the prompt plus the result
is worth 96–100%. The fourth instance is the only one that was **predicted in advance** rather than
discovered: `docs/process/prompt-provenance.md` recorded, before the matrix ran, that a first-time
implausible figure is a create and `CONFIRM_CHANGE` only rides a change, so nothing would instruct
the model, "which makes this rule prompt-only, the 0-80% class. If the check misses its gate, the
fix is a result-carried instruction on an implausible CREATED, not prompt wording." It missed its
gate at 77%, the predicted fix was applied, and it went to 100%.

---

## 6. What the evaluations found that the tests did not

`uv run pytest tests/agent` is at 356 passed, 1 deselected; the domain, frontend and end-to-end
suites are green. Every defect below survived all of them.

### 6.1 The model did arithmetic and read the answer out as plan output

`correction_and_conflict-20260912-215702.json`, turn 20. `finalize_plan` returned
`in 0, out 14,000, lowest 1,000 on 10 October / surplus 1,000`:

```text
[20] assistant:
  'The plan leaves out the shop income because it may not arrive; after rent, you’d have one
   thousand rupees, and the electricity amount is still unknown. First, set aside the one thousand
   rupees for essentials until the shop money arrives; if it doesn’t, rent uses the available money
   and leaves a shortfall of thirteen thousand rupees—does that make sense?'
```

Thirteen thousand is in no tool result and no user turn: 14,000 − 1,000, computed by the model and
spoken as plan output, in the one place a wrong figure costs the person money. `numbers_traceable`
reports `not in any tool result: [13000]`.

This is the **named failing case** for the never-invent rule, and it is **not fixed**. It is on
record as an open item in `docs/process/prompt-provenance.md` under "Open failing cases". Note the
dependency: before the retirement repair (I1) this would very likely have passed, because the
retirement half was inert and the invention half never sees a figure the model derived from two it
was given.

### 6.2 The model summed two balances

`fragmented_balance-20260912-195809.json`, turn 4: `"That’s 40,000 rupees available today"` after
three fragments each carrying 20,000. The alternative it chose in other runs was worse — two
`upsert_item` calls, and since the domain keeps one opening balance and ignores its name, the second
silently replaced the first and a person with 40,000 was planned for as if they had 20,000. The fix
was in code: `ToolContext.balance_total` keeps the parts of one turn and returns the sum, which
comes back in the result where the model may read it.

### 6.3 The goodbye and the hang-up could not both happen

Structurally impossible, and no unit test could have found it because both rules were individually
correct: the prompt said never speak before a tool, and `end_call`'s result said "call ended, say
nothing more". Every run ended either in silence or in a farewell followed by a gap. Sixteen to
twenty-eight per cent, over three matrix passes, before anybody understood why.

### 6.4 A silent number-parsing bug that both invented and masked violations

"Day thirty. Thirty-eight thousand rupees." parsed as 68,000 (§4.5, I3). Two consequences, in
opposite directions: the 38,000 the person actually said was treated as never said, so the assistant
was failed for speaking a figure it had been handed; and any real invented sum of the same shape
would have been laundered into the allowed set. Found only by reading the transcripts of a 93% pass.

### 6.5 Four checks that were failing correct behaviour

| Check | What it wrongly failed | Evidence |
|---|---|---|
| `banned_phrases` | `"the credit-card minimum"` (hyphen not flattened) and `"affect your credit record"` (the model's paraphrase of the engine's own "nothing reaches your credit report") | 84% → 100% on replay |
| `one_goodbye_with_the_end_call` | `"Goodbye, and take care."` counted as two goodbyes because it counted farewell *words* | Sentences now; `"You're welcome. Goodbye.Goodbye."` is still correctly two |
| `no_question_after_unknown` | Read the whole turn, so `"I've noted the credit card is outside this window. Anything else?"` counted as asking about the credit card; and matched on the item, so parking the rent *amount* made `"When is your rent due?"` a violation; and a semicolon is not a full stop, so `"the electricity amount is parked as not known; when is your rent due?"` read as one question carrying the word "amount" | 84% → 100% |
| `amounts_repeated` | Demanded the amount back on a call that recorded only a **date** — the result says `recorded salary date 1 Oct`, and the prompt forbids speaking a figure no result offered. Then the first fix was scoped too wide: it read the *whole* result, and the totals line underneath (`in 45,000, out 12,000...`) names the amount anyway | 80% → 100% on the same transcripts |

The same rule also had the opposite defect: `no_question_after_unknown` **never caught the defect it
was written for**. It derived the item name from everything before the dot in the field, so a bare
field like `monthly_income` — exactly what the live call parked before asking "What's your monthly
income?" — produced an empty subject and passed. Both shapes are handled now and a test replays the
live turn.

### 6.6 Two ways to park nothing

`mark_unknown` accepted field ids that named nothing. First `optional_expenses` (shape not
validated), so the model parked a non-field and then asked about optional expenses. After shape
validation landed, `essential:rent.day_of_month` — the *tool's argument name* rather than the
field's attribute — still passed and still parked nothing, and the model asked when the rent was due
a turn later. The attribute must now be one the domain actually has. Both failures were visible only
as a `no_question_after_unknown` violation two turns downstream.

### 6.7 Open, and not yet reflected in any pass rate: the dropped half of the balance

Found while assembling this report, by reading state rather than transcripts.

`fragmented_balance` gives the person 20,000 in cash **and** 20,000 in the bank. Across every saved
run of that scenario:

| Era | `upsert_item(kind=balance)` amounts | Final `opening_balance` |
|---|---|---|
| Pre-cut (20:43–20:49, 6 runs) | `[20000, 20000]` | **40,000** ✓ |
| Transitional (21:21–21:27) | mixed: `[20000, 20000, 40000]`, `[20000]` | 40,000 or 20,000 |
| Post-cut (21:35 onward, 15 runs) | `[20000]` | **20,000** ✗ |

In all fifteen post-cut runs the model makes a **single** `upsert_item` for the cash and never
records the bank balance. `ToolContext.balance_total` still exists and still works; it is simply
never given a second part. The person's plan is then built on half their money.

Every check passes on these runs. `numbers_traceable` is clean because nothing was invented;
`amounts_repeated` is clean because the model read back 20,000 and the result named 20,000;
`changed_value_acknowledged` has no change to see. The most likely mechanism is the read-back
instruction itself: `recorded opening balance 20,000; say this back, then ask` tells the model to
speak and ask after the *first* call, which ends the turn before the second fact is recorded.

This is the sharpest available demonstration of the gap between "the rules pass" and "the plan is
right". The suite has no check that the recorded state matches the persona's hidden facts — every
scenario file carries `expect.plan_final` and `expect.status`, which the suite does not currently
assert — and this defect lives exactly in that gap.

---

## 7. Honest limits

**The text harness cannot hear the pipeline.** It has no Pipecat pipeline, no VAD, no TTS. It
therefore cannot observe the filler word (`voice/filler.py`), the turn-completion judge, barge-in,
interruption recovery, or first-audio latency. Every finding about those comes from the live calls
and the headless spike runs, and none of them is under the 95% gate.

**The harness cannot see what it concatenates.** The original acknowledge-then-act defect was
invisible in text because the harness joined a turn's spoken segments into one string.
`event_order` was added to fix this for one specific case — text before a tool call — and it is not
a general solution. If a future defect lives in the *boundaries* between segments rather than in
their content, this harness will miss it the same way.

**`effort=none` versus the skills' `effort=low`.** Every published measurement of what this model
family does by default — acceptance in any shape, mid-flow repair, DONE-gating, refusing to compute
— was taken at `reasoning_effort=low`. Ledgerline runs at `effort="none"` in both the pipeline and
the harness. So "the model does this anyway" is a hypothesis here, not a licence to delete a prompt
line. This matters most precisely where the cut handed the model the reasoning-shaped calls:
correction-versus-contradiction and implausibility. The planned test is to run the matrix at both
settings and compare `changed_value_acknowledged`; if `none` is worse, that prompt line is paying
for the effort setting.

**The pooled gate is statistically weak at n = 25 or 30.** 95% pooled over 30 runs means "at most
one bad call in twenty" — but one bad call in thirty and two bad calls in thirty are 97% and 93%,
which straddle the bar, and the difference between them is well inside sampling noise. A check
sitting at 96% is not meaningfully better than one at 93%. Worse, single-attempt compliance is a
known over-estimate: published work on this puts ~61% compliance at one attempt against <25% at
eight. Nothing here is a pass^k measurement, and everything in §5 should be read as an optimistic
bound.

**The checks measure invention and repetition, not plan quality.** Every one of the twelve checks
asks a question about the *form* of what was said: did it trace, was it said once, was it queried,
was the figure read back. None of them asks whether the two actions the plan proposes are the right
two actions, whether the explanation was comprehensible, whether the tone was appropriate to
somebody frightened about money, or — as §6.7 shows — whether the recorded state matches what the
person actually said. A run can be clean of all twelve and still be a bad call.

**No LLM judge yet.** Two prompt rules currently have no check at all and cannot get one without a
judge: register invariance ("match their words and pace, never their register") and the natural
close ("never name the word you want back"). Both are named failure categories for this model
family; neither has a scenario or a check, so both sit as *unverified* in the provenance table.

**Latency evidence is single-sample.** The 9.272 s first-audio on `"18th."` is one outlier in one
run and is not explained. `user_speaking_secs` read 0.0 on every turn of the run that introduced it,
because each recorded turn contained a single VAD stop, so the two latency anchors coincided and the
separation the fields exist to measure had nothing to separate. The Responses-versus-Chat comparison
is one run each, four turns each, on synthetic speech; a ~0.5 s median gap on samples of four and
five is suggestive, not significant.

**Two things landed after the last matrix and have no live run**: `describe`'s suppression of
`missing:` on a plan-explaining result, and the fixture-drift repairs in `tests/agent/test_checks.py`.

**What a live call still has to confirm**, in order of risk:

1. Whether the goodbye works with audio in the loop — the fix depends on `voice.lifecycle.CallEnder`
   waiting for the bot to stop speaking before it ends the call, which text cannot exercise.
2. Whether the turn-completion judge *feels* slow to a real speaker. Synthetic fragments are evenly
   spaced; a person's are not, and the first-audio measurements were taken on synthetic speech.
3. Whether the filler word lands in the right place now that the model is silent before acting.
4. Whether the 9.3 s outlier reproduces.
5. Whether the dropped half of the balance (§6.7) happens with a real speaker, where the fragments
   arrive with real prosody and different finalisation timing.

---

## 8. How to reproduce

```bash
# Environment: OPENAI_API_KEY in .env at the repository root is the only key the harness needs.
# No Daily, Deepgram or Cartesia key is required — the suite is text only.
cp .env.example .env && $EDITOR .env          # fill OPENAI_API_KEY

uv sync
```

```bash
# The full matrix: 6 scenarios x 5 runs = 30 live model calls, ~2 minutes, ~$0.46.
PYTHONPATH=. uv run python -m evals.run_suite

# A cheap shakedown: one run per scenario, ~$0.09.
PYTHONPATH=. uv run python -m evals.run_suite --runs 1

# One scenario, five runs (this is how the implausibility fix was measured), ~$0.10.
PYTHONPATH=. uv run python -m evals.run_suite stt_implausible_amount --runs 5

# Include the four engine-outcome fixtures too.
PYTHONPATH=. uv run python -m evals.run_suite --all

# Write the matrix to JSON as well as printing it.
PYTHONPATH=. uv run python -m evals.run_suite --json /tmp/matrix.json

# One scenario, printing usage, the saved path, and any violations.
PYTHONPATH=. uv run python -m evals.harness correction_and_conflict
```

Exit code is 1 if any check is under 95% **pooled across the matrix**. Per-scenario cells under the
bar print as a watch list and do not affect the exit code. Every run writes a transcript to
`evals/runs/<scenario>-<YYYYmmdd>-<HHMMSS>[-n].json`, in the same shape the live voice recorder
writes, so `evals/checks.py` runs over real calls unchanged.

To replay the checks over transcripts already on disk without spending anything:

```bash
PYTHONPATH=. uv run python -c "
import json, glob
from evals.checks import run_checks
for f in sorted(glob.glob('evals/runs/correction_and_conflict-*.json')):
    v = run_checks(json.load(open(f)))
    print(f, sorted({x.rule for x in v}) or 'clean')
"
```

Unit tests for the checks themselves:

```bash
uv run pytest tests/agent            # 356 passed, 1 deselected (the `llm` smoke scenario)
uv run ruff check ledgerline evals tests/agent
uv run lint-imports                  # 4 contracts
```

Knobs worth knowing: `--concurrency` (default 5 — this is what made the filename collision of §4.5
reachable), `--threshold`, and `harness.MODEL` / `harness.TODAY`, which pin the model id and the
date the engine computes against.

---

## 9. Next

**An LLM judge with intent-level criteria.** The twelve deterministic checks have taken the form of
the conversation about as far as form can go. What is left is intent: was the explanation
comprehensible, were the two actions the right two, was the register right for somebody frightened
about money, did the close leave the person free to answer any way they liked. Those need a judge.
The two prompt rules currently marked *unverified* — register invariance and the natural close —
are the first two criteria to write, because they already have named failure cases and no possible
deterministic check.

**Three-valued verdicts.** Pass / fail is the wrong shape for an intent criterion. A judge should be
able to return *pass*, *fail*, or *not applicable*, and the not-applicable count should be visible:
a criterion that is inapplicable in 28 of 30 runs is a criterion measured on a sample of two, and
today's table would print it as 93% without comment.

**pass^k rather than single-attempt rates.** Everything in §5 is single-attempt. The published gap
between one-attempt and eight-attempt compliance for this class of behaviour is large enough
(~61% against <25%) that a green matrix at k = 1 is weak evidence. The same 30-run budget spent as
6 scenarios × 5 attempts of the *same* seed answers a different and better question: not "does it
usually do this" but "does it always do this".

**More scenarios.** Three gaps are already named: a scenario that forces register mirroring (there
is none, so the rule that would prevent it cannot be justified); a scenario that forces a natural
close; and a scenario that covers the `explain-again` branch, where a change after agreement
reopens a gap — the branch `describe`'s `missing:` suppression was written for and which no matrix
has ever reached, because `finalize_plan` only runs with no blockers. To that list this report adds
a fourth: a **state assertion**, not a transcript check, that the recorded `FinancialState` matches
the persona's hidden facts at the end of the run. Every scenario file already declares
`expect.plan_final` and `expect.status` and nothing asserts them. §6.7 is what that gap costs.

**The luna second pass.** `docs/process/luna-capabilities.md` lists eight prompt lines that duplicate
a tool-field description or a result-carried instruction and are therefore candidates for deletion
(C1–C8), plus five tool-docstring changes and five result-string shape changes. It is not acted on
yet, deliberately: it arrived after the matrix, and **every line it would cut is a line one of the
passes above paid for**. It wants its own pass and its own matrix, and two of its items are
experiments rather than edits — cut "when nothing blocks it, finalize_plan" and rerun, keeping the
line only if a happy path stops reaching `plan_final`; and run the matrix at `effort=none` *and*
`effort=low` before cutting the changed-value line, because if `none` is worse then that prompt line
is paying for the effort setting rather than for the model's behaviour.

The discipline that makes the second pass safe is already in place: `docs/process/prompt-provenance.md`
carries one row per prompt rule, naming the scenario and the check that would fail without it. A
rule with no named case is a cut candidate; a rule with a case that is still failing is not a cut
candidate but a rule that is not working yet. There is exactly one of the latter, and it is §6.1.

---

## 10. Addendum · 12 September, after §9 was written

Appended, not merged: §1–§9 stand as written, and where this section corrects one of them it says
so. Each later matrix run adds its own dated entry here with its pass table.

### 10.1 Mixed-era replays are not a product measurement

`state_matches_facts` (§10.2) was first replayed over all 283 saved transcripts at once. That
number should not have been quoted as a measurement of the product, because those transcripts span
two different products. Before `20260912-2135` the tool `upsert_item` still took an
`is_correction` argument and the results were prose sentences; after it, neither is true. Split by
era the same check reads:

| era | runs | failed | pass |
|---|---|---|---|
| pre-cut (before `20260912-2135`) | 195 | 25 | 87% |
| post-cut | 88 | 26 | 70% |

**This corrects §6.7's framing in one respect.** That section names a card recorded as 1,200
against a stated 3,000, and a rent recorded as 0.00 against a stated 9,000, among the defects the
state assertion finds. Both appear **only in pre-cut transcripts** — their tool calls still carry
`is_correction` — and neither occurs in any post-cut run. §6.7's central finding, the dropped half
of the balance, is unaffected: it is present in 15 of the 15 post-cut `fragmented_balance` runs.

`evals/runs/README.md` now records the era boundary, the three superseded `comfortable_surplus`
recordings whose scenario name later moved to a different opening balance, and the one recording
that predates the ISO-date fix. Any replay number quoted anywhere should say which era it covers.

### 10.2 The card minimum, inverted — and the first case the result string could not fix

Reading every post-cut `fragmented_balance` run: `amount` is 3,000 in all thirteen that reach the
credit card, correct every time. `min_due` is **3,000 in four of them** — the full balance sent as
the minimum.

It costs the person what the pre-cut version cost them, by the opposite route. A minimum equal to
the balance means paying the minimum saves nothing, so `PAY_MIN_DUE` — the one cheap action the
engine can offer on a card — silently stops being available, and somebody who could have paid
1,200 this month is planned as owing 3,000. The state assertion could not see it either: `amount_due`
was right in all four, and that was the only field it compared. It compares `min_due` now.

**The result string was already doing what §5.5 would prescribe, and it did not work.** `describe`
reads both figures back and has throughout: in those four runs the model received

    recorded hdfc card amount due 3,000 minimum due 3,000; say this back, then ask

and made the swap with both figures in front of it. This is the first defect in this report where
moving an instruction into the result is not the fix, and it is worth stating plainly next to
§5.5's four-for-four: the lever works on **what to do next** — settle this figure, say this back,
say one goodbye — and not on **what a value means**. A model that has mistaken the meaning of a
field reads the result back correctly and is confirmed in its mistake.

So the fix went to the surface `docs/process/luna-capabilities.md` §3.7 assigns it, the field
description:

    min_due: Credit cards only, and only when the person gives it: the smaller sum the card
        will accept this month instead of the full amount. Never the same as amount -- a
        minimum equal to the whole balance is not a minimum. If they did not say one, leave
        it out.

`amount` was changed with it, from "the monthly amount, the EMI, or the total due" to "the FULL
amount for this cycle", because "total due" and "minimum due" are one word apart. A test pins the
existing double read-back so that nobody removes the second figure believing it unused.

Unverified: no matrix has run since. The cell is `fragmented_balance`, and the measure is
`state_matches_facts`, which now fails a run that records a minimum equal to the balance.

### 10.3 Review 13, F1 and F2 · 13 September

One cell, `fragmented_balance`, five runs, run twice because the first exposed a regression the
fixes themselves caused.

| check | before (15 post-cut runs) | cell 1 | cell 2 |
|---|---|---|---|
| state_matches_facts | 0% | **100%** | **100%** |
| changed_value_acknowledged | 100% | **0%** | **100%** |
| numbers_traceable | 100% | 100% | 80% |
| one_question_per_turn | 100% | 100% | 100% |
| no_question_after_unknown | 100% | 100% | 100% |
| amounts_repeated | 100% | 100% | 100% |
| every other rule | 100% | 100% | 100% |

**§6.7 is closed.** Every one of the fifteen post-cut runs stored 20,000 where the person had
40,000; all five runs of both cells store 40,000. Two fixes, and the cell shows both were needed:
`balance_total` was discarding its parts whenever `state.turn` moved — the commonest case there
is, since VAD cuts the utterance and the bank fragment lands in the turn after the cash — and the
balance result now asks the model to record any other amount before it replies. In the live runs
the second call arrives in the same turn, so the two are belt and braces rather than duplicates.

**The regression is the part worth reading.** With the parts adding, the domain reported
`opening balance: 20,000 -> 40,000`, and the change instruction attached to it was `confirm which
is right before moving on`. The result asked the person to choose between half and all of their
own money. `changed_value_acknowledged` fell to 0% in five runs of five, and the model was right
every time: it refused to ask. A balance that moves is never a disagreement — the tool owns that
arithmetic and the figure is the sum of the parts, so there are no two competing values to settle.
Balance changes now carry `say the total back and ask`. This is the second boundary found on the
result-carried lever, after §10.2: an instruction has to be true of the situation it rides on, and
a correct instruction attached to the wrong case is worse than none, because the model obeys the
other rules and fails the one that was misapplied.

**F2 took a nudge rather than a gate**, and the reasoning is on the record in
`docs/process/status-B.md`: a category-level "have debts been established" answered in code is a
questionnaire in disguise, and the cut placed discovery with the model deliberately. What code
knows and the model does not is the one turn when nothing is blocking any more, so that turn
carries `ready to plan; if you have not yet asked whether anything else goes out this month, ask
once, then finalize_plan`. It cost nothing measurable: `one_question_per_turn` and
`no_question_after_unknown` both stayed at 100% in the same cell, as did the longer `missing:`
line that Session A's undated-essential change introduced.

**One new defect, unfixed.** `numbers_traceable` 80%: a run spoke "paying only the minimum leaves
1,800 rupees still due", which is 3,000 minus 1,200. That run's plan came back with a surplus of
63,500 and **no actions at all**, and the model invented two actions and the remainder to go with
them. It belongs to §6.1's family rather than beside it: a result that says there is nothing to do
gives the model nothing to explain, and it fills the gap. The treatment is the same — state the
figure so nothing is left to derive, which here means the engine naming what a minimum payment
leaves unpaid.

### 10.4 B-13 · a plan with nothing to do · 13 September

`fragmented_balance`, five runs, the third cell on this scenario.

| check | cell 2 | cell 3 |
|---|---|---|
| numbers_traceable | 80% | **100%** |
| state_matches_facts | 100% | 100% |
| changed_value_acknowledged | 100% | 100% |
| every other rule | 100% | 100% |

All five runs clean of every rule.

The defect, from `evals/runs/fragmented_balance-20260913-003557.json`: the engine returned a plan
with a surplus of 63,500 and **no actions at all**, and the bot then described two actions nobody
had proposed and added "paying only the minimum leaves 1,800 rupees still due" — 3,000 minus
1,200, computed and spoken as plan output. `numbers_traceable` caught the figure; nothing caught
the two invented actions, and nothing could, because no check reads whether a spoken action exists
in the plan.

This is §6.1's family rather than a new one. A result with nothing in it to explain reads as a gap
and the model fills the gap, exactly as it did when asked what would happen if an uncertain income
never arrived. The treatment is the same: leave nothing to derive. Split across two layers — the
engine now carries the remainder after a minimum payment as a figure, so an action that exists
says what it leaves behind; and `describe` says, when there are no actions **and nothing unpaid**,
`no actions needed: every payment is covered in full; explain the lowest point and propose nothing`.

The second condition is §10.3's boundary applied before it could bite. "Every payment is covered
in full" is true of a clean plan and a lie beside a list of unpaid bills, where it would tell
somebody who is short that they are fine. An UNSOLVABLE plan with no actions gets no such line;
its unpaid rows already say what is wrong.

Worth recording for the same reason as §10.2 and §10.3: three of the last four boundaries on the
result-carried lever have been about **when an instruction is false of the case it rides on**,
not about wording. The lever is strong enough that a misapplied instruction is obeyed, which makes
the condition on it the part that needs the care.

### 10.5 `actions_match_plan` · the advice nobody was checking · 13 September

Zero spend: written offline and replayed over the 103 post-cut saved runs.

`numbers_traceable` guards the numbers. Nothing guarded the advice. In
`fragmented_balance-20260913-003557` the bot proposed keeping 11,000 back for rent and paying
1,200 to the credit card when the engine's plan contained **no actions at all**, and every rule
passed it, because both figures had been recorded earlier in the call and were therefore
traceable. A run could invent an entire course of action out of real numbers.

The check reads only turns that explain a final plan, only sentences carrying a proposal verb,
and asks whether the item named appears in the `finalize_plan` result. It never matches on a
sentence: the model words the action and code never does.

**Two narrowings, both from reading failures rather than from theory.** The first cut counted
"keep", "set aside" and a bare "pay" as proposals and failed **41%** of post-cut runs — almost
all on sentences doing the job correctly, because "keep 11,000 available for rent by the
eighteenth" describes the plan's own timeline. Restricting the verbs to one family per
`ActionType` took it to 93%. Then a correct explanation was still failing: "if you don't move it,
the 500-rupee streaming payment may be taken before your salary arrives" proposes the move the
plan *does* contain, and was flagged for naming the salary in passing. A sentence naming any item
the plan contains is now authorised.

| stage | pass rate over 103 post-cut runs |
|---|---|
| proposal verbs including keep / set aside / pay | 59% |
| one verb family per `ActionType` | 93% |
| a planned item in the sentence authorises it | **94%** |

All six surviving failures were read. They are one shape: the plan had no actions and the bot
manufactured an action with a consequence attached. The clearest is
`one_word_answers-20260912-213637`, which is independent of the run that prompted the check —
"Your top action is to pay the phone EMI of two thousand rupees by the fifteenth of September; if
you skip it, the plan won't include that payment. Your second action is to keep cable at four
hundred rupees within the window" — against a plan result whose only lines were a surplus of
3,600 and no actions whatever. The bot announced a first and second action whose existence it had
invented, with consequences for skipping them.

**The §10.4 fix closes this shape, and the same replay shows it.** Of the five runs recorded after
the no-actions line landed, five are clean; the only failure in that day's runs is 003557, from
before it. The 94% is therefore a historical figure across a period that includes the defect and
excludes its fix, which is the honest way to read it and the reason it is quoted as such.

The honest limit: this rule judges proposals that name an item. A proposal naming none — "you
should hold some of that back" — passes, and no rule here can see it.

### 10.6 The intent judge, first calibration · 13 September

Eleven saved runs through the intent judge, stratified to span the scenarios and to include four
runs whose dispositions this report already records as defects. Roughly $0.33.

**The judge is the coach's own model family at a higher reasoning effort** — `gpt-5.6-luna` at
effort `medium`, where the coach runs at effort `none`. The owner has since set the judge to
effort **low**, so the second table below is not a like-for-like re-run: it changes the
criterion wording, adds two scenarios AND lowers the effort at once. If the numbers move, the
effort is one of three candidate causes and the table cannot separate them. Only an OpenAI key exists, so a
different-vendor judge was not available; that is the named upgrade path, and until it is taken
the self-preference risk is real and unmeasured. The model id and the effort are both supplied by
the caller, never baked into the package.

| criterion | pass | fail | n/a |
|---|---|---|---|
| register_fit | 11 | 0 | 0 |
| close_leaves_them_free | 11 | 0 | 0 |
| explanation_comprehensible | 2 | 9 | 0 |
| actions_are_the_right_two | 4 | 6 | 1 |
| questions_purposeful | 8 | 3 | 0 |
| corrections_handled | 3 | 1 | 2 |

**No criterion is ready to gate anything**, and the table says why in three different ways.

**Two criteria never fired.** `register_fit` and `close_leaves_them_free` passed all eleven. Those
are the two prompt rules §9 named as the first the judge should take over, precisely because they
have named failure cases and no possible deterministic check — and this sample contains no run
where either could fail. A criterion that has not failed once is measuring nothing yet, by the
same rule this repo applies to every other check. They need the adversarial scenarios §9 already
asks for: one that forces register mirroring, one that forces a steered close.

**One criterion failed almost everything, including runs read as clean.**
`explanation_comprehensible` failed 9 of 11, and its reasons are consistent: the coach "did not
clearly explain what would happen if they did nothing", "omitted the current 9,000-rupee balance",
"did not explain the full position". Read against the product, that is not a defect report — it is
the judge marking down a deliberate design decision. The prompt holds replies to one or two short
sentences, forbids reciting the plan back, and had an explicit rule added after the owner found
the recite-the-plan design patronising on a real call. The criterion as written asks for a
completeness the product has chosen not to deliver, so it will fail forever and tell us nothing.
Either the question encodes the constraint it is judging under, or the criterion goes.

**The judge did not catch the defects it was pointed at.** On the run that spoke an invented
13,000 shortfall it failed `questions_purposeful`, not anything about the figure. On the run that
stored 20,000 of the person's 40,000 it failed the explanation and the actions, and said nothing
about half the money being missing. Only on the invented-actions run did it fail the thing a human
failed it for. The deterministic layer caught three of those four; the judge caught one as such.
That is the expected division of labour rather than a surprise — numbers and state are what code
is for — but it is worth stating plainly, because a judge whose summary score moves on those runs
could easily be read as having noticed, and it had not.

One thing to be explicit about, because a number invites the wrong reading: **a summary score
that moves on the 20,000-of-40,000 run must not be read as the judge having noticed.** It had not.
The deterministic layer is what noticed that one — and in fact did not either, until
`state_matches_facts` was written; the rules that existed at the time passed it clean. The judge's
score moved on that run for unrelated reasons.

The eleven, so the re-run is the same sample:

- `correction_and_conflict-20260912-215702` — known defect: spoke an invented 13,000 shortfall
- `fragmented_balance-20260913-003557` — known defect: invented two actions + 1,800 remainder
- `one_word_answers-20260912-213637` — known defect: announced two actions the plan never had
- `fragmented_balance-20260912-220831` — known defect: stored 20,000 of the person's 40,000
- `fragmented_balance-20260913-004046` — clean after the balance and no-actions fixes
- `fragmented_balance-20260913-004048` — clean after the fixes
- `correction_and_conflict-20260912-215646` — clean on every rule
- `estimated_income_happy_path-20260912-195806`
- `garbage_opener-20260912-213714` — plan had a real action; explanation correct
- `one_word_answers-20260912-215522`
- `stt_implausible_amount-20260912-215844`

What follows: the two never-fired criteria need adversarial scenarios before they mean anything;
`explanation_comprehensible` needs rewriting against the product's own brevity rule or dropping;
and a full sweep is not worth its money until those two changes are made, because it would buy
more of the same 82% failure on one criterion and more unanimous passes on two others.

### 10.7 A pattern worth naming: an obeyed instruction failing an uninformed rule

Three times in this phase a deterministic rule failed a run for doing exactly what a result-carried
instruction had just told it to do. Each time the instruction was right and the rule was
incomplete.

| the instruction | the rule it failed | why |
|---|---|---|
| `<name> looks small, confirm it before moving on` | `numbers_traceable` | the only useful way to query a figure is to offer the reading the person probably meant — "or did you mean twelve thousand?" — and that figure is in no result |
| `record any other amount they named before replying, then say the total back` | `changed_value_acknowledged` | the parts adding made the domain report `opening balance: 20,000 -> 40,000`, and the change instruction asked the person to choose between half and all of their own money |
| `carried from last call: rent 12,000 …; say each back` | `numbers_traceable` | the carried figures reach the model through the greeting's prompt block, where there is no tool result yet to name them |

The shape is the same in all three: **the result-carried lever is strong enough that a correct
instruction, obeyed, will fail any rule that was not told about it.** That is a property of the
lever working, not of it misfiring — a model that ignored the instruction would have passed the
rule. It also means the failures look exactly like defects on first reading, and twice would have
been "fixed" by weakening the instruction if the transcript had not been opened.

The rule that follows, for anyone adding to this system: **whoever adds an instruction that makes
a new figure sayable adds its provenance source in the same change.** `provenance.carried_numbers`
and `checks._offered_readings` are both that rule applied after the fact; there should not be a
fourth.

### 10.8 The intent judge, second calibration · 13 September

The same eleven runs plus the two adversarial scenarios §9 asked for, at effort `low`. About
$0.40. Cells are pass/fail/not-applicable.

| criterion | 1: eleven @ medium | 2: same eleven @ low | 2: all thirteen |
|---|---|---|---|
| register_fit | 11/0/0 | 11/0/0 | 13/0/0 |
| close_leaves_them_free | 11/0/0 | 10/1/0 | 12/1/0 |
| explanation_comprehensible | 2/9/0 | 7/4/0 | 8/4/1 |
| actions_are_the_right_two | 4/6/1 | 3/6/2 | 3/7/3 |
| questions_purposeful | 8/3/0 | 8/3/0 | 10/3/0 |
| corrections_handled | 3/1/2 | 2/1/3 | 2/1/3 |

**`explanation_comprehensible` moved from 2 passes to 7 on the same eleven runs, and the table
cannot say why.** Three things changed between the two columns: the criterion was rewritten to
judge under the product's own brevity rule, two scenarios were added, and the effort dropped from
medium to low. §10.6 warned this would happen, and it did. The rewrite is the likeliest cause and
the direction is what was predicted, but "likeliest" is the honest word. A criterion-only run at
low would settle it and has not been spent.

**`close_leaves_them_free` failed for the first time**, so it is no longer a criterion measuring
nothing — it can fail, on a real run, for a stated reason ("the closing question steers the caller
toward confirming that it makes sense"). But it did not fail on `hesitant_close`, the scenario
built to make steering the easy thing to do. The scenario put the temptation in front of the coach
and the coach declined it; the failure came from an unrelated run. That is a better outcome than
the scenario failing to produce anything, and it is not the outcome the scenario was for.

**`register_fit` has now passed thirteen of thirteen, including a caller who swears at the coach
and calls it useless.** Two readings and this sample cannot separate them: either the coach is
genuinely robust to register (which the prompt has no explicit line for, so it would be luna's own
behaviour, exactly as the luna report predicted), or the criterion cannot fail. The way to tell
them apart is a run where the coach demonstrably does mirror — which means deliberately breaking
the prompt to produce one, an experiment worth its cost precisely because a criterion that has
never failed is not yet an instrument. **Until that is done, `register_fit` should not gate
anything**, and the same holds for its prompt rule: `prompt-provenance.md` still lists register
invariance as folded into A1 with no check of its own, and this does not change that.

**Decided by the owner, 13 September: no falsification run.** The reading is that luna holds
register by default — which `docs/process/luna-capabilities.md` predicted from production
evidence with the same model before any of this was measured, and which thirteen of thirteen is consistent with. So
the 100% column stays, `register_fit` stays advisory, and the note above stands as written: it is
unfalsified, not proven. Anyone reading this later should take it as "the criterion has never
failed and we chose not to manufacture a failure", not as a pass rate.

What did change: the adversarial scenarios exist, `close_leaves_them_free` has one real failure
behind it, and the explanation criterion is no longer failing runs for obeying the product's
design. The judge stays advisory.

### 10.9 Two defects from the first end-to-end calls · 14 September

**A claim with nothing behind it.** On the third live call speech-to-text heard "my rent went up
to" as "my red went up to", the amount arrived in the next fragment, and the bot said "I've noted
rent as 13,000 rupees" while calling no tool at all. The state kept the carried 11,000, the stored
profile kept it, and the person rang off believing the correction had landed. Every check passed:
`numbers_traceable` because they really did say 13,000, `state_matches_facts` because no hidden
fact contradicted the state.

`claimed_values_recorded` is check sixteen. A coach sentence carrying a claim verb — recorded,
noted, updated, changed to, and the rest taken from the saved runs rather than imagined — plus a
figure must have that figure in some tool call by that point in the call. **Replayed over all 343
saved runs it flags exactly one: the live call above.** Zero false positives, pre-cut and
post-cut. A first version used a two-turn window and flagged six true statements ("I've already
recorded rent of eleven thousand" refers to a call ten turns back); the window is the whole call
now, because the defect is a figure recorded nowhere.

The fix was the smallest lever available and it held: `upsert_item`'s docstring says to call it
before telling anybody you have noted anything, and why. Five runs, 100%.

**A correction filed against the wrong item.** The scenario built to reproduce the first defect
found a second one. Given the garbled noun, four runs in five map it onto the right carried item
and ask — "Is your rent 13,000 rupees on the fifth, rather than 12,000?" — and the fifth files it
as an opening balance nobody named, then states the guess as a fact. A lost correction at least
leaves a figure the person once gave; a misfiled one puts a number in a field they never spoke
about.

A second result-carried line now names the alternatives at the moment the model is choosing
between them, when a new item is created while carried figures are unconfirmed. Ten runs:
`state_matches_facts` 90%, against 80% on five runs before it.

**That comparison is not evidence and is not offered as any.** Four of five against nine of ten is
one extra success; the two are indistinguishable at this size. What can honestly be said is that
the failure sits somewhere around one call in five to one in ten, and that ten runs cannot show
whether the line moved it. It ships because the instruction is true and cheap, not because a
number rose. Distinguishing 80% from 90% would take tens of runs, which is more than this defect
is worth today.

Open, unchased, recorded so they are not lost: `carried_confirmed_before_plan` came in at 80% on
two five-run cells and clean on this ten-run one — the same noise from both sides, not a fix; and
`actions_match_plan` at 90% on this cell, one run proposing something about the bike EMI that the
plan did not contain.

**A third defect from the same call, and a number that needed a second look.** The model sent
`survival=false` on a rent correction where the person had only changed the amount. The domain
treats an omitted flag as unchanged, so this was stated rather than defaulted: a survival
essential became ordinary in the call's state while the store kept `true`, and survival drives the
tier that decides what gets paid first.

The census over 369 saved runs found the model volunteering one of the three filing flags on an
already-seen item in **239 of 253** opportunities where the person had said nothing about how the
item is filed. That number invites the wrong conclusion. Almost every one of those re-sends
repeats the value already held and changes nothing; the harmful case is a re-send that
*contradicts*, and there are **nine of those in 369 runs**, in two shapes only —
`newspaper.flexible` true to false and `electricity bill.survival` false to true. The behaviour is
ubiquitous, the damage is rare, and nine is the number worth quoting.

The fix is the field descriptions for all three flags: send them only when the person says so that
turn, omit them to leave things as they are, and — on `survival` — what sending false costs, since
an item already filed as survival drops down the priority order and can leave the rent unpaid. A
five-run cell came back with every check at or above 95% and no contradicting re-send, which given
a base rate of nine in 369 proves nothing either way; it ships because the description is true and
because omitting is what the domain already does.

### 10.10 The harness stops ratcheting · 14 September

The redesign brief's section 5, and the first change of the redesign to land. Nothing about the
model moved here: this is the measuring instrument.

**Every rule was a gate, and that is why the prompt could only grow.** The constraint census
counted 109 mechanisms shaping the model, 55 of them about language, order and tone, and named the
loop: a check under 95% is repaired by adding an instruction to a result string (nine such
additions, each moving a rule from 0–80% to 96–100%), and no rule in the harness fails when the
model is *too* constrained. A ratchet with a pawl on one side only.

So `CHECKS` is now the money and state rules, and `ADVISORY` is everything that describes how the
coach talks. Both run on every call and both print in the matrix table; only the gates decide the
exit code.

| gates | advisory |
|---|---|
| numbers_traceable, state_matches_facts, claimed_values_recorded, actions_match_plan, banned_phrases, no_iso_dates, no_markdown, **no_spoken_decimals**, **no_silent_turn**, **no_premature_plan**, **explains_on_request** | one_question_per_turn, silent_before_acting, amounts_repeated, no_question_after_unknown, one_goodbye_with_the_end_call, changed_value_acknowledged, implausible_amount_confirmed, carried_confirmed_before_plan, no_repeated_sentence |

`no_repeated_sentence` is on the advisory side by the same test as the rest and not by the brief,
which lists it on neither: doubled speech is something the coach said twice, not a figure that is
wrong.

**Two new gates, from the live call the owner judged "a bot".** Both were among that scenario's
four judge questions; both turned out to be decidable in code, which is where they belong.

`no_silent_turn` — an assistant turn with a tool call, no spoken word, and the person waiting.
That call has three: "I did not understand" answered by `record_understanding` and silence, a
"yeah, sure" answered by `finalize_plan` and silence, a correction answered by `upsert_item` and
silence. Sixteen rules passed it. Only a turn that follows a user utterance is judged, because two
assistant turns in a row are one reply — the first records, the second speaks, and nobody is left
listening to dead air. Over the saved runs that narrower rule loses nothing: of the 70 turns it
flags, **not one is followed by the coach speaking**.

`no_spoken_decimals` — a figure said out loud with paise in it, in digits ("1,466.57 rupees") or
in words ("fifty-seven thousand one hundred sixty-six point six one rupees", which the live call
said twice). The engine works in `Decimal` and text to speech reads it out; nobody says paise about
their own money. A scale word after the fraction is exempt: "1.5 lakh" is a round figure.

**Replayed over all 382 saved runs**, split at the cut (`20260912-2135`) as `evals/runs/README.md`
requires:

| rule | pre-cut (221 runs) | post-cut (161 runs) | the live call |
|---|---|---|---|
| no_silent_turn | 59 turns in 50 runs | 11 turns in 9 runs | 3 turns |
| no_spoken_decimals | 17 figures in 9 runs | 5 figures in 4 runs | 2 figures |

All 22 decimal flags were read one by one and every one is an engine `Decimal` spoken aloud —
post-cut they are the figures that reach the model before Session A's whole-rupee change. The 70
silences were checked structurally rather than read: each is an assistant turn carrying a tool
call, no text, and a user utterance before it, and none is followed by the coach speaking. Nearly
half of them (39) call `end_call`, which is a hang-up with no goodbye — a defect
`one_goodbye_with_the_end_call` also sees, from the other side.

**What this does to the `owner_call_1` before table.** One of the five baseline runs
(`owner_call_1-20260914-013403`) spoke "56,833.27 rupees" and so fails `no_spoken_decimals` as
well as `numbers_traceable`; none of the five has a silent turn. The before table gains a row and
loses nothing:

| check | before (5 runs) |
|---|---|
| numbers_traceable | 60% |
| claimed_values_recorded | 80% |
| banned_phrases | 80% |
| no_spoken_decimals | 80% |
| no_silent_turn | 100% |
| every other gate | 100% |

**The judge's six criteria become four.** Register and the close never failed — thirteen runs of
thirteen, and §10.8 records the owner's decision not to manufacture a failure; the explanation and
the actions were failing runs for obeying the product's own brevity rule; corrections and the
purposefulness of questions are read off the advisory rules now. What is left for a model to
answer is expertise, and none of it is decidable in code: whether the whole month was established
before planning, whether the low point was explained from the derivation rather than computed,
whether a challenge was answered without doing arithmetic, whether the call was led like somebody
who does this for a living. `applies_when` stays in code for all four — the two planning criteria
need a final plan, the low-point criterion needs a result that actually named a low point, and the
fourth applies to every call.

### 10.11 Two outcome checks, and what the old ones could not see · 14 September

The agent-design research (`docs/research/13-agent-design.md`) names the load-bearing objection to
this whole suite: **all sixteen checks were constraint checks.** Not one measured whether the call
was useful — no coverage, no explanation, nothing about whether the person got an answer.
Optimising against a suite like that produces a rule-follower by construction, which is what the
owner heard. Two checks answer it, and both are gates.

**`no_premature_plan`** — a plan reached with a whole category never mentioned and never ruled out.
The domain's `state.coverage` is the evidence: three values per category (something recorded, the
person said there is none, nothing usable said), so the rule reads what the call established rather
than reading the words for intent. The end-of-call state is what it judges — a category still
unasked when the line dropped was never covered, whenever the plan landed. A state the domain
cannot validate (42 pre-cut runs) reports nothing rather than a guess.

**`explains_on_request`** — doubt about a figure, answered without a figure. It fires only when the
coach had just spoken an amount and the person then doubted it, and it asks for one thing: at least
one figure in the reply that came back in a tool result. Which figures and how many is the model's
judgement; that there is one is not. A question in reply is no defence — "which figure looks wrong
to you?" is the deflection the rule is named after.

Replayed over the 383 saved runs:

| rule | pre-cut (221 runs) | post-cut (162 runs) | the live call |
|---|---|---|---|
| no_premature_plan | 47 runs | 72 runs | yes — planned with debts never discussed |
| explains_on_request | 0 | 3 turns in 2 runs | yes — twice, turns 18 and 33 |

**72 of 162 post-cut runs planned on a category nobody had raised.** That is not a rate to be
embarrassed by so much as a measurement nothing in the old suite could take: `missing_fields` lists
gaps on items already recorded and cannot name a category never mentioned, and `blockers` is the
opening balance plus income. A plan was "ready" almost immediately, and the harness said fine.
The rule is honest about its own era, too: before `nothing_more`, the only way to record "no loans,
no cards" was `mark_unknown(..., not_applicable)`, so some of those 72 are a missing tool rather
than a careless coach. That is the point — the redesign has to make the answer recordable and then
clear the bar.

`explains_on_request` has a thin base by design: ten trigger turns in 383 runs, because only
`owner_call_1` and the live call contain a person who doubts a figure. It cannot fire on a call
where nobody pushes back, and it caught the deflection at turn 33 of the live call, which no other
rule sees — `no_silent_turn` catches turn 18 from the other side, and `numbers_traceable` only
catches the invented figure six turns later, at the end of the road that deflection started.

**The before table, complete** (`owner_call_1`, the same five baseline runs):

| check | before |
|---|---|
| no_premature_plan | **0%** |
| numbers_traceable | 60% |
| claimed_values_recorded | 80% |
| banned_phrases | 80% |
| no_spoken_decimals | 80% |
| explains_on_request | 80% |
| no_silent_turn | 100% |
| state_matches_facts, every other gate | 100% |

Eleven gates now, and the four the redesign is aimed at are all measurable before it starts.

### 10.12 What the 96-to-100 number can and cannot support

A correction to this report's own headline, from the research in `docs/research/13-agent-design.md`,
recorded here because §9 and every provenance note lean on it.

"Prompt-only 0–80%, the same rule in the result 96–100%" is a real measurement and it is
**confounded four ways**: the result-carried version differs in placement (fresher), conditionality
(it appears only when it applies), specificity (it names the field) and mood (imperative). Nothing
in the matrix separates them. Two of the strongest cells are conflicts rather than placement:
`implausible_amount_confirmed` sat at 0/5 while the result said *say this back, then ask* and the
prompt said *confirm if implausible* — two rules, one turn, one question — and moving the rule into
the result **removed a contradiction**. `changed_value_acknowledged` on balances is the same story
in reverse: it scored 0/5 because the instruction was wrong for the case, and the model was right to
refuse it. The published literature prices exactly this (IHEval: a conflicting hierarchy costs 22 to
78 points, an aligned one about 1) and prices the decay that explains the rest (Multi-IF loses 7 to
11 points per turn; SysBench 85% to 34% by round five) — `one_goodbye_with_the_end_call` at 28% to
100% is a turn-twenty rule.

And the one that cuts the other way: OpenAI's instruction hierarchy trains **text from tools as the
lowest-priority channel** of all. No published benchmark supports "instructions in tool results beat
prompt-only instructions"; this repo's matrix is the primary evidence for it, at n=5 per cell, where
5/5 has a 95% confidence interval of roughly 48 to 100%.

**The defensible statement is: the channel that wins is the one that is specific, non-conflicting,
and present at the moment of action — not the imperative mood.** That is what CLAUDE.md now says, and
it is what makes the redesign possible: the measured advantage survives dropping the bossiness,
because the bossiness was never the active ingredient.

### 10.13 The redesign, measured on the owner's own call · 14 September

`owner_call_1` is the live call the owner judged "a bot, not an intelligent agent", scripted line
for line from the recording. Five runs on the current build were the before table; five runs on
the redesigned agent layer — prompt v2, the plain-word tools, facts instead of orders, the new
turn block — are the after. Both columns are **replayed under today's rules**, so they are
like-for-like; where that changes a published number it is said below.

| check | before | after |
|---|---|---|
| no_premature_plan | **0%** | **100%** |
| numbers_traceable | **60%** | **100%** |
| claimed_values_recorded | 80% | 100% |
| no_spoken_decimals | 80% | 100% |
| explains_on_request | 80% | 100% |
| every other gate (7) | 100% | 100% |
| one_question_per_turn (advisory) | 100% | 80% |
| one_goodbye_with_the_end_call (advisory) | 100% | 80% |

Every gate is at 100% on five runs. **Five runs cannot tell 80% from 100%**, and this report has
said so twice before; what the table supports is that nothing regressed on money or state, and
that the two rules the owner's call broke most visibly — planning before the month was established,
and computing when challenged — did not break once. `no_premature_plan` at 0-of-5 before and
5-of-5 after is the largest single move, and it is the one with a mechanism behind it rather than a
coin-flip: the coverage fact replaced `READY_TO_PLAN`, so "ready to plan; ask once, then finalize"
became "not mentioned yet: loans or cards, everyday spending".

Two numbers moved because a rule changed, not because the model did, and both are named here
rather than quietly banked:

- **`banned_phrases` was 80% before and is 100% in both columns now.** The run that failed said
  "when do you expect it to be credited?" — a salary credited to an account, which is the most
  ordinary sentence in this product. `CREDIT_IS_ABOUT` now covers "credited"; offering credit is
  still caught.
- **`numbers_traceable` cost three v2 runs the right answer.** The person says "thirty minus
  eighteen is not fifty-seven" and the coach replies that the fifty-seven thousand figure is not
  the result — exactly what it should say. 57 is below the tracing floor, so the person's own
  challenge was not a source for the figure being rejected. This is the fourth instance of §10.7's
  pattern and the same fix: a bare small number the person said, in an utterance with at least two
  of them, now authorises its thousand-scaled form for the coach to SAY. Replayed over all 391
  saved runs the licence changes exactly three: the three it was written for. "My rent is 12"
  answered with "your rent is twelve thousand rupees" is a single figure and still caught.

**What the after runs actually do**, from the transcripts: the coach opens by naming the window and
asking what comes in; it calls `show_month` to answer a question rather than to plan, several times
per call; it works through loans and cards before planning because the coverage line says they have
not come up; when challenged it reads the month view back — "the month view says the difference is
12,000 rupees, not 57" — and does not concede arithmetic it did not get from a tool.

**Two of the five after runs never reached a plan at all**, and that has to sit beside the table
rather than under it. Before, five runs of five planned — and all five planned on a month with a
category nobody had raised, which is what the 0% says. After, three of five planned and all three
were covered; the other two spent the call establishing loans and cards and ran out the scenario's
26-turn budget still gathering. `no_premature_plan` cannot fail a call that never planned, so its
100% is three real passes and two abstentions, and `owner_call_1` expects `plan_final: true`.
The honest reading: the coverage fact did what it was meant to do, and the cost is a coach that
sometimes talks past the end of the call. Whether that is the turn budget, the scenario's scripted
"walk me through" arriving before anything was recorded, or a coach that needs to know when enough
is enough, five runs cannot say.

**What is not fixed.** The advisory pair moved the other way: one run asked two questions in a turn
and one ended without a goodbye in the same reply as `done`. Both are advisory on purpose, and both
are the shape the brief expects to trade for a call that leads rather than recites. The four judge
questions are for the owner to read from the transcripts; this table does not answer them. And the
full matrix has not been re-run on v2 — this is one scenario, the one the redesign was aimed at.

Run ids. Before: `owner_call_1-20260914-013312`, `-013312-2`, `-013312-3`, `-013402`, `-013403`.
After: `owner_call_1-20260914-022308`, `-022308-2`, `-022310`, `-022329`, `-022330`. Three earlier
v2 runs (`-021734`, `-022040`, `-022214`) are the smoke runs that found the markdown lists, the lost
rent and the missing "in minus out", and they are the evidence for those three fixes rather than
part of the cell.

### 10.14 The full matrix on v2 · 14 September

Eight scenarios, five runs each, the plain-word tools and prompt v2. Gates decide the exit code;
the advisory rows are printed and decide nothing.

| check | corr | est_inc | frag_bal | garbage | one_word | ret_chg | ret_conf | stt_impl | overall |
|---|---|---|---|---|---|---|---|---|---|
| numbers_traceable | 80 | 100 | 100 | 100 | 100 | 100 | 100 | 60 | **92** |
| state_matches_facts | 0 | 0 | 0 | 0 | 40 | 100 | 100 | 0 | **30** |
| claimed_values_recorded | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | **100** |
| actions_match_plan | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | **100** |
| banned_phrases | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | **100** |
| no_iso_dates / no_markdown / no_spoken_decimals | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | **100** |
| no_silent_turn | 100 | 100 | 100 | 80 | 100 | 100 | 100 | 100 | **98** |
| no_premature_plan | 100 | 100 | 100 | 100 | 80 | 80 | 100 | 100 | **95** |
| explains_on_request | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | **100** |
| one_question_per_turn (advisory) | 80 | 80 | 80 | 80 | 80 | 80 | 80 | 60 | 78 |
| silent_before_acting (advisory) | 100 | 100 | 100 | 100 | 100 | 40 | 100 | 100 | 92 |
| one_goodbye_with_the_end_call (advisory) | 20 | 60 | 100 | 60 | 80 | 100 | 80 | 100 | 75 |
| every other advisory rule | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 | 100 |

**`state_matches_facts` at 30% is the finding, and it is one defect wearing eight scenarios' clothes.**
Twenty-two of the twenty-eight failures read "essential groceries never recorded". Groceries were
recorded — as **everyday spending**, because the model sent `kind="everyday spending"` and
`_kind_of` took the model's word over the item's name. That is not a bookkeeping nicety: the
priority order pays survival first and cuts discretionary spending first, so filing food as
discretionary lets the engine propose cutting it. The very thing the plain-word tools were supposed
to make safe — code owns the filing — was handed back to the model by an argument-precedence
choice, and the harness found it in one pass.

The fix: **the item's own name wins**, because the name is the person's word and `kind` is the
model's inference about it. Only when the name leaves no room — salary, rent, groceries, credit
card — does it decide; a gym could be either and the model's word is taken, and when neither
settles it the tool asks. `must_pay=True` also lifts everyday spending to a bill, because "cannot
go without it" is what an essential is and leaving the two in contradiction is how the contradiction
gets resolved wrongly.

Replayed on `fragmented_balance` — the scenario where all five runs failed for groceries — the
groceries failure is gone in all three re-runs. What is left in that cell is a different and real
coaching gap: two of three never asked for the credit card's minimum, so it is unset while the
scenario's person would have given it. That one is not fixed and is not a recording bug; it is the
coach not asking.

The rest of the table, briefly:

- **`numbers_traceable` 92%**, three runs. Two in `stt_implausible_amount` where the coach offers
  "twelve thousand" for a rent heard as "12" **outside** a question (the offered-reading licence is
  a question only), and one in `correction_and_conflict`. A fourth, in `fragmented_balance`, is the
  model **adding the balance parts itself** — "20,000 in cash and 20,000 in the bank" sent as one
  call for 40,000. The rule caught the one thing this product forbids, from a direction nobody had
  watched. `note`'s description now says one call per part and never add two amounts yourself.
- **`no_premature_plan` 95%**, two runs, both planning with a category never raised.
- **`one_goodbye_with_the_end_call` 75%** and **`one_question_per_turn` 78%** are the advisory cost
  of the redesign, unchanged in shape from the `owner_call_1` cell: the goodbye is the model's own
  now, and it sometimes says it a turn early or not at all.
- **`silent_before_acting` 40% in `returning_changes_rent`** — the returning-caller path, where the
  coach speaks before recording. Advisory, and worth a look if that path matters.

Gates under 95% on this matrix: `numbers_traceable` 92% and `state_matches_facts` 30%. Both have a
named cause above, one is fixed and re-measured, one (the unasked card minimum) is recorded and open.

### 10.15 Three follow-ups from the owner's report, and what they cost · 14 September

Three changes asked for after the owner's before-and-after report, measured on two five-run cells
of `owner_call_1`.

**1. The derivation now reads as lines a person can follow.** The after coach stated the low point
and never explained it, with the arithmetic sitting in the same result — as one dense
comma-separated clause nobody would read aloud. It is now a line per step:

```
why the lowest point is 56,200 on 29 September:
start with 60,000
groceries takes 3,800 by 29 September
that leaves 56,200, the lowest point
salary adds 30,000 on 30 September
rent takes 13,000 on 7 October
closing 71,000
```

and `show_month`'s description says what it is for: "when they ask why a figure is what it is, or
say it looks wrong, the lines under 'why the lowest point is' are the answer: read them out." One
thing that fell out of the rewrite and was nearly missed: the old line said "low point", and
`criteria._low_point` — the predicate deciding whether the judge is asked about the explanation at
all — matches on the word **lowest**. A criterion whose predicate stops matching the product's own
line silently stops applying, and the test that pins the pairing is the only reason it did not.

**2. A coverage fact for when there is nothing left to ask.** One run asked about loans and cards
four times: the result only ever said what had *not* come up, so an empty "not mentioned yet" read
as silence rather than as an answer. Complete coverage now says so — "everything they mentioned is
on the books; nothing left unasked" — with no order attached.

**It did not fix the looping, and the next cell was worse: none of five reached a plan.** The
person in `owner_call_1` never answers the loans question at all; they say "yeah, sure", "walk me
through", "think the calculation is wrong". Coverage therefore never completes, the fact never
fires, and "not mentioned yet: loans or cards" comes back every turn — a fact that cannot change
becomes an instruction to keep asking. The ratchet this report has described in the prompt, in the
result strings and in the check suite has a fourth form: **a standing fact the conversation cannot
satisfy.**

The fix is not in code, because when to stop asking is the model's judgement. One line went into
v2: *"If they will not answer something, say what you will do without it and move on: a plan that
names what it is missing beats a question asked a fourth time."* With it, and with `90,000 to work
with` published (see below), two of five reached a plan. Better than none and worse than the three
of five before any of this, on five runs that cannot tell those apart.

**3. The turn budget was not the cause.** `owner_call_1` went from 26 turns to 36 so it would stop
being one of three candidate explanations. Every run in both later cells ended at 32 turns or fewer,
by the simulated person's own `ends_when` — they say "that makes sense" after the challenge is
answered and the call is over. So the budget is ruled out, and what is left is the real one: **the
coach spends its turns establishing loans and cards while the person is pushing to be walked
through the numbers now.** Which of those a coach should serve is a product judgement, not a bug,
and it is the owner's to make.

**A fourth thing the cells found.** Two runs said "60,000 and 30,000 is 90,000 available" — the
opening balance added to the income, out loud. Identical in shape to the subtraction that produced
`net_flow`: a figure a person asks for, in no result, so the model built it. The month view now
says `opening 60,000 plus in is 90,000 to work with, closing 71,000`. After that, five runs of five
were clean on `numbers_traceable`.

**The cells, in full.** Cell A (after the derivation, coverage-complete and turn-budget changes):
every gate 100% except `numbers_traceable` 60% — the 90,000 — and no run reached a plan. Cell B
(after the v2 line and the "to work with" figure): **every gate 100%**, `one_question_per_turn` and
`one_goodbye_with_the_end_call` 80%, two of five planned. Run ids for cell B:
`owner_call_1-20260914-090351`, `-090352`, `-090353`, `-090353-2`, `-090354`.

`Summary.net_flow` landed from Session A in the middle of this, so the "in minus out" figure is the
engine's own now and the three figures on that line always reconcile; the agent layer works nothing
out except the `opening + in` addition above, which `requests.md` asks A for in the same shape.

### 10.16 Twenty checks fold into three · 14 September

The owner's instruction: too many deterministic checks, and a Langfuse trace nobody can read.
Three now, and the argument for the fold is a bug this report already recorded.

| check | what it carries |
|---|---|
| `money_traceable` | numbers_traceable, claimed_values_recorded, no_spoken_decimals |
| `state_matches_call` | state_matches_facts, actions_match_plan, no_premature_plan |
| `speakable` | banned_phrases, no_iso_dates, no_markdown, no_silent_turn |

**Nothing about what is detected changed.** Each rule is the same function under a private name,
and every violation still names the sub-rule that raised it, in the detail:
`no_spoken_decimals: 56,833.27 rupees`. Granularity moved into the violation rather than out of the
product. Replayed over all **448 saved runs the folded output equals the sub-rules' output exactly**
— same rule, same turn, same detail, run for run, zero mismatches — and that replay is now a test
(`test_the_fold_changes_nothing_it_detects`), which is why the recordings are committed.

**Deleted outright**: the nine advisory rules (one_question_per_turn, silent_before_acting,
amounts_repeated, no_question_after_unknown, one_goodbye_with_the_end_call,
changed_value_acknowledged, implausible_amount_confirmed, carried_confirmed_before_plan,
no_repeated_sentence) and `explains_on_request`, which the judge's
`challenge_answered_without_computing` and `low_point_explained` already cover. How the coach talks
is `led_like_a_coach`'s job now — a criterion a model answers, which a harness cannot ratchet the
way §10.14 describes a gate ratcheting the prompt.

**The argument for the fold is `changed_value_acknowledged`, and it is one of the nine.** It parsed
v1's `rent: 11,000 -> 12,000`; v2 writes `rent 11,000 before, now 12,000`; the rule stopped matching
and went on reporting 100% on runs it was not looking at. A rule per surface is a rule per way to
rot silently, and twenty of them meant twenty chances that a green score means nobody looked. Three
checks over ten sub-rules is not fewer things measured — it is fewer places for that to happen, and
the two pairings that nearly rotted are now pinned by tests against the product's own output.

**Per trace**: about 25 scores before (twenty rules, four criteria, one summary), 8 after (three
checks, four criteria, one summary).

`RuleResult.advisory` leaves the wire contract with the rules it described. One line in the ledger
that belongs here too: with v1 deleted, **the before column of §10.13 can never be re-run** — the
recordings and this report are the record.
