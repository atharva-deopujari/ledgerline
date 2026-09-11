# 01 — Pipecat Core Framework (v1.9.0)

Research date: 2026-09-11. All API names below were verified by reading the **sdist of `pipecat-ai==1.9.0`**
(`https://files.pythonhosted.org/packages/a0/66/.../pipecat_ai-1.9.0.tar.gz`) and example files from the
`v1.9.0` git tag, not from memory or from prose docs. Where the published docs contradict the source, the
source wins and is flagged.

---

## Decision summary

- **`pipecat-ai==1.9.0`**, uploaded to PyPI **2026-09-11T03:05:13Z** (CHANGELOG dates it 2026-09-10). `requires-python = ">=3.11"`. Python 3.11 is fine; 3.13+ pulls `audioop-lts`, 3.14 forces `pydantic>=2.13`.
- **`PipelineTask` and `PipelineRunner` are deprecated** (since 1.3.0, removal in 2.0.0). Use **`PipelineWorker`** from `pipecat.pipeline.worker` and **`WorkerRunner`** from `pipecat.workers.runner`. Every tutorial you find online older than ~2026-05 uses the dead names.
- **`OpenAILLMContext` no longer exists at all** in 1.9.0 — not deprecated, *removed*. So is `create_context_aggregator()` and `LLMMessagesFrame`. Use `LLMContext` + `LLMContextAggregatorPair`.
- **The system prompt now lives on the LLM service, not in the context.** Set `OpenAILLMService.Settings(system_instruction=...)`; change it mid-call with `LLMUpdateSettingsFrame(delta=OpenAILLMService.Settings(system_instruction=...))`. This is exactly the hook we need to re-inject the "missing info" list each turn.
- **`allow_interruptions` is gone from the entire codebase.** Interruption is always on and is expressed by frame *category* (SystemFrame survives, Data/Control frames are cancelled) plus the `UninterruptibleFrame` mixin. `StartInterruptionFrame` → `InterruptionFrame`.
- **Use "direct functions" for our tools**: a plain `async def f(params: FunctionCallParams, arg: str)` with a Google-style docstring, passed as `LLMContext(tools=[f])`. Pipecat derives the JSON schema *and* auto-registers the handler — no `register_function` call, no hand-written schema.
- **For pushing cards to the browser, use RTVI, not raw transport messages.** `PipelineWorker(enable_rtvi=True)` is the **default**, so `RTVIServerMessageFrame(data={...})` reaches `client.on(RTVIEvent.ServerMessage, ...)` in daily-js with zero extra wiring. `TransportMessageFrame`/`TransportMessageUrgentFrame` were renamed to `OutputTransportMessageFrame`/`OutputTransportMessageUrgentFrame`.
- **Set `processor_unusable_policy=ProcessorUnusablePolicy.END`** on the worker. "Fatal errors" are deprecated as of 1.8.0, and this is how a bad Deepgram/Cartesia key now ends the call cleanly instead of retrying forever.
- **Skip Pipecat Flows.** It is now bundled as `pipecat.flows` inside `pipecat-ai`, but it models conversations as a fixed node graph. Our finance conversation is adaptive (slot-filling in any order), so a single `LLMContext` + a rebuilt system prompt + tools is a better fit.

---

## 1. Version, extras, Python support

```bash
uv add "pipecat-ai[daily,deepgram,cartesia,openai,silero,runner]==1.9.0"
```

Verified from `pyproject.toml` in the 1.9.0 sdist (88 optional dependency groups total):

| Extra | Resolves to |
| --- | --- |
| `daily` | `daily-python>=0.29.0,<1` |
| `deepgram` | `deepgram-sdk>=6.1.1,<8` |
| `runner` | `uvicorn>=0.32.0,<1.0.0`, `fastapi>=0.115.6,<1`, `pipecat-ai-prebuilt>=1.1.0` |
| `cartesia` | `[]` — **empty**, Cartesia is driven over raw websockets from base deps |
| `openai` | `[]` — **empty**, `openai>=1.74.0,<3` is a *base* dependency |
| `silero` | `[]` — **empty**, `onnxruntime~=1.24.3` is a *base* dependency |

Keep the empty extras in the install line anyway: they are the documented spelling and are cheap, and if
the maintainers re-populate them a later bump still works. `requires-python = ">=3.11"`. Pin to
**Python 3.11** in the Dockerfile — 3.13/3.14 are supported but add conditional deps.

`transformers`, `torch` and friends are **not** base dependencies (removed in 1.3.0), so the image stays small.
`websockets` became core in 1.4.0; `soundfile` and `python-dotenv` became core in 1.9.0 (the `[soundfile]`
extra is now a no-op).

**Flat service imports were removed in 1.0.0.** `from pipecat.services.openai import OpenAILLMService`
raises `ImportError`; every service needs its full submodule path. Our four:

```python
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.transports.daily.transport import DailyParams
```

---

## 2. Pipeline, FrameProcessor, the Frame model

`pipecat.frames.frames.Frame` has three categories, verified verbatim from source docstrings:

- **`SystemFrame`** — "takes higher priority than other frames. System frames are handled in order and are **not affected by user interruptions**." Jumps the queue.
- **`DataFrame`** — "processed in order and usually contains data such as LLM context, text, audio or images. Data frames are **cancelled by user interruptions**."
- **`ControlFrame`** — in-order like data frames, carries control information (settings updates, end-of-pipeline). "Control frames are **cancelled by user interruptions**."
- **`UninterruptibleFrame`** — a *mixin*, not a category: "Frames with this mixin are still ordered normally, but unlike other frames, they are preserved during interruptions."

Direction:

```python
from pipecat.processors.frame_processor import FrameDirection

FrameDirection.DOWNSTREAM  # = 1, input -> output
FrameDirection.UPSTREAM    # = 2, output -> input (errors, control)
```

The frame classes we will touch, with their **actual** base classes at 1.9.0:

