# Status C · voice + api

Steps 1 to 5 are done. Step 0 (the spike) is still on hold: Deepgram and Cartesia keys are not
in `.env` yet.

## Checks

| Check | Result |
|---|---|
| `uv run pytest tests/voice tests/api` | **56 passed**, 2.1 s, fully offline |
| `uv run ruff check ledgerline tests/voice tests/api` | clean |
| `uv run lint-imports` | 3 contracts kept, 0 broken |
| `uv run uvicorn ledgerline.main:app` + `GET /api/health` | boots, `{"ok":true,"active_sessions":0}` |

Every Pipecat name below was verified against the installed 1.9.0 wheel by importing it and
reading the real signature, not from docs. No test opens a socket
(`test_construction_opens_no_socket` asserts it for `build_worker`).

## Implemented

**`ledgerline/config.py`** — `Settings(BaseSettings)` with the fields from the brief.
`validate_for_boot()` raises one error listing every missing variable; Cartesia's key is only
required when `tts_provider == "cartesia"`. Default voice is Cartesia "Daniel".

**`ledgerline/voice/transport.py`** — `create_room` (exp = now + `room_expiry_secs`,
`eject_at_room_exp`, `enable_chat=False`, `start_video_off=True`, no `max_participants`),
`create_token(owner=)`, `room_name_from_url`, `delete_room` (best effort, never raises), and
`make_transport` with audio-only `DailyParams`.

**`ledgerline/voice/pipeline.py`** — `build_worker` returns `Built(worker, context, llm,
user_aggregator)`. Deepgram `nova-3-general` with `smart_format`, `numerals`,
`interim_results` and 16 finance keyterms; `OpenAIResponsesLLMService` with
`reasoning=ReasoningConfig(effort="none")`; Cartesia `sonic-3.6` + `GenerationConfig(emotion=
"calm", speed=0.95)` or Deepgram Aura-2 per `tts_provider`, both carrying the `speak_rupees`
text transform; Silero VAD + Smart Turn v3 (or `SpeechTimeoutUserTurnStopStrategy` when
`turn_strategy="timeout"`) + `MinWordsUserTurnStartStrategy(min_words=3)` + idle 10 s on
`LLMUserAggregatorParams`; processor order exactly as the 1.9 scaffold; metrics on, both log
observers, idle timeout from settings.

**`ledgerline/voice/session.py`** — `run_session`: state for today, `push_cards` closure
pushing one `OutputTransportMessageUrgentFrame` per snapshot, `ToolContext`, transport,
worker, `WorkerRunner(handle_sigint=False)`. Handlers: `on_client_ready` (greeting developer
message + `LLMRunFrame`), `on_user_turn_stopped` (`state.turn += 1`, `confirm_untouched`,
`LLMUpdateSettingsFrame` with the rebuilt system instruction), `on_user_turn_idle` (gentle
nudge), `on_client_disconnected` (cancel the worker). Wrapped in try/except/finally: exceptions
are logged with the session id, the worker is always cancelled, the room is always deleted.

**`ledgerline/api/sessions.py`** — `SessionRegistry`: `start(factory) -> session_id`, `active`,
`cancel_all()`. Entries remove themselves when the task ends; a crashed task is logged, not
re-raised.

**`ledgerline/api/routes.py`** — `POST /api/sessions` (201; room, owner token for the bot,
non-owner token for the browser, task started; 409 while one is live) and `GET /api/health`.

**`ledgerline/main.py`** — `create_app(settings=None, frontend_dist=None)`; lifespan validates
settings, configures loguru at `log_level`, and cancels every session at shutdown; API router
mounted before `StaticFiles(frontend/dist, html=True)`, with a one-line placeholder page when
the frontend is not built.

## Deviations from the brief, and why

1. **`build_worker` returns a 4-field `NamedTuple`, not a 3-tuple.** `session.py` registers
   `on_user_turn_stopped` and `on_user_turn_idle` on the `LLMUserAggregator`, and recovering it
   from a linked `Pipeline` means index arithmetic over Pipecat's own source/sink wrappers.
   `Built` unpacks like a tuple, so nothing else changes.
2. **`function_call_timeout_secs` is on the LLM service, not `PipelineWorker`.** Verified:
   `PipelineWorker.__init__` has no such parameter; `LLMService.__init__` does. Set to 5 s.
3. **No `pytest-httpx` anywhere.** `DailyRESTHelper` talks over **aiohttp**, which pytest-httpx
   cannot intercept. Daily REST is faked at the `DailyRESTHelper` seam in `tests/voice/
   test_transport.py`, and `tests/api/test_routes.py` fakes `create_room`/`create_token`/
   `run_session` directly. Same coverage, no new dependency. If a real wire-level test is wanted
   later, `aioresponses` is the tool and would need adding to the dev group.
4. **Config tests live in `tests/api/test_config.py`.** `config.py` is mine but is not voice;
   `main.py` is what validates it at boot, so the api directory was the closer home.
5. **Room DELETE is implemented** per the orchestrator's live check against the owner's Daily
   account, called from the `finally` of `run_session` after the worker is cancelled. It is
   wrapped and logged, never fatal; `exp` + `eject_at_room_exp` remain the real guarantee.

## Assumptions pending the spike

Each is one line to flip and is marked in the code:

| Item | Current choice | Where |
|---|---|---|
| LLM service | `OpenAIResponsesLLMService`, `effort="none"` | `pipeline._build_llm` |
| Turn end | Smart Turn v3, `stop_secs` from `settings.smart_turn_stop_secs` (1.5) | `pipeline._turn_strategies` |
| Cards frame | generic `OutputTransportMessageUrgentFrame` | `session.CardsFrame` |
| Deepgram language | `"en"` — `en-IN` is documented for Nova-2, not corroborated for Nova-3 | `pipeline.STT_LANGUAGE` |
| Strict tool schemas | not asserted either way | spike item 4 |

## Spike (run 2026-09-11) — complete

`docs/process/spike-findings.md` has the detail. All six items settled. Not one pipeline.py
choice was contradicted; the only code change the spike produced was `pipeline.STT_LANGUAGE`
from `"en"` to `"en-IN"`, and tests stayed green.

| Item | Answer |
|---|---|
| 1 Turn end | Smart Turn beats `SpeechTimeout(0.6)` by ~0.4 s and did **not** hang on a bare "yes" (0.455 s). `stop_secs=3.0` buys nothing over 1.5 s. Keep smart, 1.5 s |
| 2 Cards frame | generic `OutputTransportMessageUrgentFrame` reaches the remote participant intact; no Daily subclass needed |
| 3 LLM service | `OpenAIResponsesLLMService` + `gpt-5.6-luna` + direct function works, 0.70 s TTFT. Keep |
| 4 Strict mode | direct functions send `strict: null`. Orchestrator's call: handler-side validation, no change |
| 5 Deepgram | `en-IN` accepted, same model id as `en`. **Flipped** |
| 6 Room DELETE | immediate DELETE returns 200. Already wired |

Measured end to end: first audio **1.818 s** after the person stops (no tool call), **2.651 s**
with one tool call. Cartesia TTFB 0.092 s against Aura-2 0.32 s, so the primary/fallback split
is confirmed by measurement.

Cost: four calls, ~8 Daily participant-minutes, one Cartesia sentence. `GET /v1/rooms` returns
`total_count=0` afterwards and no process is left joined.

## Observability, after the first live call (2026-09-11)

**`ledgerline/voice/recorder.py`, `CallRecorder`.** A Pipecat observer, added to the worker in
`run_session`. It records per turn: user transcript, bot text, every tool name, args and result
string, card versions pushed, and timings anchored to the VAD stop (`first_token`,
`first_audio`). One INFO line per turn while the call runs:

```
turn 3 | user: 'Yes.' | tools: - | first audio: 2.25s
turn 4 | user: 'My salary is 45,000 rupees' | tools: upsert_item,upsert_item | first audio: 3.251s
```

