# 10. State model and tool design for conversational fact extraction (voice)

Scope: how gpt-5.6-luna extracts a person's finances into one Pydantic state object via function calls, how corrections and conflicts flow, and how the prompt keeps the model asking the right next question without a questionnaire. Pipecat internals are out of scope (see other docs).

## Decision summary

- **Tool shape: option B+ (generic `upsert_item` / `remove_item` per kind, with a small set of purpose-built control tools).** One `upsert_item(kind, name, fields)` with an enum `kind` keeps the toolset under ten, keeps schemas strict, and gives the model one habit ("every fact becomes an upsert"). Per-entity tools (option A) multiply schemas without adding accuracy; whole-state JSON (option C) is the worst for corrections, streaming latency and testing.
- **Upsert is idempotent by `(kind, normalized_name)`.** "Actually my rent is 12,000" hits the same record as "rent is 11,000" from three turns earlier. The handler, not the model, decides whether a call is create, update or conflict.
- **Conflicts are detected in code, stored in state, and resolved by a tool.** A different amount for an existing record inside a recent window (default 6 turns, or any time the previous value was already `confirmed`) creates a `Conflict` entry; the tool result tells the model exactly what to ask; cards render "needs confirmation" until `resolve_conflict` runs.
- **Missing info is hybrid.** The engine derives structural gaps deterministically (debt without minimum payment, income without frequency); the model records conversational unknowns with `mark_unknown` so it stops re-asking. Both feed a "still missing" block re-injected into the system prompt every turn.
- **Numbers: record provisionally, confirm selectively.** Every upsert writes `confirmed=false`; the model repeats the figure back in its next sentence (implicit confirmation) and the handler flips to confirmed on the next non-contradicting user turn. Explicit "did you say X?" only when STT confidence is low, a value is a plan-critical outlier, or a conflict exists. Never block the pipeline on confirmation; that costs a full turn.
- **The model never speaks a number that did not come back in a tool result.** Every tool result returns recomputed totals; the prompt bans arithmetic and estimates.
- **Phases are hints, not a state machine.** `readiness` (score plus blocking gaps) is injected every turn and also returned by `finalize_plan`, which refuses with a precise reason when blockers remain. `record_understanding` closes the loop.
- **Strict mode on every tool**, `parallel_tool_calls=true`, amounts as JSON `number` (two-decimal), dates as `day_of_month` ints or ISO strings resolved by the model against the injected today's date; code validates and normalizes.

---

## 1. Tool granularity

| Option | LLM reliability | Streaming latency | Testability | Corrections |
|---|---|---|---|---|
| **A. One tool per entity and verb** (`add_income`, `update_income`, `remove_income`, `add_debt`, ...) | 15-20 near-identical schemas; the model must pick add vs update, which is exactly the judgment we do not want it making. Selection errors are "almost always a description problem" and here the descriptions would be nearly identical. | Fine per call, but the model often emits several calls in one turn; each is a separate schema to fill. | Many handlers, much duplication. | Model must remember whether an item exists to choose update vs add. It frequently gets this wrong and creates duplicates. |
| **B. `upsert_item(kind, name, fields)` + `remove_item(kind, name)`** | One habit: "a fact came in, upsert it". `kind` is an enum so strict mode guarantees a valid category. Per-kind field sets are expressed as nullable fields in one object. | One short call per fact; parallel calls when the user dumps several facts in one breath. | One handler with per-kind validation; table-driven tests. | Handler decides create vs update vs conflict by key. The model never needs to know if a record exists. |
| **C. `update_state(full_json)`** | Model must regenerate the entire state each turn; long arguments, more tokens to stream, more chance to drop or hallucinate an existing field. | Worst: a 40-field JSON argument streams for seconds before the handler can run. | Hard to unit-test intent; diffs are noisy. | Silent overwrites; conflicts invisible. |

OpenAI's own guidance points the same way: "Combine functions called in sequence into single operations", "Don't make the model fill in known arguments", and keep the active toolset small. Anthropic's tool-writing guidance adds that tools "can consolidate functionality, handling potentially multiple discrete operations under the hood", and MLflow's practitioner guide cautions the opposite extreme, that a fully generic `query_database(sql)` tool is unsafe; `upsert_item` with an enum `kind` and a typed field set sits in the sweet spot: generic verb, narrow typed payload. Daily's June 2025 advice for voice specifically: "Define as few tools as possible. Write detailed, multi-shot prompts."

### Upsert-by-name semantics

Key = `(kind, normalize(name))` where `normalize` lowercases, strips punctuation and articles, and maps a small synonym table (`"house rent" -> "rent"`, `"car emi" -> "car loan"`, `"credit card" -> "credit card"`). The handler:

1. Looks up the key. Not found: create with `id`, `confirmed=false`, `source_turn=n`.
2. Found and fields identical: no-op, returns `"unchanged"`.
3. Found and a monetary field differs: run conflict logic (section 2). If the change is a correction (user said "actually", "sorry", "no, it's", or the previous value is unconfirmed and within the window), overwrite and log `history`.
4. Found and only non-monetary fields differ (adding a due date to an existing debt): merge.

Fuzzy match on name (ratio > 0.85) triggers a `possible_duplicate` note in the result rather than a silent merge, so the model can ask "is that the same as the personal loan you mentioned?"

Every item keeps `history: list[Revision]` (value, turn, confirmed) so corrections update everything without losing provenance; the engine always computes from the head value.

### Proposed tool list

| Tool | Args | Returns | When the model calls it |
|---|---|---|---|
| `upsert_item` | `kind: enum[income, expense, debt, asset, goal]`, `name: str`, `amount: number\|null`, `frequency: enum[monthly, weekly, yearly, one_time]\|null`, `due_day: int\|null`, `interest_rate_pct: number\|null`, `balance: number\|null`, `min_payment: number\|null`, `notes: str\|null`, `is_correction: bool` | `{status: created\|updated\|unchanged\|conflict, item, totals, missing_for_item[], conflict?}` | Immediately when the user states or changes any financial fact. Also when a partial fact arrives (name without amount). |
| `remove_item` | `kind`, `name`, `reason: str\|null` | `{status, totals}` | User says an item no longer applies ("I paid off the bike loan"). |
| `resolve_conflict` | `conflict_id: str`, `chosen_value: number\|null`, `resolution: enum[keep_previous, use_new, both_separate, custom]` | `{status, item, totals, open_conflicts: int}` | After the user answers which figure is right. `both_separate` splits into two items (two credit cards). |
| `mark_unknown` | `kind`, `name\|null`, `field: str`, `reason: enum[user_does_not_know, user_declined, not_applicable, will_check_later]` | `{status, missing}` | User says "I don't know", "skip that", "not applicable". Stops the gap from being re-asked. |
| `get_state_summary` | none | compact summary plus `missing`, `open_conflicts`, `readiness` | Rarely; the summary is already in the system prompt. Useful after interruptions or when the user asks "what have you got so far?" |
| `finalize_plan` | `user_priority: enum[debt_first, emergency_fund_first, balanced]\|null` | `{status: ok\|blocked, blockers[], plan: {top_actions[], monthly_surplus, ...}}` | When `readiness.blockers` is empty and the user agrees to see the plan. |
| `record_understanding` | `confirmed: bool`, `restated_actions: str[]`, `notes: str\|null` | `{status, gaps_in_understanding[]}` | After the user restates the plan's top two actions in their own words. |

Seven tools, well under the twenty OpenAI suggests as a soft ceiling, all strict.

---

## 2. Corrections and conflict handling

### Detection (in the handler, deterministically)

On `upsert_item` where the key exists and `amount` (or `balance`) differs:

```
if is_correction or (not existing.confirmed and turn - existing.source_turn <= 2):
    overwrite, push to history, status="updated"
elif existing.confirmed or turn - existing.source_turn <= CONFLICT_WINDOW (6):
    create Conflict, status="conflict"
else:
    overwrite (stale unconfirmed value), status="updated", note="replaced older unconfirmed value"
```

The window matters because STT garbles numbers: "forty-two hundred" and "forty-five hundred" three turns apart is more likely a mis-hearing than a life change. A confirmed value always triggers a conflict regardless of age, because the user already agreed to it.

### What the tool returns

```json
{"status": "conflict",
 "conflict_id": "c_03",
 "item": "rent",
 "previous": {"amount": 4200, "turn": 4, "confirmed": true},
 "new": {"amount": 4500, "turn": 9},
 "suggested_question": "Earlier I had rent at four thousand two hundred; is it four thousand five hundred now?",
 "totals": {"monthly_expenses": 18700, "note": "totals exclude disputed amount; using previous"}}
```

The `suggested_question` is a crutch the model may rephrase, but it guarantees the model has both figures in front of it. Anthropic's guidance that error responses should "guide agents toward success rather than displaying opaque error codes" applies directly.

### State shape

```python
class Conflict(BaseModel):
    id: str
    kind: Kind; item_id: str; field: str
    previous: Revision; new: Revision
    status: Literal["open", "resolved"] = "open"
    resolution: str | None = None

class FinanceState(BaseModel):
    items: dict[str, Item]          # key -> Item (Item has history, confirmed, unknown_fields)
    conflicts: list[Conflict]
    unknowns: list[Unknown]
    plan: Plan | None
    understanding: Understanding | None
    turn: int
```