```python
from pipecat.frames.frames import (
    # audio
    InputAudioRawFrame,              # SystemFrame + AudioRawFrame mixin
    OutputAudioRawFrame,             # DataFrame + AudioRawFrame mixin
    # text / STT
    TextFrame,                       # DataFrame
    TranscriptionFrame,              # TextFrame
    InterimTranscriptionFrame,       # TextFrame
    # LLM
    LLMRunFrame,                     # DataFrame  <- kicks off inference
    LLMContextFrame,
    LLMMessagesUpdateFrame,          # DataFrame
    LLMSetToolsFrame,                # DataFrame
    LLMUpdateSettingsFrame,          # ControlFrame + UninterruptibleFrame
    LLMFullResponseStartFrame,       # ControlFrame
    LLMFullResponseEndFrame,         # ControlFrame
    # turn / VAD
    UserStartedSpeakingFrame,        # SystemFrame
    UserStoppedSpeakingFrame,        # SystemFrame
    BotStartedSpeakingFrame,         # SystemFrame
    BotStoppedSpeakingFrame,         # SystemFrame
    InterruptionFrame,               # SystemFrame  <- was StartInterruptionFrame
    # lifecycle
    StartFrame,                      # SystemFrame
    EndFrame,                        # ControlFrame + UninterruptibleFrame
    CancelFrame,                     # SystemFrame
    # transport
    OutputTransportMessageFrame,        # DataFrame
    OutputTransportMessageUrgentFrame,  # SystemFrame
    InputTransportMessageFrame,
)
```

Note two traps: **`AudioRawFrame` is a bare mixin class, not a `Frame` subclass** — never
`isinstance(frame, Frame)`-filter on it expecting a pipeline frame; use `InputAudioRawFrame` /
`OutputAudioRawFrame`. And **`StartInterruptionFrame` / `StopInterruptionFrame` do not exist**; there is a
single `InterruptionFrame`.

---

## 3. Context management

`OpenAILLMContext`, `OpenAILLMContextFrame` and `create_context_aggregator` return **zero grep hits** in the
1.9.0 source tree. The universal context is the only context.

```python
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
    LLMAssistantAggregatorParams,
)

context = LLMContext(tools=[collect_income, collect_expense])   # direct functions
user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
    context,
    user_params=LLMUserAggregatorParams(
        vad_analyzer=SileroVADAnalyzer(),
        user_turn_stop_timeout=5.0,   # replaces the old `aggregation_timeout`
        user_idle_timeout=0,          # 0 disables on_user_turn_idle
        audio_idle_timeout=1.0,
    ),
    assistant_params=LLMAssistantAggregatorParams(),
)
```

`LLMContextAggregatorPair` implements `__iter__`, so the tuple-unpack above and
`pair.user()` / `pair.assistant()` both work. The pair takes a `context` plus `user_params`,
`assistant_params`, `add_tool_change_messages` and `realtime_service_mode`.

`LLMContext` API: `.add_message(m)`, `.add_messages([...])`, `.set_messages([...])`,
`.transform_messages(...)`, `.set_tools(...)`, `.set_tool_choice(...)`, `.messages`, `.get_messages(...)`.

**Turn-stop strategies** (relevant if Deepgram endpointing is too eager) live in `pipecat.turns`:
`UserTurnStrategies`, and start/stop strategies such as `VADUserTurnStartStrategy`,
`MinWordsUserTurnStartStrategy`, `SpeechTimeoutUserTurnStopStrategy`, `TurnAnalyzerUserTurnStopStrategy`,
`DeferredUserTurnStopStrategy`. Pass via `LLMUserAggregatorParams(user_turn_strategies=...)`.

### Changing the system prompt mid-conversation

This is the important one for our "inject the list of still-missing fields each turn" design. **1.9.0
explicitly deprecated putting a `{"role": "system", ...}` message at the head of `LLMContext`** — the
CHANGELOG says it "will stop working in 2.0.0". The system prompt is now **service settings**:

```python
llm = OpenAILLMService(
    api_key=os.environ["OPENAI_API_KEY"],
    settings=OpenAILLMService.Settings(system_instruction=BASE_PROMPT),
)

# ...later, e.g. from a tool handler or a custom processor, once per turn:
await worker.queue_frame(
    LLMUpdateSettingsFrame(
        delta=OpenAILLMService.Settings(
            system_instruction=BASE_PROMPT + "\n\nSTILL MISSING: " + ", ".join(missing)
        )
    )
)
```

`LLMUpdateSettingsFrame` is a `ControlFrame + UninterruptibleFrame`, so it is ordered but never dropped by
an interruption. Internally `LLMService._compose_system_instruction()` always rebuilds from the base string,
so repeated updates never compound. There is also `llm.append_system_instruction(text)` for *durable* addons
that survive `LLMMessagesUpdateFrame(messages=[])` — but its docstring says it is intended for framework
components, so prefer the settings delta for per-turn changes.

---

## 4. Function calling

Three ways to define a tool, in increasing verbosity.

**(a) Direct functions — recommended.** The function *is* the schema; Pipecat parses the signature and the
Google-style docstring, and auto-registers the handler for any `LLMContext` that advertises it. Verified
verbatim from `examples/function-calling/function-calling-openai.py` @ v1.9.0:

```python
from pipecat.services.llm_service import FunctionCallParams

async def get_current_weather(params: FunctionCallParams, location: str, format: str):
    """Get the current weather.

    Args:
        location: The city and state, e.g. "San Francisco, CA".
        format: The temperature unit to use. Must be either "celsius" or "fahrenheit".
    """
    await params.result_callback({"conditions": "nice", "temperature": "75"})

context = LLMContext(tools=[get_current_weather, get_restaurant_recommendation])
```

No `@direct_function` decorator is required — a bare callable in `tools=` is wrapped by
`DirectFunctionWrapper`. There *is* a `@tool_options(...)` decorator to set `cancel_on_interruption` /
`timeout_secs` per tool.

**(b) Explicit `FunctionSchema`**, when you need an `enum` or other JSON-schema detail the generator won't emit:

```python
from pipecat.adapters.schemas.function_schema import FunctionSchema

async def fetch_current_weather(params: FunctionCallParams):
    location = params.arguments["location"]
    await params.result_callback({"conditions": "nice", "temperature": "75"})

weather_function = FunctionSchema(
    name="get_current_weather",
    description="Get the current weather",
    properties={
        "location": {"type": "string", "description": "The city and state"},
        "format": {"type": "string", "enum": ["celsius", "fahrenheit"],
                   "description": "The temperature unit to use."},
    },
    required=["location", "format"],
    handler=fetch_current_weather,   # bundling the handler auto-registers it
)
context = LLMContext(tools=[weather_function])
```

