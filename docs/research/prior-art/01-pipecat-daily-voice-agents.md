# Prior art: open-source voice agents on Pipecat and Daily

Researched 2026-09-12. Scope: open-source repositories with real, readable code that do what Ledgerline
does — collect structured data by voice, call tools that mutate server-side state, and push UI state to a
browser during the call. Star counts and push dates come from the GitHub API on the date above.

Companion: `docs/research/00-index.md` (facts verified against source before building),
`docs/architecture/02-hld.md` (the design this is checked against).

## Summary — ranked, most useful first

1. **`PipelineWorker(app_resources=...)` is the injection seam we need.** Every tool handler receives
   `params.app_resources`, passed by reference and never copied, and custom `FrameProcessor`s read the same
   bag via `self.pipeline_worker.app_resources`. That is exactly how `FinancialState` + the card-push
   callback should reach the six handlers — no globals, no closures, testable.
   ([pipecat `features-app-resources.py`](https://github.com/pipecat-ai/pipecat/blob/main/examples/features/features-app-resources.py))
2. **Per-turn `system_instruction` swaps are cheap on `OpenAIResponsesLLMService`, but per-turn context
   *messages* are not.** `instructions` is a top-level request param, outside the `input` list that the
   `previous_response_id` prefix hash covers. So the "still missing" block belongs in
   `LLMUpdateSettingsFrame(delta=Settings(system_instruction=...))` and must *never* be appended as a
   context message — that would break the prefix match and force a full context resend every turn.
   Pipecat's own example comments on exactly this hazard. (§2, §3)
3. **`bot-transcription` is deprecated.** HLD §6 names it for the question headline. RTVI deprecated it in
   favour of **`bot-output`** (Pipecat 0.0.95 / client-js 1.5.0), which adds a `spoken` flag and
   `aggregated_by`. Fix before building. (§4)
4. **`RTVIServerMessageFrame` is a `SystemFrame`** — same high-priority lane and same interruption
   immunity as `OutputTransportMessageUrgentFrame`, but it arrives at the browser as
   `onServerMessage` / `useRTVIClientEvent(RTVIEvent.ServerMessage)` instead of a raw `app-message`
   listener. Costs ~40 bytes of envelope against the 4 KB cap; buys the whole client SDK. (§4, §6)
5. **Gradient Bang's `event_relay.py` is the routing table we should copy in spirit**: a declarative
   `EventConfig` per event type deciding *client push* vs *LLM context* vs *triggers inference*,
   independently. Every event is pushed to the client; only some reach the model. (§6)
6. **Gradient Bang also runs a second, parallel LLM whose only job is driving the UI** (`ui_agent.py`,
   `control_ui` tool). We do not need this, but it confirms the principle: keep UI control off the
   conversational model's critical path. Our engine-derived card snapshot is the cheaper version of the
   same idea. (§6)
7. **`group_parallel_tools=True` (default) means the LLM runs exactly once after a whole batch of tool
   calls completes** — so a turn with four `upsert_item` calls yields one spoken reply. But
   `run_in_parallel=True` (also default) runs those four handlers concurrently against one mutable
   `FinancialState`. Decide deliberately. (§3)
8. **The canonical intake bot is a fixed questionnaire, and that is what we are rejecting.** Pipecat's
   `examples/flows/yaml/patient_intake` is a linear node graph with `transition_to` edges. Worth lifting
   anyway: its per-node `role_message` / `task_messages` split, its `context_strategy: reset`, its
   read-back-and-confirm node, and its spoken-output prompt clauses. (§5)
9. **RTVI already emits per-tool-call events** (`llm-function-call-started` / `-in-progress` /
   `-stopped`, gated by `function_call_report_level`). The browser can learn which tool just fired without
   us spending bytes on a `focus` field. (§4)
10. **Daily `app-message` is hard-capped at 4 KB, is not delivered to the sender, and late joiners never
    see earlier messages.** `setMeetingSessionData()` persists for late joiners but syncs at most once per
    second — wrong for per-turn cards, right for a single resume snapshot. (§7)

---

## 1. pipecat-ai/pipecat — the framework and its `examples/` tree

- URL: https://github.com/pipecat-ai/pipecat
- 15,438 stars; last push 2026-09-11; Python; BSD-2-Clause.
- Examples are organised by topic under `examples/`: `function-calling/`, `features/`, `flows/`,
  `update-settings/`, `turn-management/`, `transports/`, `observability/`, `multi-worker/`.

The examples directory is the highest-signal prior art we have, because every example is pinned to
Pipecat 1.9.0 — the exact version we build on. Sections 2–5 below each take one theme from it.

---

## 2. Per-turn prompt updates: `LLMUpdateSettingsFrame` and the `previous_response_id` trap

HLD §7 says the "still missing" block is "rebuilt and applied with `LLMUpdateSettingsFrame`". That is
correct, and the reason it is correct is worth writing down, because the neighbouring approach is a
performance trap.

### `system_instruction` is a runtime setting

`OpenAIResponsesLLMService.Settings` exposes `system_instruction` alongside `temperature`, `model`,
`reasoning`, etc., and the docs state these "can be updated mid-conversation with
`LLMUpdateSettingsFrame`"
([docs](https://docs.pipecat.ai/api-reference/server/services/llm/openai-responses.md)).

The shipped example only swaps `temperature`, but the mechanism is identical:

```python
# examples/update-settings/llm/llm-openai-responses.py
await worker.queue_frame(
    LLMUpdateSettingsFrame(delta=OpenAIResponsesLLMService.Settings(temperature=1))
)
```

[source](https://github.com/pipecat-ai/pipecat/blob/main/examples/update-settings/llm/llm-openai-responses.py)

### Why this is cheap and the alternative is not

`OpenAIResponsesLLMService` (WebSocket variant, our default) optimises every turn by sending only new
input items plus a `previous_response_id`, guarded by a SHA-256 hash of the previous input prefix:

```python
# src/pipecat/services/openai/responses/llm.py
prefix = full_input[: self._previous_input_length]
prefix_hash = self._hash_input_items(prefix)
if prefix_hash != self._previous_input_hash:
    logger.debug(f"{self}: Sending full context ({len(full_input)} items)")
    ...
    return params
```

[source](https://github.com/pipecat-ai/pipecat/blob/main/src/pipecat/services/openai/responses/llm.py)

The hash covers only `invocation_params["input"]`. `instructions` is set separately, outside that list:

```python
# _build_response_params
# instructions (set by the adapter when input is non-empty)
if "instructions" in invocation_params:
    params["instructions"] = invocation_params["instructions"]
```

**Consequence for us:** rewriting `system_instruction` every turn does *not* invalidate the prefix hash.
Rewriting it is free. Injecting the same text as a context message would rewrite the tail of `input`,
miss the prefix match on the *following* turn, and resend the whole conversation.

Pipecat's own example flags this hazard in a different guise — a filler phrase during a tool call:

```python
@llm.event_handler("on_function_calls_started")
async def on_function_calls_started(service, function_calls):
    # Avoid appending this filler message to the LLM context — it would
    # alter the conversation history and prevent
    # OpenAIResponsesLLMService's previous_response_id optimization from
    # matching, forcing a full context resend.
    await tts.queue_frame(TTSSpeakFrame("Let me check on that.", append_to_context=False))
```

[source](https://github.com/pipecat-ai/pipecat/blob/main/examples/features/features-app-resources.py)

**Learnings**

- Keep the per-turn missing block strictly in `system_instruction`. Never `context.add_message` it.
- `TTSSpeakFrame(..., append_to_context=False)` is the way to speak anything the model did not generate
  (a filler line, the idle "still there?" nudge) without polluting context. Directly applicable to HLD
  §8's 10-second idle nudge.
- Turn on `logger.trace` during development: the service logs the exact reason for each full-context
  resend ("input prefix hash mismatch", "response output mismatch after prefix"). That is a free
  regression check that our per-turn prompt refresh has not started costing a full resend.
- `@llm.event_handler("on_completion_timeout")` and `on_connection_error` exist; wire both to the error
  banner rather than letting the call die silently.

---

## 3. Tool calling: `app_resources`, parallel batches, and result control

### `app_resources` — the dependency-injection seam

```python
@dataclass
class AppResources:
    tool_call_logger: ToolCallLogger
    transcription_logger: TranscriptionLogger

worker = PipelineWorker(pipeline, app_resources=resources, ...)

async def get_current_weather(params: FunctionCallParams, location: str, format: str):
    resources = cast(AppResources, params.app_resources)
    resources.tool_call_logger.log_tool_call(params.function_name, params.arguments)
    await params.result_callback({"conditions": "nice", "temperature": "75"})
```

[source](https://github.com/pipecat-ai/pipecat/blob/main/examples/features/features-app-resources.py)

The documented guarantees: resources are **passed by reference**, the framework **never copies or clears**
them, all handlers share one instance, and the caller can read mutations after the session ends
([docs](https://docs.pipecat.ai/pipecat/learn/function-calling.md)).

That last clause is the one that matters for our eval harness: after `runner.run()` returns we can read
the final `FinancialState` straight off our own handle, with no extra plumbing. The example does exactly
this, dumping its loggers after the run.

A custom processor reads the same bag:

```python
if isinstance(frame, TranscriptionFrame) and self.pipeline_worker is not None:
    resources = cast(AppResources, self.pipeline_worker.app_resources)
    resources.transcription_logger.log_transcription(frame.text)
```

`FunctionCallParams` in 1.9.0 carries: `function_name`, `tool_call_id`, `arguments`, `llm`,
`pipeline_worker`, `context`, `result_callback`, `app_resources`, `worker_runner`. Note
`params.tool_resources` is a **deprecated alias** for `app_resources`.

### Parallel tool calls

Two `LLMService` constructor flags, both defaulting to `True`:

- `run_in_parallel` — whether multiple tool calls in one turn run concurrently or in sequence.
- `group_parallel_tools` — when `True`, the whole batch is grouped so **the LLM is triggered exactly
  once** after every call completes. The docs explicitly warn: with it disabled, "the bot answers once per
  tool instead of once total".

There is also `function_call_timeout_secs` on the service, overridable per tool:

```python
@tool_options(cancel_on_interruption=False, timeout_secs=30)
async def get_current_weather(params: FunctionCallParams, location: str, format: str):
    ...
```

A call past its deadline is cancelled with `asyncio.CancelledError` thrown into the handler, settles as
cancelled, and inference runs so the bot can say it did not complete.

### Result control

```python
@dataclass
class FunctionCallResultProperties:
    run_llm: bool | None = None                 # skip inference after this result
    on_context_updated: Callable | None = None  # async hook after result lands in context
    is_final: bool = True
```

**Learnings and risks for Ledgerline**

- Use `app_resources` for the `FinancialState` + card-push callback. This replaces any module-level state
  and makes the handlers unit-testable with a plain fake.
- **Risk:** with `run_in_parallel=True`, a turn stating three facts runs three `upsert_item` handlers
  concurrently against one mutable state object, each calling `build_plan()` and each pushing a card
  snapshot. Three snapshots per turn, ordering not guaranteed, and two of them show a half-built state.
  Options: (a) `run_in_parallel=False` — handlers are in-memory and microsecond-fast, so serialising costs
  nothing; (b) keep parallelism but push cards once from `on_context_updated` on the last result. (a) is
  simpler and matches HLD §4's "never await the network inside a handler". Either way the monotonic `v`
  field must be assigned under the same lock that mutates state.
- Keep `group_parallel_tools=True` so the bot speaks once per turn regardless of how many facts landed.
- `function_call_timeout_secs=5` (HLD §4) is right, but note it is a *global* default; `@tool_options`
  is how you'd give `finalize_plan` a longer leash if the 30-day simulation ever grows.
- Tool **docstrings can carry the conversational next step**. Pipecat's intake handlers do this:
  `"""Record the user's prescriptions. Once confirmed, the next step is to collect allergy
  information."""` We can encode "after recording, ask about the single most blocking unknown" in the
  `upsert_item` docstring rather than spending base-prompt tokens on it.
- Direct-function schema generation does **not** map `Literal` to a JSON-schema `enum` yet. Our
  `kind` (income/debt/essential/optional/balance) and `debt_kind` arguments want a strict enum, so they
  need the verbose `FunctionSchema` form, or the constraint has to live in docstring prose. This is a
  real decision point for `agent/tools.py`.

---

## 4. RTVI: the protocol we are half-using

- `pipecat-ai/pipecat-client-web` — https://github.com/pipecat-ai/pipecat-client-web — 326 stars, last
  push 2026-09-05, TypeScript.
- `pipecat-ai/pipecat-client-web-transports` — https://github.com/pipecat-ai/pipecat-client-web-transports
  — 31 stars, last push 2026-09-11.
- Protocol reference: https://docs.pipecat.ai/client/rtvi-standard.md (server protocol version 2.1.0).

### Server messages

```python
from pipecat.processors.frameworks.rtvi import RTVIServerMessageFrame

await self.push_frame(RTVIServerMessageFrame(data={"type": "event", "value": frame.value}))
```

Wire format at the client: `{ label: "rtvi-ai", type: "server-message", data: ... }`, handled by
`pcClient.onServerMessage((message) => ...)` or, in React,
`useRTVIClientEvent(RTVIEvent.ServerMessage, cb)`.

The docs note: "`RTVIServerMessageFrame` is a `SystemFrame`, so it uses the high-priority SystemFrame
lane, remains ordered with other SystemFrames, and is not discarded by interruptions."
([source](https://docs.pipecat.ai/api-reference/server/rtvi/rtvi-processor.md))

That is the same guarantee HLD §6 is buying with `OutputTransportMessageUrgentFrame` (also a
`SystemFrame`, `src/pipecat/frames/frames.py:1471`).

### Corrections to HLD §6

- **`bot-transcription` is deprecated** in favour of **`bot-output`** (Pipecat 0.0.95 / client-js 1.5.0).
  `bot-output` carries `text`, `spoken: boolean`, and `aggregated_by` ("sentence", "word", …). For the
  question headline we want `aggregated_by === "sentence" && spoken`.
- The other three messages HLD names are current: `bot-started-speaking`, `bot-stopped-speaking`,
  `user-started-speaking`.
- Also available and free: `user-transcription` (with a `final` flag) for showing the user their own
  words, and `vad-user-started-speaking` / `-stopped-speaking` for the raw VAD signal — but these are
  **disabled by default** and need `RTVIObserverParams(vad_user_speaking_enabled=True)`.

### Function-call events for free

`llm-function-call-started`, `llm-function-call-in-progress`, `llm-function-call-stopped`, each carrying
`function_name` and `tool_call_id`, and at `function_call_report_level=FULL` also `arguments` and
`result`. `llm-function-call-stopped` carries a `cancelled` flag.

HLD §6 spends bytes on a `focus` field naming the card the last tool touched. `llm-function-call-stopped`
already tells the browser which tool just fired. Dropping `focus` buys back budget against the 4 KB cap,
at the cost of a mapping table in the frontend.

The React SDK already wires these:

```ts
// pipecat-client-web/client-react/src/conversation/useConversationEventWiring.ts
useRTVIClientEvent(
  RTVIEvent.LLMFunctionCallInProgress,
  useAtomCallback(useCallback((get, set, data: ...) => { ... }, []))
);
```

### The UI messaging layer we did not know existed

RTVI 2.1 defines a whole GUI-control sub-protocol: `ui-snapshot` and `ui-event` (client → server),
`ui-command` and `ui-job-group` (server → client), plus a server-side `UIWorker`. Standard `ui-command`s
include `scroll_to`, `highlight`, `select_text`, `click`, `type`, `toast`, `navigate`, and
`@pipecat-ai/client-react` ships default handlers for them.

We should **not** adopt `UIWorker` — it is aimed at an agent reasoning over an accessibility tree, which
is the opposite of our "cards are derived from state, never from the model" rule. But `ui-command` with
`highlight` is a clean, zero-payload way to flash the focused card, and `toast` is a ready-made error
channel.

### Anti-patterns visible in the protocol

- `append-to-context` is marked `// DEPRECATED` in
  [`client-js/rtvi/messages.ts`](https://github.com/pipecat-ai/pipecat-client-web/blob/main/client-js/rtvi/messages.ts).
- `llm-function-call` (singular) is deprecated in favour of `-in-progress`.
- `MessageTooLargeError` exists in the JS client for messages over the transport maximum — worth catching
  on the client side too, not only guarding size on the server.
- The client's protocol-version handshake sends an error response but **continues the connection** on a
  major-version mismatch. A silent-ish failure mode: check server logs for version warnings.

---

## 5. Structured collection as a fixed graph: `examples/flows/yaml/patient_intake`

- https://github.com/pipecat-ai/pipecat/tree/main/examples/flows/yaml/patient_intake
- Sibling YAML flows in the same directory: `insurance_quote`, `restaurant_reservation`,
  `podcast_interview`, `food_ordering`, `hello_world`.
- Related standalone framework: `pipecat-ai/pipecat-flows` — https://github.com/pipecat-ai/pipecat-flows
  — 625 stars, last push 2026-07-05.

This is the canonical voice-intake shape, and it is the thing Ledgerline deliberately does not do: a
linear node graph, one question per node, `transition_to` edges.

```yaml
initial_node: start

nodes:
  start:
    role_message: >
      You are Jessica, an agent for {{ practice_name }}, on the phone with a
      patient. You must ALWAYS use one of the available functions to progress
      the conversation. ...
    task_messages:
      - role: developer
        content: >
          Introduce yourself briefly to {{ patient_name }} and ask for their
          date of birth, including the year. ...
    functions:
      - name: verify_birthday
        transition_to:
          field: verified
          cases:
            true: get_prescriptions

  get_prescriptions:
    context_strategy: reset
    ...
```

Handlers never choose the next node; they return `(result, TRANSITION_IN_YAML)` and the YAML routes on a
field of the result:

```python
async def verify_birthday(flow_manager: FlowManager, birthday: str):
    """Verify the user has provided their correct birthday. Once confirmed, the next step is to record the user's prescriptions.

    Args:
        birthday (str): The user's birthdate (convert to YYYY-MM-DD format).
    """
    is_valid = birthday == "1983-01-01"
    flow_manager.state["birthday_verified"] = is_valid
    flow_manager.state["birthday"] = birthday
    return BirthdayVerificationResult(verified=is_valid), TRANSITION_IN_YAML
```

[handlers.py](https://github.com/pipecat-ai/pipecat/blob/main/examples/flows/yaml/patient_intake/handlers.py)

**Learnings**

- **The `role_message` / `task_messages` split is exactly our base-prompt / per-turn-block split**, done
  with full context replacement per node instead of `LLMUpdateSettingsFrame`. Our version is strictly
  better for the Responses API (see §2), but the *shape* validates HLD §7.
- **Steal these prompt clauses verbatim.** They are load-bearing and battle-tested:
  - "You must ALWAYS use one of the available functions to progress the conversation." — this is the
    one-habit line HLD §4 wants for `upsert_item`.
  - "Your words are spoken aloud: keep each reply to one or two short sentences, don't thank the patient
    for every answer or repeat back what they just said, and never use lists, markdown, or parentheses."
    Note **"don't thank for every answer"** and **"don't repeat back what they just said"** — neither is
    in our HLD §7 prompt, and both are the classic intake-bot failure mode. Ours *does* want one
    controlled repeat ("repeat a newly recorded figure once"), so the rule needs to be narrowed, not
    copied.
- **Tool results are deliberately tiny TypedDicts** — `{"verified": true}`, `{"count": 3}`. Same
  discipline as HLD §4's "short string with the recomputed totals". Confirms the choice.
- **The `verify` node is our `record_understanding`**: "Read back their prescriptions, allergies,
  conditions, and reason for the visit in a couple of spoken sentences, **not a list**, and ask if that's
  all correct." Then `confirm_information` vs `revise_information`. We have this; the "not a list" clause
  is worth borrowing.
- `context_strategy: reset` is the flows answer to prompt drift. **Do not adopt it** — a context reset
  destroys the `previous_response_id` prefix and costs a full resend at every phase boundary.
- **Anti-pattern to avoid:** the whole flow is a questionnaire, so a user who volunteers three facts at
  once, or corrects an earlier one, has nowhere to put them. Every node has exactly one tool. Our
  single-`upsert_item` design is the direct answer, and this repo is the evidence for why.

Also in `examples/features/`, the smallest structured-collection example:
[`features-user-email-gathering.py`](https://github.com/pipecat-ai/pipecat/blob/main/examples/features/features-user-email-gathering.py).
One tool, `store_user_emails(params, emails: list[str])`, and a system instruction that leans on TTS
markup — `<spell>a@a.com</spell>` for Cartesia — to read a value back unambiguously. **Directly
relevant:** HLD §7 says "4,200 rupees" never "₹". For read-back of an amount the user must verify, a
Cartesia `<spell>` tag (or Rime's `spell()`) is the tested way to force digit-by-digit pronunciation.

---

## 6. pipecat-ai/gradient-bang — the largest open example of an LLM driving a browser mid-call

- URL: https://github.com/pipecat-ai/gradient-bang
- 419 stars; last push 2026-06-05; Python server + React/TypeScript client; by the Pipecat team.
- A multiplayer space-trading game where you talk to your ship. The voice agent calls tools, a game
  server emits events, and the browser UI updates live.

This is the closest thing to Ledgerline's "cards change the moment you correct something", at a scale
well past a demo (a 1,970-line event relay, a 2,213-line client context).

### The event relay: one declarative routing table

`src/gradientbang/runtime/event_relay.py` is the file to read. Its docstring:

> Subscribes to game_client events and routes them to RTVI (client push) and/or LLM context. Each event
> type has a declarative config entry (EventConfig) that controls routing.

The routing axes are separate enums:

```python
class AppendRule(Enum):
    NEVER = "never"          # RTVI only, never sent to LLM
    PARTICIPANT = "participant"
    OWNED_TASK = "owned_task"
    DIRECT = "direct"
    LOCAL = "local"

class InferenceRule(Enum):
    NEVER = "never"          # Don't trigger inference
    ALWAYS = "always"
    VOICE_AGENT = "voice_agent"   # Trigger only if event came from our own tool call
    ON_PARTICIPANT = "on_participant"
    OWNED = "owned"

class Priority(Enum):
    NORMAL = "normal"
    HIGH = "high"
    LOW = "low"
```

The client push happens **unconditionally, before** the append/inference decisions:

```python
# ── Phase 3: RTVI push ──
await self._rtvi.push_frame(
    RTVIServerMessageFrame(
        {"frame_type": "event", "event": event_name, "payload": clean_payload}
    )
)

# ── Phase 4: Append decision ──
should_append = self._should_append_to_llm(cfg, event_name, ...)
if not should_append:
    return
```

Note `self._rtvi.push_frame(...)` — pushed on the `RTVIProcessor` directly, not queued on the worker.

There is also a small hardening detail worth copying, since our card rows carry user-supplied names:

```python
def _xml_escape_attr(value: Any) -> str:
    """Escape an XML attribute value. Attr values may contain user-controlled
    text (ship names, character names, etc.); a stray `"`, `<`, `>`, or `&`
    would corrupt the envelope the LLM parses, so escape the standard set."""
```

They wrap events for the LLM in XML envelopes and escape attribute values. Our per-turn missing block and
our tool result strings will contain whatever the user called their debt ("Rahul's loan", "EMI <HDFC>").

### The UI agent: a second LLM, off the critical path

`src/gradientbang/runtime/subagents/ui_agent.py`:

> Runs in a parallel branch to the voice pipeline. It watches the latest user message (or course.plot
> events) and decides whether to issue UI actions. It maintains a rolling context summary for
> UI-relevant state. Pipeline: UIAgentContext → LLMService → UIAgentResponseCollector

Its single tool is `control_ui`, a `FunctionSchema` with strict enums for `show_panel`, `show_modal`,
`show_player_ship_tab`, plus `map_center_sector`, `map_zoom_level`, `map_highlight_path`. Plus
`queue_ui_intent`, which defers a UI change until a matching server event arrives.

Note that the enum descriptions are doing heavy disambiguation work, e.g. for `show_player_ship_tab`:
*"Use 'strategy' ONLY when the user explicitly asks to see their ship's combat strategies … Do NOT use as
a general strategy catch-all."* That is what per-value guidance looks like after contact with a real
model.

### Client side: the anti-pattern

`client/app/src/GameContext.tsx` is 2,213 lines built around a single handler:

```tsx
useRTVIClientEvent(
  RTVIEvent.ServerMessage,
  useCallback((e: Msg.ServerMessage) => { /* giant switch on e.event */ }, [])
)
```

dispatching deltas into a Zustand store. Comments inside it read like reconciliation bug scars:

```
// Largely a noop as status.update is dispatched immediately after
// Noop — status.update is dispatched immediately after fighter purchase
// directly — no client-side dispatch needed.
```

**Learnings**

- **Adopt the routing-table idea, not the delta protocol.** A small table in `voice/session.py` saying,
  per state change, whether it pushes cards / enters context / triggers inference, is the same
  clarity at a tenth the size. Our engine already gives us the "what changed"; what's missing is an
  explicit statement of "and therefore what happens".
- **Push to the client before deciding anything about the model.** Cards on screen at ~1.0 s (HLD §2)
  depends on the push not waiting on inference decisions.
- **Full-snapshot-per-change is the right call, and this repo is the argument for it.** Their per-event
  deltas are what produced a 2,213-line reconciler with noop comments. HLD §6's monotonic `v` +
  reconcile-by-card-id is a one-screen `useReducer`.
- **Escape user-supplied text before it enters any structured envelope** the model parses.
- Their separate UI agent is worth citing in the design notes as the alternative we rejected: it costs a
  second LLM per turn and can disagree with the conversation. Deriving cards from the same state object
  the tool just mutated makes disagreement impossible.

---

## 7. Daily: the transport constraints

Docs: https://docs.daily.co/docs/daily-js/guides/custom-messages

### `sendAppMessage()`

> A JSON-serializable object. Must be within the 4KB size limit.
> ([daily-js reference](https://docs.daily.co/reference/daily-js/instance-methods/send-app-message))

Two properties HLD §6 does not mention:

- **Not delivered to the sender.** Broadcast (`'*'`) messages skip the sender.
- **Ephemeral, and late joiners never see them.** "Messages are not stored and not delivered to the
  sender. Participants who join after a message is sent will not receive it."

There is a REST equivalent, `POST /rooms/{room_name}/send-app-message`, same 4 KB cap — useful for
injecting a message from FastAPI without going through the pipeline.

### `setMeetingSessionData()` — the persistent alternative

> writes to a single shared data object scoped to the meeting session. All participants receive updates
> in near real-time, and the data persists as participants join and leave — new joiners receive the
> current state immediately.

But:

> Updates are batched and synced at most once per second. … unsuitable for high-frequency updates where
> sub-second ordering matters — use `sendAppMessage()` for those instead.

Supports `'replace'` and `'shallow-merge'`, plus `keysToDelete`, and has a REST form
(`POST /rooms/{room_name}/set-session-data`).

**Learnings**

- The 4 KB cap in HLD §6 is correct and is a hard Daily limit, not a Pipecat one. The size guard in
  `domain/cards.py` is non-negotiable.
- **Join race:** the browser posts `/api/sessions` and joins; the bot joins and greets. If the bot's
  first card push lands before the browser's `app-message` listener is attached, the browser shows an
  empty screen until the second turn. Two fixes, both cheap: (a) greet and push the first snapshot from
  RTVI's `on_client_ready` rather than the transport's `on_first_participant_joined` — `client-ready` is
  sent by the client *after* its media channels connect and it is ready to receive; (b) belt and braces,
  mirror the latest snapshot into `setMeetingSessionData()` so a reload or a late tab gets current state
  immediately. (b) costs one extra call per turn and is rate-limited to 1 Hz, so it should carry the
  snapshot only, never be the primary channel.
- The greeting pattern in every 1.9.0 example is a developer message plus `LLMRunFrame`, which matches
  HLD §8:
  ```python
  context.add_message({"role": "developer", "content": "Please introduce yourself to the user."})
  await worker.queue_frames([LLMRunFrame()])
  ```
  Move this from `on_client_connected` to the RTVI `on_client_ready` handler, and call
  `await rtvi.set_bot_ready()` first.

---

## 8. Session lifecycle

Sources: https://docs.pipecat.ai/api-reference/server/pipeline/pipeline-idle-detection,
https://docs.pipecat.ai/api-reference/server/pipeline/pipeline-worker,
https://docs.pipecat.ai/api-reference/server/utilities/daily/rest-helper,
https://docs.pipecat.ai/api-reference/server/utilities/runner/transport-utils

- **Idle detection is built in.** `PipelineWorker(idle_timeout_secs=..., idle_timeout_frames=...,
  cancel_on_idle_timeout=...)`, default **5 minutes** with auto-cancel. HLD §8's `IDLE_TIMEOUT_SECS=300`
  is the framework default; we do not need to build this.
- `@worker.event_handler("on_idle_timeout")` fires before cancel. This is where the 10-second "still
  there?" nudge and the 300-second wind-down belong — and the nudge should be a
  `TTSSpeakFrame(..., append_to_context=False)` so it never enters context (§2).
- `idle_timeout_frames` is configurable: which frame types reset the clock. Worth checking that a tool
  call alone counts as activity, otherwise a long silent computation could look idle.
- `ProcessorUnusablePolicy.END` appears in every 1.9.0 example's `PipelineWorker(...)`. Adopt it: a
  service that goes unusable ends the pipeline cleanly rather than hanging.
- Every example pairs `on_client_connected` → greet with `on_client_disconnected` → `await
  runner.cancel()`. HLD §8 matches.
- The runner's own Daily rooms default to **2-hour expiry** with automatic ejection and UUID-prefixed
  names. HLD §8's 1-hour `exp` is a deliberate tightening; fine, just note the divergence from the
  default. `DailyRESTHelper.get_token(..., eject_at_token_exp=...)` is how the token expiry is bound to
  the room's.
- HLD §8's claim that Daily "only allows [room DELETE] 24 h after expiry" should be re-verified against
  the REST API reference before it goes in the README; the docs surface for room deletion did not
  confirm it in this pass. **Open item.**

---

## 9. pipecat-ai/voice-ui-kit — the frontend shape

- URL: https://github.com/pipecat-ai/voice-ui-kit
- 413 stars; last push 2026-09-09; TypeScript/React. Docs: https://voiceuikit.pipecat.ai

"Components, hooks and template apps for building React voice AI applications quickly."

Published hooks: `usePipecatConnectionState`, `usePipecatConversation`, `useBotAudioOutput`,
`usePipecatEventStream`, `useDTMF`, `useTheme`.

**Learnings** — we are building our own components (HLD §6b), which is right, but the hook *names and
boundaries* are the tested decomposition and our `frontend/src/` should mirror them:

- one hook owning connection state (idle / connecting / connected / error),
- one hook owning the conversation transcript,
- one hook owning bot audio output and the speaking flag,
- and — ours — one hook owning the cards snapshot and its version.

Keeping the cards hook separate from the conversation hook is what lets a card update land without
re-rendering the transcript.

## 10. pipecat-ai/pipecat-examples — `phonellm`

- URL: https://github.com/pipecat-ai/pipecat-examples — 381 stars; last push 2026-09-11.
- The `phonellm/` example ships a `server/` bot plus a Vite + React `client/` built on Voice UI Kit.

Its `client/src/hooks/use-tool-calls.ts` is the pattern for making tool activity visible in the UI
without a bespoke server message:

```ts
/**
 * How many times `name` has been called this session. Must be rendered
 * inside a PipecatClientProvider.
 */
export function useToolCallCount(name: string): number {
  useAttachToolCallListeners()
  return useToolCallsStore((state) => state.counts[name] ?? 0)
}

/**
 * Session call count for `name` plus a momentary `flashing` pulse on each
 * new call. Only increments flash, so the reset at the start of a session
 * stays silent.
 */
export function useToolCallFlash(name: string, durationMs = 600): UseToolCallFlashReturn
```

**Learnings**

- `useToolCallFlash` is precisely the "focus card flashes when a tool touches it" behaviour HLD §6b
  wants, built entirely on the RTVI `llm-function-call-*` events — no payload cost (§4).
- "Only increments flash, so the reset at the start of a session stays silent" is the kind of detail
  that only shows up after someone watched it flash on connect.
- The example also ships **behavioural evals** — scripted conversations run against the live bot with no
  microphone, via `uv run pipecat eval suite evals/manifest.yaml`, with a judge LLM configured against a
  local Ollama model so the judge is free. That is a direct template for HLD §9's text harness, and the
  `pipecat-ai[evals]` extra plus an `EvalTransportParams` transport are already wired into every 1.9.0
  example's `transport_params` dict.

---

## 11. Repos checked and set aside

| Repo | Meta | Why not central |
|---|---|---|
| [daily-demos/daily-bots-web-demo](https://github.com/daily-demos/daily-bots-web-demo) | 247★, last push 2025-09-10 | Stale by a year; targets the hosted Daily Bots API, not a self-run Pipecat pipeline. Still the clearest small RTVI React client if a reference is needed. |
| [NVIDIA/voice-agent-examples](https://github.com/NVIDIA/voice-agent-examples) | 65★, last push 2026-07-17 | Pipecat-based orchestrator, but the interesting parts are Riva/NIM service integration, not UI state push. |
| [NVIDIA-AI-Blueprints/nemotron-voice-agent](https://github.com/NVIDIA-AI-Blueprints/nemotron-voice-agent) | last push 2026-09-11 | Same: model-serving focus. |
| [pipecat-ai/pipecat-quickstart](https://github.com/pipecat-ai/pipecat-quickstart) | **archived** | Superseded by `uv tool install pipecat-ai-cli && pipecat init quickstart`. Do not copy from it. |
| [pipecat-ai/pipecat-flows](https://github.com/pipecat-ai/pipecat-flows) | 625★, last push 2026-07-05 | The standalone framework; the in-core `examples/flows/` YAML (§5) is the fresher surface. |

---

## Ideas to adopt in Ledgerline

Effort: **S** ≤ 1 h, **M** ≤ half a day, **L** ≥ a day.

### Correctness fixes — do before writing the code

- [ ] **S — Replace `bot-transcription` with `bot-output` in the protocol types.** Filter on
      `aggregated_by === "sentence"` and `spoken === true`. `bot-transcription` is deprecated as of
      Pipecat 0.0.95. *Touches:* `docs/architecture/02-hld.md` §6, `frontend/src/` protocol types and parse.
- [ ] **S — State the per-turn prompt rule as a hard invariant:** the missing block goes in
      `system_instruction` via `LLMUpdateSettingsFrame` and is never appended to context, because
      `instructions` sits outside the `previous_response_id` prefix hash. *Touches:*
      `ledgerline/agent/prompt.py`, `ledgerline/voice/session.py`, HLD §7.
- [ ] **M — Decide and document the parallel-tool-call policy.** Recommend `run_in_parallel=False` +
      `group_parallel_tools=True`: handlers are in-memory, so serialising is free, and it removes
      concurrent mutation of `FinancialState` and out-of-order card pushes. Assign the monotonic `v`
      under the same lock as the mutation. *Touches:* `ledgerline/voice/pipeline.py`,
      `ledgerline/agent/tools.py`, `ledgerline/domain/cards.py`, HLD §4.
- [ ] **S — Use `FunctionSchema` (not a direct function) for `upsert_item`.** Direct-function schema
      generation does not emit JSON-schema `enum` for `Literal`, and `kind` / `debt_kind` need strict
      enums. *Touches:* `ledgerline/agent/tools.py`.
- [ ] **S — Move greeting and first card push from `on_first_participant_joined` to RTVI
      `on_client_ready`,** after `await rtvi.set_bot_ready()`. `app-message` is not replayed to late
      joiners, so a push before the listener attaches is lost. *Touches:*
      `ledgerline/voice/session.py`, HLD §8.
- [ ] **S — Verify the Daily room-deletion claim** in HLD §8 ("Daily only allows it 24 h after expiry")
      against the REST API reference, or drop the sentence. *Touches:* HLD §8, `README.md`.

### Patterns to lift

- [ ] **M — Pass `FinancialState` and the card-push callback via `PipelineWorker(app_resources=...)`,**
      read in handlers as `cast(LedgerlineResources, params.app_resources)`. Passed by reference and
      never cleared, so the eval harness reads the final state off its own handle after the run.
      *Touches:* `ledgerline/voice/pipeline.py`, `ledgerline/voice/session.py`,
      `ledgerline/agent/tools.py`, `tests/agent/`, `evals/`.
- [ ] **S — Use `TTSSpeakFrame(text, append_to_context=False)` for the idle nudge** and any other line the
      model did not generate, so it never enters context and never breaks the prefix hash. *Touches:*
      `ledgerline/voice/session.py`.
- [ ] **S — Adopt the framework's idle detection** rather than a hand-rolled timer:
      `PipelineWorker(idle_timeout_secs=..., cancel_on_idle_timeout=True)` plus an `on_idle_timeout`
      handler. Also set `ProcessorUnusablePolicy.END`. *Touches:* `ledgerline/voice/pipeline.py`.
- [ ] **M — Write the routing table explicitly**, in the spirit of Gradient Bang's `EventConfig`: for each
      state change, does it push cards, does it enter context, does it trigger inference. One small table,
      not five enums. *Touches:* `ledgerline/voice/session.py`, HLD §2.
- [ ] **S — Escape user-supplied names** before they enter the per-turn missing block or any tool result
      string the model parses. Item names come from speech and will contain quotes and angle brackets.
      *Touches:* `ledgerline/agent/prompt.py`, `ledgerline/agent/tools.py`.
- [ ] **S — Borrow the intake prompt clauses**, narrowed to our case: "You must ALWAYS use one of the
      available functions to progress the conversation"; "never use lists, markdown, or parentheses";
      "don't thank the user for every answer"; "read it back in a couple of spoken sentences, not a list".
      Note our deliberate exception: we *do* repeat a newly recorded figure once. *Touches:*
      `ledgerline/agent/prompts/v1`.
- [ ] **S — Put the conversational next step in tool docstrings**, as the intake handlers do
      ("Once confirmed, the next step is …"), to keep the base prompt at ~450 tokens. *Touches:*
      `ledgerline/agent/tools.py`.
- [ ] **S — Read back amounts with a Cartesia `<spell>` tag** when the user must verify a figure
      digit by digit, as `features-user-email-gathering.py` does for email addresses. *Touches:*
      `ledgerline/agent/prompts/v1`.

### Frontend

- [ ] **M — Consider `RTVIServerMessageFrame` instead of `OutputTransportMessageUrgentFrame`.** Same
      `SystemFrame` lane, same interruption immunity, but the browser gets
      `useRTVIClientEvent(RTVIEvent.ServerMessage)` instead of a raw `app-message` listener, and the
      protocol stays transport-independent. Cost: ~40 bytes of RTVI envelope against the 4 KB cap.
      *Touches:* `ledgerline/domain/cards.py`, `ledgerline/voice/session.py`, `frontend/src/`, HLD §6.
- [ ] **S — Drop the `focus` field from the cards payload** and derive it from
      `llm-function-call-stopped`, which already carries `function_name`. Buys back payload budget.
      *Touches:* `ledgerline/domain/cards.py`, `frontend/src/`, HLD §6.
- [ ] **S — Add a `useToolCallFlash`-style hook** for the focus-card pulse, built on RTVI function-call
      events. Only flash on increment so connect is silent. *Touches:* `frontend/src/`.
- [ ] **S — Mirror the Voice UI Kit hook decomposition**: separate hooks for connection state,
      conversation, bot audio, and — ours — the cards snapshot, so a card update does not re-render the
      transcript. *Touches:* `frontend/src/`.
- [ ] **M — Optionally mirror the latest snapshot into `setMeetingSessionData()`** so a reload or late tab
      gets current state. Rate-limited to 1 Hz, so snapshot-only, never the primary channel. *Touches:*
      `ledgerline/voice/session.py`, `frontend/src/`.
- [ ] **S — Catch `MessageTooLargeError` on the client** in addition to the server-side size guard.
      *Touches:* `frontend/src/`.

### Testing and observability

- [ ] **M — Model the text harness on `phonellm`'s eval suite**: scripted conversations against a live
      headless bot via `EvalTransportParams` and the `pipecat-ai[evals]` extra, with a local Ollama judge
      so judging is free. *Touches:* `evals/`, `pyproject.toml`, HLD §9.
- [ ] **S — Add a trace-level assertion that the prompt refresh has not started forcing full context
      resends.** The Responses service logs the exact reason on every fallback. *Touches:* `evals/`,
      `tests/`.
- [ ] **S — Wire `on_completion_timeout` and `on_connection_error`** to the error banner instead of
      letting the call die silently. *Touches:* `ledgerline/voice/pipeline.py`, `frontend/src/`.

### Explicitly rejected

- **`context_strategy: reset` per phase** (pipecat-flows). Destroys the `previous_response_id` prefix and
  costs a full resend at each boundary.
- **A second LLM for UI control** (Gradient Bang's `ui_agent.py`). Costs an extra inference per turn and
  can disagree with the conversation. Cards derived from the state object the tool just mutated cannot.
- **RTVI `UIWorker` / `ui-snapshot`** — designed for an agent reasoning over an accessibility tree, the
  opposite of "cards are derived from state, never from the model". `ui-command` `highlight` / `toast`
  remain available as cheap primitives.
- **Delta events to the browser** (Gradient Bang's client). Produced a 2,213-line reconciler with noop
  comments. Full snapshot plus monotonic version is a one-screen reducer.