While a conflict is open the engine uses the previous value (or excludes the item if never confirmed) and flags the item `needs_confirmation=True`; the card renders an amber badge with both numbers. `finalize_plan` treats any open conflict as a blocker.

### `resolve_conflict`

Takes `conflict_id` and one of `keep_previous | use_new | custom(chosen_value) | both_separate`. `both_separate` handles the common voice case where "credit card" was two cards; the handler clones the item with a `name` suffix and asks the model to rename it on the next upsert. Result includes recomputed totals and the number of remaining open conflicts so the model can decide whether to keep clarifying or move on.

---

## 3. Unknowns and missing information

Two sources of "missing":

- **Engine-derived (structural).** A rules table per kind: `debt` requires `balance` and `min_payment`, wants `interest_rate_pct` and `due_day`; `income` requires `amount` and `frequency`; the plan requires at least one income and any expenses or an explicit "no fixed expenses". Computed fresh from state every turn; never stale, never forgotten.
- **Model-declared (`mark_unknown`).** The user said they do not know their card's interest rate. Without this, the derived list re-surfaces the gap every turn and the agent nags. `mark_unknown` records `reason`; the derived list then shows the field as `unknown (user_does_not_know)` rather than `missing`, the engine uses a labelled default (e.g. 36% APR for Indian credit cards, clearly marked as an assumption in the plan), and the card shows "assumed".

Hybrid wins because each half fails alone: pure engine lists cause nagging; pure model-declared lists forget things. This mirrors the shift from fixed slot schemas toward LLM-generated, interpretable state descriptions in recent dialogue-state-tracking work (NL-DST, Carranza and Rojas 2025), while keeping the slot ledger deterministic.

### Prompt injection each turn

The system prompt is rebuilt every turn (Pipecat lets us swap the system message in context). The "still missing" section is ranked by the engine: blockers first (needed to compute anything), then plan-quality gaps, then nice-to-haves. Cap at five lines so the model does not read a list aloud; it picks the top one and asks a single natural question. This is how the agent stays adaptive: the ordering changes as facts arrive, so the next question always follows from what the user just said rather than from a script.

---

## 4. Preventing hallucinated numbers

Three layers, all cheap:

1. **Prompt rule.** "Only say a number that appears in the latest tool result or in the user's own words. Never add, subtract, or estimate. If you need a total, call a tool." The Zero-Mental-Math pattern (LLM as citation copier, Python as calculator) is the model here.
2. **Tool results carry the numbers the model will need next.** Every upsert returns `totals` (monthly income, expenses, debt payments, surplus) so the correct figures are always in the most recent tool message. The model can say "that puts your monthly fixed costs at eighteen thousand seven hundred" without doing arithmetic.
3. **Post-generation check (guardrail, not blocker).** A regex over the assistant text extracts numbers; any that appear in neither the last two tool results nor the last user turn is logged as a hallucination candidate. In v1 this only logs; it becomes an eval metric.

### Confirm-before-record vs provisional record

| Pattern | Latency cost | Error recovery | Verdict |
|---|---|---|---|
| Explicit confirm, record only after "yes" | One extra full turn (STT + LLM + TTS, roughly 1.5-3 s) per fact. With 10-15 facts that is minutes of overhead and a "form-like" feel Vapi's guide warns against. | Best. Classic SDS studies show explicit confirmation recovers from errors more reliably than implicit. | Use only for high-risk values. |
| Provisional record with `confirmed=false`, implicit read-back | Zero extra turns; the read-back rides on the next question. | Good: the user hears the figure and corrects if wrong; Shin et al. found implicit confirmation recovers less often (68% vs 80-90%) and takes longer, so it needs a backstop. | Default. |
| Batch confirm at the end | Zero mid-conversation cost; one summary turn. | Catches whatever the read-backs missed. | Yes, as the `finalize_plan` preamble. |

Recommendation: **provisional by default, implicit read-back always, explicit confirmation triggered by rules.** Triggers for explicit: (a) STT word-confidence below threshold on the number span, (b) value is an outlier against the kind (rent above 60% of income, a 2-digit salary), (c) any conflict, (d) the value is a plan driver (total income, largest debt). `confirmed` flips to true when the next user turn does not contradict the read-back. Cards show a faint "unconfirmed" state until then; the product rules's "never present guesses as facts" is met because unconfirmed and assumed values are visually distinct and spoken with hedges ("I have your rent as...").

On the STT side, turn on Deepgram `numerals` (or equivalent) so "twelve thousand" arrives as `12000` rather than words, and keep `smart_format` off for the number path if it degrades digits; both are documented pain points in Deepgram's own discussions.

---

