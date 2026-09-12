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