`ToolsSchema(standard_tools=[...], custom_tools={AdapterType.OPENAI: [...]})` from
`pipecat.adapters.schemas.tools_schema` is only needed to mix in provider-specific tools (e.g. OpenAI
web search). `LLMContext` normalizes a plain list into a `ToolsSchema` for you.

**(c) `register_function`**, still supported:

```python
llm.register_function(
    "get_current_weather", handler,
    cancel_on_interruption=None,   # default -> @tool_options -> True
    timeout_secs=None,             # per-tool override of the global timeout
    cancellable_by_llm=None,       # exposes a `cancel_<name>` tool; pair with cancel_on_interruption=False
)
```

`function_name=None` registers a catch-all handler.

**`FunctionCallParams`** (`pipecat.services.llm_service`) fields, verbatim: `function_name`, `tool_call_id`,
`arguments`, `llm`, `pipeline_worker`, `context`, `result_callback`, `app_resources`, `worker_runner`.
(`tool_resources` is a deprecated alias for `app_resources`, removal in 2.0.0.)

**Pushing frames from inside a handler** — this is how a tool sends a card update to the browser. `params.llm`
is an `LLMService`, which is a `FrameProcessor`, so it has `push_frame`:

```python
from pipecat.frames.frames import FunctionCallResultProperties
from pipecat.processors.frameworks.rtvi import RTVIServerMessageFrame
from pipecat.processors.frame_processor import FrameDirection

async def set_monthly_income(params: FunctionCallParams, amount: float):
    """Record the user's monthly take-home income.

    Args:
        amount: Monthly take-home pay in rupees.
    """
    plan = engine.set_income(amount)
    await params.llm.push_frame(
        RTVIServerMessageFrame(data={"type": "plan_update", "plan": plan}),
        FrameDirection.DOWNSTREAM,
    )
    await params.result_callback(
        {"ok": True},
        properties=FunctionCallResultProperties(run_llm=True),
    )
```

`FunctionCallResultProperties` (`pipecat.frames.frames`) carries `run_llm: bool | None`,
`on_context_updated: Callable[[], Awaitable[None]] | None`, and `is_final: bool = True`.
Set `run_llm=False` on all but the last of a batch of parallel calls to avoid extra inferences.
`is_final=False` streams an intermediate update and is only meaningful for async tools
(`cancel_on_interruption=False`); realtime LLM services **drop** intermediate results and raise.

**Parallel tool calls** are supported and batched: `LLMService(group_parallel_tools=True)` is the default,
so the LLM is re-run **once, after the last call of a parallel batch**, not once per result. The assistant
aggregator tracks a `_function_calls_in_progress` dict keyed by `tool_call_id`, and
`on_function_calls_started` receives the whole list.

**Timeouts:** since 1.0.0 `LLMService.function_call_timeout_secs` defaults to **`None`** (no timeout), not
`10.0`. Since 1.8.0 a call that exceeds it is *cancelled* — the handler is thrown `asyncio.CancelledError`,
a `FunctionCallCancelFrame` fires, and inference runs so the LLM can say it failed. Pass
`function_call_timeout_secs=10.0` explicitly so a wedged plan-engine call can't hang the turn forever.

---

## 5. Interruption handling

There is **no `allow_interruptions` parameter anywhere in 1.9.0** (zero grep hits across `src/pipecat`).
Interruption semantics are structural:

- VAD (or a turn strategy) causes an **`InterruptionFrame`** — a `SystemFrame`, so it overtakes queued work.
- All in-flight `DataFrame`s and `ControlFrame`s are cancelled: the LLM's streaming response and the TTS
  audio queue are dropped.
- Anything tagged `UninterruptibleFrame` survives — notably `EndFrame` (so shutdown is never lost) and
  `FunctionCallResultFrame` ("once a result is generated we always want to update the context").
- **A tool call in flight** is cancelled only if it was registered with `cancel_on_interruption=True`
  (the default); the handler is thrown `asyncio.CancelledError`. Register long-running work with
  `cancel_on_interruption=False` to make it asynchronous — the LLM keeps talking and the result is injected
  later as a developer message. Our plan-engine calls are fast and deterministic, so leave the default.
- **What the assistant aggregator records**: `_handle_interruptions` calls
  `_trigger_assistant_turn_stopped(interrupted=True)` then `reset()`. So the partial assistant turn *is*
  committed to context, flagged as interrupted — the LLM knows it was cut off mid-sentence.
- For a call that was started but not settled, the aggregator writes an `assistant` message with the
  `tool_calls` entry plus a `{"role": "tool", "content": "IN_PROGRESS", "tool_call_id": ...}` placeholder,
  which keeps the OpenAI message sequence valid.

Interruption sensitivity is tuned via `VADParams` and turn strategies, not a boolean. The 1.0.0 CHANGELOG
gives the exact replacement for `allow_interruptions=False`:

```python
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.turns.user_start import (
    MinWordsUserTurnStartStrategy,
    TranscriptionUserTurnStartStrategy,
)
from pipecat.turns.user_turn_strategies import UserTurnStrategies

LLMUserAggregatorParams(
    vad_analyzer=SileroVADAnalyzer(
        params=VADParams(confidence=0.7, start_secs=0.2, stop_secs=0.8, min_volume=0.6)
    ),
    # the modern spelling of `allow_interruptions=False`:
    user_turn_strategies=UserTurnStrategies(
        start=[TranscriptionUserTurnStartStrategy(enable_interruptions=False)],
    ),
)
```

Docs note two other documented ways to get the old `allow_interruptions=False` behaviour *(corrected via
context7)*: `VADUserTurnStartStrategy(enable_interruptions=False)` (the `fundamentals/interruptions` page's
canonical spelling — user speech during the bot's turn is then *queued* and processed after the bot finishes,
not dropped), and `user_mute_strategies`, which the 1.0 migration guide names as the official replacement.
The `TranscriptionUserTurnStartStrategy(enable_interruptions=False)` form above also works.