On session end it writes `evals/runs/voice-<session_id>-<timestamp>.json` in the harness shape
(`scenario`, `prompt_version`, `model`, `today`, `turns[{role,text,tool_calls[{name,args,
result}]}]`, `state`, `plan_final`, `cards_versions`) plus `source`, `session_id`, per-turn
`timings` and `llm_warnings`. `evals/checks.py` runs over it unchanged — there is a test that
asserts exactly that, and a real recorded call returns zero violations.

`delete_room` now logs at INFO on success and on failure.

Verified on two real calls through the actual app (`POST /api/sessions` + a `spike/drive.py`
fake user), not only in tests. The first of those exposed two bugs in the recorder, both fixed
with tests: the INFO line was logged twice for any turn with a tool call (the LLM responds
twice), and every turn after the first was timed from an earlier turn's VAD stop, which
reported 17.9 s to first audio. Turns now close on `BotStoppedSpeakingFrame` and each anchors
to the last VAD stop before its own transcript.

## The `previous_response_not_found` retries

**`LLMUpdateSettingsFrame` is not the cause.** Verified directly: the adapter puts
`system_instruction` into the `instructions` request field, while the optimization hashes the
`input` items only, so changing the system prompt leaves the hashed prefix byte-identical.

```
instructions differ: True
input items identical: True
```

The real mechanism, from the 1.9.0 source: the WebSocket variant's `previous_response_id` is
**connection-local** (`"store": False` is hardcoded, and `_disconnect_websocket` calls
`_clear_previous_response_state`), and an id is stored only on `response.completed`. When a
response is cancelled by an interruption and the drain times out — which is exactly the
`Error draining cancelled response` warning seen alongside — the socket state diverges, the
server no longer recognises the stored id, and the next call falls back to full context. So the
retries track **interruptions**, which matches "right after an interrupted response" in the
live log.

There is no `store` setting on `Settings` to change. It could be forced through `extra`, but the
docs are explicit that the WebSocket optimization is connection-local by design, so that is
unverified and was not done. **Verdict: unavoidable without giving up the optimization**, and
the cost is one extra round trip resending full context.

**Not yet measured.** Three short verification calls produced zero retries, including one with a
3 s gap intended to force barge-in; the live 24-turn call produced four. The recorder now counts
both warnings into `llm_warnings` and timestamps every turn, so the next long call measures the
cost directly by comparing `first_token` on turns with and without a retry. No number is claimed
until then.

## Worth Session B's attention

The first recorded call shows **duplicate parallel tool calls**: four `upsert_item` calls for one
utterance, two identical failing pairs and two identical succeeding pairs, same args, same
result string. That is the risk research C1 flagged when it chose parallel tool calls
("revisit if luna produces duplicate or contradictory parallel calls"). Idempotent upsert means
it is harmless to state, but it doubles tool latency on those turns. `agent/tools.py` and the
prompt are not mine; raised rather than changed.

## Freeing a stranded session (review finding F8, backend half)

A browser that failed to join held the only session slot until the idle timeout, so every retry
got a 409 while the page told the user to start again. Two changes, both verified against the
running app, not only in tests.

**`DELETE /api/sessions/{session_id}`** returns 204, or 404 for an unknown id. Cancelling the
task is the whole job: `run_session` deletes its Daily room and writes its recording in a
`finally`, which still runs on cancellation. `SessionRegistry.cancel(session_id)` cancels one
task and waits for its teardown, leaving other sessions alone.

**A join watchdog in `run_session`.** If no remote participant connects within
`settings.join_timeout_secs` (new, default 45), the session logs why and cancels itself. The
watchdog is cancelled in the `finally`, so a normal call never pays for it.

Observed on the real app with `JOIN_TIMEOUT_SECS=10`:

```
DELETE -> 204        health after delete={"ok":true,"active_sessions":0}
DELETE unknown -> 404
no one joined within 10s; cancelling to free the slot
deleted Daily room EgpzPbpZQ5MGKUaAferr
health after join timeout={"ok":true,"active_sessions":0}
retry POST -> 201
```

## Ending the call (Session B's `end_call` tool, voice half)

