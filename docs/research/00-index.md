# Research index and stack decisions

Researched 2026-09-11 by 11 parallel agents against live docs and the Pipecat v1.9.0 source tag, then
cross-checked claim by claim against context7 (see "Context7 cross-check" below; each report carries its own
appendix with the per-claim table). This file reconciles them. Where two reports disagree, the conflict and the chosen resolution are recorded here so the
decision is defensible later. Anything marked **VERIFY IN SPIKE** must be confirmed by running code
before it is treated as settled.

## Reports

| # | File | Topic | Words |
|---|------|-------|-------|
| 01 | `01-pipecat-core.md` | Pipeline, frames, context, tools, interruption, 1.x renames | ~3300 |
| 02 | `02-daily-transport.md` | Daily REST, DailyTransport, app-message, daily-js | ~2700 |
| 03 | `03-stt.md` | STT comparison, Deepgram Nova-3 deep dive | ~2350 |
| 04 | `04-tts.md` | TTS comparison, Cartesia deep dive, text normalisation | ~2150 |
| 05 | `05-llm-openai.md` | gpt-5.6-luna, reasoning effort, Responses vs Chat, cost | ~2350 |
| 06 | `06-vad-turn-detection.md` | Silero, Smart Turn v3, interruption gating, idle | ~1700 |
| 07 | `07-frontend.md` | Vanilla JS vs client SDK vs React, card protocol | ~1950 |
| 08 | `08-server-process-docker.md` | Process model, room lifecycle, Dockerfile, compose | ~2500 |
| 09 | `09-plan-engine.md` | Data model, day simulation, priority tiers, 10 test scenarios | ~3800 |
| 10 | `10-state-and-tools.md` | Tool granularity, upsert/conflict semantics, prompt skeleton | ~4100 |
| 11 | `11-testing-evals.md` | Test pyramid, text harness, judge rubric, regression story | ~3000 |

## Stack, one line each

| Layer | Choice | Rejected | Report |
|---|---|---|---|
| Voice framework | pipecat-ai **1.9.0**, Python **3.11** | LangGraph in the loop (barrier kills streaming and interruption) | 01 |
| Transport | Daily via `DailyTransport`; room per call, `exp` about 1 h, `eject_at_room_exp=True`, rely on expiry not DELETE | fixed room (leaks state between calls) | 02, 08 |
| STT | Deepgram **nova-3-general**, `smart_format`, `numerals`, `keyterm`; `language="en"` (try `en-IN`, not corroborated for Nova-3) | Speechmatics/AssemblyAI (slower), Flux (no smart_format) | 03 |
| TTS | Cartesia **sonic-3.6** websocket, `model` set explicitly (default may be 3.5), voice Daniel or Skylar, `calm`, speed 0.95 | ElevenLabs Flash (no number normalisation on free), OpenAI TTS (HTTP, slow) | 04 |
| TTS fallback | Deepgram Aura-2 behind an env var (`$200` credit, thousands of minutes) | | 04 |
| LLM | **`gpt-5.6-luna`** exactly (bare `gpt-5.6` aliases to Sol, the expensive tier), reasoning effort **none**, verbosity low, no temperature | gpt-4.1-mini (2x price, fallback only) | 05 |
| LLM service | `OpenAIResponsesLLMService` (WS Responses API, auto-disables reasoning) | `OpenAILLMService` + `extra={"reasoning_effort":"none"}` kept as one-line fallback | 05 |
| VAD | Silero (bundled ONNX, no download) on `LLMUserAggregatorParams` | longer `stop_secs` (breaks STT latency budget) | 06 |
| Turn end | Smart Turn v3 (`LocalSmartTurnAnalyzerV3`), `SmartTurnParams.stop_secs` lowered | Deepgram endpointing (ignored by Pipecat) | 03, 06 |
| Barge-in gate | `MinWordsUserTurnStartStrategy(min_words=3)` | | 06 |
| Idle | `user_idle_timeout=10` + `on_user_turn_idle` | `UserIdleProcessor` (removed) | 06 |
| Tools | Pipecat direct functions, generic `upsert_item`/`remove_item` + control tools | per-entity tools, whole-state JSON | 01, 10 |
| State | one Pydantic `Facts` object, in memory, per call | Redis, SQLite | 09, 10 |
| Plan engine | pure `build_plan(facts, policy) -> PlanResult`, `Decimal`, day simulation | monthly totals (miss timing shortfalls) | 09 |
| Cards channel | Daily app-message via `OutputTransportMessageUrgentFrame`, full snapshot, 4 KB guard | RTVI client SDK (ESM only, needs bundler), own websocket | 01, 02, 07 |
| Frontend | **Revised 2026-09-11:** React 19 + Vite + TypeScript, `@daily-co/daily-js` **0.92.2** as npm dep, built in a Node Docker stage, served by FastAPI. Research 07 recommended vanilla JS; overridden for production-grade structure, see `docs/architecture/03-folder-structure.md` | vanilla single file (prototype feel), Pipecat client SDK | 07 |
| Server | FastAPI, pipeline runs **in-process** as asyncio task, `PipelineWorker` + `WorkerRunner` | subprocess per call (pattern removed from Pipecat examples) | 08 |
| Docker | `python:3.11-slim-bookworm` + `libgomp1`, `uv sync --locked`, prebake NLTK `punkt_tab`, one compose service, port 7860, bind `0.0.0.0` | Alpine (daily-python is manylinux only) | 08 |
| Tests | pytest unit + text-only harness calling OpenAI directly with same tools + rule checks + judge | DeepEval, promptfoo, Braintrust, OpenAI Evals (shutting down Nov 2026) | 11 |