Use `MinWordsUserTurnStartStrategy` to require N words before a barge-in counts — the replacement for the
removed `MinWordsInterruptionStrategy`. Muting (the old `STTMuteFilter`) is now `user_mute_strategies` from
`pipecat.turns.user_mute`.

---

## 6. PipelineWorker / PipelineParams / WorkerRunner

```python
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker, ProcessorUnusablePolicy
from pipecat.workers.runner import WorkerRunner

worker = PipelineWorker(
    pipeline,
    params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
    processor_unusable_policy=ProcessorUnusablePolicy.END,
)
runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)
await runner.add_workers(worker)
await runner.run()
```

`PipelineParams` (a pydantic `BaseModel`) fields, verbatim: `audio_in_sample_rate=16000`,
`audio_out_sample_rate=24000`, `enable_heartbeats=False`, `enable_metrics=False`,
`enable_usage_metrics=False`, `heartbeats_period_secs`, `heartbeats_monitor_secs`,
`report_only_initial_ttfb=False`, `send_initial_empty_metrics=True`, `start_metadata={}`.
Note that **idle timeout and observers are *not* in `PipelineParams`** — they are `PipelineWorker`
constructor kwargs:

```python
PipelineWorker(
    pipeline,
    idle_timeout_secs=300,                 # None disables
    idle_timeout_frames=(BotSpeakingFrame, InterimTranscriptionFrame, TranscriptionFrame,
                         UserSpeakingFrame, UserStartedSpeakingFrame),   # the default tuple
    cancel_on_idle_timeout=True,
    observers=[TranscriptionLogObserver()],
    enable_rtvi=True,                      # DEFAULT — auto-adds RTVI to the pipeline
    enable_tracing=False,
    enable_turn_tracking=True,
    conversation_id=...,
    app_resources=my_session_state,        # reaches every handler via params.app_resources
)
```

Event handlers on the worker: `on_pipeline_started`, `on_pipeline_finished`, `on_pipeline_error`,
`on_idle_timeout`, `on_heartbeat_timeout`, `on_pipeline_timeout`, `on_frame_reached_upstream/downstream`.

Observers subclass `pipecat.observers.base_observer.BaseObserver` and implement
`async def on_push_frame(self, data: FramePushed)`. Built-ins worth knowing:
`pipecat.observers.loggers.{transcription_log_observer, llm_log_observer, metrics_log_observer,
debug_log_observer}`, plus `turn_tracking_observer`, `function_call_observer`, `user_bot_latency_observer`.

**Graceful shutdown when the user leaves** (verbatim from the v1.9.0 examples):

```python
@transport.event_handler("on_client_disconnected")
async def on_client_disconnected(transport, client):
    await runner.cancel()
```

Alternatives: `await worker.stop_when_done()` queues an `EndFrame` and lets everything drain;
`await worker.end(reason=...)` drains the pipeline then ends the session; `runner.stop_when_done()` /
`runner.end(reason)` / `runner.cancel(reason)` at the runner level. Use `cancel()` on disconnect (nobody is
listening to the drained audio) and `stop_when_done()` when the bot should finish its sentence first.

---

## 7. A custom FrameProcessor

Verified pattern from `examples/features/features-custom-frame-processor.py` @ v1.9.0 — note the source
comment "SUPER IMPORTANT: always push every frame!":

```python
from pipecat.frames.frames import Frame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.frameworks.rtvi import RTVIServerMessageFrame

class PlanStateEmitter(FrameProcessor):
    """Watches the plan engine and emits a card update to the browser."""

    def __init__(self, engine, **kwargs):
        super().__init__(**kwargs)
        self._engine = engine
        self._last = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)          # 1. always call super first

        if isinstance(frame, TranscriptionFrame):
            snapshot = self._engine.snapshot()
            if snapshot != self._last:
                self._last = snapshot
                await self.push_frame(
                    RTVIServerMessageFrame(data={"type": "plan_update", "plan": snapshot}),
                    FrameDirection.DOWNSTREAM,
                )

        await self.push_frame(frame, direction)                # 2. always forward every frame
```

Rules: call `super().__init__(**kwargs)`; `await super().process_frame(frame, direction)` as the first line
(the base class handles `StartFrame`, `EndFrame`, `CancelFrame` and `InterruptionFrame`); forward **every**
frame or the pipeline stalls; push errors and control upstream with `FrameDirection.UPSTREAM`.

Place the processor after the LLM / before `transport.output()` so that RTVI's observer sees the frame.
Because `enable_rtvi=True` is the `PipelineWorker` default, no `RTVIProcessor` needs to be added by hand.
If you prefer raw transport data messages instead of RTVI, push
`OutputTransportMessageUrgentFrame(message={...})` (a `SystemFrame`, sent immediately, survives
interruptions) or `OutputTransportMessageFrame(message={...})` (a `DataFrame`, ordered, dropped on
interruption). For live cards, the urgent variant is the right one.

---

## 8. Pipecat Flows — and why we skip it

Flows is now vendored **inside** `pipecat-ai` as `pipecat.flows` (the standalone `pipecat-ai-flows` PyPI
package last shipped 1.4.0 on 2026-07-05). The 1.9.0 sdist contains `src/pipecat/flows/{manager,flow,config,
adapters,actions,types}.py` plus a `flow_config.schema.json`, exporting `FlowManager`, `Flow`, `FlowConfig`,
`NodeConfig`, `FlowsFunctionSchema`, `FlowArgs`, `FlowResult`, `ContextStrategy`, `flows_direct_function`,
`flows_tool_options`. There are both Python and **YAML** flow examples in the repo.

Flows models a conversation as a graph of nodes; each node narrows the system prompt and the advertised tool
set to one step, which materially reduces hallucination for scripted funnels (patient intake, food ordering,
insurance quote — all the shipped examples). It requires a text LLM with function calling; speech-to-speech
models are unsupported because those APIs can't rewrite tools mid-session.

**We skip it.** Our assistant gathers ~6 finance slots that the user may volunteer in any order, revise
later, or skip; the "state machine" is really a set-cover problem over missing fields, not a path through a
graph. Encoding that as nodes means one node per subset. The adaptive alternative — one `LLMContext`, a
stable tool set, and a system prompt rebuilt each turn with the remaining gaps (§3) — is less code and
degrades more gracefully. Flows would be the right call if the product were a fixed script.