`run_session` passes a `request_end` coroutine into `ToolContext`. It does **not** hang up: it
sets a flag, because the bot still has a goodbye to say and ending there would cut it off
mid-sentence. A `_GoodbyeWatcher` observer sets an event on `BotStoppedSpeakingFrame`; once the
end is requested, the session waits for that event and then calls
`await worker.end(reason=...)` — verified against 1.9 as the graceful path ("Request a graceful
end of the session, draining the pipeline first"), which is what lets the transport leave
cleanly so the browser sees participant-left while `run_session`'s `finally` still records and
deletes the room. A `settings.end_grace_secs` fallback (default 6) ends the call anyway if the
stopped-speaking event never arrives, and an `ended_once` guard means the two paths can never
both fire.

The recorder now marks every transcript with `ended_by`: `"bot"` when `end_call` ran, `"client"`
on disconnect, `"idle"` when the join watchdog fired, `"unknown"` otherwise. The first reason
wins — the disconnect that follows a goodbye is a symptom, not the cause.

## Cartesia voice, after the first live call sounded robotic

The robotic voice was Aura-2, not Cartesia: the run had `TTS_PROVIDER=deepgram`. Separately, the
Cartesia generation parameters are now tunable by ear without a code change.

`GenerationConfig` in Pipecat 1.9 is exactly `volume`, `speed`, `emotion`, all optional and only
sent when set; ranges are volume [0.5, 2.0] and speed [0.6, 1.5]. So:

- `cartesia_speed`, default **1.0** — Cartesia's own default. 0.95 read as sluggish.
- `cartesia_emotion`, default **empty, i.e. not sent**. Cartesia documents emotion as working
  best with a named set of voices (Leo, Jace, Kyle, Gavin, Maya, Tessa, Dana, Marian); Daniel is
  not among them, so an emotion tag there is guidance the model may ignore or overdo.
- `cartesia_voice_id` already existed.

Three voices for the owner to choose by ear, from the live Cartesia voice list (a free GET; no
synthesis minutes spent):

| Voice | Id | Why |
|---|---|---|
| **Janvi - Steady Agent** | `7ea5e9c2-b719-4dc3-b870-5ba5f14d31d8` | Native Indian English (en-IN), calm and neutral with a slow steady delivery, built for support. The closest match to a money coach talking to an Indian user. Try `CARTESIA_SPEED=1.05` since it is described as slow |
| **Devansh - Warm Support Agent** | `1259b7e3-cb8a-43df-9446-30971a46b8b0` | Native Indian English, warm and conversational male. The male counterpart if Janvi reads too formal |
| **Daniel - Modern Assistant** | `47c38ca4-5f35-497b-b1a3-415245fb35e1` | The current default. US English, clear and crisp, one of Cartesia's five recommended sonic-3.6 agent voices. Keep as the control to compare the other two against |

## Concurrent starts (review finding F5)

`start_session` checked `sessions.active`, then awaited a room and two tokens, then registered.
Two requests arriving together both passed the check and each created a room and a bot.

The slot is now claimed **before the first await**. `SessionRegistry.reserve()` is synchronous:
it returns a session id or `None` when the slot is taken, and `active` counts reservations as
well as running tasks. `release(session_id)` gives the slot back if room or token creation
fails, and `start(make_coro, session_id)` turns the reservation into the running task.

Tested with two genuinely concurrent POSTs over `httpx.ASGITransport`, asserting exactly one
201, one 409, and exactly one room created — and the fake `create_room` sleeps, which is where
the race lived. Confirmed the test earns its keep by reverting `routes.py` to the old
check-then-await shape and watching it fail. There is also a test that a failed room creation
returns the slot rather than stranding it.

## `push_cards` never raises

It runs inside a tool handler that has already mutated the state and still has to reach
`result_callback`. If the transport has gone — browser closed, room expired, worker cancelled —
the model losing its result string is worse than the screen missing one update, and the next
snapshot is a full one anyway. The `queue_frames` call is now wrapped, logging
`could not push cards v<n>: <error>` at warning and returning. Two tests: a worker whose
`queue_frames` raises leaves `push_cards` returning normally with the line logged, and the
normal path still queues exactly one `CardsFrame` whose payload survives a JSON round trip.

## Teardown survives a cancel landing inside it

The browser can `DELETE /api/sessions/{id}` at the moment `run_session` is already in its
`finally`. `SessionRegistry.cancel` calls `task.cancel()`, so a `CancelledError` could be raised
at `await built.worker.cancel()` and skip everything after it — the transcript was never
written and the room was never deleted.

Two changes. `recorder.close()` and `recorder.write()` now run **first and synchronously**, so
no cancellation can land between the end of the call and the transcript reaching disk; the
pipeline is finished by the time `runner.run()` returns, and `transcript()` closes the turn it
was mid-way through, so nothing of substance is lost by writing before the worker is torn down.
Each remaining await goes through a `_finish` helper that shields the step, keeps a strong
reference to it, and **keeps waiting for it** after recording a `CancelledError`. Returning as
soon as the cancellation arrived was review 9's F4: the next teardown step started, and
ultimately `SessionRegistry.cancel` released the single session slot, while the previous
worker was still shutting down, so a replacement session could begin on top of it. At the very
end the first recorded cancellation is re-raised, so the task still reports as cancelled rather
than swallowing the caller's intent.

No timeout was added to `_finish` itself. `worker.cancel` already bounds itself with
`cancel_timeout_secs` (20 s by default), and each cancellation is delivered once, so the wait
loop blocks rather than spins.

The Daily REST calls did need one. Awaiting the room delete to completion meant an unbounded
call could hold the single session slot for aiohttp's default `ClientTimeout(total=300)`, so
`transport._rest` now builds its session with `total=REST_TIMEOUT_SECS` (10 s, a module
constant — there is no existing settings knob for HTTP client behaviour, and the ones that
exist are call-lifecycle timings). It bounds `create_room` and `create_token` too, which is
right: the browser is waiting on that POST. A timed-out delete is already swallowed by
`delete_room`, so teardown still completes. Both are tested, and the bound test was confirmed
to fail (`assert 5.001 < 2`) against an unbounded session.

Test: a `run_session` whose worker cancel parks, cancelled from outside while parked, then
released. It asserts the recording is written before anything awaits, that the task is **not**
done and the room delete has **not** started while the worker cancel is still parked, and that
after release the cancel coroutine completed, the room was deleted, and the task ends cancelled.
It failed at `assert not task.done()` before the fix.

## Rooms are private (review 10, F3)

`create_room` asked Daily for `privacy="public"`, so anyone holding the room URL could join a
call full of income, debt and balance figures, and the owner and guest tokens we already mint
protected nothing. Rooms are now `privacy="private"`; `exp` and `eject_at_room_exp` are
unchanged.

**No frontend change is needed.** `useDailyCall.ts` already calls
`call.join({ url: session.room_url, token: session.token })` with the guest token from
`POST /api/sessions`, which is exactly what a private room requires. Confirmed by reading it,
not assumed.

Verified on a real call rather than only in a unit test: the bot joined with its owner token
(`client joined`), the fake user joined with the guest token (`participant joined: Ledgerline`),
one fact turn completed (`turn 1 | user: 'I have 8,000 rupees in my account right now.' |
tools: upsert_item | first audio: 3.663s`), a card snapshot reached the remote participant, and
the room was deleted. `GET /v1/rooms` afterwards returns `total_count=0`. About one Daily
participant-minute, no Cartesia.

`spike/drive.py` now takes an optional meeting token as its second argument, because a fake user
with no token cannot join a private room.

## Code-quality refactor (2026-09-12)

Behaviour-preserving. No test was rewritten, the suite stayed green throughout, and the one
place behaviour *did* change is recorded below rather than hidden.

**New file: `ledgerline/voice/lifecycle.py` (136 lines).** `run_session` was a long function
whose real structure lived in nested closures. The parts with a life of their own moved out:

| Class | Owns |
|---|---|
| `GoodbyeWatcher` | an observer that sets an event when the bot stops speaking (was `_GoodbyeWatcher` in session.py) |
| `JoinWatchdog` | the "nobody joined, free the slot" timer, with `client_joined()` / `start()` / `cancel()` |
| `CallEnder` | the `end_call` handshake: request, wait for the goodbye, grace period, hang up once |
| `Teardown` | shutdown steps a cancellation cannot skip — `step()` shields and waits, `reraise_if_cancelled()` re-raises at the end (was the module-level `_finish`) |

`Teardown` deliberately owns the *mechanism* and not the list of steps: the order of shutdown is
the thing a reader most needs to see, so it stays visible in `run_session`. `session.py` is now
182 lines, down from 243 and reads as an ordered list of named steps.

**Enums instead of compared strings.**

- `config.TtsProvider`, `config.TurnStrategy`, `config.LlmApi` replace the `Literal[...]`
  settings types, so `pipeline.py` compares enum members rather than string spellings.
- `recorder.EndedBy` (`BOT`, `CLIENT`, `IDLE`, `UNKNOWN`), `recorder.Role` (`USER`,
  `ASSISTANT`, the wire contract with `evals/checks.py`), and `recorder.LlmWarning`
  (`RETRY`, `DRAIN_FAILED`, which double as the log text that identifies them).
- Named constants for the rest: `transport.ROOM_PRIVACY`, `routes.CALL_IN_PROGRESS` and
  `routes.NO_SUCH_SESSION`, `session.DEVELOPER`, `pipeline.SPEECH_TIMEOUT_SECS`,
  `recorder.CARDS_MESSAGE_TYPE` and `recorder.SOURCE`.

Every enum is a `StrEnum`, so the JSON on the wire is byte-identical — checked, not assumed:
`dict.fromkeys(LlmWarning, 0)` still serialises to
`{"previous_response_not_found": 0, "drain_failed": 0}`.

**Two things deliberately left as raw strings.** Pipecat event names (`"on_client_ready"` and
friends) are the library's vocabulary, not ours, and aliasing them would hide which API is being
called. The per-turn transcript dict keys (`"role"`, `"text"`, `"timings"`, `"vad_stop"`) mirror
the JSON schema one-for-one; an enum there would read worse than the key it replaces.

**The refactor broke something, and the tests did not catch it.** Moving the end-of-call
handshake into `CallEnder` dropped the `recorder.mark_ended_by("bot")` that used to sit beside
it, so a bot hangup would have been recorded as `unknown`. Nothing failed, because no test
asserted `ended_by` through `run_session` — only the recorder's own unit tests covered it. The
marking now lives in `end_gracefully`, which only `CallEnder` reaches, and a new test asserts it
end to end. That test was written to fail first (`assert None == 'bot'`).

## After the owner's third live call (2026-09-12)

Five changes; the measurement behind the first is in `docs/process/spike-findings.md`.

**1. Hesitation no longer ends the turn**, and there is exactly one judge of that. A frame
trace showed `OpenAILLMService` broadcasting `UserTurnInferenceCompletedFrame` itself — four
times to our own processor's once in a single call — so a downstream gate could never win. The
chain is Pipecat 1.9's documented pairing,
`[deferred(TurnAnalyzerUserTurnStopStrategy(...)), LLMTurnCompletionUserTurnStopStrategy(...)]`,
and our linguistic rule survives as guidance **inside** the model's completion brief:
`UserTurnCompletionConfig` accepts `instructions`, and the config renders Pipecat's default as
`completion_instructions`, so we append `TURN_COMPLETION_HINTS` to it rather than replacing it.
`voice/turn_gate.py`, `voice/turn_completeness.py` and `settings.turn_hold_secs` are deleted.
Measured: one bot response per intended utterance, against 4, 5 and 4 for the gate.

**2. Chat Completions is now the default** (`llm_api`, env switch unchanged). The Responses
chain does not survive the cancellations that constant human interruption produces: the owner's
call shows `Error draining cancelled response` then `previous_response_not_found, retrying with
full context`, and first audio of 7.5 s. Across the runs on 2026-09-12, Chat produced zero
retries in every run; the Responses runs produced 0, 1 and 2.

**3. A filler while a tool runs.** `voice/filler.py` speaks one short word ("Okay.", "Got it.",
"Noted.", rotating) the moment the first function call of a turn starts, so the model can call
tools silently and speak once after the result without leaving a silent gap. Once per user
turn, never for `end_call`: the model says one goodbye and calls `end_call` in the same reply,
and a filler on top would be a second farewell.

**4. `USER_IDLE_TIMEOUT_SECS` 10 to 25.** Someone thinking about their money is not idle at ten
seconds; in the before-run the nudge landed in the middle of a sentence.

**5b. A user turn is now the aggregated turn** the model was handed, closed on
`UserStoppedSpeakingFrame` with the assistant's first action as a fallback, with the raw
Deepgram finalisations kept beside it as `finalisations`. The old one-turn-per-transcript count
measured finalisations, not turns.

**5. The recorder answers the new questions.** Per assistant turn it now writes `event_order`
in the text harness's vocabulary (`"message"`, `"function_call"`), so
`evals/checks.py::silent_before_acting` runs over voice recordings too, plus `completions` and
`spoke_before_acting`. There is a test asserting the check fires on a recorded voice turn.

New files: `voice/turn_completeness.py`, `voice/turn_gate.py`, `voice/filler.py`, and their
tests. Pipeline order is now input, STT, gate, user aggregator, LLM, filler, TTS, output,
assistant aggregator.

## Left to do

- **One human call** before the demo. Every spike utterance was synthetic Aura-2 speech, which
  is cleaner and more evenly paced than a person. Smart Turn classifies prosody, so the
  encouraging "yes" number and the mid-pause behaviour both want confirmation from a real
  speaker. `spike/index.html` is the page for it.
- Nothing else in steps 1 to 5 is outstanding. Nothing was committed; the tree is left dirty.

## Handover for the next Session C

You have read `00-orchestration.md` and `cut-brief.md`. This is everything else about `voice/`
and `api/`.

### Modules

| File | What it is |
|---|---|
| `config.py` | `Settings`; `validate_for_boot()` names every missing variable at once. `TtsProvider`, `TurnStrategy`, `LlmApi` are StrEnums — compare with `==`, never `is` (`model_copy` skips validation and leaves a raw string) |
| `voice/transport.py` | Daily room, tokens, `DailyTransport`. Rooms are **private**; bot joins owner, browser guest. `REST_TIMEOUT_SECS=10` bounds create/token/delete — aiohttp's default is 300 s and teardown awaits the delete |
| `voice/pipeline.py` | `build_worker` -> `Built(worker, context, llm, user_aggregator)`. Order: input, STT, user agg, LLM, `ActionFiller`, TTS, output, assistant agg. **Chat Completions is the default** (`llm_api`); Responses loses its chain on every interruption |
| `voice/turn_completeness` | **Deleted.** Turn completion is `deferred(TurnAnalyzerUserTurnStopStrategy(...))` + `LLMTurnCompletionUserTurnStopStrategy(config=...)`, with `TURN_COMPLETION_HINTS` appended to `UserTurnCompletionConfig().completion_instructions`. One judge: the model, with our domain hints in its brief |
| `voice/filler.py` | One rotating word ("Okay.", "Got it.", "Noted.") on the first tool call of a turn. Never for `end_call` — the model owns the goodbye |
| `voice/lifecycle.py` | `GoodbyeWatcher`, `JoinWatchdog`, `CallEnder`, `Teardown`. `Teardown.step()` shields and **waits**; returning early released the session slot while the old worker was still cancelling |
| `voice/session.py` | `run_session` as an ordered list of named steps. `push_cards` never raises. The finally writes the recording synchronously first, then shielded steps, then re-raises any cancellation |
| `voice/recorder.py` | One JSON per call in `evals/runs/`, in the text harness's shape so `evals/checks.py` runs over it. `event_order` uses B's vocabulary (`message`, `function_call`) |
| `voice/trace.py` | Frame-level trace, attached only when `log_level` is DEBUG. This is how the turn bug was found in one run instead of seven |
| `api/sessions.py` | `SessionRegistry`. `reserve()` is synchronous and claims the slot **before** the first await |
| `api/routes.py`, `main.py` | `POST/DELETE /api/sessions`, `GET /api/health`; app factory, lifespan, static mount |

### The headless hesitant check

```
ROOM_EXPIRY_SECS=600 TTS_PROVIDER=deepgram uv run uvicorn ledgerline.main:app --port 7890
# POST /api/sessions, then, with the room_url and the token from the response:
SPIKE_SCRIPT=hesitant SPIKE_UTTERANCES=5 PYTHONPATH=. uv run python spike/drive.py <room_url> <token>
```

`spike/run_once.sh <label> env VAR=...` does the same against `spike/spike_bot.py`. Rooms are
private, so the token argument is required. About two Daily participant-minutes per run out of
10,000 a month, and zero Cartesia while `TTS_PROVIDER=deepgram`. Always finish with
`PYTHONPATH=. uv run python spike/rooms.py` and confirm `total_count=0`.

### Open

- **Full `tests/voice` + `tests/api` count.** Blocked: `agent/tools/describe.py` still imports
  `Understanding`, which the cut removed. 66 of the non-agent tests pass today. Re-run both
  suites the moment B's tools import.
- **A 9.3 s first-audio on `"18th."`** in one run. One sample; either repeatable or noise.
- **Latency on a live call.** `"Yes."` measured 1.805 s, inside its pre-cut band, so the
  completion judge does not tax short answers. Synthetic fragments are evenly spaced; a person's
  are not.

### Traps, all of which cost me real time

- **The recorder's counts are not Pipecat's.** A user turn is the aggregated turn the model saw,
  closed on `UserStoppedSpeakingFrame`; the raw Deepgram finalisations sit beside it in
  `finalisations`. My first metric counted finalisations and read flat at 8 across a change that
  altered the bot's behaviour completely. Count **bot responses per intended utterance** and read
  the text.
- **Anchor latency to the last fragment.** `first_token` / `first_audio` are from the last
  fragment of the turn; `*_from_turn_start` and `user_speaking_secs` are the other half.
  Anchoring to the first fragment counts the person's own speaking time as our latency and
  turned 2.2 s into 4.6 s.
- **The LLM emits `UserTurnInferenceCompletedFrame` itself** — four times to our processor's once
  in one call — and `ExternalUserTurnCompletionStopStrategy` finalises on any of them. A
  downstream gate can never win. That is why the gate was deleted.
- **Do not filter the LLM's completion frames.** Tried; the mixin's marker text leaked into
  speech (`"0 rupees. How much money do you have right now..."`). The protocol is load-bearing.
- **The gap between two fragments of one sentence is ~3.5 s**, not the 1.6 s of silence: the next
  fragment has to be spoken and finalised too. Any timeout tuned against the silence is too short.
- **`SmartTurnParams.stop_secs` only bounds an INCOMPLETE verdict.** Smart Turn calls `"I have"`
  COMPLETE, so raising it changes nothing (9 turns at 1.5 s, 8 at 3.0 s).
- **Write a test that fails first.** Two of mine passed against missing code — a watchdog that
  teardown would have satisfied anyway, and a timeout test whose outer guard raised the same
  exception as the bug. Both hid real defects.

## 2026-09-12 (freeze) · Final verification and the filler question

`uv run pytest tests/voice tests/api` — **98 + 33 = 131 passed, 0 failed**, after the agent layer
landed. `uv run ruff check .` clean. `uv run lint-imports` — 4 contracts kept, 0 broken. Nothing
in `voice/` or `api/` broke on the cut; no edits were needed.

### The filler stays, unchanged

Asked whether `ActionFiller` still makes sense now that a create's `describe()` result ends with
"say this back, then ask" — the worry being "Got it." followed by the model's own "Got it, rent
twelve thousand...". Measured over 235 runs in `evals/runs` dated 2026-09-12, counting the 2,179
assistant replies that follow a tool call and excluding `end_call` turns where the filler never
fires:

| | count | share |
|---|---|---|
| open with `Okay` / `Got it` / `Noted` (literal doubling) | 8 | 0.37% |
| open with any acknowledgement word | 43 | 1.97% |

Six of those eight are one pre-cut run (`timing_emi_before_salary-20260912-023328`), one is the
pre-cut voice run at 20:06 ("Got it: twenty thousand rupees in cash and..."), one is
`one_word_answers` at 20:14. The post-cut runs at 21:37-21:40 have **zero** acknowledgement
openers: the read-back instruction makes the model open with the value, so the commonest first
words tonight are `Your` (242), `The` (217), `What` (187), `You` (98). The suffix suppresses the
collision rather than causing it.

So: no change. `Mm-hm.` would trade a 0.37% word collision for unreliable TTS on a non-word, and
deleting the filler restores the silence over the tool round trip that it exists to cover.

**Caveat, and it matters:** no voice run exists after the cut — every 21:xx run is text-harness.
The filler is a `TTSSpeakFrame` pushed by the pipeline and never enters the context, so it never
appears in a transcript. This is an inference from what the model says, not from recorded audio.
The live call is the real check. If it grates there, drop `"Okay."` from `FILLERS` first: `"Okay,"`
was the model's opener in both recent collisions.

### Still open for whoever picks this up

- The 9.272 s `first_audio` on `"18th."`, one sample, one run.
- Latency on a live call with a real speaker; `user_speaking_secs` was 0.0 on every synthetic
  turn, so the two anchors have not yet been separated by real data.
- Tree frozen for the commit phase on the owner's instruction; `voice/`, `api/`, `config.py`,
  `main.py`, `tests/voice/`, `tests/api/` and `spike/` are untouched since the 131-green run above.

## 2026-09-13 · Observability and sessions (phases 0 to 2)

Phase 0's spikes are in `spike-findings.md` (S1 to S3 from the installed source, S4 folded into
the live calls). Phase 1 is tracing; phase 2 is sessions, memory and the after-call work.

