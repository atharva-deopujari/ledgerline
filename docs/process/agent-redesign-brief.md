# Brief: the agent layer, from bot to coach

Decided by the owner on 14 Sep after live call `voice-9869101897-20260913T194053Z`: "a bot, not an
intelligent agent; the state and engine are too deterministic; the model's intelligence is not trusted".
Evidence: the constraint census (109 mechanisms shape the model, 55 of them about language, order and tone,
54 with no recorded failing case, nine result-string orders that can be false of the case they fire on, and a
harness where every check is a hard gate so nothing can ever push a constraint back off), and
`docs/process/luna-capabilities.md`, which said on 13 Sep what this brief now does: identity not
prohibition, subtract before relocate, results fact-only and neutral, docstrings say when, field
descriptions say what. The before table for the owner's own conversation (`owner_call_1`, five runs on the
current build): numbers_traceable 60%, claimed_values_recorded 80%, banned_phrases 80%, every failure on the
turns where the person pushes back.

## The line, restated

Code owns money and memory: arithmetic, dates, the plan, provenance of every spoken figure, what is
persisted. The model owns the conversation: what to ask, in what order, when it knows enough to plan, how
to explain, how to handle doubt. Code informs the model with facts; it commands only where a wrong move loses
money. **The model never computes** stays absolute, and it is enforced by giving the model every number it
could need, not by forbidding it from thinking.

## 1. Prompt (`prompts/v2.md`, B)

Identity, goal, a few hard rules. Target 250 tokens, ceiling 400 (test moves). Shape:

- Who: a calm, experienced money coach on a voice call, helping one person get through the next thirty days.
- Goal: understand their month the way a good coach would before saying anything about it: what comes in and
  when, everything that must go out (rent, EMIs, card dues, bills, fees), everyday spending, anything owed or
  overdue, anything unusual this month. Ask what a coach would ask, in a natural order, more than one thing
  at once when they belong together. When you know enough, look at the month with the tools and explain it
  plainly, then agree with them what to do.
- Hard rules (money): every figure you say comes from a tool result, never from your own arithmetic; when
  asked why a figure is what it is, use the derivation the tool gives you; never suggest new borrowing;
  never say something is approved or guaranteed; record what they tell you with the tools before you say you
  have noted it.
- Voice: short spoken sentences, figures as people say them with "rupees", dates as day and month.

Cut, with the failing case each was added for recorded as "superseded by the goal": one question per turn,
start every reply with the figure, ask missing fields in the given order, the scripted close ("does that and
what happens if you skip it make sense"), a yes is understanding, the goodbye script, the result legend, the
schema duplicates (C1 to C8 of luna-capabilities). English only stays.

## 2. Tools (B; domain support from A already landed or in flight)

Plain words the model would say, code translates. Names and arguments read aloud on a call must sound like
speech, not code. Descriptions say when to use the tool and what a value looks like, in one or two
sentences, no grammar the model must reproduce.

| tool | arguments | replaces |
|---|---|---|
| `note` | `item` (plain name), `amount`, `when` (plain: "7th", "end of month", "spread over the month"), `kind` optional (income, bill, loan or card, spending; code infers when obvious), `might_not_arrive`, `minimum_due`, `must_pay` | `upsert_item` with its enums and flag trio |
| `forget` | `item` | `remove_item` |
| `nothing_more` | `of` (income, bills, loans and cards, spending, balance) or `about` (an item's detail, plain name) | `mark_unknown` and its field grammar; kind-level answer via `state.none_of` (A) |
| `show_month` | none | `finalize_plan` as a gate. Callable any time. Returns the full picture: coverage (what has been stated, what they said there is none of, what has not come up), every item with its figures, timeline summary, low point with its derivation, closing balance, all feasible actions with consequences (not top two), unpaid, warnings, what is excluded and by how much. Marks the plan final when the model says so via `final=true` |
| `what_if` | `changes` (list of plain edits: "skip gym", "pay card in full", "rent on the 10th") | new: engine reruns on a copy, returns the same picture and the deltas |
| `remember_this` | `note` (free text about the person) | soft-notes input for the extractor's vocabulary; optional, only if cheap |
| `done` | `understood` (bool), `reason` | `record_understanding` + `end_call` folded: says whether the person understood and ends the call; the goodbye is the model's own |

`confirm_carried` folds into `note`: restating a carried figure confirms it; "all the same as last time" is
`nothing_more(of="changes since last call")` or a plain confirm flag on `show_month`. The carried blocker is
gone (A); carried items are simply listed with "from last call" in results and the model decides.

Refusals route in plain words and never lecture: "no item called that; on the books: rent, salary,
groceries". Name matching is fuzzy against what is on the books; date parsing accepts what people say.

## 3. Results (B)

Facts and options, no orders, except the three that protect money:
- a figure the person just gave is echoed ("rent 13,000 on the 7th, noted") so the read-back is natural;
- a changed value shows old and new ("rent 12,000 last time, now 13,000");
- a claim without a recording cannot happen because `note` is the only way in.

Gone: "say this back, then ask", "ask once, then finalize", "propose nothing", "go over the actions once
more", "record any other amount before replying", "looks small, confirm it", the one-instruction latch, the
fixed line order, the two-action cap, the three-unpaid cap, `warnings[0]` only, `blocked:` without a route.
Coverage is a fact line: "not mentioned yet: loans or cards, bills other than rent, everyday spending".
Provisional says what is excluded and how much the figures would move. Whole rupees always.

## 4. Turn block (B)

Today, the window, and the coverage facts. No "still missing" list, no phase word, no counts.

## 5. Checks and judge (B)

Gates stay for money and state: `numbers_traceable` (extended: the derivation figures count as provenance),
`state_matches_facts`, `claimed_values_recorded`, `actions_match_plan`, `banned_phrases`, `no_iso_dates`,
`no_markdown`, new `no_spoken_decimals`, new `no_silent_turn`. Move to advisory (reported, never gating):
`one_question_per_turn`, `silent_before_acting`, `amounts_repeated`, `no_question_after_unknown`,
`one_goodbye_with_the_end_call`, `changed_value_acknowledged`, `implausible_amount_confirmed`,
`carried_confirmed_before_plan`. Judge criteria become expertise: "established the full month before
planning", "explained the low point in plain words from the derivation", "answered a challenge without
computing", "led the conversation like a coach". The four `judge_questions` on `owner_call_1` are the first.

## 6. Order of work and acceptance

1. A lands low_point, whole rupees, coverage + none_of, blocker removal (in flight).
2. B: v2 prompt, the tool set, results, turn block, checks split, judge criteria. Keep v1 and the old tools
   behind `PROMPT_VERSION=v1` until the after table is read, then delete.
3. B runs `owner_call_1` five times on the new build, then the full matrix once. Gates: every money check at
   or above 95%; the four judge questions read per run by a human (the owner) from the transcripts.
4. C: session.py wiring for the new tool set and the greeting (the model greets in its own words from the
   goal; GREETING shrinks to "the call has started"). D: cards for `none` rows and the low point derivation.
5. The final report: before and after transcripts of `owner_call_1` side by side, the check table, the judge
   answers, and a plain judgement of whether it reads as an expert.

Spend cap for the phase $1.00. Reinvent nothing: the engine, the store, tracing, the recorder, the harness
all stay. Ponytail pass at the end by every session that touched code.
