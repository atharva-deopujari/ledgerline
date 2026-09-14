# 12 — Voice observability: tracing, evaluation storage, memory, persistence

Researched 2026-09-13 against the installed Pipecat 1.9.0 source, Langfuse docs and vendor pages. Where a claim could
not be settled from the source it is marked **(unverified)**. Three claims in the first draft were wrong and were
corrected by spike S3; see §6.

## Decision summary

- **Langfuse Cloud over OTLP, nothing else.** Pipecat already emits the span tree and the latency numbers, so a vendor
  sells UI, audio capture and a judge, not the measurement. Langfuse ingests Pipecat OTLP first-party, is free at the
  size we run, and is the same tool already used for the text agents.
- **One `TracerProvider`, built by us, handed to the Langfuse SDK.** `Langfuse(tracer_provider=provider)` owns the
  OTLP/HTTP exporter, auth, masking and flush. Pipecat's `setup_tracing()` is not called and no exporter of our own is
  registered; either one causes silent duplicate export or dropped scores (§6).
- **Tool calls need our own spans.** The Chat Completions path in Pipecat emits no span per executed tool call.
  Verified in source, not inferred. Our observer opens one, typed `tool`, under the current turn.
- **The JSON recording stays the archive.** Langfuse is the viewer and its free retention is 30 days.
- **The end-of-call judge is our code, scores pushed by `trace_id`.** Langfuse's managed trace-level evaluators are
  deprecated in v4 and one call is one trace, which is exactly the shape that was deprecated.
- **No memory framework.** mem0, Zep and Letta all re-derive structure from prose. Our facts arrive already typed from
  `upsert_item`. Paying a model to guess back what we already hold inverts the one rule.
- **Postgres for what Langfuse cannot hold, no Redis.** Users, a slim session row and the person's remembered facts
  and notes with supersession rows. Turns are not stored twice: Langfuse holds every turn and tool call, the JSON
  recording is the archive. Had turns been stored, row per turn beats a JSONB blob (appending to a blob rewrites the
  whole document, a 60-turn call is O(n^2) bytes written). At a single instance Redis adds a hop, a container and a
  failure mode and buys nothing.

## 1. Pipecat's OpenTelemetry surface

Docs https://docs.pipecat.ai/server/utilities/opentelemetry , source read at
https://github.com/pipecat-ai/pipecat/blob/0498609/src/pipecat/utils/tracing/

**Span tree.** `conversation` -> `turn-N` -> `stt_* | llm_* | tts_*`, built by `TurnTraceObserver`, itself a
`BaseObserver`, so it sits alongside our transcript observer rather than in place of it. Enabled with
`PipelineWorker(..., enable_tracing=True, enable_turn_tracking=True, conversation_id=session_id,
additional_span_attributes={...})` plus `PipelineParams(enable_metrics=True, enable_usage_metrics=True)`. Both flags
default to True in 1.9.0; we pass them explicitly anyway. `conversation_id` auto-generates a UUID if omitted. Write
`PipelineWorker`: `PipelineTask` has been a deprecated alias since 1.3.0, though Langfuse's guide still shows the old
name.

**Attributes.** Conversation: `conversation.id`, `conversation.type`. Turn: `turn.number`, `turn.type`,
`turn.duration_seconds`, `turn.was_interrupted`. STT: `gen_ai.provider.name`, `gen_ai.request.model`, `transcript`,
`is_final`, `language`, `vad_enabled`, `metrics.ttfb`, `settings.*`. TTS: the same plus `voice_id`, `text`,
`metrics.character_count`. LLM: `gen_ai.operation.name`, `stream`, `input`, `output`, `tools`, `tool_count`,
`tool_choice`, `gen_ai.system_instructions`, `gen_ai.usage.*` (input, output, cached input, audio), `metrics.ttfb`,
`gen_ai.request.*`.