### What landed

| File | What it is |
|---|---|
| `observability/tracing.py` | One `TracerProvider` for the process, and the Langfuse client that exports it. Reads the **registered** provider back rather than trusting its own registration: OTel keeps the first one and drops later ones with a warning, so building one blind would hand the SDK a provider no span comes from. `should_export_span` widens the SDK's default filter to the `pipecat` and `ledgerline` scopes |
| `observability/attributes.py` | Every attribute name we set, read out of the SDK rather than the docs (`user.id` and `session.id` are **not** `langfuse.`-prefixed), and the conversation attributes for one call |
| `observability/langfuse.py` | `LangfuseClient` protocol, `RealLangfuse`, `NullLangfuse`. Nothing raises except `get_prompt`, which **must**: the caller's fallback is the file, and it reaches it through the exception |
| `voice/tool_trace.py` | One `tool` span per executed function call, parented to the turn via `TurnTraceObserver.get_current_turn_context()`. Also writes the trace's input and output from a `call` span at the end, and keeps the trace id for `aftercall` |
| `api/phone.py` | The one definition of a phone number: ten digits or E.164, as a body field and a path type, so a bad number is a 422 and never a row key |
| `api/review.py` | `UserReview` and the builder behind `GET /api/review/users/{phone}`: active facts, the whole ledger with tombstones, notes, calls with trace links |
| `api/aftercall.py` | The four steps after the call — close the row, record the profile, extract the notes, judge — each isolated so one failure does not stop the rest, plus `Verdicts`, the in-process copy the screen polls |