---

## Gotchas

1. **Every pre-1.3.0 tutorial is wrong about the top-level objects.** `PipelineTask` → `PipelineWorker`
   (`pipecat.pipeline.worker`), `PipelineRunner` → `WorkerRunner` (`pipecat.workers.runner`). The old modules
   are thin deprecation shims that will be **removed in 2.0.0**. `PipelineParams` moved to
   `pipecat.pipeline.worker` too (still re-exported from `pipecat.pipeline.task`).
2. **`OpenAILLMContext` is removed, not deprecated.** So is `create_context_aggregator()` and
   `LLMMessagesFrame`. Any snippet with `llm.create_context_aggregator(context)` will `AttributeError`.
3. **`StartInterruptionFrame` does not exist.** It is `InterruptionFrame`. There is no `StopInterruptionFrame`.
4. **`allow_interruptions` does not exist.** Passing it to `PipelineParams` raises a pydantic validation
   error, since `PipelineParams` is a `BaseModel`.
5. **`TransportMessageFrame` / `TransportMessageUrgentFrame` do not exist.** They are
   `OutputTransportMessageFrame` / `OutputTransportMessageUrgentFrame` / `InputTransportMessageFrame`.
6. **The RTVI import path is `pipecat.processors.frameworks.rtvi`.** In 1.9.0 the class lives in
   `pipecat.processors.frameworks.rtvi.frames` and is re-exported from `pipecat.processors.frameworks.rtvi`.
   `pipecat.frames.frames` has **no** `RTVIServerMessageFrame`. *(corrected via context7: the current
   `client/guides/custom-messaging` page no longer shows the stale `pipecat.frames.frames` import this gotcha
   was written against, and `api-reference/server/rtvi/rtvi-processor` uses
   `from pipecat.processors.frameworks.rtvi import RTVIServerMessageFrame`. Context7 additionally documents
   `RTVIServerMessageFrame` as a **`SystemFrame`** delivered on the high-priority lane — so it is not dropped
   on interruption, and §7's "use the urgent transport variant for live cards" caveat does not apply to it.)*
7. **`aggregation_timeout` is gone** from `LLMUserAggregatorParams`; the nearest equivalent is
   `user_turn_stop_timeout` (default 5.0s), with real control living in `user_turn_strategies`.
8. **The system prompt is service settings, not a context message.** Putting a `{"role": "system", ...}`
   message in `LLMContext` is no longer the idiomatic path; use `Settings(system_instruction=...)` and
   `LLMUpdateSettingsFrame`. Use `{"role": "developer", ...}` messages to nudge a turn (that is what the
   official examples do to trigger the greeting).
9. **`AudioRawFrame` is a mixin, not a `Frame`.** Filter on `InputAudioRawFrame` / `OutputAudioRawFrame`.
10. **`enable_rtvi=True` is the `PipelineWorker` default** — adding your own `RTVIProcessor` on top can
    double-handle messages. Pass `rtvi_processor=` if you need a custom one.
11. **`cartesia`, `openai` and `silero` extras are empty in 1.9.0.** If a build breaks with a missing
    Cartesia/Silero dependency, the fix is a base-dependency version problem, not a missing extra.
12. **`tool_resources` on `FunctionCallParams` is deprecated** (1.2.0) in favour of `app_resources`;
    `PipelineWorker(app_resources=...)` passes the object *by reference* to every handler, which is the clean
    way to share our plan-engine instance.
13. **Realtime/S2S services drop intermediate tool results** (`is_final=False`) and raise. Irrelevant for our
    cascaded Deepgram→gpt-5.6-luna→Cartesia pipeline, but it rules out a later S2S swap if we stream tool progress.
14. **Flat service imports were removed in 1.0.0.** `from pipecat.services.openai import OpenAILLMService`
    is an `ImportError`. Also gone: `pipecat.transports.services.*`, `pipecat.transports.network.*`,
    `pipecat.services.ai_services`, `pipecat.sync`. Use full submodule paths.
15. **`vad_analyzer` was removed from `TransportParams` and every transport input class in 1.0.0.** Silero
    now attaches to `LLMUserAggregatorParams(vad_analyzer=...)`. Passing it to `DailyParams` will fail. The
    `turn_analyzer` transport param is gone for the same reason.
16. **`function_call_timeout_secs` defaults to `None`** (no timeout) since 1.0.0 — it used to be `10.0`.
    Set it explicitly.
17. **Functions must use named parameters.** The single-`arguments`-dict handler signature was removed in
    1.0.0 for direct functions (an explicit `FunctionSchema` handler still reads `params.arguments`).
18. **RTVI protocol is at 2.1.0** (2.0.0 in 1.4.0, 2.1.0 in 1.6.0). Pre-2.x clients other than 1.x are
    **rejected outright**, so pin a current `@pipecat-ai/client-js` in the frontend. In 1.6.0 the `dtmf`
    client message switched from `button` to a `buttons` list.
19. **The dev runner's Daily redirect moved from `GET /` to `GET /daily`** in 1.3.0, and `pipecat create`
    became **`pipecat init`** in 1.5.0 (`pipecat init quickstart`). Note the dev runner itself did *not*
    move — `pipecat.runner.{run,types,utils,daily}` still exist; only `PipelineRunner` moved.
20. **Cartesia's default model became `sonic-3.6` in 1.9.0**, and the `cartesia_version` param is deprecated
    (auth moved to `X-API-Key` headers in 1.8.0). Pin `model="sonic-3.5"` if 3.6 changes prosody on us.
21. **Deepgram no longer emits `ProcessingMetricsData`** (1.8.0), so RTVI `metrics.processing` is empty for
    STT; TTFB still works. `profanity_filter` is no longer sent by default (1.9.0).
22. **"Fatal" errors are deprecated** (1.8.0): `ErrorFrame.fatal`, `FatalErrorFrame`, `push_error(fatal=...)`
    all go in 2.0.0. Use `PipelineWorker(processor_unusable_policy=ProcessorUnusablePolicy.END)` — which is
    what the official examples now do, and what we should do so a bad API key ends the call cleanly.
23. **`WorkerParams.loop` was removed in 1.5.0** — pass `WorkerParams(task_manager=...)` instead. And
    `PipelineTaskParams` is now `WorkerParams` in `pipecat.workers.base_worker`.
24. **`StartFrame.enable_metrics` / `audio_*_sample_rate` etc. are deprecated** (1.8.0) in favour of reading
    them from `FrameProcessorSetup` inside a processor's `setup()` — relevant if our custom processor needs
    the sample rate.
25. **UNVERIFIED:** the exact model id `gpt-5.6-luna` was not checked against the OpenAI API in this pass —
    Pipecat passes the string straight through to `OpenAILLMService`, so this is an OpenAI-side question.
26. **UNVERIFIED:** whether `pipecat-ai-flows` 1.4.0 still installs cleanly alongside `pipecat-ai` 1.9.0, or
    whether it now conflicts with the vendored `pipecat.flows`. Since we are skipping Flows, untested.
27. **UNVERIFIED:** exact `@pipecat-ai/client-js` / `@pipecat-ai/daily-transport` versions that speak RTVI
    2.1.0 — covered in the frontend research task, not here.

---

## Sources

- PyPI JSON API, `pipecat-ai` — https://pypi.org/pypi/pipecat-ai/json and `/1.9.0/json` (version 1.9.0,
  `requires_python >=3.11`, upload 2026-09-11T03:05:13Z)