## 5. Phase awareness without a state machine

Phases gather -> clarify -> plan -> explain -> confirm are **hints derived from state**, not a controller. The engine computes:

```python
class Readiness(BaseModel):
    score: float            # 0..1, weighted coverage of required fields
    blockers: list[str]     # "no income recorded", "conflict c_03 open", "debt 'car loan' missing min_payment"
    suggested_phase: Literal["gather", "clarify", "plan", "explain", "confirm"]
```

`suggested_phase` is injected into the prompt as a one-line hint ("Phase hint: clarify; 1 conflict open"), and the model decides what to say. This avoids the brittleness of hard-coded flows while giving the model a reliable signal. Daily's advice to attach "a system instruction for the state" is honoured by swapping the phase-hint block, not by locking tools.

**`finalize_plan`.** Runs the deterministic engine. If `blockers` is non-empty it returns `{status: "blocked", blockers, suggested_question}` and the model goes back to gathering. Otherwise it stores `Plan` in state (cards flip to plan view) and returns a compact, speakable summary: `top_actions` (max three, each with one number), `monthly_surplus`, `assumptions` (from unknowns), `emergency_fund_months`. Any figure the model will speak is in this result.

**Explain.** The prompt tells the model to deliver the plan in two or three short turns, one action per turn, checking in between ("does that make sense so far?"), never as a monologue.

**`record_understanding`.** After explaining, the model asks the user to say back the two most important things they will do. The model passes the user's restatement to `record_understanding(confirmed, restated_actions, notes)`. The handler does a keyword match of `restated_actions` against `plan.top_actions` and returns `gaps_in_understanding`; if non-empty the model re-explains just that action. `confirmed=true` with no gaps ends the session; the card shows a "plan understood" state. This satisfies the product rules's "confirm the user understands" with evidence, not a yes/no.

---

## 6. Tool schema style for gpt-5.x

- **`strict: true` on all tools.** Requirements: `additionalProperties: false` on every object, every property listed in `required`, optional fields typed `["number", "null"]` etc. OpenAI: "Setting strict to true will ensure function calls reliably adhere to the function schema, instead of being best effort." Pydantic models with `model_json_schema()` plus a small post-processor (add `additionalProperties: false`, make all required, convert `Optional` to null unions) produce compliant schemas.
- **Descriptions.** State when to call and when not to, naming the sibling tool: "Use `upsert_item` for any new or changed fact. Do not use it to answer a conflict question; use `resolve_conflict`." Selection errors are a description problem.
- **Enums for `kind`, `frequency`, `resolution`, `reason`.** Strict mode makes invalid categories impossible.
- **Money as JSON `number`, not string.** Structured outputs support `number` with `multipleOf`, `minimum`, `maximum`, `exclusiveMinimum` and `exclusiveMaximum` — confirmed current, and the list is wider than the draft assumed (corrected via context7: "Numbers support multipleOf, minimum, maximum, exclusiveMinimum, and exclusiveMaximum, while arrays support minItems and maxItems. These constraints are not supported for fine-tuned models."). The handler converts to `Decimal` and quantizes to 0.01. Strings invite "12,000" and "12k". Add `minimum: 0`.
- **Dates.** Two fields: `due_day: integer 1-31 | null` for recurring items (code resolves to the next occurrence) and `date: string format=date | null` for one-offs, with today's date injected in the prompt so the model resolves "the fifth" and "next March" itself. `due_day` as an int is more robust to STT than free text; `date` as ISO with `format` lets strict mode reject garbage.
- **`is_correction: boolean`** is required (not nullable) so the model must decide; it is a cheap signal that changes conflict behaviour.
- **`parallel_tool_calls: true`** so "I earn 80k, rent is 12k and I have a car loan" becomes three upserts in one LLM turn. Handler applies them in order; conflicts computed after all three.
- **Reasoning effort `none` (not `low`), verbosity low** for the conversational turn (corrected via context7). `low` is OpenAI's recommended floor for *Realtime* voice agents ("start with a 'low' setting for most production voice agents"), but this pipeline calls tools over Chat Completions, and "starting with GPT-5.4, Chat Completions does not support tool calling with reasoning_effort values other than none" — `low` plus tools is a 400, not a latency trade-off. Use `none` on the Chat Completions path; `low` is only an option on the Responses path, where doc 05 still prefers `none` for TTFT. The rest of the guidance stands: lowering `reasoning_effort` "dials back initiative" and improves latency; contradictory instructions cost reasoning tokens, so the prompt must not both say "confirm every number" and "never ask twice".
- **Tool preambles off.** GPT-5's preamble habit ("Let me record that...") is a chat pattern; in voice it becomes "I have updated the card". Prompt explicitly: act silently, speak outcomes.