Wiring: `tracing.setup` and `open_store` in the lifespan with `shutdown`/`close` on teardown;
`POST /api/sessions {phone}` deriving `session_id = phone + "-" + UTC timestamp`;
`SessionRegistry.start(after=...)` running the after-call work **once the slot is free**, for a
cancelled call too, which is the ordinary ending; `GET /api/sessions/{id}/verdict` answering 202
while pending; `DELETE /api/users/{phone}`; hydration, the carried figures and the notes reaching
the tools and the prompt before the greeting.

### Tests

`tests/observability` 22, `tests/voice` 134, `tests/api` 70; whole suite **1135 collected, 0
failed**, ruff clean, 7 import contracts kept.

### The ponytail pass

Run over the whole phase diff. Four cuts applied, all of them things with no caller:

| Cut | Why |
|---|---|
| `Attr.TURN_NUMBER` | never set on any span |
| `flush()` on the protocol and both twins | no caller; `shutdown()` in the lifespan flushes, and the SDK batches on its own interval |
| `SUMMARY_SCORE` constant | one use; the literal is shorter than the name |
| `_managed(settings)` | a one-line helper with one caller |

Application code in the phase: **1,601 lines before the pass, 1,578 after**. The pass also found
a gap rather than a complexity: `CallRecord.prompt_version` was being set and never used, so a
recording still named the file's version even when the prompt came from Langfuse. The recorder
now takes the version the call actually ran on.

### Open

- Two live-call items from phase 1 stand: the `9.272 s` first-audio on `"18th."` (one sample),
  and latency with a real speaker rather than synthetic speech.
- STT and TTS spans carry no token usage and the Deepgram TTS span reports `model: unknown`.
  Both are Pipecat's, both accepted in the HLD.
- Nothing has yet exercised `aftercall` against a real Postgres and a real judge model end to
  end; every step of it is covered by fakes that carry the real error types.

## 2026-09-14 · The end-to-end run, and the two things it found

Three headless calls from one phone-shaped number (`9876500042`) against the compose Postgres,
`JUDGE_MODEL` and `NOTES_MODEL` set to `gpt-5.6-luna`, Langfuse keys live, `TTS_PROVIDER=deepgram`.
Everything on the acceptance list is verified below, with the two defects the run found.

### What the run proved

| Checked | Result |
|---|---|
| `users`, `sessions`, `profile_facts`, `profile_notes` rows | all four written; the session row carries `ended_by`, the Langfuse trace id and the recording path |
| `GET /api/sessions/{id}/verdict` | `202`, `202`, then `200`: status `ready`, summary `0.941`, 15 deterministic rules and 2 intent criteria, `judge_model` `gpt-5.6-luna` |
| The verdict in the recording file | present, matching the endpoint |
| Scores on the trace | 18: 15 `BOOLEAN`, 2 `CATEGORICAL`, 1 `NUMERIC` summary |
| `user.id` and `session.id` | both the phone, on both roots of both traces, `langfuse.trace.name` `coach-call` |
| The second call's first result | `carried from last call: income 0, rent 11,000; say each back, then ask whether all still hold` |
| `prompt_version` on the recording | `1` — Langfuse's version, not the file's `v1`, which is the point of the fix |
| Supersession | 11,000 superseded, 13,000 current, in the real database (see the caveat below) |
| `GET /api/review/users/{phone}` | 3 active facts, 10 history rows including tombstones, 6 notes, 3 calls newest first, with a Langfuse link once `LANGFUSE_PROJECT_ID` is set |

### The first defect: neither model call had credentials

The judge and the extractor both fell back to `OpenAI()`, which reads `OPENAI_API_KEY` from the
process environment — and the key lives in `Settings`, loaded from `.env` by pydantic-settings,
which never puts it there. Both layers caught the credentials error and carried on, so the call
looked perfectly healthy: no notes were extracted, the intent judge was skipped, and the only
sign was two tracebacks in the log. `aftercall` now builds one client from
`settings.openai_api_key` and hands it to both, with a test that asserts each receives it.