- **Primary source of truth:** sdist `pipecat_ai-1.9.0.tar.gz` —
  https://files.pythonhosted.org/packages/a0/66/07eeb9828559717736ac7a3398c2b419646d8d16ca1e8ab1cd230c488558/pipecat_ai-1.9.0.tar.gz
  (`pyproject.toml`, `src/pipecat/frames/frames.py`, `src/pipecat/pipeline/worker.py`,
  `src/pipecat/pipeline/task.py`, `src/pipecat/pipeline/runner.py`, `src/pipecat/workers/runner.py`,
  `src/pipecat/processors/aggregators/llm_context.py`,
  `src/pipecat/processors/aggregators/llm_response_universal.py`, `src/pipecat/services/llm_service.py`,
  `src/pipecat/adapters/schemas/{function_schema,tools_schema,direct_function}.py`,
  `src/pipecat/processors/frameworks/rtvi/frames.py`, `src/pipecat/audio/vad/vad_analyzer.py`,
  `src/pipecat/flows/__init__.py`, `CHANGELOG.md`)
- Examples at git tag `v1.9.0` —
  https://github.com/pipecat-ai/pipecat/blob/v1.9.0/examples/function-calling/function-calling-openai.py ,
  `.../function-calling-advanced-functionschema.py` , `.../function-calling-direct.py` ,
  https://github.com/pipecat-ai/pipecat/blob/v1.9.0/examples/features/features-custom-frame-processor.py ,
  `.../examples/update-settings/llm/llm-openai.py` ,
  `.../examples/turn-management/turn-management-interruption-config.py`
- https://github.com/pipecat-ai/pipecat/releases
- https://docs.pipecat.ai/pipecat/fundamentals/custom-frame-processor
- https://docs.pipecat.ai/pipecat/flows/introduction
- https://docs.pipecat.ai/client/guides/custom-messaging (stale import path — see gotcha 6)
- https://pypi.org/pypi/pipecat-ai-flows/json (1.4.0, 2026-07-05)


---

## Context7 cross-check (2026-09-11)

**Library used:** `/pipecat-ai/docs` (Context7; "Pipecat", 6869 snippets, source reputation High, benchmark
78.01). Context7 returned **no version-pinned variant** for this library — the corpus is the live
`github.com/pipecat-ai/docs` `main` branch, so it is *unversioned*. Version markers observed inside it
(`migration-1.0.mdx`, "deprecated since version 1.5.0", "default since 0.0.102", `LocalSmartTurnAnalyzerV3`,
`WorkerRunner`, `LLMContext`) place it firmly in the post-1.0 era and broadly consistent with 1.9.0, but a
handful of API-reference pages lag the source tree (noted below). Other candidates
(`/pipecat-ai/pipecat`, `/websites/pipecat_ai`) were rejected as lower-coverage mirrors of the same content.

**Ground rule applied:** this report's claims were verified against the 1.9.0 **sdist**. Where context7's prose
docs disagree, the disagreement is flagged and the body is left alone unless context7 is unambiguously the
current, canonical statement.