---

## 7. Prompt skeleton (draft, about 520 tokens with placeholders filled)

```
# Role
You are Mira, a calm, plain-spoken money coach speaking with one person on a live voice call. Your job: understand their income, expenses, debts and goals by conversation, then explain a simple plan the engine computes. You are not a licensed adviser; say so if asked.

# Hard rules
- Record every financial fact the user states by calling upsert_item immediately. Call remove_item when something no longer applies.
- Only speak numbers that appear in the latest tool result or the user's own words. Never add, estimate or round on your own. If you need a total, use the tool result.
- Repeat each new amount back once, in passing, inside your next sentence. If a tool result says "conflict", ask which figure is right, then call resolve_conflict.
- If the user does not know something, call mark_unknown and move on; do not re-ask.
- Never say you updated a card, record, or system. Just continue the conversation.
- Never present an assumption as a fact. Say "assuming" or "I have this as" for unconfirmed or assumed values.
- No questionnaire. Ask the single most useful next question based on the "Still missing" list. Skip anything already answered.

# Speaking style (text-to-speech)
- One to two short sentences per turn. One question per turn. No lists, bullets, markdown or symbols.
- Say numbers in words as people say them: "twelve thousand rupees", "the fifth of each month".
- Do not read back everything; summarise at most two facts at a time.
- Plain everyday words. No jargon unless the user uses it first.

# Today
{{today_iso}} ({{weekday}}). Resolve "the fifth", "next month" against this date.

# What I know so far
{{state_summary}}          e.g. Income: salary 80,000 monthly (confirmed). Expenses: rent 12,000 (unconfirmed), groceries 6,000. Debts: car loan balance 240,000, min payment 8,500, rate unknown (user does not know). Totals: fixed costs 26,500; surplus 53,500.

# Still missing (highest value first)
{{missing_ranked}}         e.g. 1. car loan due day  2. any credit card debt?  3. emergency savings balance

# Open conflicts
{{conflicts_or_none}}      e.g. rent: 4,200 (turn 4, confirmed) vs 4,500 (turn 9). Ask which.

# Phase hint
{{phase_hint}}             e.g. gather (readiness 0.6). | clarify: 1 conflict open. | plan: call finalize_plan when the user is ready. | explain: one action per turn, check in between. | confirm: ask the user to say back the two most important actions, then call record_understanding.
```

Sections mirror the LiveKit and Vapi structures (identity, output formatting, tools, context, guardrails) with the dynamic blocks at the end so the static prefix stays cacheable. The dynamic blocks are regenerated by code each turn.

---

## 8. Anti-patterns to avoid

- **Two questions in one turn** ("What's your rent, and do you have any loans?"). Every platform guide says one question per turn; STT also handles a single short answer far better.
- **Monologues.** LiveKit: one to three sentences. Plan explanation must be chunked with check-ins.
- **Reading lists aloud.** Vapi: "offer two and ask if they want to hear more." Never enumerate the missing list or all expenses.
- **Narrating the system.** "I've updated the card", "Let me record that", "Calling the tool". The user sees the card change; saying it is noise and breaks the illusion of a conversation.
- **Identical openers every turn** ("Got it. ..."). LiveKit flags this; rotate or omit acknowledgements.
- **Doing arithmetic in the model.** Any total spoken without a tool result is a hallucination risk.
- **Confirming everything explicitly.** Turns a conversation into a form; costs a round-trip per fact.
- **Confirming nothing.** Numbers will be mis-heard; silent acceptance violates "never present guesses as facts".
- **Re-asking known or declined items.** Solved by `mark_unknown` and the ranked missing list.
- **Contradictory prompt rules.** GPT-5 burns reasoning tokens reconciling them; each rule must have one owner (prompt or tool description, not both with different wording).
- **Filler on every tool call** ("Let me check...") when the tool is a sub-100 ms local upsert. Fillers are for slow tools; ours are fast, so speak the outcome directly.
- **Reciting identifiers or raw tool JSON.** Tools return human names, not ids, for anything the model may say.

---

## Open questions

1. Conflict window: 6 turns is a guess; tune from transcripts. Should time (seconds) matter rather than turns?
2. Should `confirmed` flip automatically after one non-contradicting turn, or require the read-back sentence to actually have been spoken (check the assistant text contains the number)?
3. STT confidence: does the chosen STT expose per-word confidence in Pipecat frames? If not, trigger explicit confirmation on outlier rules only.
4. `both_separate` conflict resolution needs a rename step; is a `rename_item` tool worth the eighth slot, or can `upsert_item` with `notes` carry it?
5. Whether to expose `get_state_summary` at all, given the summary is already in the prompt; it may tempt the model to call it every turn.
6. Locale: currency and number words (lakh, crore) in both STT normalisation and TTS output; decide before writing the synonym table.
7. Whether the hallucination regex check should ever block TTS (adds latency) or stay log-only.