This is the shape of thing no fake can catch. Both fakes answered to a client and neither cared
whether one was passed.

### The second defect: a spoken number the domain never received (not mine to fix)

On the third call the person said their rent had gone up. Deepgram heard "my red went up to",
the amount arrived in the next fragment, and the bot replied **"I've noted rent as 13,000
rupees"** — while calling no tool. The state kept 11,000, the profile kept 11,000, and the
person's correction was lost.

The judge did not catch it. `numbers_traceable` passed, presumably because the person themselves
said 13,000, so the figure is traceable to the transcript; `state_matches_facts` passed too. But
the assistant asserted it had recorded something it had not, which is the claim the rules exist
to make impossible. Reported to the orchestrator for B: the gap is a check for "the bot said it
noted a value that is not in the state", not anything in `voice/` or `api/`.

### Caveats, said plainly

- **Supersession was driven by code, not by a call.** The third call was meant to exercise it and
  could not, because of the defect above. With the three-run cap reached, I called
  `store.record_call` directly against the same live database with the state the bot should have
  recorded: rent went 11,000 -> 13,000, the old row is marked superseded, `history_all` returns
  both. Real Postgres, real supersession, but the last mile from a spoken correction to a
  superseded row has still never run end to end.
- That direct call also tombstoned the income rows, because the state I passed had no income and
  `loaded` was not None. Correct behaviour, and a demonstration of why `loaded=None` must never
  become `[]`.
- `spike/drive.py` gained `SPIKE_SAY="one|two|three"` for the returning-caller script; the fixed
  scripts could not say a corrected figure.
- `LANGFUSE_PROJECT_ID` is not in `.env`, so `trace_url` was null until I set it for one boot to
  check the link. One line for whoever owns `.env`; the project id is in the Langfuse settings.
- The demo database now holds three calls and a profile under `9876500042`, including the rows
  the direct `record_call` wrote.

Suite after the run: **1139 collected, 0 failed**, ruff clean, 7 contracts kept, `total_count=0`
Daily rooms.

## 2026-09-14 · The fourth call: a correction that reached the domain

One call from `9876500042` with the two-fragment correction, after B's `upsert_item` fix and
check sixteen landed. What the third call lost, this one recorded.

The person said, in two fragments with a real pause: *"Yes, all of that still holds, but my rent
went up to"* / *"thirteen thousand rupees."* The model called `upsert_item` with 13,000 **before**
saying it, and only then replied "Rent is thirteen thousand rupees, due on the eighteenth of
September".

| Checked | Result |
|---|---|
| `profile_facts` | rent 11,000 marked superseded by the 13,000 row, whose `source_session_id` is this call |
| `history_all` / the review page | both values, the older struck, the newer current, four calls listed with working trace links |
| `claimed_values_recorded` (check sixteen) | passed, in a verdict of 16 deterministic rules |
| Intent criteria | `register_fit`, `questions_purposeful` and the new `corrections_handled`, all pass; summary 0.947 |
| The recording | the `upsert_item` precedes the sentence that claims it |

**The profile is now proven end to end**: a spoken correction, heard in fragments, reaching a
tool, the domain, Postgres and the review page as a superseded row.

### The one failure, and it is a real disagreement

`numbers_traceable` **failed**: `not in any tool result: [11000]`. The bot's first reply, before
any tool call in this call, was "Rent is eleven thousand rupees. Does that..." — reading the
carried figure back, which is exactly what the carried design asks it to do. But it read it out
of the **prompt**: `turn_block(carried=...)` puts the carried line in the greeting turn, because
the greeting has no tool result to carry it (B-obs-3). The check only scans this call's tool
results, so a carried figure spoken before the first tool call has no provenance it can see.

The rule and the design disagree, and the rule is right to complain: HLD section 0 says carried
facts are tool results too, and here one was not. Two ways to settle it, both outside my files:
let the check treat facts hydrated at call start as an allowed provenance, or hold the carried
figures back until a tool result carries them. Reported to the orchestrator for B; nothing in
`voice/` or `api/` decides it.

### Two smaller observations

- The `upsert_item` for the corrected rent sent `survival: false`, though the person only changed
  the amount. Overwrite semantics are the cut's deliberate design, so the *call's* state had rent
  as non-survival. The store was unbothered: the persisted profile still reads `survival: true`,
  because `record_call` supersedes only fields the state actually states.
- The profile was put back to rent 11,000 by a direct `record_call` before this call, since the
  earlier direct write had already moved it to 13,000. The history therefore reads
  11,000 -> 13,000 -> 11,000 -> 13,000; only the last step was driven by a call.

Suite: **1148 collected, 0 failed**, ruff clean, Daily rooms `total_count=0`. `spike/drive.py`
gained `~` inside `SPIKE_SAY` for fragments within one utterance.

## 2026-09-14 · The carried key on the voice transcript

The `numbers_traceable` disagreement from the fourth call was settled on my side: the check
already knows how to authorise a carried figure — `judge.checks.provenance.carried_numbers`
reads a `carried` key of `[name, spoken]` pairs, which `evals/harness.py` has written since it
grew a carried block. The voice recorder never wrote it.

`CallRecorder` now takes the same pairs `session.py` hands `ToolContext` and writes them under
`carried`, in the harness's shape, always present so an empty list is a first-time caller rather
than an older file. They are captured **at the start of the call**: confirming a carried figure
clears its flag, so recomputing at the end would record an empty list for a call that carried
plenty.

Replayed over the fourth call's recording, with the pairs that call actually started with:

| Input | `numbers_traceable` |
|---|---|
| the recording as saved (no `carried` key) | `turn=2, not in any tool result: [11000]` |
| the same recording with `carried: [["rent", "11,000"]]` | no violations |

**The saved file is left as it is.** Adding the key to a recording written before the fix would
be editing evidence after the fact, and that file is the only real instance of the false positive
we have. It will keep failing `numbers_traceable` in any replay over `evals/runs`; say the word
and I will patch that one key, but I would rather it stayed a known, explained failure than a
quietly corrected one.

Suite: **1151 collected, 0 failed**, ruff clean, 7 contracts kept.

## 2026-09-14 · One span per exchange, so a session reads as the conversation

Langfuse's Sessions view lists observations that carry input and output. Pipecat's turn spans
carry neither, so a whole call showed as the single `call` span. `CallRecorder` already
aggregates both halves of a turn, so it now drives one `exchange` span per turn through the same
object that owns the tool spans: `begin_exchange(user_text)` when the user turn flushes,
`end_exchange(bot_text)` when the assistant turn flushes, parent from
`get_current_turn_context()` as the tool spans do, typed `span`, name fixed at `exchange` so it
stays low-cardinality and filterable.

Edges, each with a test: the greeting has no user turn before it and becomes an exchange with an
empty input rather than no span at all; a person who speaks again before the coach answers closes
the previous exchange rather than leaving it open, because an unended span never reaches
Langfuse; anything still open at the end of the call is closed by `ToolTracer.close()`; and with
tracing off the whole path costs two `is None` checks per turn.

Verified on one headless call (Deepgram TTS, trace `f900529830556eb735e277cff8bfe3f0`): 41
observations — `conversation`, 4 `turn`, 8 `exchange`, 11 `llm`, 7 `tts`, 6 `stt`, 3 `upsert_item`
and the `call` span — with every exchange parented to a turn and carrying the text of both sides.

