# 04. Prior art: LLM-driven structured information gathering, memory, corrections, conflicts

Angle: open-source systems that gather structured facts by conversation and have to survive the same
problems Ledgerline has — partial facts, corrections vs contradictions, "I don't know", uncertain values,
mis-heard numbers, readiness, and derived state that must not go stale.

Companion docs: `01-pipecat-daily-voice-agents.md` §5 (Pipecat Flows `patient_intake` — the fixed-graph
intake shape, already covered there, not repeated here), `docs/research/10-state-and-tools.md`,
`docs/architecture/02-hld.md` §§3–4, 7.

## Summary — ranked by how much we can actually use

1. **Dialogflow CX parameter status** (`UNFILLED`/`FILLED`/`INVALID`/`UPDATED`, `$page.params.status = FINAL`) is the cleanest statement of the idea Ledgerline needs most: a field has a *lifecycle*, not just a value, and readiness is a predicate over those statuses. §3
2. **Rasa `FormValidationAction`** gives the dynamic `required_slots` pattern and, more usefully, the canonical **anti-pattern**: writing `None` back to re-ask conflates "never asked", "rejected" and "declined", which is why Rasa forms loop. Our `Unknown(field, reason)` is the fix. §1
3. **Guardrails AI `on_fail` taxonomy** (`reask` / `fix` / `filter` / `refrain` / `noop`) names our outlier bug exactly: a `reask` the user ignores silently becomes a `noop`. The durable answer is `filter` + block finalisation. §5
4. **LiveKit `examples/survey`** — `AgentTask[T]` with a `_check_completion()` predicate over accumulated partial results, a `disqualify()` refusal tool, and the handler (not the model) driving the next turn. The closest working analogue to our `readiness()` + `describe()` loop. §6
5. **LiveKit `examples/survey/test_survey_agent.py`** is the best multi-turn testing guidance found anywhere: drive until the tool call appears, assert on the *set* of calls, pin `temperature=0.2` and disable parallel tool calls in tests. §8
6. **Instructor** — `Maybe` (explicit escape hatch reduces hallucination), `partial=True` (a half-filled record is valid), and the warning that model-emitted `confidence` floats are not calibrated. §2, §11
7. **Instructor `CitationMixin`** — per-field provenance validated against the source text; the model for storing the utterance span behind a suspicious number. §11
8. **Parlant journeys** — adaptive graphs with backtracking and fast-forward, dynamically loaded per turn, plus canned responses for high-stakes utterances. Confirms our "no state machine, phase derived from readiness" choice. §4
9. **Duckling** — time as `{value, grain}` and ranges as one interval, not two drifting slots; the reference for uncertain income dates. §12
10. **MultiWOZ / SGD** — belief states are latest-write-wins and have no conflict concept; MultiWOZ 2.1's re-annotation changed **32% of state annotations across 40% of turns**, which is the empirical case for keeping both values and asking. §9

**Bottom line:** the seven open problems are all already answered in `domain/state.py` — the design is
ahead of every open-source intake agent found. What prior art adds is (a) six small residual bugs the
implementation still has, (b) a counted re-ask ladder, (c) per-field provenance, and (d) a concrete
testing shape. See "Answers to our seven open problems" and the checklist.

## 1. Rasa forms and `FormValidationAction` (rasa-sdk)

- https://github.com/RasaHQ/rasa-sdk — ~1.1k stars, active (`main` branch, `rasa_sdk/forms.py`).
- Docs: https://rasa.com/docs/rasa/action-server/validation-action and
  https://legacy-docs-oss.rasa.com/docs/rasa/forms/

**What it is.** The oldest widely deployed open-source slot-filling machine. A *form* is a loop with
`required_slots`; a magic slot `requested_slot` holds the one slot currently being asked; the loop
deactivates when every required slot is non-`None`.

**Learnings**

1. **The "what am I asking next" pointer is itself state, not a prompt-time computation.**
   `REQUESTED_SLOT = "requested_slot"` is a real slot on the tracker, so the policy can condition on it
   (`influence_conversation: true`) and handle "unhappy paths" differently depending on *which* question
   is outstanding. Ledgerline computes the same thing per turn in `missing()`; storing the top item as
   `state.asking` would let us count re-asks and detect "asked three times, still nothing".

2. **`required_slots` is a method, not a list — question ordering is dynamic and data-dependent.**

   ```python
   async def required_slots(self, domain_slots, dispatcher, tracker, domain):
       additional_slots = ["outdoor_seating"]
       if tracker.slots.get("outdoor_seating") is True:
           additional_slots.append("shade_or_sun")
       return additional_slots + domain_slots
   ```
   Slots are *unlocked by other slots' values*. Our `missing()` already does the derived-gap version of
   this (a debt only needs `min_due` once `debt_kind == CREDIT_CARD`). Validated pattern.