## Sources

- OpenAI, Function calling guide (strict mode, descriptions, "fewer than 20 functions", combine sequential functions, parallel tool calls): https://developers.openai.com/api/docs/guides/function-calling
- OpenAI, Structured outputs guide and supported schemas: https://developers.openai.com/api/docs/guides/structured-outputs
- OpenAI Cookbook, GPT-5 prompting guide (tool preambles, agentic eagerness, contradictions, verbosity): https://developers.openai.com/cookbook/examples/gpt-5/gpt-5_prompting_guide
- Anthropic, Writing effective tools for agents (consolidation, meaningful context, helpful errors): https://www.anthropic.com/engineering/writing-tools-for-agents
- MLflow, AI agent tool use best practices (narrow tools, idempotency, Pydantic validation): https://mlflow.org/articles/ai-agent-tool-use-best-practices-for-practitioners/
- Daily.co, Advice on building voice AI in June 2025 (few tools, multi-shot prompts, async tool results, state instructions): https://www.daily.co/blog/advice-on-building-voice-ai-in-june-2025/
- LiveKit, Prompting guide (output formatting for TTS, one question, tool guidance, anti-patterns): https://docs.livekit.io/agents/start/prompting/
- Vapi, Voice AI prompting guide (six sections, one question at a time, batch confirmation, anti-patterns): https://docs.vapi.ai/prompting-guide
- Retell AI, Prompt engineering guide (sectional prompts, under two sentences, exact tool triggers): https://docs.retellai.com/build/prompt-engineering-guide
- Stream, Speculative tool calling for voice (filler speech, avoid eager execution for state-changing tools): https://getstream.io/blog/speculative-tool-calling-voice/
- Gladia, Safety, hallucinations and guardrails for voice AI (architecture over model, "I don't know" paths): https://www.gladia.io/blog/safety-voice-ai-hallucinations
- Dev.to, Trust the server, not the LLM (Zero Mental Math architecture): https://dev.to/nodefiend/trust-the-server-not-the-llm-a-deterministic-approach-to-llm-accuracy-20ag
- Carranza and Rojas, Interpretable and Robust Dialogue State Tracking via Natural Language Summarization with LLMs (2025): https://arxiv.org/abs/2503.08857
- Shin et al., Analysis of User Behavior under Error Conditions in Spoken Dialogs (implicit vs explicit confirmation recovery rates): https://sail.usc.edu/publications/files/shininterspeech2002.pdf
- Sagawa et al., A Comparison of Confirmation Styles for Error Handling in Spoken Dialogue Systems (Interspeech 2004): https://www.isca-archive.org/interspeech_2004/sagawa04_interspeech.pdf
- Deepgram discussions on number recognition and the numerals feature: https://github.com/orgs/deepgram/discussions/957 and https://github.com/orgs/deepgram/discussions/914
- Kommunicate, OpenAI function calling guide 2026 (description-driven selection errors, structured error results): https://www.kommunicate.io/blog/openai-function-calling/

---

## Context7 cross-check (2026-09-11)

Cross-verified claim-by-claim against context7 MCP documentation. Only the OpenAI-sourced claims are checkable here; the platform guides (LiveKit, Vapi, Retell, Daily, Stream, Gladia), Anthropic's tool-writing essay, MLflow, and the academic citations are outside context7's indexed corpus and are reported as NOT COVERED rather than guessed at.

### Libraries consulted

| Library | Context7 id | Notes |
|---|---|---|
| OpenAI API (platform docs + API reference) | `/websites/developers_openai_api` | 7,786 snippets, High reputation, benchmark 80.06. No version pinning offered; served as "current". |
| OpenAI Python SDK | `/openai/openai-python` | 594 snippets, benchmark 84.34. Versions: v1.68.0, v1_105_0, v2.8.1, v2.11.0. |
| Pipecat docs | `/pipecat-ai/docs` | 6,869 snippets, High reputation, benchmark 78.01. Sourced from `github.com/pipecat-ai/docs` main; no version pinning. |
| Pipecat Flows | `/pipecat-ai/pipecat-flows` | 236 snippets, benchmark 82.46. Consulted for the `FlowsFunctionSchema` comparison only. |