| # | Claim (section) | Status | Context7 evidence |
| --- | --- | --- | --- |
| 1 | `PipelineTask`/`PipelineRunner` deprecated → `PipelineWorker`/`WorkerRunner` (§6, gotcha 1) | VERIFIED | `pipecat/learn/your-first-agent`: "The terms PipelineTask and PipelineRunner are deprecated aliases for PipelineWorker and WorkerRunner"; `workers/runner`: "PipelineRunner … is a deprecated alias for WorkerRunner" |
| 2 | `from pipecat.pipeline.worker import PipelineParams, PipelineWorker`; `from pipecat.workers.runner import WorkerRunner` (§6) | VERIFIED | `pipeline/pipeline-worker` snippet uses exactly these import paths |
| 3 | `await runner.add_workers(worker); await runner.run()` (§6) | VERIFIED | `get-started/quickstart` and `workers/runner` both show this two-call form |
| 4 | `OpenAILLMContext` removed → `LLMContext` (§3, gotcha 2) | VERIFIED | `migration/migration-1.0` "What was removed": "OpenAILLMContext, AnthropicLLMContext, and AWSBedrockLLMContext are now consolidated into LLMContext" |
| 5 | `create_context_aggregator()` removed → `LLMContextAggregatorPair` (§3, gotcha 2) | VERIFIED | same page: "creation of context aggregators has shifted to the LLMContextAggregatorPair pattern" |
| 6 | `LLMContextAggregatorPair(context)` tuple-unpacks to `(user, assistant)` (§3) | VERIFIED | `fundamentals/saving-transcripts`, `learn/context-management`, `migration-1.0` all unpack the pair |
| 7 | System prompt is service settings: `OpenAILLMService.Settings(system_instruction=...)` (§3, gotcha 8) | VERIFIED | `learn/context-management` "Using system_instruction (recommended)" — "prepended to context messages by the service, survives context updates and summarization … supports runtime updates" |
| 8 | Context `{"role":"system"}` head message is deprecated and "will stop working in 2.0.0" (§3, gotcha 8) | PARTIAL / softer in docs | Docs label it **"legacy"**, not removed: "less reliable than system_instruction because it can be lost during full context replacement". Also adds a fact this report omits: **if both are provided, `system_instruction` takes precedence.** Report's 2.0.0 removal date comes from the 1.9.0 CHANGELOG and is retained |
| 9 | `LLMUpdateSettingsFrame(delta=Service.Settings(...))` queued on the worker (§3) | VERIFIED | `services/s2s/openai` and `services/llm/azure` both show `await worker.queue_frame(LLMUpdateSettingsFrame(delta=...))` |
| 10 | `LLMUpdateSettingsFrame` is uninterruptible (§3) | VERIFIED | `fundamentals/service-settings`: "Update settings frames are uninterruptible and will always be processed" |
| 11 | Partial settings deltas — unspecified fields unchanged (§3) | VERIFIED | same page: "only specify the fields you wish to alter; all other fields will remain unchanged" |
| 12 | `allow_interruptions` removed entirely (§5, gotcha 4) | VERIFIED | `migration-1.0` "Turn Management": "The legacy allow_interruptions parameter … has been removed" |
| 13 | Replacement spelling for `allow_interruptions=False` is `TranscriptionUserTurnStartStrategy(enable_interruptions=False)` (§5) | CONTRADICTED (corrected inline) | `fundamentals/interruptions` canonicalises **`VADUserTurnStartStrategy(enable_interruptions=False)`**; `migration-1.0` names **`user_mute_strategies`** as *the* replacement. Docs also add a behavioural detail the report lacks: with interruptions disabled, user speech is **queued and processed after the bot finishes**, not discarded |
| 14 | `StartInterruptionFrame`/`StopInterruptionFrame` gone → single `InterruptionFrame` (§2, gotcha 3) | VERIFIED | `frames/system-frames`: "The InterruptionFrame is used to interrupt the pipeline by discarding all pending DataFrames and ControlFrames" |
| 15 | Frame categories: SystemFrame jumps queue; Data/Control cancelled on interruption (§2) | VERIFIED | same snippet, exactly this split |
| 16 | `UninterruptibleFrame` is a mixin, and `FunctionCallResultFrame` carries it (§2, §5) | VERIFIED | `frames/overview`: `class FunctionCallResultFrame(DataFrame, UninterruptibleFrame)` — "Must be delivered even if the user interrupts" |
| 17 | Direct functions: `async def f(params: FunctionCallParams, arg: str)` + Google docstring, no decorator (§4a) | VERIFIED | `learn/function-calling` "Define a Tool with Direct Function" — byte-identical `get_current_weather` example |
| 18 | Bare callables in `LLMContext(tools=[...])` auto-register; no `register_function` needed (§4a) | VERIFIED | `service-switchers/llm-switcher`: "`register_direct_function` … is deprecated. Direct functions now register automatically when listed in `LLMContext(tools=[...])`" |
| 19 | `@tool_options(cancel_on_interruption=..., timeout_secs=...)` exists (§4a) | VERIFIED | `learn/function-calling` shows `from pipecat.adapters.schemas.direct_function import tool_options` with both kwargs |
| 20 | A `FunctionSchema` with a bundled `handler=` auto-registers (§4b) | VERIFIED | `llm-switcher` note: "You don't need `register_function` when your tool's handler is bundled on its `FunctionSchema`" |
| 21 | `register_function(..., cancellable_by_llm=...)` exposes a `cancel_<name>` tool (§4c) | CONTRADICTED (body left, see Corrections) | Context7's `register_function` signature is `(function_name, handler, cancel_on_interruption, timeout_secs)` — **no `cancellable_by_llm`**. The documented model-directed-cancel path is `OpenAILLMService(enable_async_tool_cancellation=True)`, which adds one built-in tool named **`cancel_async_tool_call`**, not a per-function `cancel_<name>` |
| 22 | `FunctionCallParams` fields include `pipeline_worker` and `worker_runner` (§4) | CONTRADICTED (body left) | `learn/function-calling` dataclass lists only `function_name, tool_call_id, arguments, llm, context, result_callback, app_resources` — no `pipeline_worker`, no `worker_runner`, and no deprecated `tool_resources` |
| 23 | `app_resources` is the shared-state channel into every handler (§4, §6, gotcha 12) | VERIFIED | `FunctionCallParams.app_resources` — "Application-defined resources shared across tool calls"; `pipeline-worker` constructor docs: "application-defined resources, such as database handles or API clients, which are shared across tool handlers" |
| 24 | `function_call_timeout_secs` defaults to `None` (§4, gotcha 16) | NOT COVERED | Docs reference "the global `function_call_timeout_secs`" only as the thing `timeout_secs` overrides; no default is stated anywhere in the corpus |
| 25 | `group_parallel_tools=True` is the default (§4) | NOT COVERED | No snippet mentions this kwarg |
| 26 | `enable_rtvi=True` is the `PipelineWorker` default (§6, gotcha 10) | VERIFIED | `rtvi/introduction` documents *disabling* it: `PipelineWorker(pipeline, enable_rtvi=False)` |
| 27 | `RTVIServerMessageFrame` lives at `pipecat.processors.frameworks.rtvi` (§4, §7, gotcha 6) | VERIFIED (+ correction) | `rtvi/rtvi-processor`: `from pipecat.processors.frameworks.rtvi import RTVIServerMessageFrame`. **New fact:** it is a **`SystemFrame`** "delivered via the high-priority lane" — so it already survives interruption. The current `client/guides/custom-messaging` page no longer shows the stale `pipecat.frames.frames` import gotcha 6 was written against |
| 28 | Client receives it via `client.on(RTVIEvent.ServerMessage, ...)` (§ decision summary) | VERIFIED | `client/guides/custom-messaging` shows exactly this listener |
| 29 | `OutputTransportMessageFrame` is a DataFrame; urgent variant is a SystemFrame (§2, §7, gotcha 5) | VERIFIED | `frames/data-frames` documents `OutputTransportMessageFrame`; `frames/system-frames` documents "an urgent variant designed to bypass the standard queue for immediate delivery" |
| 30 | `PipelineWorker(idle_timeout_secs=300)` default, `cancel_on_idle_timeout=True` default (§6) | VERIFIED | `pipeline/pipeline-idle-detection`: "Defaults to 300. Set to None to disable"; "Defaults to True" |
| 31 | `idle_timeout_frames` default is the 5-tuple `(BotSpeakingFrame, InterimTranscriptionFrame, TranscriptionFrame, UserSpeakingFrame, UserStartedSpeakingFrame)` (§6) | CONTRADICTED (body left — see Corrections) | Context7 states the default **twice** as `(BotSpeakingFrame, UserSpeakingFrame)` (`pipeline-idle-detection` and `learn/pipeline-termination`) |
| 32 | `observers=[...]` is a `PipelineWorker` kwarg, not a `PipelineParams` field (§6) | VERIFIED | `observers/observer-pattern`: `PipelineWorker(pipeline, observers=[LLMLogObserver(), TranscriptionLogObserver(), ...])` |
| 33 | Worker event handlers incl. `on_pipeline_error` (§6) | VERIFIED | `pipeline/pipeline-worker` shows `@worker.event_handler("on_pipeline_error")` |
| 34 | `ProcessorUnusablePolicy.END`; "fatal errors" deprecated in 1.8.0 (§ decision summary, gotcha 22) | NOT COVERED / mild disagreement | `ProcessorUnusablePolicy` returns **zero** hits in the corpus. Worse, `pipeline/pipeline-worker` still actively documents the supposedly-deprecated surface: `if frame.fatal: print("Fatal error — pipeline will be cancelled")`. Context7 is behind here; the report's CHANGELOG-sourced claim is retained |
| 35 | Custom `FrameProcessor`: `await super().process_frame(...)` first, then push **every** frame (§7) | VERIFIED | `client/guides/custom-messaging` `CustomFrameProcessor` follows this exact shape |
| 36 | Observers subclass `BaseObserver` and implement `on_push_frame(self, data: FramePushed)` (§6) | VERIFIED | `custom-messaging` `CustomObserver(BaseObserver)` with `async def on_push_frame(self, data: FramePushed)` |
| 37 | Flows is vendored inside `pipecat-ai` as `pipecat.flows` (§8) | VERIFIED | `pipecat-flows/guides/functions`: `from pipecat.flows import flows_tool_options` |
| 38 | `cancel_on_interruption` defaults to `True` (§4c) | CONTRADICTED for the Flows decorator | `api-reference/pipecat-flows/types` documents `@flows_tool_options(cancel_on_interruption: bool — Optional (Default: **False**))`. This is the Flows wrapper, not core `register_function`, so it is not strictly the same knob — but if we ever touch Flows, do not assume `True` |
| 39 | Extras `cartesia`/`openai`/`silero` resolve to `[]` (§1, gotcha 11) | NOT COVERED | Prose docs never enumerate extra contents; unverifiable here, sdist `pyproject.toml` remains the only source |
| 40 | Flat service imports removed in 1.0.0 (§1, gotcha 14) | VERIFIED (indirectly) | Every context7 snippet uses full submodule paths (`pipecat.services.openai.llm`, `pipecat.services.deepgram.stt`, `pipecat.audio.vad.silero`); `migration-1.0` is the stated cutover |