**The tool-call gap, verified in source.** `tools`, `tool_count` and `tool_choice` are the definitions *offered*, not
the calls *made*. In `utils/tracing/service_decorators.py`, `traced_llm` (the Chat Completions path) captures model
info, context messages, tool configurations, token usage, TTFB and aggregated output, with no executed-call operation.
`traced_gemini_live` does have `llm_tool_call` ("Function call information") and `llm_tool_result` ("Function
execution results"); `traced_openai_realtime` captures function calls inside `llm_response`. So per-executed-call
spans exist for the realtime APIs and not for Chat Completions: the arguments and result of `upsert_item(...)` appear
only indirectly, inside the next turn's `input`. A vendor advertising "tool calls from Pipecat tracing" is showing the
definitions or running its own instrumentation **(unverified)**. Our per-call JSON recording therefore keeps its job as
the only record of executed tool calls and final state, and `voice/tool_trace.py` adds the spans Pipecat does not.

**Turn context is public API.** `PipelineWorker.turn_trace_observer.get_current_turn_context()` returns the current
turn's span context and `get_turn_context(n)` survives the pipeline, so a tool span can parent itself correctly and
the trace id for scoring is `format(ctx.trace_id, "032x")` with no lookup and no private attribute.

**Metrics frames are separate from spans.** `MetricsFrame(data: list[MetricsData])` is a `SystemFrame`, with
subclasses for TTFB, first audio (TTFB plus TTS leading silence), first answer token, processing, LLM usage, STT usage
in audio seconds, TTS usage in characters, smart turn, turn and text aggregation. `MetricsLogObserver` prints all of
it for free. Separately, `UserBotLatencyObserver` decomposes user-stopped-speaking to bot-started-speaking into named
contributions including the parts no single service measures, which is the real end-of-utterance breakdown and is
*not* in the OTel spans. Audio replay also needs no vendor: `AudioBufferProcessor(auto_start_recording=True)` emits
`on_audio_data` and `on_track_audio_data`, and Daily has `cloud-audio-only` recording plus `dataOutputs:
transcript-webvtt` aligned to the media.

## 2. Langfuse

**Ingest, HTTP only.** First-party and documented: https://langfuse.com/integrations/frameworks/pipecat , runnable
example https://github.com/pipecat-ai/pipecat-examples/tree/main/open-telemetry/langfuse . Endpoint
`https://cloud.langfuse.com/api/public/otel` (US `us.`, JP `jp.`, self-host on v3.22.0+), signal path `/v1/traces`,
auth `Authorization=Basic <base64 pk-lf-...:sk-lf-...>` plus `x-langfuse-ingestion-version=4`. "Langfuse currently
supports OTLP over HTTP with both HTTP/JSON and HTTP/protobuf"; gRPC is not supported, so the `.grpc` exporter shown
in Pipecat's first doc example fails silently. Since the SDK owns the exporter in our design, this cannot be got wrong
by hand.

**Mapping.** One Pipecat conversation is one Langfuse trace, not a session, and the guide says explicitly not to
invent a session per call. Turn and service spans nest as observations. Recognised attributes are
`langfuse.trace.name`, `langfuse.user.id` or `user.id`, `langfuse.session.id` or `session.id`, `langfuse.trace.tags`,
`langfuse.trace.metadata.*`, `langfuse.trace.input` / `.output`, `langfuse.observation.type`, `gen_ai.request.*` and
`gen_ai.usage.*`. Passing these through `additional_span_attributes` is documented on both sides but the combination
is **(unverified)**.

**Rough edges, accepted.** (a) STT and TTS arrive as `span`, not `generation`, so they carry no cost and no
input/output; only the LLM gets cost. Open since Dec 2025, https://github.com/langfuse/langfuse/issues/11573 . The
workaround, emitting `langfuse.observation.type=generation` with `usage_details` and a custom model price, we have not
taken. (b) STT and TTS span latency has been reported missing (issue 7909, closed with no fix cited). (c)
Conversation-level input and output are not set by Pipecat; the Langfuse guide monkeypatches
`service_decorators.add_llm_span_attributes`, a private-ish seam that breaks silently on upgrade, so we set
`langfuse.trace.input` / `.output` from our own observer instead.

**Scores are the right home for the judge.** `langfuse.create_score(name=, value=, trace_id=, data_type=)` or REST
`POST /api/public/scores`, types `NUMERIC | CATEGORICAL | BOOLEAN | TEXT`
(https://langfuse.com/docs/evaluation/evaluation-methods/custom-scores). A score can be posted by `trace_id` **before
or after the trace exists**; it links when the trace lands. So the judge runs after disconnect in a background task,
keyed on the conversation trace id, and needs no ordering guarantee.

**Managed evaluators are the wrong shape for voice.** Langfuse's server-side LLM-as-a-judge
(https://langfuse.com/docs/evaluation/evaluation-methods/llm-as-a-judge) runs on *observations*, filterable by type,
name, metadata and trace-level userId/sessionId/tags, with percentage sampling. Trace-level evaluators are deprecated
in v4. A Pipecat conversation is one trace, so "judge the whole call" is precisely what was deprecated; the implied
workaround is writing a call summary onto the root observation and judging that **(unverified)**. Our own judge is
strictly better here: it is testable offline and can read the final domain state, which no span carries.

**Prompt management, no Redis.** Versions plus labels (`production`, `latest`, custom), playground, experiments. The
client-side cache TTL defaults to 60 s, `get_prompt("name", cache_ttl_seconds=300)`, `0` disables; on expiry the SDK
returns the stale prompt immediately and revalidates in the background, and `fallback=` covers a cold cache with the
API down (https://langfuse.com/docs/prompt-management/features/caching). Stale-while-revalidate in process: zero
hot-path latency after the first fetch and no cache of our own.

**Versions.** PyPI `langfuse` 4.15.2, Python `>=3.10,<4.0`; the SDK was rewritten in v4 (March 2026) and is still
OTel-based, as v3 was; v4 GA 2026-08-17, **Cloud goes v4-only on 2026-11-16**. Self-host is free: all product features
were open-sourced under MIT on 2025-06-04, the commercial licence covering only governance (RBAC, audit logs, SCIM,
retention, masking).

**Units, and what actually binds.** Billable units are traces plus observations plus scores, every nested span
counted, including scores Langfuse's own judge writes (https://langfuse.com/docs/administration/billable-units). A
30-turn call is roughly 1 + 30 + about 90, call it **about 120 units**, so Hobby's 50k a month is **about 400 calls**.
Cost is a non-issue at our size; **the 30-day retention is the real limit**, which is why the recordings and Postgres
are the archive. Pricing was read off marketing pages **(unverified)**.

## 3. Alternatives, for voice specifically

Pipecat's `evals/platforms/` index lists five partners (Arize, Bluejay, Cekura, Coval, Roark; Cekura is a simulation
platform in Coval's category at unpublished prices), `services/analytics/` lists eight community-maintained analytics
services, and `pipecat-examples/open-telemetry/` ships jaeger, langfuse, langsmith, opik, signoz and arize demos.

| Tool | What it adds for voice | Why not now |
|---|---|---|
| Arize Phoenix / AX | `openinference-instrumentation-pipecat` 2.0.5 requires `pipecat-ai>=1.3`, so it works on 1.9; turn-grouped spans, audio playback in the trace UI, an audio-input judge | audio replay is not a need yet; Phoenix is Elastic License 2.0, not Apache; AX self-host is enterprise |
| Bluejay | audio playback, richest personas, red-teaming, LLM judge | weakest latency reporting, run-level average only; per-minute rate unpublished |
| Coval | the most complete voice set: audio, personas, judge, latency-as-silence-gap, TTFA, interruption rate, WER, tempo; no SDK so version-agnostic | no free tier, $100/mo floor, simulation $0.40/min |
| Roark | best-documented voice metrics anywhere (`response_time`, `time_to_first_word`, `latency_spike_count`, `interruption_duration`, 70+), stereo audio via `AudioBufferProcessor`, cheapest entry | **blocked: `pipecat-roark` 0.2.0 pins `pipecat-ai>=0.0.104,<1`**, and Pipecat's own page concedes it was tested on v0.0.108 |
| LangSmith | first-party `langsmith[pipecat]>=0.9.7`, maps the existing spans, audio via `AudioBufferProcessor` | beta; simulation is text-only; free tier is one seat and overage is priced in opaque units |
| Braintrust | first-party `BraintrustPipecatObserver`, requires `pipecat-ai>=1.3.0`, names time-to-first-token | no simulation, no end-of-utterance breakdown, 14-day retention on the free tier |
| Vapi | recording, simulation, scorecards, AI judge | **cannot ingest Pipecat traces**: it replaces the stack rather than observing it |
| Retell | the best-documented per-turn latency model found anywhere: E2E, ASR, LLM, TTS, KB and S2S each at p50/p90/p95/p99 | **cannot ingest** either; copy it as a metrics specification, do not integrate |
| Finchvox | local session replay, audio plus logs plus traces in one view, surfaces interruptions and high user-to-bot latency, no account or API key for local use | genuinely tempting given the Cartesia minute cap; held back only because Langfuse already covers the tracing need and this adds a second UI |

Three categories can ingest Pipecat 1.9: plain OTel sinks (Jaeger, Langfuse, SigNoz), partner simulation platforms
that connect externally and are therefore version-agnostic, and span-mappers (Arize, LangSmith, Braintrust, Future
AGI, MLflow), none of which run simulated voice calls or compute end-of-utterance breakdowns. Hamming is absent from
Pipecat's index and its docs sit behind an access-code wall, so nothing about it could be verified.

## 4. Per-user memory

- **mem0** (`mem0ai` 2.0.20, Apache-2.0) is explicitly an LLM over unstructured text: one model call extracts facts, a
  second decides ADD/UPDATE/DELETE. `infer=False` skips both, but then "Mem0 stores your payload exactly as provided,
  so duplicates can land", a key-value store with extra steps. The OSS package is being hollowed out: graph memory is
  platform-only and the README concedes proprietary optimisations are absent. Pipecat ships `Mem0MemoryService`, but
  `add()` is now async server-side, so newly stored memories are queryable only once processed.
- **Zep / Graphiti**: Zep Community Edition is dead, moved to `legacy/` and no longer supported. What remains open is
  `graphiti-core` 0.30.2 over Neo4j 5.26+, FalkorDB or Neptune, which you operate yourself. The bi-temporal edges
  (facts invalidated, not overwritten) are attractive, but ingest is LLM-heavy at roughly 50 episodes a minute.
- **Letta** is an agent runtime, not a memory library; self-host needs Postgres with pgvector. The v1 Python server
  was archived on 2026-08-16 and PyPI `letta` 0.16.8 is months stale. Archival memory "must be queried on-demand via
  tools", an extra round trip inside a voice turn, and there is no Pipecat integration.
- **Langfuse has no memory.** Its Users view is analytics: `userId` propagated across observations, cost and usage
  aggregated. No persisted fact store, no read-back API.

**Why all three are rejected.** Our facts already arrive typed, as `upsert_item(name, amount, kind)`. Every one of
these frameworks is built around a model re-deriving structure from prose, so adopting one means serialising `Decimal`
facts to text, paying a model to guess them back, and inheriting non-determinism plus an eventual-consistency window
directly into the money path. That is not over-engineering, it is a regression against the one rule. Instead: one
table keyed `(user_id, item_name)` with `amount numeric`, `kind`, `updated_at`, `source_session_id`, written from the
same tool handlers that already mutate domain state; on call start, hydrate domain state from it and give the model a
`load_profile` **tool result** stating the facts and their age. Knowingly given up: semantic recall ("that gym thing"
will not match `Gym membership`, though the alias column exists), automatic dedup, decay. Correction versus
contradiction was deliberately assigned to the model, so these frameworks sell judgement that was cut on purpose.

## 5. Session persistence

**What comparable projects do.** The dominant shape is a `sessions` row plus a row per turn, with JSON only inside the
turn payload. OpenAI Agents SDK `SQLAlchemySession` is `agent_sessions(session_id PK, created_at, updated_at)` plus
`agent_messages(id PK, session_id FK CASCADE, message_data, created_at)` indexed on `(session_id, created_at)`.
LangGraph's Postgres checkpointer splits `checkpoints` (JSONB), `checkpoint_blobs` (BYTEA for oversized state) and
`checkpoint_writes`, deliberately spilling large values out of JSONB. LiveKit Agents v1 and Pipecat 1.9 ship no
schema: Pipecat's `examples/persistent-context` writes `context.get_messages()` to a timestamped JSON file and reloads
with `set_messages()`, which is what we do today, and recommends hooking the turn-stopped events.

**Why not one JSONB blob per call.** There is no partial JSONB update: `jsonb_set` and `||` rewrite the whole
document, so MVCC writes a new row version, new TOAST chunks and WAL for the entire value. Appending turn N to a
transcript blob is O(size), making a 60-turn call O(n^2) bytes written, where row-per-turn is O(1). The planner is
also blind inside JSONB: no per-key statistics, operators without statistics fall back to a flat 0.01 selectivity, and
values over 1 kB are dropped before statistics are collected, so a real transcript never lands in the MCV list. Rule:
anything grouped, ordered, joined or filtered across sessions is a typed column (`role`, `tool_name`, `turn_index`,
`latency_ms`, `created_at`, `amount numeric`). Given the `Decimal` rule, money inside JSONB is a live correctness
hazard: every read path has to remember to re-wrap. PG 18 documents `numeric` as "especially recommended for storing
monetary amounts".

**Why not Redis.** At a single FastAPI instance, a module-level dict in one uvicorn worker is the right data
structure: no network hop, no serialisation, no extra container, no new failure mode. The cases that normally justify
Redis do not apply. Multi-process: the right fix is making Postgres the source of truth and keeping the dict as a
per-process handle on the live pipeline, which is not serialisable anyway. Cross-process fan-out for cards: Postgres
`LISTEN` / `NOTIFY` covers it with no new dependency, send the key and not the record given the 8000-byte cap, and
Pipecat's own multi-worker handoff example uses Postgres PGMQ rather than Redis. TTL eviction is a timed `WHERE
ended_at IS NULL AND started_at < now() - interval '1 hour'`, about five lines. Surviving restarts: a live pipeline
dies with the process regardless, and what survives is the rows. Rate limiting and cross-process idempotency are the
one clean fit, and irrelevant at one instance.

Net shape chosen (`04-observability-hld.md` section 4): `users`, a slim `sessions` row (who, when, trace id,
recording path), `profile_facts` and `profile_notes` with supersession rows. No turns table: Langfuse already holds
every turn and tool call and the JSON recording is the archive, so storing them a third time would be reinventing
what exists. The row-per-turn finding above stands for the day turns are queried across sessions in SQL. Money is
stored as `text` holding the `Decimal` string rather than `numeric`: the driver never sees a float either way, and
text keeps the exact digits the person said with no scale to configure; the PG recommendation of `numeric` applies
when the database itself does arithmetic, which this schema never does.

## 6. What changed the design

Three claims in the first draft of this report were wrong. Spike S3 (`docs/process/spike-findings.md`, 13 Sep, read
against the installed source) corrected them, and `docs/architecture/04-observability-hld.md` §3 carries the corrected
version.

1. **`enable_turn_tracking` does not default to False.** Turn tracking defaults on in 1.9.0. The draft warned it must
   be set or there would be no per-turn spans. We pass it explicitly for readability, not necessity.
2. **No separate OTLP exporter, and no `setup_tracing()`.** A Langfuse client with tracing disabled drops every score,
   and a tracing-enabled client attaches its span processor to whatever provider it finds, so an exporter of our own
   would export every span twice. `observability/tracing.py` builds the `TracerProvider` with the resource attributes,
   registers it globally, and hands it to `Langfuse(tracer_provider=provider)`; the SDK owns the exporter, auth,
   masking and flush. Pipecat's `setup_tracing()` would register a second provider that OpenTelemetry drops with a
   warning.
3. **Turn context is public API.** The draft treated parenting a tool span under the current turn as an open question
   with a fallback to the conversation span. `TurnTraceObserver.get_current_turn_context()` and `get_turn_context(n)`
   settle it, and the same call yields the trace id for scoring.

Two items ride with the first live call: whether `additional_span_attributes` carrying `langfuse.user.id` and
`langfuse.session.id` land at trace level, and whether a 30-turn call really costs about 120 units.