3. **`next_requested_slot` is literally "first required slot whose value is `None`":**
   [`rasa_sdk/forms.py`](https://github.com/RasaHQ/rasa-sdk/blob/main/rasa_sdk/forms.py)
   ```python
   missing_slots = (
       slot_name for slot_name in required_slots
       if tracker.slots.get(slot_name) is None
   )
   return SlotSet(REQUESTED_SLOT, next(missing_slots, None))
   ```
   `requested_slot = None` *is* the readiness predicate. Ledgerline's `readiness().blockers == []`
   is the same idea with a richer predicate.

4. **Rejection re-asks by writing `None` back.** A validator that dislikes a value returns
   `{"cuisine": None}` and the loop re-requests it. This is the **anti-pattern for us**: it conflates
   "never asked", "asked and rejected" and "user declined" into one `None`. Rasa needs separate
   `ignored_intents` / `not_intent` machinery and hand-written `stop` rules to stop re-asking, and the
   Rasa forums are full of "form keeps asking the same question" threads for exactly this reason.
   Ledgerline's `Unknown(field, reason)` with `_NEVER_ASK_AGAIN` is the fix Rasa never made: a
   three-valued field (`value` / `not asked` / `recorded as unanswerable-with-reason`).

5. **Extraction and validation are two separate passes over the same slot set**
   (`get_extraction_events` then `get_validation_events`, each re-reading `required_slots`, each
   writing back to the tracker so later handlers see earlier writes). Our handlers mutate then
   `build_plan()` — same record-then-derive ordering.

6. **Anti-pattern seen in the code itself:** slot extraction silently no-ops with a `warnings.warn`
   when a method is missing (`"Skipping validation for {slot_name}: there is no validation method"`).
   Silent skips in a gathering loop mean the form deactivates with a slot the developer thought was
   validated. Our equivalent risk is a `field_of()` string that no `question_for()` knows — worth a
   test that every field `missing()` can emit has a question.

## 2. Instructor — `Maybe`, optional fields, `partial=True`

- https://github.com/567-labs/instructor — ~12k stars, very active.
- https://python.useinstructor.com/concepts/maybe/ and
  https://python.useinstructor.com/learning/patterns/optional_fields/

**What it is.** Pydantic-schema-constrained LLM extraction. Two patterns matter to us.

**Learnings**

1. **The `Maybe` type: give the model an explicit escape hatch instead of letting it guess.**
   ```python
   class MaybeUser(BaseModel):
       result: Optional[UserDetail] = None
       error: bool = False
       message: Optional[str] = None   # why extraction failed
   # or: instructor.Maybe(UserDetail)
   ```
   The docs' stated motivation is verbatim our problem: *"providing language models with an escape
   hatch can effectively reduce hallucinations."* Ledgerline's `mark_unknown(field, reason)` is a
   `Maybe` at the tool boundary rather than the schema boundary — the same escape hatch, but ours
   **persists** the `message`/`reason`, which the Instructor pattern does not.

2. **Optional ≠ unknown.** Instructor's guidance is that `Optional[T] = None` tells the model "skip
   when unavailable **or uncertain**" — the two collapse. That collapse is exactly open problem (1)
   and (3). The lesson for us is the negative one: a nullable field alone cannot distinguish
   *not yet asked* from *asked and unknowable*, so the distinction has to live in a sibling structure
   (our `unknowns` list), not in the nullability of the value.

3. **`partial=True` validates a model whose optional fields are still missing** — built for streaming
   and truncation, but the shape generalises: *a half-filled record is a first-class object, not an
   error*. This is the direct precedent for treating "item exists with `amount=None`, amount arrives
   two turns later" as **completion**, not conflict (open problem 1). Our `upsert()` docstring already
   states the rule — "a field that was unknown becoming known is completion, not a contradiction" —
   and Instructor is the citation for it.

## 3. Google Dialogflow CX form parameters (closed source, but the reference semantics)

- https://docs.cloud.google.com/dialogflow/cx/docs/concept/parameter
- Open equivalents that copy the model: Rasa forms (§1), Botpress "capture" cards, Jovo `$session.state`.

**What it is.** Per-page *form* of parameters, each `required` or not, each with an *initial prompt
fulfillment* and *reprompt event handlers*.

**Learnings (the two that matter most to Ledgerline)**

1. **Every parameter carries a lifecycle status, not just a value.**
   `$page.params.<parameter-id>.status` is one of `UNFILLED` / `FILLED` / `INVALID` / `UPDATED`, and
   `$page.params.status = "FINAL"` is the whole-form readiness predicate. **Four states, not two.**
   `INVALID` is precisely the state Ledgerline needs for an STT outlier: a value exists, it is on the
   record, and the form is *not* `FINAL` until it is resolved. Our `state.outliers` list already
   implements this (`_record_outlier` blocks readiness via `unconfirmed amount on {field}`), and the
   Dialogflow status enum is the prior art that says a per-field status is the right shape — arguably
   better than a parallel list, because it cannot be orphaned when the item is removed (open problem 7).

2. **Re-asking is counted, and the count is an event you can branch on.**
   Reprompt handlers fire on `sys.no-match-1`, `sys.no-match-2`, ... `sys.no-match-default`, likewise
   `sys.no-input-N`. "If a required parameter value is not provided after an agent prompt, the initial
   prompt will be repeated unless a different behavior is defined in the reprompt handlers." The
   escalation ladder — rephrase on 1, offer to skip on 2, move on at default — is the standard fix for
   a stuck gathering loop. Ledgerline has no `asked_count`; adding one to `Unknown`/`missing()` gives us
   "ask twice, then `mark_unknown(reason='user_does_not_know')` ourselves" without needing the model to
   volunteer it (open problem 3).

3. **Order is explicit and reorderable** ("collected in the order defined on the page"), and only one
   parameter is normally filled per turn, though the engine may fill several when an intent supplies
   them. Our design deliberately inverts this: the *user* sets the order, `missing()` only ranks what is
   left. Good — but their "one per turn" rule is the same constraint our prompt states as "exactly one
   question a turn".

4. **Redaction is a per-parameter flag** (`$parameter-name_redacted` in logs). Relevant to money data if
   Ledgerline ever logs transcripts.

## 4. Parlant — guidelines and journeys

- https://github.com/emcie-co/parlant — ~10k stars, very active 2026.
- Docs: https://parlant.io/docs/concepts/customization/journeys

**What it is.** An "interaction control harness": *guidelines* are `condition → action` pairs matched
per turn, *journeys* are multi-turn SOPs expressed as a state diagram of chat states, tool states and
fork states.

**Learnings**

1. **Journeys are adaptive graphs, not linear forms.** The docs are explicit: the agent "may jump
   multiple states (if the conditions for doing so apply), revisit previous ones, or adjust its pace",
   with **backtracking when the customer changes a previous decision** and **fast-forward when the
   customer supplies several answers at once**. Those two behaviours are exactly our correction path and
   our parallel-`upsert_item` path. Parlant is the strongest evidence that a fixed-graph intake
   (Pipecat Flows `patient_intake`, see `01-pipecat-daily-voice-agents.md` §5) is not the ceiling — but
   also that if you keep a graph you must bolt backtracking on. Ledgerline's "no state machine, phase is
   derived from `readiness()`" avoids the bolt-on entirely.

2. **Only relevant guidelines and journeys are loaded into the LLM context each turn** ("Dynamic
   Loading", "Scoped Resources" — guidelines scoped to a journey, even to a single state). This is the
   same economy as our `turn_block()`: the base prompt is fixed and small, and only the top five
   missing facts plus the open conflicts are injected per turn. Independent convergence on the design.

3. **Canned responses** — pre-approved response templates "that eliminate hallucination at critical
   moments." Our equivalent is the hard rule "every figure must come from the latest tool result" plus
   result strings that carry the question verbatim. Parlant's stronger version (the model *selects* a
   template rather than generating) is worth noting as the escalation if figure hallucination shows up
   in evals — it would apply best to the `finalize_plan` summary, the highest-stakes utterance.

4. **Guidelines outrank journey states** and can attach tools. The analogue for us: the hard rules in
   `prompts/v1.md` must beat anything the per-turn block says, which is why the base prompt is first in
   `system_instruction()` and the block is appended, not prepended.

## 5. Guardrails AI — `on_fail` policies

- https://github.com/guardrails-ai/guardrails — ~5k stars.
- https://github.com/guardrails-ai/guardrails/blob/main/docs/hub/concepts/on_fail_policies.md

**What it is.** Validators over LLM output fields, each with a corrective policy.

**Learning: the taxonomy of "what do you do with a value you don't trust" is a closed set of six.**
`reask` (send it back to the model with *which* criterion failed), `fix` (programmatic repair),
`filter` (structured data only — drop just the failing field, keep the rest), `refrain` (return
nothing), `noop`, `exception`, `fix_reask`.

Mapped onto Ledgerline's outlier problem (open problem 6): we currently do the equivalent of `reask` —
`outlier_question()` goes into the result string and the model asks. The bug the brief describes is that
we did `reask` *without persistence*, so a `reask` the user ignored became a silent `noop`. The
correct combination is **`filter` + block**: keep the item, exclude the suspect amount from the maths,
and refuse `finalize_plan` while it stands. `state.outliers` + the `readiness()` blocker
`unconfirmed amount on {field}` is that combination, and `confirm_untouched()` explicitly refuses to
let silence confirm a doubted amount:

```python
doubted = {o.field for o in state.outliers}
for kind, item in _items(state):
    if field_of(kind, item.name) in doubted:
        continue  # an amount the bot has questioned is never confirmed by silence
```
That guard is the single most important line for problem 6 and it should have a dedicated test.

## 6. LiveKit Agents `examples/survey` — typed sub-tasks with a completion predicate

- https://github.com/livekit/agents — ~8k stars, extremely active (`main`, 2026).
- https://github.com/livekit/agents/tree/main/examples/survey (`agent.py`, `test_survey_agent.py`)
- Docs referenced by the example: https://docs.livekit.io/agents/logic/tasks/

**What it is.** A screening-interview voice agent. Each stage is an `AgentTask[ResultType]` with its own
instructions and its own `record_*` tools; a `TaskGroup` sequences them and collects typed results.

**Learnings**

1. **Facts are recorded one tool call at a time into a plain dict, and completion is a predicate over
   the keys — not a counter, not a graph edge.**
   ```python
   @function_tool()
   async def record_strengths(self, strengths_summary: str):
       self._results["strengths"] = strengths_summary
       self._check_completion()

   def _check_completion(self):
       if self._results.keys() == {"strengths", "weaknesses", "work_style"}:
           self.complete(BehavioralResults(**self._results))
       else:
           self.session.generate_reply(
               instructions="Continue incrementally collecting the remaining answers "
                            "for the behavioral stage. Maintain a conversational tone."
           )
   ```
   This is `readiness()` in miniature, and the `else` branch is the important half: **the handler, not
   the model, decides that gathering continues, and it says so in the same turn.** Ledgerline does the
   equivalent with `describe(outcome, plan)` + the per-turn "Still missing" block. Note LiveKit reaches
   for `generate_reply(instructions=...)` — a second steering channel besides the tool result. We have
   the same channel available (`LLMUpdateSettingsFrame` / a developer message) if a result string ever
   proves too weak to redirect the model.

2. **The record tools are per-field (`record_strengths`, `record_weaknesses`, `record_work_style`), and
   the task explicitly says "in no particular order".** The unordered-collection instruction is
   verbatim our design. The per-field-tool choice is the alternative we rejected in
   `docs/research/10-state-and-tools.md` §1; it buys a tighter JSON schema per field (`work_style` is an
   enum) at the cost of N tools. Our single `upsert_item` with `kind` keeps the model's habit simple but
   loses per-field enum constraints — the compensating control is `_one_of()` validation in
   `tools.py` returning a *repair instruction* ("Call upsert_item again with debt_kind set to one of:
   ..."), which is the right shape.

3. **Refusal is a first-class tool with a recorded reason, and it terminates.**
   ```python
   @function_tool()
   async def disqualify(context: RunContext, disqualification_reason: str) -> None:
       """Call if the candidate refuses to cooperate ..."""
   ```
   Same shape as `mark_unknown(field, reason)` and `end_call(reason)`. The learning is that a
   *refusal path must be a tool, not a prompt instruction*, or the model improvises around it.

4. **`livekit.agents.beta.workflows` ships `GetEmailTask`** — a prebuilt "collect this one hard-to-hear
   value, with spelling and confirmation" task. Evidence that verification-of-a-mis-hearable-value is
   common enough to be a framework primitive, which is the generic form of our STT-outlier problem.

## 7. LiveKit Agents `examples/drive_thru` — mutable item collection with a change hook

- https://github.com/livekit/agents/tree/main/examples/drive_thru (`order.py`, `agent.py`,
  `database.py`, `test_agent.py`)

**Learnings**

1. **The change hook that pushes UI state is fired inside the mutation and is exception-isolated.**
   [`order.py`](https://github.com/livekit/agents/blob/main/examples/drive_thru/order.py)
   ```python
   @dataclass
   class OrderState:
       items: dict[str, OrderedItem]
       # Optional async hook fired after every add/remove. The agent
       # wires this up to push the current cart to the playground UI;
       # exceptions inside the hook never block the order mutation.
       on_change: Callable[[], Awaitable[None]] | None = None

       async def _fire(self) -> None:
           if self.on_change is None: return
           try: await self.on_change()
           except Exception: logger.exception("OrderState.on_change failed")
   ```
   This is exactly Ledgerline's "push cards through an injected callback" (HLD §4) — **including the
   detail we should copy verbatim: a failed card push must never fail the state mutation or the tool
   result.** Worth checking `ToolContext.recompute_and_push` wraps the push in `try/except`.

2. **Items are keyed by a generated `order_id`, not by name, and modification is remove-then-re-add.**
   The agent is instructed to call `list_order_items` first when it does not know the `order_id`. That
   is a **round trip we do not pay** because `(kind, normalise_name(name))` is a natural key the model
   already knows from the conversation. But it is also why drive-thru has no correction semantics at
   all: re-adding mints a new id, so there is nothing to compare against, no provenance, no conflict.
   Our natural key is what makes conflict detection possible; keep it.

3. **Tool schemas are built dynamically with the valid ids injected as a JSON-schema `enum`**
   (`build_combo_order_tool`, `build_regular_order_tool` close over the item lists). The generic lesson:
   *constrain the argument space with the schema when the valid set is known*. Ledgerline's open set of
   item names cannot use this, but `kind`, `debt_kind`, `reason` and `chosen` all can and should be
   literal enums in the tool schema, not validated strings.

4. **Discriminated unions for heterogeneous records:**
   `OrderedItem = Annotated[OrderedCombo | OrderedHappy | OrderedRegular, Field(discriminator="type")]`
   — the same shape as our four item models keyed by `ItemKind`.

## 8. Scripted multi-turn testing: `examples/survey/test_survey_agent.py`

- https://github.com/livekit/agents/blob/main/examples/survey/test_survey_agent.py
- Practices it documents: https://docs.livekit.io/agents/logic/tasks/#testing-task-groups

The module docstring is an unusually candid list of the traps in testing a multi-turn gathering agent,
and every one of them applies to Ledgerline's `tests/` and `evals/`:

- **Drive multiple turns; don't assert on one turn.** *"The LLM often replies conversationally before
  invoking a completion tool. `_drive_until_called` sends an initial input, then keeps nudging until
  every expected tool name appears in `sess.history.items`."* Assert on the *set* of tool calls made
  across a scripted transcript, never on the tool call at index N.
  ```python
  extra_kwargs={"parallel_tool_calls": False, "temperature": 0.2}
  ```
  Temperature pinned low and parallel tool calls disabled **for tests only** — a cheap determinism lever.
- **Prefer `contains_function_call()` over `next_event()`** — "don't couple the test to a specific event
  index in a single `RunResult`."
- **Parse `item.arguments` with `json.loads`** and assert on the arguments, or assert on the resulting
  state (`userdata`), not on the wording of the reply.
- **Don't assert on startup output** — the greeting is produced before the first driven turn.
- **Test each sub-task in isolation and then the whole group** — four isolation tests plus one
  `test_full_task_group_flow`.

For Ledgerline this argues for two layers, which is what `docs/architecture/02-hld.md` §9 already
wants: (a) pure fixtures against `state.upsert/remove/resolve_conflict/mark_unknown` with no LLM at all
— the seven open problems are all testable this way and *should be*; (b) a small number of scripted
LLM transcripts asserting "the set of tool calls contains `mark_unknown` and never contains a second
`upsert_item` for the same field".

## 9. Dialogue state tracking corpora: MultiWOZ and the Schema-Guided Dialogue dataset

- https://github.com/google-research-datasets/dstc8-schema-guided-dialogue (~600 stars)
- MultiWOZ 2.1 (state corrections): https://arxiv.org/pdf/1907.01669 ·
  MultiWOZ 2.2: https://arxiv.org/pdf/2007.12720
- Survey of the field: https://github.com/yukyunglee/Awesome-Dialogue-State-Tracking

**Learnings**

1. **The academic belief state has no notion of a conflict — and that is a documented weakness.**
   In SGD, `slot_values` maps a slot to a list, but the list holds *spoken variants of one value*
   ("6 pm", "six in the evening"), for non-categorical slots; categorical slots carry exactly one.
   The state is always "the current belief", latest-write-wins. MultiWOZ 2.1's own abstract is the
   cautionary tale: re-annotation "resulted in changes to over 32% of state annotations across 40% of
   the dialogue turns" — i.e. **when humans re-read the same transcripts, a third of the latest-write
   beliefs were wrong.** That is the empirical case for Ledgerline keeping both values in a `Conflict`
   and asking, rather than silently overwriting.

2. **Corollary for problem 2 (conflicts detected only on amount).** DST treats every slot in the schema
   uniformly — there is no privileged slot. Restricting conflict detection to `amount` is an
   implementation shortcut with no precedent behind it; the principled rule is "any *financially
   material* field", which `upsert()`'s docstring already states (amount, date, card minimum, debt kind,
   opening balance). The gap is between the docstring and what the code compares.

3. **Prompt-based LLM DST feeds the model "previous dialogue state + the conversation so far"** —
   the belief state is re-serialised into the prompt each turn rather than left implicit in the message
   history. Our `turn_block()` does the compact version of this (counts, missing, conflicts). The
   research consensus is that serialising the state beats relying on the model to re-read history.

## 10. Briefly noted, lower value for us

- **NVIDIA NeMo Guardrails / Colang 2.0** — https://github.com/NVIDIA-NeMo/Guardrails. Colang is an
  event-driven language for multi-turn flows with pattern matching over an event stream, but its
  published material is about safety rails, not slot state; multi-turn support is still an open
  feature request (https://github.com/NVIDIA/NeMo-Guardrails/issues/945). No correction semantics to
  borrow.
- **Microsoft TypeChat** — schema-as-TypeScript-types with a validate-and-repair loop. Its one
  transferable idea (repair by feeding the *validation error text* back to the model) we already do in
  `_refused()`: `"...Call upsert_item again with debt_kind set to one of: {DEBT_KINDS}."`
- **Pipecat Flows `patient_intake`** — covered in `01-pipecat-daily-voice-agents.md` §5. The fixed-graph
  intake; not repeated here.

## 11. Instructor `CitationMixin` and per-field confidence — provenance

- https://python.useinstructor.com/concepts/citation/
- https://python.useinstructor.com/concepts/reask_validation/

**Learnings**

1. **`CitationMixin` attaches `substring_quotes` to an extracted record and validates that each quote
   actually occurs in the source text**; a quote that does not exist fails validation and the model is
   re-asked. This is per-field provenance with a *machine-checkable* link back to the utterance. The
   voice analogue: store the transcript span that produced an amount alongside the amount. For
   Ledgerline that is cheap (`Item.notes` / a new `source_text` field on the item or on the outlier) and
   it is what turns "the bot asked about 45 once" into "the bot can say *'you said forty-five — did you
   mean forty-five thousand?'*" on a later turn, which is the fix for open problem 6.

2. **Validators receive a `context` and re-ask on failure** — the "repair with the reason" loop.

3. **The documented caveat is important and worth writing into our design notes:** a model-emitted
   `confidence: float` is *not* a calibrated probability — "a 0.95 score means 'the model expressed high
   confidence in its reasoning', not '95% chance correct'." So **do not** add an LLM-supplied confidence
   to `upsert_item`. Ledgerline's outlier detection is deterministic and range-based
   (`outlier_question()`: rent < 500, salary < 1000, ...), which is the right call. Deepgram's
   per-word STT confidence, if we ever plumb it through, *is* calibrated and would be a legitimate
   second signal.

## 12. Duckling — how classical NLU represents uncertain and range-valued time

- https://github.com/facebook/duckling (~4k stars; the Rasa/Dialogflow date extractor)
- Rasa integration notes: https://forum.rasa.com/t/duckling-and-filling-slots/10504

**Learnings**

1. **A resolved time is `{value, grain}`, not a timestamp.** `grain` is one of `second … day, week,
   month, year`: "next week" resolves to a day *with* `grain: "week"`, so downstream code knows the
   precision it was given. Ledgerline's `day_of_month` silently asserts day-grain precision for
   "sometime early next month".

2. **An interval is a distinct value type with `from` and `to`**, and Duckling returns a **`values`
   array of several competing interpretations** rather than one answer, leaving the caller to choose.
   The Rasa forum threads on "multiple, conflicting high-confidence results from Duckling" are the
   known failure mode: frameworks that force a single value at extraction time push the ambiguity into
   the application, where it shows up as a wrong slot. Ledgerline's answer to open problem 4 is already
   the interval type — `day_of_month` (earliest) + `latest_day_of_month` (latest) + `certainty` on
   `Income`, consumed by the engine as "uncertain income takes its latest date" (HLD §5.2). Duckling is
   the prior art that says an interval must be *one* value, not two independent slots that can drift
   apart — so `latest_day_of_month < day_of_month` must be a validation error, not a stored state.

## Answers to our seven open problems

Ledgerline's current `domain/state.py` already answers most of these; what follows says which prior art
backs each answer and, where the code and the docstring disagree, what is still open.

### (1) Partial facts — an item with a null amount later completed must be completion, not conflict

**Prior art.** Instructor `partial=True` treats a half-filled model as valid, not as an error
(https://python.useinstructor.com/learning/patterns/optional_fields/). Dialogflow CX gives every
parameter a status of `UNFILLED` / `FILLED` / `INVALID` / `UPDATED` — filling an `UNFILLED` parameter is
never a conflict, only `FILLED → different FILLED` is
(https://docs.cloud.google.com/dialogflow/cx/docs/concept/parameter).

**Our answer — already implemented.** `state.py:400-402`:
```python
for field_attribute, _, was, fresh in proposed:
    if was is None:
        continue  # an unknown becoming known is completion, not a contradiction
```
**Residual gap (recommend fixing).** A field that was `mark_unknown`'d and *then* answered stays in
`state.unknowns`. `missing()` will not re-ask it (right), but `noted_unknowns()` still shows it on the
"not known" card and it still reads as a reason the plan is provisional (wrong). `upsert()` should drop
any `Unknown` whose `field` it just filled — the same cascade `remove()` already does via
`_clear_unresolved`.

### (2) Conflicts detected only on amount, not dates / min due / debt kind

**Prior art.** DST schemas treat every slot uniformly — there is no privileged slot
(https://github.com/google-research-datasets/dstc8-schema-guided-dialogue). Rasa validates every slot in
`required_slots`, not one.

**Our answer — already implemented** via `_MATERIAL`, which is the explicit list of financially material
fields per kind (`state.py:108`):
```python
_MATERIAL = {
    ItemKind.INCOME: (("amount","amount"), ("date","date")),
    ItemKind.DEBT:   (("amount","amount_due"), ("due_date","due_date"),
                      ("min_due","min_due"), ("kind","kind")),
    ItemKind.ESSENTIAL: (("amount","amount"), ("due_date","due_date")),
    ItemKind.OPTIONAL:  (("amount","amount"), ("date","date")),
}
```
Soft fields (`certainty`, `spread`, `survival`, `flexible`) deliberately never conflict — they are
preferences, not claims.

**Residual gap (recommend fixing).** The conflict loop `return`s on the *first* conflicting field, and
the `setattr` loop that applies the rest of `proposed` is below that return. So "actually it's fifteen
thousand on the tenth" — a turn that changes both amount and date — records a conflict on the amount and
**silently discards the date change**. Either collect every conflicting field into one `Conflict` batch
before returning, or apply the non-conflicting changes first and then return the conflict.

### (3) "User does not know" still re-enters the question queue

**Prior art.** This is the classic Rasa failure — validation writes `None` back and the form re-asks
forever, because `None` means both "never asked" and "cannot be answered"
(https://legacy-docs-oss.rasa.com/docs/rasa/forms/). Dialogflow CX solves the loop with counted reprompt
events `sys.no-match-1 … sys.no-match-default`, escalating to a different page. Instructor's `Maybe`
carries `error` + `message` rather than a bare `None`.

**Our answer — already implemented.** `Unknown(field, question, reason)` with
`_NEVER_ASK_AGAIN = ("user_declined", "not_applicable", "user_does_not_know")` excluded from
`missing()`, while `noted_unknowns()` (only `user_does_not_know`) keeps them on the card and the plan
provisional. `readiness()` explicitly refuses to let a recorded unknown become a blocker, with the
reason written into the code comment — "Leaving it in would strand the call, because `missing()` no
longer offers a question for it." That is the correct three-valued design.

**Residual gap (recommend).** Nothing counts *re-asks*. Borrow the Dialogflow ladder: add
`asked: int` to the `Unknown`/missing entry, increment when a field is at the top of the turn block,
and after two unanswered turns have the *handler* record `mark_unknown(reason="user_does_not_know")`
itself rather than waiting for the model to volunteer it.

### (4) Uncertain income and date ranges have no tool inputs

**Prior art.** Duckling resolves time as `{value, grain}` and represents a range as one interval value
with `from`/`to`, returning a `values` array of competing readings rather than forcing one
(https://github.com/facebook/duckling). The known failure mode — "multiple, conflicting high-confidence
results from Duckling" on the Rasa forum — is what happens when a range is flattened to a point.

**Our answer — already implemented.** `upsert_item` takes `certainty` and `latest_day_of_month`;
`state.py` stores them as `soft` fields on `Income`; the engine takes the latest date for uncertain
income (HLD §5.2); `prompts/v1.md` tells the model: *"If income may not come, set certainty uncertain.
Over a range of days, give the earliest as day_of_month, the latest as latest_day_of_month."*

**Residual gap (recommend).** The pair is two independent fields that can drift. Duckling's lesson is
that an interval is one value: reject `latest_day_of_month` earlier than `day_of_month` in `tools.py`
`_day()`/`_income_fields()` with a repair message, and treat "uncertain with no `latest`" as a
structural gap in `missing()` so we ask for the late edge.

### (5) Confirming a fully affordable plan with zero actions

**Prior art.** Teach-back (asking the person to restate) is a *healthcare* technique with measured
benefit — comprehension deficit fell from 49% to 11.9% in the EM-TeBa ED study
(https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7513274/) — but it is a technique for *discharge
instructions that contain actions*. With no actions there is nothing to teach back, and asking anyway
reads as an exam. LiveKit's survey tasks confirm by **completing when the predicate holds and moving
on**, not by asking for a recital. Parlant's canned responses cover the "critical moment" utterance
with an approved template rather than free generation.

**Our answer — already implemented, and deliberately not teach-back.** `prompts/v1.md`: *"Then ask once
if that works or they'd change anything. **Never ask them to repeat it back.** A yes, 'makes sense' or
'got it' is agreement."* And `record_understanding` states it in the handler comment: *"Agreement is the
whole test. Gaps exist only to tell you what to go over again when the person is unsure."*

**Residual gap (recommend).** When `plan.actions` is empty, `describe(None, plan)` emits only the plan
shape, the shortfall/surplus and the totals — no action phrases. The model is then free to invent
something to say. Add an explicit clause to `describe()` for the zero-action case
("nothing needs changing; you finish the month with a surplus of X") so the one sentence the model has
to work with is supplied, exactly as the "canned response" pattern prescribes. Cover it with a fixture:
a state with a large balance and one small expense must finalise, speak a surplus, and never produce an
action phrase.

### (6) Outlier amounts (STT heard "45" for 45,000) reach the final plan

**Prior art.** Guardrails AI's `on_fail` taxonomy names the exact bug: a bare `reask` that the user
ignores degrades to `noop`. The durable combination is `filter` (keep the record, exclude the bad field)
plus a refusal to emit a final result
(https://github.com/guardrails-ai/guardrails/blob/main/docs/hub/concepts/on_fail_policies.md).
Dialogflow CX's `INVALID` parameter status keeps the form out of `FINAL`. Instructor's `CitationMixin`
keeps the source span so the re-ask can quote it back
(https://python.useinstructor.com/concepts/citation/). Instructor's own docs warn that a model-emitted
`confidence` float is not calibrated — so keep detection deterministic.

**Our answer — already implemented.** `state.outliers` is a real list of `Conflict` records
(`_record_outlier`), readiness adds `unconfirmed amount on {field}` as a blocker so `finalize_plan`
refuses, and `confirm_untouched()` has the decisive guard:
```python
doubted = {o.field for o in state.outliers}
...
if field_of(kind, item.name) in doubted:
    continue  # an amount the bot has questioned is never confirmed by silence
```
Detection is a deterministic range check in `outlier_question()`, not an LLM confidence.

**Residual gap (recommend).** No provenance. Store the transcript span that produced the number
(`Conflict.source_text`, or reuse `Item.notes`) so the second ask can be "you said forty-five — was that
forty-five thousand?" rather than a generic re-ask. This is the `CitationMixin` idea at voice scale, and
it is what makes a second ask land differently from the first.

### (7) Removing an item leaves its unknowns and conflicts behind

**Prior art.** Rasa has no cascade at all — `SlotSet(slot, None)` clears one slot and any derived
state you built yourself is your problem, which is why "form re-asks after the user cancels" is a
recurring forum thread. LiveKit's `OrderState.remove` pops the item and fires the change hook so the UI
cannot show a stale cart. LangGraph makes the general point structurally: derived fields are produced by
reducers from the state, never stored independently.

**Our answer — already implemented.** `remove()` calls `_clear_unresolved(state, prefix)`, which strips
`unknowns`, `conflicts` and `outliers` sharing the item's field prefix, and its docstring names the
failure it prevents: *"Otherwise a paid-off expense keeps showing as a 'not known' chip and its conflict
keeps blocking finalisation forever."*

**Residual gaps (recommend).**
- `remove()` (and any post-finalisation `upsert`) does not invalidate `state.understanding` or
  `state.plan_final`. Delete a debt after the person agreed to the plan and the state still claims an
  agreed plan that no longer exists. Any material mutation while `plan_final` is true should clear
  `understanding` and set `plan_final = False`, pushing `readiness().phase` back to `ready`.
- Copy LiveKit's exception isolation on the card push: a failed `on_change`/`recompute_and_push` must
  never fail the mutation or the tool result.

## Ideas to adopt in Ledgerline

| # | Idea | Prior art | Effort | Files |
|---|---|---|---|---|
| 1 | `upsert()` clears any `Unknown` for a field it just filled (completion cascade, mirror of `remove()`) | Dialogflow `UNFILLED → FILLED`; Instructor `partial` | **S** | `domain/state.py`, `tests/domain/test_state.py` |
| 2 | Conflict loop must not swallow the non-conflicting half of a multi-field update | DST uniform slots; Rasa validates all slots | **S** | `domain/state.py`, `tests/domain/test_state.py` |
| 3 | Reject `latest_day_of_month < day_of_month` with a repair message; make "uncertain with no latest" a structural gap | Duckling interval `{from,to,grain}` | **S** | `agent/tools.py`, `domain/state.py` (`missing`), `tests` |
| 4 | Explicit zero-action clause in `describe()` for a finalised plan with no actions | Parlant canned responses; teach-back is for action lists | **S** | `agent/tools.py`, `tests/agent/test_tools.py` |
| 5 | Exception-isolate the card push so it can never fail a mutation or a tool result | LiveKit `OrderState._fire` | **S** | `agent/tools.py` (`ToolContext.recompute_and_push`) |
| 6 | Invalidate `plan_final` + `understanding` on any material mutation after finalisation | LangGraph derived-state discipline | **S** | `domain/state.py`, `agent/tools.py`, `tests` |
| 7 | `asked: int` on missing entries; auto-`mark_unknown` after two unanswered turns | Dialogflow `sys.no-match-1..N` ladder | **M** | `domain/models.py`, `domain/state.py`, `agent/prompt.py`, `tests` |
| 8 | Store the source utterance span on an outlier/conflict and quote it in the re-ask | Instructor `CitationMixin` | **M** | `domain/models.py`, `domain/state.py`, `agent/tools.py`, `prompts/v1.md` |
| 9 | Move `kind`, `debt_kind`, `reason`, `chosen` to real JSON-schema enums instead of validated strings | LiveKit dynamic enum tool schemas | **M** | `agent/tools.py` |
| 10 | Test suite shape: deterministic pure-state fixtures for all seven problems, plus a few scripted transcripts asserting on the *set* of tool calls with `temperature=0.2, parallel_tool_calls=False` | `examples/survey/test_survey_agent.py` | **M** | `tests/domain/`, `tests/agent/`, `evals/` |
| 11 | Property test: every field `missing()` can emit has a non-empty `question_for()` | Rasa's silent "no validation method" skip | **S** | `tests/domain/test_state.py` |
| 12 | Keep `state.asking` (the field currently being asked) as real state, so re-asks and "answered a different question" are detectable | Rasa `requested_slot` | **M** | `domain/models.py`, `domain/state.py`, `agent/prompt.py` |
| 13 | If figure hallucination shows up in evals, template the `finalize_plan` summary rather than free-generating it | Parlant canned responses | **L** | `agent/prompts/v1.md`, `agent/tools.py`, `evals/` |
