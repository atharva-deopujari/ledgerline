# Session C · voice + api (config, main, pipeline, session, transport, routes, spike)

Read `docs/process/00-orchestration.md` first. You own `ledgerline/config.py`, `main.py`, `voice/**`, `api/**`,
`tests/voice/**`, `tests/api/**`, and a throwaway `spike/` folder. You read `ledgerline/agent/**` and
`ledgerline/domain/**` but never edit them.

Research to read: `docs/research/01-pipecat-core.md`, `02-daily-transport.md`, `06-vad-turn-detection.md`,
`08-server-process-docker.md`, `05-llm-openai.md` sections 3 to 4, `03-stt.md` and `04-tts.md` deep-dive
sections, `docs/architecture/02-hld.md` sections 1, 2, 8. Also `docs/reference/pipecat-scaffold/server/bot.py`,
which is what Pipecat 1.9 generates for this exact stack; follow its form.

**Verify every Pipecat name with the `pipecat-context-hub` MCP before you type it.** Run
`check-deprecation` on each class you import. Research 00-index lists the renames.

Sessions A and B are implementing domain and agent in parallel. Code against the contracts
(`ledgerline/agent/tools.py::build_tools`, `ToolContext`; `ledgerline/agent/prompt.py::system_instruction`,
`turn_block`; `ledgerline/domain/models.py::FinancialState`). In tests, fake them.

## 0. Spike (first, 2 to 3 hours, throwaway)
`spike/spike_bot.py`: minimal Daily + Deepgram + luna + Cartesia pipeline with ONE direct function
`record_number(params, value: float)` that echoes the value back, and ONE `OutputTransportMessageUrgentFrame`
push from inside that handler. `spike/index.html`: bare page with daily-js from CDN that joins the room and
`console.log`s every `app-message`. Needs the four keys in `.env` (ask the owner; do not commit `.env`).

Settle and write findings in `docs/process/spike-findings.md`:
1. Turn end: Smart Turn v3 default vs `SpeechTimeoutUserTurnStopStrategy`. Say "yes" alone; say "my EMI is,
   um, forty-two hundred". Record how long each takes to respond, and whether "yes" hangs.
2. Cards frame: does the generic `OutputTransportMessageUrgentFrame` reach the browser through `DailyTransport`,
   or is `DailyOutputTransportMessageUrgentFrame` required?
3. LLM service: `OpenAIResponsesLLMService` with `gpt-5.6-luna`. Does it work with a direct function? Time to
   first token. If it fails, fall back to `OpenAILLMService` with `settings.extra={"reasoning_effort": "none",
   "verbosity": "low"}` and record why.
4. Strict mode: does the derived tool schema carry `strict: true`? Check the request Pipecat sends.
5. Deepgram `language="en-IN"` on nova-3: accepted or rejected? How does "forty-two hundred" transcribe?
6. Daily room DELETE right after the call: works or 4xx?
Delete nothing from `spike/`; the orchestrator decides.

## 1. `config.py`
`Settings(BaseSettings)`: `openai_api_key`, `daily_api_key`, `deepgram_api_key`, `cartesia_api_key` (required
unless `tts_provider == "deepgram"`), `openai_model="gpt-5.6-luna"`, `tts_provider: Literal["cartesia","deepgram"]
= "cartesia"`, `cartesia_voice_id` default from research 04, `turn_strategy: Literal["smart","timeout"]="smart"`,
`smart_turn_stop_secs=1.5`, `prompt_version="v1"`, `log_level="INFO"`, `host="0.0.0.0"`, `port=7860`,
`room_expiry_secs=3600`, `idle_timeout_secs=300`, `enable_tracing=False`. A `validate_for_boot()` that raises a
single error naming every missing required variable. Tests: missing keys named; deepgram provider does not
require cartesia key; defaults.

## 2. `voice/transport.py`
`async create_room(settings) -> (room_url, room_name)` and `async create_token(settings, room_url, owner) -> str`
via `DailyRESTHelper` from `pipecat.transports.daily.utils` (verify path). Room props: `exp = now + expiry`,
`eject_at_room_exp=True`, `enable_chat=False`, `start_video_off=True`. Do not send `max_participants`.
`make_transport(settings, room_url, token) -> DailyTransport` with `DailyParams(audio_in_enabled=True,
audio_out_enabled=True)`. Tests with `pytest-httpx` mocking the REST calls; transport construction tested for
params only.