## Facts that changed earlier assumptions

These came from source, not docs. Every pre-1.3 tutorial and most web summaries are wrong on them.

- `PipelineTask` is now `PipelineWorker`, `PipelineRunner` is now `WorkerRunner`. Old names are shims removed in 2.0.
- `OpenAILLMContext`, `create_context_aggregator`, `LLMMessagesFrame`, `StartInterruptionFrame`, `TransportMessageFrame`, `allow_interruptions`, `aggregation_timeout`, `UserIdleProcessor` are **removed**, not deprecated.
- `vad_analyzer` moved from `DailyParams` to `LLMUserAggregatorParams`.
- System prompt is `OpenAILLMService.Settings(system_instruction=...)`, changed mid-call with `LLMUpdateSettingsFrame(delta=...)`. Not a `role: system` message. This is the hook for re-injecting the "still missing" list each turn.
- `enable_rtvi=True` is the `PipelineWorker` default. Our vanilla frontend must filter out messages with `label: "rtvi-ai"`.
- Since GPT-5.4, Chat Completions rejects tools with any `reasoning_effort` other than `none`. Luna reasons at `medium` by default, first token ~1.9 s. At `none`, ~0.7 s. Report 10 originally said `low`; corrected to `none`.
- Subprocess-per-call is gone from Pipecat's own examples. In-process asyncio is the reference pattern now.
- Silero model is bundled in the wheel (2.3 MB ONNX). Nothing to download or prebake. NLTK `punkt_tab` is the thing to prebake.
- daily-js 0.92.2 UMD global is `window.Daily`, not `DailyIframe`.
- Daily app-message is capped at **4 KB**. Ordering and reliability undocumented.
- Daily `max_participants` is fine on free (default 200). Paid plan only gates raising it above 200. Earlier claim that it 400s on free was wrong.
- **Daily requires a credit card at signup** to enable usage. 10,000 free minutes per month still apply. Earlier claim of no card was wrong. Deepgram, Cartesia, OpenAI need no card.
- Daily changelog: a room can only be DELETEd once it has been expired for more than 24 h. So "delete room on disconnect" will likely fail. Use `exp` about 1 h plus `eject_at_room_exp=True` and let rooms self-clean. Confirm in spike.
- Runner default `--host localhost` breaks Docker port mapping. Bind `0.0.0.0`.
- Pipecat's runner leaks Daily rooms for 4 h. Use a short `exp` (see DELETE caveat above).
- `DailyRESTHelper.get_token(room_url, expiry_time=3600, owner=True)`. Param is `expiry_time`, not `expiry`.
- On `on_client_disconnected`, canonical docs cancel the `PipelineWorker`, not the `WorkerRunner`.
- `RTVIServerMessageFrame` is also a SystemFrame (high-priority lane), so both card-frame options are immediate. C3 unchanged.
- Context7's production Dockerfile still shows `torch.hub.load` for Silero. Stale: torch is not a pipecat dependency and the 1.9.0 wheel bundles `silero_vad.onnx`. Do not add that line.
- FastAPI now ships `app.frontend(path, directory=...)` for static hosting, avoiding the mount-at-`/` ordering problem.
- Cartesia API accepts `normalization: "en-IN"` for Indian number and date reading, but Pipecat's `Settings` does not expose it. Our regex text-transform layer covers rupee symbols anyway.
- `function_call_timeout_secs` defaults to `None`. Set it.

## Conflicts between reports and resolutions

**C1. Parallel tool calls.** 05 says `False` (one fact per turn). 10 says `true`.
Resolution: **true**. Users state two facts in one breath. Serial means two LLM round trips. Idempotent upsert by `(kind, name)` makes parallel safe. Revisit if luna produces duplicate or contradictory parallel calls in the text harness.