**One thing the owner should see before calling this done.** Eight exchanges for four turns,
because the hesitant script's fragments each finalise as their own recorder turn: "I have" /
"20,000 in cash and" / "20,000 in bank balance." are three exchanges, the first two with an input
and no output, the third carrying the coach's reply. That is faithful — the recording splits
those fragments the same way — but in the Sessions view it reads as three lines where a person
said one sentence. The alternative is to keep an exchange open while the coach has not answered
and append the next fragment to its input, which would collapse a fragmented sentence into one
line. That changes what "one exchange" means, so I have not done it unasked; it is a small change
if the owner prefers the second reading.

### Not mine, worth knowing

The live call's `aftercall` failed to record the profile: `profile_facts_phone_fkey`, because the
`users` row written at the start of the call was gone by the end. The demo database is shared
with A's `db`-marked tests, which truncate and re-seed it; the call itself, the trace and the
recording are unaffected. Nothing to fix in `api/` — but a run against the compose Postgres while
A's tests are running will keep producing this.

Suite: **1178 collected, 0 failed**, ruff clean, 7 contracts kept, Daily rooms `total_count=0`.

### Fragments merged, and the silent turn that was closing them early

The owner chose the merged reading: while the coach has not answered, each further fragment joins
the exchange that is open, joined with a space, so a sentence said in pieces is one line in the
Sessions view. The recording keeps its per-fragment turns exactly as before; only the span merges.

The first live call after that change still split one sentence in two, and the reason was not the
merge: a tool-only assistant turn flushes with **no text**, and `end_exchange("")` was closing the
exchange on it. The coach had acted without speaking, which is not an answer. Empty text now
leaves the exchange open — the tool call has its own span to show what happened — and the same
script came back as three exchanges for three intended utterances:

```
IN : I have 20,000 in cash and 20,000 in bank balance.
OUT: Twenty thousand rupees in your bank balance. What income do you expect between...
IN : It is on September 18.
OUT: What income do you expect on the eighteenth of September?
IN : Yes.
OUT: What's the income amount?
```

Trace `840cfa1c1a5be2157286277fa8c1178b`, Deepgram TTS: `conversation`, 3 `turn`, 3 `exchange`,
8 `llm`, 4 `tts`, 4 `stt`, 1 `upsert_item`, `call`. Two tests hold both halves: three fragments
then a reply give one exchange with the three joined, and a silent tool turn between fragments
does not end it.

Suite: **1204 collected, 0 failed**, ruff and format clean across `ledgerline/`, my tests and
`spike/`, 7 contracts kept, Daily rooms `total_count=0`.

## 2026-09-14 · v2: one setting switches the prompt, the tools and the greeting

B-redesign-2 wired through `voice/`. `PROMPT_VERSION` (now defaulting to `v2`) decides the tool
set (`build_tools(ctx, version)`), the turn block and the prompt text (`turn_block(...,
version=)`, `managed_prompt(..., version=)`), and the greeting: v1 tells the model what to say,
v2 says only `"The call just connected."` — same wording as the harness's `OPENING_V2` — because
the prompt already says what the call is for and scripting the first sentence is the form the
redesign exists to stop being. `IDLE_NUDGE` is untouched. `ActionFiller` now skips `done` as it
skipped `end_call`: v2 folds the hang-up into `done`, so the model still owns the one goodbye.
`tool_trace` needed nothing — it names spans after whatever tool ran.

### The bug the live call found: v2 tools on v1's prompt

The first v2 call worked and was wrong. `ensure_prompt` publishes and `managed_prompt` fetches
under the same `MANAGED_NAME`, so the v2 fetch got the v1 text that an earlier boot had published
there — the fetch succeeded, the fallback never came near it, and the call ran v2's tools against
v1's prompt with nothing in the log to say so. Confirmed by reading the prompt back out of
Langfuse: `ledgerline-coach` v1, first line `# Role`, the v1 file.

Both call sites now pass `name=f"{prompt.MANAGED_NAME}-{settings.prompt_version}"`. After that,
`ledgerline-coach-v2` reads back with `# Who you are`, the v2 file. Suggested as C-obs-4 that the
naming move into `agent/prompt.py`, where a caller cannot omit it.

### The greeting had never been exercised headlessly

No headless call has ever greeted, in any version: `on_client_ready` is an RTVI handshake the
browser sends, and `spike/drive.py` is a raw Daily client that never sent it. Every transcript
from this driver opens with the person speaking. The driver now sends `client-ready`, and the
greeting appears:

```
BOT : Hi, let's get through the next thirty days together. How much money is in your
      accounts and cash today?
USER: My rent is 11,000 rupees and it is due on the 5th.
  note {"item": "rent", "amount": 11000, "when": "the 5th", "kind": "bill", ...}
BOT : I've noted rent of 11,000 rupees, due on 5 October. How much money is in your accounts...
USER: Show me the month so far.
  show_month {"final": false}
BOT : I can't show a meaningful month yet. I have rent of 11,000 rupees due on 5 October, but
      I don't know your current balance or income...
```

The model opens in its own words, `note` and `show_month` both work live, and `show_month`
refusing to show a month it cannot compute is the domain's blocker speaking through the new
vocabulary.

One thing to read carefully: the recording says `prompt_version: 1`, which is Langfuse's numeric
version of `ledgerline-coach-v2`, not v1. Flagged in C-obs-4.

Suite: **1350 collected, 0 failed**, ruff clean across `ledgerline/`, my tests and `spike/`,
7 contracts kept, Daily rooms `total_count=0`.

## 2026-09-14 · Cleanup census: what came out of voice, api and config

Delete-only sweep for the owner's cleanup. Every removal below has its evidence beside it; the
sweep started mechanically (parse every def, class and constant in `voice/`, `api/`,
`observability/`, `config.py`, `main.py` and `spike/`, then count references outside the defining
line) and finished by reading, because the mechanical pass found **no** orphan symbol in my layer
beyond the ones the ruling named. What was left was branches, keywords and comments.

### Removed

| Symbol or file | Evidence it had no caller |
|---|---|
| `session.GREETING` (the v1 instruction) and the `settings.prompt_version == "v1"` branch | one greeting survives; the branch was its only reader. `GREETING_V2` is now simply `GREETING` |
| `session.managed_prompt_name()` | replaced by `prompt.managed_name(version)`, which C-obs-4 asked for and B landed; both call sites (session, main) now use the shared one |
| `CallRecord.prompt_version` | written by `run_session`, read by nothing: the recorder takes the version directly, and the `sessions` row takes `prompt_version` from `settings` in `routes.py`. Only reference outside the write was its own test |
| `"end_call"` in `ActionFiller.NEVER_FILLED` | no tool of that name exists; `plain.TOOL_NAMES` ends at `done`, which stays in the set |
| `Settings.host`, `Settings.port` | no reader anywhere in the tree. The container hardcodes `--host 0.0.0.0 --port 7860` in the Dockerfile CMD |
| `tool_trace.TOOL`, `.SPAN`, `.EXCHANGE`, `.NO_RESULT` | one use each; the literal at the use site says the same thing (ponytail pass) |
| `version=` keyword at three call sites, `carried=` on `ToolContext` | the callees no longer take them — `turn_block` had already lost `version` in B's tree, so that call was **broken, not merely dead**: every turn raised `TypeError` until it went |

Tests removed with the code they covered: `test_end_call_is_never_filled` (the `done` test covers
the surviving rule), `test_the_tool_set_follows_the_prompt_version`,
`test_the_version_reaches_the_turn_block`, the `tool_ctx.carried` half of the carried test (the
half asserting the figures reach the prompt survives), the `version` stubs in two files, the
`carried` parameter of the tests' `FakeToolContext`, and the `host`/`port` assertions. Nothing
covering surviving behaviour was weakened.

Comments naming machinery that no longer exists went too: `TurnCompletionGate` in
`pipeline._turn_strategies`, "our gate" in `trace.py`, and `end_call` in `lifecycle.py` and
`recorder.py`.

### Removed in the second pass, after B's check fold