## 3. `voice/pipeline.py`
`build_worker(settings, state, tool_ctx, transport) -> (PipelineWorker, LLMContext, llm)`:
- STT `DeepgramSTTService(settings=Settings(model="nova-3-general", language=<from spike>, smart_format=True,
  numerals=True, interim_results=True, keyterm=[...]))`
- LLM per spike outcome; `system_instruction=prompt.system_instruction(state)`; `LLMContext(tools=build_tools(ctx))`
- TTS Cartesia `sonic-3.6` explicit model, voice id, `GenerationConfig(emotion="calm", speed=0.95)`; or Deepgram
  Aura-2 when `tts_provider == "deepgram"`. Register a text transform that rewrites "₹" and "Rs." to " rupees ".
- `LLMContextAggregatorPair(context, user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer(),
  turn_analyzer or user_turn_strategies per settings.turn_strategy, user_turn_start strategies with
  MinWordsUserTurnStartStrategy(min_words=3), user_idle_timeout=10))`. Verify every param name.
- Pipeline order exactly as the scaffold. `PipelineWorker(pipeline, params=PipelineParams(enable_metrics=True,
  enable_usage_metrics=True), observers=[LLMLogObserver(), TranscriptionLogObserver()],
  idle_timeout_secs=settings.idle_timeout_secs, function_call_timeout_secs=5)`.
Tests (`tests/voice/test_pipeline_wiring.py`): with fake keys and monkeypatched service classes, assert the
processor order, that tools were passed to the context, that the TTS class follows `tts_provider`, and that no
network call happens at construction.

## 4. `voice/session.py`
`async run_session(settings, room_url, bot_token, session_id) -> None`:
- `state = FinancialState(today=date.today())`; `push_cards` closure that wraps `CardsMessage` in
  `OutputTransportMessageUrgentFrame(message=msg.model_dump())` (or the Daily subclass per spike) and pushes via
  the worker; `ctx = ToolContext(state, push_cards)`
- build transport, worker; `runner = WorkerRunner(handle_sigint=False)`; `await runner.add_workers(worker)`
- `@worker.rtvi.event_handler("on_client_ready")`: developer message "Greet briefly, say you will help plan the
  next thirty days, ask what money comes in and when" then `LLMRunFrame()`
- after each user turn (hook the user aggregator or `on_user_turn_stopped` event, verify the name):
  `state.turn += 1`, `confirm_untouched(state)`, push `LLMUpdateSettingsFrame(delta=Settings(
  system_instruction=prompt.system_instruction(state)))`
- `on_user_turn_idle`: queue a developer message "the user has been silent, ask gently if they are still there"
- `on_client_disconnected`: `await worker.cancel()`; log; no room DELETE (24 h rule) unless the spike proved it
  works
- wrap in try/except, log exceptions with session_id, always cancel
Tests: with everything monkeypatched, assert handlers are registered, the greeting frame is queued on client
ready, the settings delta is pushed after a turn, cancel runs on disconnect.

## 5. `api/`
`api/sessions.py`: `SessionRegistry` holding `asyncio.Task`s by id, `start(coro) -> id`, `cancel_all()`.
`api/routes.py`: `POST /api/sessions` creates room, two tokens (bot owner, user not), starts `run_session` task,
returns `{room_url, token, session_id}`; 409 if a session is already running (single-user demo); `GET
/api/health` returns `{ok: true, active_sessions: n}`.
`main.py`: app factory; lifespan validates settings at boot and cancels sessions at shutdown; mounts
`frontend/dist` with `StaticFiles(html=True)` at `/` after the API router; if `frontend/dist` is missing, serve a
one-line HTML saying "frontend not built".
Tests (`tests/api/test_routes.py`): TestClient, Daily REST mocked with pytest-httpx, `run_session` monkeypatched;
assert response shape, 409 on second start, health count, static fallback.

## Done when
Spike findings written. `uv run pytest tests/voice tests/api` green offline. `uv run ruff check ledgerline` clean.
`uv run lint-imports` green. `uv run uvicorn ledgerline.main:app` boots with a `.env` and `GET /api/health`
answers. Write `docs/process/status-C.md`.