**Tally:** 27 VERIFIED · 4 CONTRADICTED · 2 PARTIAL · 7 NOT COVERED.

### Corrections applied

1. **§5 (Interruption handling)** — added the two spellings context7 documents for the old
   `allow_interruptions=False`: `VADUserTurnStartStrategy(enable_interruptions=False)` and
   `user_mute_strategies`, plus the behavioural note that disabled interruptions **queue** user speech rather
   than discard it. Marked *(corrected via context7)*. The original `TranscriptionUserTurnStartStrategy`
   spelling is kept — it is valid, just not the canonical one.
2. **Gotcha 6 (RTVI import path)** — rewritten. The "published docs are stale" framing is retired: the current
   `client/guides/custom-messaging` no longer carries the bad import. Added context7's new fact that
   `RTVIServerMessageFrame` is a **`SystemFrame`** on the high-priority lane, which means §7's advice to prefer
   the *urgent* transport variant for live cards does not apply when you are already using RTVI. Marked
   *(corrected via context7)*.

### Disagreements left unresolved (source-verified claim retained)

- **`idle_timeout_frames` default (row 31).** Context7 says a 2-tuple; this report says a 5-tuple read from
  the 1.9.0 sdist. Two independent doc pages agree with each other, so this is not a one-off typo — but both
  are prose pages, and the report's tuple is the kind of thing that grows release over release. **Action:
  re-grep `src/pipecat/pipeline/worker.py` before relying on either.** Practically harmless for us: we pass
  `idle_timeout_frames` explicitly, or accept the default and only care that bot/user speech resets the timer,
  which both versions do.
- **`cancellable_by_llm` / `cancel_<name>` (row 21).** Context7 documents a *different* mechanism
  (`enable_async_tool_cancellation=True` → one `cancel_async_tool_call` tool). Either the report generalised
  from a source kwarg that context7 has not documented, or the API was reshaped. We do not use this feature
  (our plan-engine calls are fast and synchronous), so it is not on the critical path — but **do not build on
  `cancellable_by_llm` without re-reading `llm_service.py`.**
- **`FunctionCallParams.pipeline_worker` / `.worker_runner` (row 22).** Context7's dataclass omits them. Docs
  routinely abbreviate dataclasses, so absence is weak evidence — but prefer `params.llm` and
  `params.app_resources` (both confirmed) over the two unconfirmed fields.
- **`ProcessorUnusablePolicy` (row 34).** Zero coverage in context7, which still documents `frame.fatal`
  as live. Here context7 is clearly the *older* view (the report cites the 1.8.0 CHANGELOG deprecation), so
  the decision-summary recommendation stands unchanged.

### Unverifiable via context7

`function_call_timeout_secs` default, `group_parallel_tools` default, extras contents, PyPI upload timestamp,
the `gpt-5.6-luna` model id, Cartesia `sonic-3.6` default, and RTVI protocol 2.1.0 client-rejection behaviour
all returned nothing. These remain sdist/CHANGELOG-only claims and keep their existing UNVERIFIED markers
where they had them.