| Symbol | Evidence |
|---|---|
| `event_order` and `spoke_before_acting` on the recording, and `_spoke_before_acting()` | `silent_before_acting` was the only reader and it went with B's fold into three checks; B removed the harness's `event_order` line in step, so both recording formats stayed the same shape |
| `recorder.Event` (`MESSAGE`, `FUNCTION_CALL`) | the vocabulary existed only to fill `event_order` |
| `_pending_calls`, `_spoke_this_completion` | both existed only to keep `event_order` from double-counting a broadcast frame or a multi-frame completion |

The order list was doing one more thing on its way to the transcript: answering "did anything
happen this turn" when the answer was a tool call that never returned — no text, no result, and
still a turn. A boolean `_acted` says exactly that and nothing else, so the flush behaviour is
unchanged; a test now pins it, because deleting the list without noticing would have quietly
dropped those turns from the recording.

Tests: `test_event_order_matches_the_harness_vocabulary`, `test_a_silent_tool_turn_is_recorded_as_silent`
and `test_one_call_in_progress_broadcast_twice_orders_once` went with the marks they read.
`test_checks_accept_a_recorded_voice_turn_order` called `checks.silent_before_acting`, which no
longer exists; it is now `test_the_checks_accept_a_recorded_voice_call`, asserting `run_checks`
runs over a voice transcript and returns violations of the documented shape. `checks._no_silent_turn`
would have been the wrong replacement — it reads `tool_calls` and `text`, not the order marks.

### Kept, with the reason

| Kept | Why it is not dead |
|---|---|
| `spike/probe.py`, `spike/probe_stt.py` | the instruments behind measurements in `spike-findings.md`; a measurement whose instrument is deleted cannot be rerun. Orchestrator's ruling, recorded here as asked |
| `spike/spike_bot.py`, `run_once.sh`, `index.html`, `rooms.py`, `drive.py` | entry points a person runs; `run_once.sh` and `rooms.py` are named in the README and in this ledger |
| `tracing.reset()` | called only by tests, but the module holds a process-wide client and the idempotency tests cannot be written without it |
| `voice/trace.py` (`FrameTrace`) | attached when `LOG_LEVEL=DEBUG`; it is how the turn bug was found in one run instead of seven |
| `DELETE /api/sessions/{id}` | the frontend calls it (`mock/install.ts`, `App.busy.test.tsx`) |
| `LlmApi.RESPONSES`, `TurnStrategy.TIMEOUT` branches | configuration a deployment can still choose, not dead code |

### For whoever owns `.env.example` and `docker-compose.yml`

`HOST` and `PORT` are set in both and now read by nothing: the Settings fields are gone and the
container hardcodes its own. They are documented settings that do nothing, which is worse than
absent.

### Verification

Headless call after the sweep (Deepgram TTS, `9876500070`): zero errors in the log, the greeting
in the model's own words — "Let's get your next thirty days clear. How much money do you have in
your bank account and in cash?" — `note` firing on the rent and the balance, `carried: []` and
`prompt_version: v2@2` on the recording, Daily rooms `total_count=0`.

`tests/voice` 153, `tests/api` 73, `tests/observability` 22; whole suite **1145 collected, 0
failed** now that B's sweep has landed; ruff and format clean; 7 contracts kept. Application code
in my layer: **2,730 lines** across `voice/`, `api/`, `observability/`, `config.py` and `main.py`.

### Two open items, unchanged on purpose

- The fourth call's recording (`voice-9876500042-20260913T184932Z-*.json`) still carries no
  `carried` key and still fails `numbers_traceable` on replay. It was written before the key
  existed; patching it now would be editing evidence, and it is the only real instance of that
  false positive we have.
- `LANGFUSE_PROJECT_ID` is unset in `.env`, so `trace_url` is null on the review page and in the
  verdict. Verified once with it set that the link resolves; the value is the owner's to add.

## 2026-09-14 · Kiro review kiro-20260914T050806Z, the three findings in my layer

**KIRO-013, two `ToolTracer` instances (`voice/session.py`).** One was handed to the recorder as
its span sink, the other was registered as the worker's observer and was the one teardown closed
and read the trace id from. So the exchange spans were written into an object nobody closed, and
a call whose only spans were exchanges left the registered tracer's `trace_id` unset — the
session row and the after-call scores would then have nothing to link to. My own edit made this:
I moved the construction above the recorder and the original construction survived below it.
Now one tracer, constructed once, given to the recorder and registered as the observer, and
`trace_id` is captured from the **first span of any kind** we open rather than only from a tool
span. Two tests: the recorder's sink *is* the registered observer, and an exchange alone captures
the trace id.

**KIRO-010, an unbounded store write on the request path (`api/routes.py`).** `create_session`
was best-effort but unbounded, so a stuck pool held the HTTP request open with a Daily room and
two tokens already paid for. Now `asyncio.wait_for(..., PROFILE_TIMEOUT_SECS)` — the store's own
constant — with a timeout treated exactly like an exception: log, carry on, start the call. Test
drives a store that sleeps 30 s and asserts the route still answers 201.

**KIRO-008, `PROFILE_MAX_AGE_DAYS` documented but not a setting.** `Settings.profile_max_age_days:
int = 60` exists now and `main.py` passes it to `open_store(...)`; A's keyword had already
landed, so nothing was left dangling. Config test covers the default and the override.

Verified on a headless call (`9876500080`, Deepgram TTS): zero errors, the session row carries
`langfuse_trace_id 3f40a8e7e508e601aa78206763687a8e`, rooms `total_count=0`. The call made one
tool call, so the zero-tool path is held by the unit test rather than by that call.

`tests/voice` and `tests/api` green, ruff and format clean, 7 contracts kept.

## 2026-09-14 · Kiro 15 F5: a failed setup no longer leaves a Daily room behind

`start_session` creates the room and then two tokens inside one `try`. If a token request
failed, the `except` released the slot and re-raised — and the room, already created and
private, had nobody left to delete it: no session task exists yet, so `run_session`'s teardown
never runs for a call that never started. It sat there until Daily expired it.

Now the room name is held before the token calls and the failure path deletes it best-effort
before releasing the slot and re-raising. `delete_room` never raises and is bounded by its own
`REST_TIMEOUT_SECS`, so it cannot mask the error the caller is about to see. Two tests: a token
failure deletes the created room exactly once by name and frees the slot, and a failure *before*
the room exists deletes nothing.

F3 (same-second session ids) was raised again and stays as recorded: one person cannot start,
end and restart a call inside a second outside a test, and the test that used to assert distinct
ids says so.

`tests/api` green, ruff and format clean.

## 2026-09-14 · Kiro 16 F5: cancellation during setup

`start_session` cleaned up under `except Exception`, and `asyncio.CancelledError` is not an
`Exception`. A request cancelled after `create_room` succeeded — a browser that gives up, a
client timeout, a shutdown — skipped `delete_room`, skipped `sessions.release` and never reached
`sessions.start`. Both the private room and the single call slot were stranded, with no session
task in existence to tear either down. The Kiro 15 fix had covered failure but not cancellation.

Setup is now one `try` with a `finally` and a `handed_over` flag set the moment `sessions.start`
returns: before that the request owns the room and the slot, after it the session task does and
tears both down itself. The room delete in the cleanup path is shielded and waited on the way
`voice/lifecycle.Teardown` does it — a cancellation arriving mid-cleanup would otherwise kill the
very delete the cleanup exists to perform. `delete_room` never raises and carries its own REST
timeout, so the cleanup can neither hang nor mask the exception on its way out.

Three tests, all driving the handler directly because a `TestClient` request cannot be cancelled
mid-flight: cancelled while a token call is parked, cancelled while the bounded store write is
parked (room and both tokens already exist by then), and a started call whose room is **not**
deleted behind its own back once ownership has transferred. The Kiro 15 tests stay green.

F4 (same-second ids) raised again; unchanged, on the phase-2 note.

`tests/api` and `tests/voice` green, ruff and format clean, 7 contracts kept.