**C2. End-of-turn strategy.** 03 warns Smart Turn v3 has open bugs (short "yes" can hang up to 5 s, issues #3643/#3988) and prefers Silero + `SpeechTimeoutUserTurnStopStrategy(~1.1 s)`. 06 says Smart Turn v3.2 is the default and is the right tool for mid-number pauses.
Resolution: **Smart Turn v3 with `SmartTurnParams.stop_secs` lowered from 3.0 to about 1.5**, plus an env flag `TURN_STRATEGY=smart|timeout` to switch. The "yes" hang hits our confirm-understanding step directly, so this is the first thing to measure in a real call. **VERIFY IN SPIKE.**

**C3. Cards frame class.** 01 recommends `RTVIServerMessageFrame` (rides the default RTVI processor). 02 says `DailyOutputTransportMessageUrgentFrame` and that RTVI is not worth it. 07 says `OutputTransportMessageUrgentFrame`.
Resolution: all three end up in Daily `send_app_message`, all share the 4 KB cap. Use **`OutputTransportMessageUrgentFrame(message={...})`**, the generic base class (a `SystemFrame`, sent immediately, survives interruption, no dependency on RTVI or on Daily-specific subclasses). Leave `enable_rtvi` at its default and filter `rtvi-ai` messages in the browser. **VERIFY IN SPIKE** that the generic frame is accepted by `DailyTransport.output()` in 1.9.0; fall back to the Daily subclass if not.

**C4. LLM service class.** 05 recommends `OpenAIResponsesLLMService` (newer, WS, auto reasoning none, `previous_response_id`, strict tools). 01 documents only `OpenAILLMService`.
Resolution: **start with `OpenAIResponsesLLMService`**. Both consume the same `LLMContext` and `LLMContextAggregatorPair`, so the swap is one import. If the WS service misbehaves in the spike, fall back to `OpenAILLMService(settings=Settings(extra={"reasoning_effort": "none", "verbosity": "low"}))`. **VERIFY IN SPIKE.**

**C5. Tool schema style.** 01 recommends direct functions (schema derived from signature + docstring). 10 wants strict mode and explicit enums on every tool.
Resolution: **direct functions first**; enums via `Literal` types in the signature. If strict mode cannot be expressed through direct functions, switch that tool to an explicit `FunctionSchema`. **VERIFY IN SPIKE** whether direct functions emit `strict: true`.

**C6. 4 KB app-message vs the plan timeline.** 09 produces a 30-row timeline. 02 caps each message at 4 KB.
Resolution: cards are a **compact full snapshot** with short keys; the timeline card carries only rows that have an event (income or payment), not all 30 days, and amounts as integers of rupees. Guard `len(json.dumps(msg).encode()) < 4096` in code and log if exceeded. Escape hatch if it ever overflows: `setMeetingSessionData` (100 KB, room-wide, replays to a refreshing browser).

**C7. Confirming numbers.** 03 and 04 say the LLM must read every amount back. 10 says record provisionally and confirm implicitly by repeating the figure in the next sentence, asking explicitly only on low confidence, outlier, or conflict.
Resolution: these agree. The prompt always repeats a newly recorded figure in speech (cheap). The handler flips `confirmed=true` on the next non-contradicting user turn. Explicit "did you say X?" only in the three named cases. Never block the pipeline on confirmation.

**C8. Conflicts and the plan.** 09 says conflicts block plan computation. 10 says conflicts are stored and cards show "needs confirmation".
Resolution: consistent. Conflict entry in state, card shows it, `build_plan` refuses with a question until `resolve_conflict` runs.

## Context7 cross-check (2026-09-11)

Six Opus agents checked every concrete claim in the 11 reports against context7. Context7's Pipecat corpus
tracks docs `main`, unversioned, broadly consistent with 1.9.0 but lagging the source tree on a few API pages.
Vendor docs (Daily, Deepgram, Cartesia, ElevenLabs, OpenAI) are current snapshots. Pricing, free-tier sizes,
latency benchmarks, GitHub issues and registry versions are outside context7 and were left as researched.

| Report | Verified | Contradicted | Not covered | Material corrections |
|---|---|---|---|---|
| 01 Pipecat core | 27 | 4 | 7 | disabled-interruption strategy spelling; RTVI import gotcha now stale; idle frame tuple flagged |
| 02 Daily | 33 | 3 | 17 | **card required**; `max_participants` fine on free; POST/DELETE rooms 50 per 30 s; DELETE only after 24 h expiry |
| 03 STT | 14 | 1 | 8 | Flux keyterm cap 100; **`en-IN` on Nova-3 not corroborated** |
| 04 TTS | 22 | 2 | 7 | six primary emotions; set `model` explicitly; `normalization: en-IN` exists in API |
| 05 LLM | 26 | 3 | 20 | tools + reasoning rule applies since GPT-5.4; **bare `gpt-5.6` = Sol**; fast mode is `service_tier="fast"` |
| 06 VAD | 17 | 0 | 14 | none; `Settings` spelling confirmed |
| 07 Frontend | 18 | 1 | 13 | `window.Daily` only, no `DailyIframe` |
| 08 Server/Docker | 27 | 1 | 20 | context7 Dockerfile with torch is stale, report stands; `get_token(expiry_time=)`; cancel worker not runner; `uv sync --locked` |
| 10 State/tools | 12 | 1 | 9 | reasoning `low` corrected to `none`; number constraints widened |
| 09 Plan engine | 5 | 3 | 2 | **scenario 2 and 10 arithmetic wrong** (see below); Pydantic frozen is opt-in via `ConfigDict(frozen=True)`, lists stay mutable |
| 11 Testing | 11 | 1 | 5 | eval transport param is `WebsocketServerParams` from `pipecat.transports.websocket.server`; `seed` now Deprecated/Beta; Pipecat Evals runnable inside pytest via `EvalSession.from_scenario` |

Where context7 disagreed with a claim verified against the 1.9.0 source tag, the source-verified claim was kept
and the disagreement recorded in the report's appendix. No stack decision changed. Two operational facts did:
Daily needs a card, and Daily rooms cannot be deleted immediately after a call.

**Scenario arithmetic in report 09.** Eight of ten scenarios recompute exactly. Two were wrong in the same way:
they read the minimum balance off the event day and ignored the 200 per day grocery spread that keeps draining
until the next income.

| Scenario | Report said | Recomputed |
|---|---|---|
| 2 (timing shortfall) | min -1,000 on 09-20; net +21,000; after deferral lowest 0 on 09-25 | min -5,800 on 09-29; net +27,000; after deferral lowest -800 on 09-29, so deferral alone does not clear the dip |
| 10 (all income uncertain) | min -3,000 on 09-20 | first negative 09-20 at -3,000; min -5,000 on 09-30 |

Corrected inline in 09. Lesson for the engine: the test oracle must be computed by an independent hand
simulation over every day, not by inspection of event days. These two become the first regression tests.
Also confirms the day-by-day simulation choice over monthly totals: both errors are exactly the kind a monthly
total would hide.

## Pinned versions

| Thing | Version | Source |
|---|---|---|
| pipecat-ai | 1.9.0 (PyPI 2026-09-11) | 01 |
| Python | 3.11 | 01, 08 |
| @daily-co/daily-js | 0.92.2 | 07 |
| OpenAI model | gpt-5.6-luna | 05 |
| Deepgram model | nova-3-general | 03 |
| Cartesia model | sonic-3.6 (Pipecat 1.9 default) | 04 |
| Smart Turn | v3.2 via `LocalSmartTurnAnalyzerV3`, bundled 8 MB ONNX | 06 |

## Environment variables

```
OPENAI_API_KEY      required
OPENAI_MODEL        gpt-5.6-luna   (exact id; bare gpt-5.6 = Sol, 5x the price)
DAILY_API_KEY       required (Daily needs a card on file, no charge under 10k min/month)
DEEPGRAM_API_KEY    required
CARTESIA_API_KEY    required unless TTS_PROVIDER=deepgram
TTS_PROVIDER        cartesia | deepgram   (default cartesia)
TURN_STRATEGY       smart | timeout       (default smart)
LOG_LEVEL           INFO
```

## Cost expectations

| Item | Free tier | Our expected use |
|---|---|---|
| Daily | 10,000 min/month, **card required** at signup | 2 participants per call, hundreds of test calls fine |
| Deepgram STT | $200 credit, no card, no expiry | ~$1-2 for 200 min |
| Deepgram Aura-2 TTS | same $200 credit | effectively unlimited for dev |
| Cartesia | 20,000 credits/month, ~27 min of speech | demo and final voice tests only; $4 Pro if needed |
| OpenAI luna | pay as you go | ~$0.35-0.70 per full text eval pass; ~$2-3 per judge run |

## Open decisions

1. **Deadline and hours available.** Not yet stated. Decides how deep the eval suite goes.
2. **Evaluation depth: full eval suite or minimal.** Research 11 makes it cheap: the text harness we need for debugging is 80% of the eval suite.
3. C2 turn strategy default after the first real call.
4. C4 Responses vs Chat service after the spike.

## Suggested spike before writing the real plan

One throwaway `spike.py`, no cards, no engine: Daily room + Deepgram + luna via Responses service + Cartesia, one direct-function tool that records a number and echoes it back, one `OutputTransportMessageUrgentFrame` to a bare HTML page that logs `app-message`. Goal: confirm C2, C3, C4, C5, measure first-token latency, hear how "forty-two hundred" transcribes, check whether Nova-3 accepts `language="en-IN"`, and check whether DELETE room works right after the call or only after expiry. Budget: 2 hours, under 5 Cartesia minutes.