### Claims table

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| 1 | "Setting strict to true will ensure function calls reliably adhere to the function schema, instead of being best effort" | VERIFIED | Near-verbatim: "Setting strict to true ensures function calls reliably adhere to the function schema rather than relying on best-effort adherence." |
| 2 | Strict requires `additionalProperties: false` on every object, every property in `required`, optional fields typed `["number","null"]` | VERIFIED | "…strict mode requires that additionalProperties is set to false for each object in parameters, and all fields in properties are marked as required. Optional fields can be accommodated by including null as a type option." The reference schema shows `"units": {"type": ["string","null"], "enum": [...]}` with `units` still listed in `required`. |
| 3 | Seven tools is "well under the twenty OpenAI suggests as a soft ceiling" | VERIFIED | "For optimal accuracy, keep the number of initially available functions under 20 per turn, and consider fine-tuning or tool search for larger toolsets." |
| 4 | "Don't make the model fill in known arguments" | VERIFIED | "…handling parameters in application code rather than relying on the model when values are already known." |
| 5 | "Combine functions called in sequence into single operations" | NOT COVERED | The best-practices snippet returned does not contain this line. The `upsert_item` consolidation argument is unaffected — it also rests on claim 3, which is verified. |
| 6 | Enums prevent invalid categories; strict mode makes invalid values impossible | VERIFIED | "…making functions intuitive, utilizing enums to prevent invalid states." Strict mode is built on Structured Outputs, which enforces `enum`. |
| 7 | Selection errors are "almost always a description problem"; descriptions should say when to call and when not to, naming the sibling tool | VERIFIED (as guidance), the "almost always" framing NOT COVERED | "When defining functions, provide clear names, parameter descriptions, and instructions detailing when to use each function." The stronger causal claim comes from the Kommunicate blog, which context7 does not index. |
| 8 | `parallel_tool_calls: true` lets one turn emit three upserts | VERIFIED | "On supported models beginning with GPT-5, functions can be called in parallel when built-in tools are available"; the inverse is spelled out: "Setting parallel_tool_calls to false ensures the model calls zero or one tool per turn." |
| 9 | Caveat the draft missed on claim 8 | ADDED (new) | "…strict mode is disabled on fine-tuned models if multiple functions are called simultaneously, and disabling parallel tool calls is recommended for gpt-4.1-nano-2025-04-14 to avoid duplicate calls." We are not fine-tuning and not on nano, so `strict: true` + `parallel_tool_calls: true` remains safe — but if doc 05's fallback ladder ever lands on a 4.1-nano-class model, flip `parallel_tool_calls` to false. |
| 10 | Structured outputs support `number` with `minimum`/`maximum`/`multipleOf` ("verify current list") | VERIFIED and widened → corrected inline | "Numbers support multipleOf, minimum, maximum, exclusiveMinimum, and exclusiveMaximum, while arrays support minItems and maxItems. These constraints are not supported for fine-tuned models." Worked example: `"value": {"type": "number", "minimum": -130, "maximum": 130}` inside a `strict: true` schema. |
| 11 | `date: string format=date` lets strict mode reject garbage | VERIFIED | Supported string formats are "date-time, time, date, duration, email, hostname, ipv4, ipv6, and uuid", plus `pattern` for regex. `date` is on the list. |
| 12 | Supported JSON Schema types include Integer and Enum (so `due_day: integer 1-31` works) | VERIFIED | "The supported data types include String, Number, Boolean, Integer, Object, Array, Enum, and anyOf." |
| 13 | Verbosity low for the conversational turn | VERIFIED | Deployment checklist: "Configure text verbosity to low when compact answers and faster response times with fewer tokens are needed", `text: {verbosity: "low"}` on `responses.create`. |
| 14 | "Reasoning effort low" for the conversational turn | CONTRADICTED for this architecture → corrected inline | Two docs collide. Realtime prompting guide: "It is recommended to start with a 'low' setting for most production voice agents" — but that is scoped to `gpt-realtime-2`. Migration guide: "starting with GPT-5.4, Chat Completions does not support tool calling with reasoning_effort values other than none." Our design is tools-on-every-turn over Chat Completions, so `low` is a 400, not a tuning choice. Corrected to `none`, consistent with doc 05. |
| 15 | Lowering `reasoning_effort` "dials back initiative" and improves latency | VERIFIED (latency), the "initiative" phrasing NOT COVERED | "Reducing reasoning effort can result in faster responses and fewer tokens used on reasoning" and "Lower effort levels optimize for speed and reduced token consumption". The "dials back initiative" wording is from the GPT-5 cookbook prompting guide, not in the indexed corpus. |
| 16 | Contradictory instructions cost reasoning tokens | NOT COVERED | Cookbook guidance; not in context7's OpenAI corpus. Left standing — it is a prompt-hygiene rule that costs nothing to follow. |
| 17 | Tool preambles are a GPT-5 chat habit to suppress in voice | NOT COVERED | Cookbook guidance. Nothing in the indexed docs contradicts it. Note the neighbouring realtime guide takes the opposite stance for *reasoning*: "For direct answers, simple lookups, and short confirmations, respond quickly and do not reason. For multi-step tasks, tool decisions, troubleshooting, or escalation, reason before acting" — a useful prompt fragment to steal, but it presumes a Realtime model with reasoning enabled, which we do not have at effort `none`. |
| 18 | Model-declared unknowns / conflict resolution / phase-hint design, upsert-by-name, confirmation-style trade-offs | NOT COVERED | These are our architecture, not documented API behaviour. Context7 neither supports nor contradicts them. |
| 19 | Anthropic, MLflow, Daily, LiveKit, Vapi, Retell, Stream, Gladia and academic citations (§1, §2, §4, §8) | NOT COVERED | Outside context7's indexed corpus. Left exactly as sourced. |
| 20 | Pipecat lets us swap the system message in context each turn (§3) | NOT COVERED (as stated) | Not in a returned snippet. The runtime-settings mechanism does exist — `LLMUpdateSettingsFrame(delta=...Settings(system_instruction=...))` is documented for updating `system_instruction` mid-session — so the capability is real even if the exact phrasing is unverified. |
| 21 | `FunctionSchema` is the right vehicle for enum fields (implied by §6's strict enums under Pipecat) | VERIFIED | "Use FunctionSchema for explicit control over tool schema, such as strict enum constraints… A strict enum — the kind of explicit control a direct function can't yet express." This directly supports using `FunctionSchema` over direct functions for `kind`, `frequency`, `resolution` and `reason`. |
| 22 | Handler applies parallel calls in order; conflicts computed after all of them | VERIFIED (mechanism available) | Pipecat: "`group_parallel_tools` dictates whether the LLM responds once after all tool calls in a batch are finished (when `True`) or independently as each result arrives (when `False`)." Set `group_parallel_tools=True` to get exactly the single post-batch re-run §6 assumes; note the default `run_in_parallel=True` runs handlers **concurrently**, so the "applies them in order" assumption needs `run_in_parallel=False` or an in-handler lock. |

Tally: 12 VERIFIED, 1 CONTRADICTED (corrected inline), 1 widened, 1 added, 9 NOT COVERED (7 of them non-OpenAI sources that context7 does not index).

### Corrections applied

1. **§6, reasoning effort** — changed "Reasoning effort low" to **`none`**, with the reason: OpenAI documents that from GPT-5.4 onward Chat Completions rejects tool calling at any `reasoning_effort` other than `none`. Since every turn in this design carries tools, `low` would 400 rather than merely cost latency. The `low` recommendation is real but scoped to Realtime voice agents. Marked "(corrected via context7)". This also removes a live inconsistency with doc 05, which already settled on `none`.
2. **§6, money as `number`** — the draft hedged ("added 2025; verify current list"). Verified and widened: `multipleOf`, `minimum`, `maximum`, `exclusiveMinimum`, `exclusiveMaximum` for numbers, `minItems`/`maxItems` for arrays, with the fine-tuned-model carve-out quoted. Marked "(corrected via context7)".

### Disagreements left standing

None. No claim in this report is contradicted by context7 in a way the body's own sourcing outranks. The 2025-era cookbook and platform-guide material (tool preambles, "dials back initiative", contradictory-instruction cost, the LiveKit/Vapi/Retell prompt structures) is simply outside the indexed corpus — unverified, not disputed.

### Follow-ups for §6 and §2 implementation

- **`run_in_parallel` default is `True`** in Pipecat's `LLMService`. §2's conflict logic assumes upserts from one turn are applied **in order** so that the second conflicting amount sees the first. With concurrent handlers that ordering is not guaranteed. Either construct the service with `run_in_parallel=False`, or serialize inside the handler with an `asyncio.Lock` and sort by tool-call index. Keep `group_parallel_tools=True` so the model gets one re-run after the whole batch, which is what the "conflicts computed after all three" design wants.
- **`strict` is not a `FunctionSchema` field in Pipecat** (see doc 05, claim 47). §6's "strict mode on every tool" therefore needs raw OpenAI tool dicts via `ToolsSchema.custom_tools` — documented as "currently supported for OpenAI-family adapters and Gemini" — or acceptance that schemas ship non-strict and Python does the validating. Since §6 already mandates Pydantic validation in the handler, the fallback is cheap; but the enum guarantees §1 leans on ("strict mode guarantees a valid category") do not hold without it. Validate `kind` defensively either way.
- **Past ~20 tools**, OpenAI now documents `{"type": "tool_search"}` with `{"type": "namespace", ...}` groupings and per-tool `defer_loading: true`. Irrelevant at seven tools; relevant if the toolset grows.
