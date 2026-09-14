# Spike findings

Run 2026-09-11 from `spike/`. **All six items are settled.** Four were answered headlessly
before any call; items 1 and 2 needed four real calls once the Daily card was added.

**No pipeline.py choice was contradicted.** The one change the spike produced was
`STT_LANGUAGE` from `"en"` to `"en-IN"` (item 5). Everything else is confirmed as built.

## Cost and cleanup

Four calls, two participants each, roughly a minute apiece: **about 8 Daily participant-minutes**
against the 10,000/month free tier. Every spike room was created with `exp` 10 minutes out and
`eject_at_room_exp=True` (`ROOM_EXPIRY_SECS=600`), and each run deleted its own room in
`run_session`'s equivalent `finally`:

```
SPIKE room DELETE right after the call: True    (x4, one per run)
```

After the last run, `GET /v1/rooms`:

```
HTTP 200 total_count=0
[]
```

Zero rooms remain and no process is left joined (`pgrep -fl "spike_bot.py|spike/drive.py"` is
empty). Cartesia spend: **one pass, one bot sentence**. Everything else ran on Deepgram Aura-2,
which comes out of the same $200 credit as STT.

### Earlier blocker, now cleared

The first attempt failed on every join, bot and client alike:

```
join (request 2) encountered an error:
  Connection(Api(RoomLookup(RoomInfoError(Unhandled("account-missing-payment-method")))))
```

REST was unaffected throughout, which is why room create and delete passed while no call could
start. The owner added a card and joins worked immediately. Worth keeping in the README as the
first thing to check if a fresh clone cannot start a call.

## 1. Turn end: Smart Turn v3 vs `SpeechTimeoutUserTurnStopStrategy` — **Smart Turn wins**

Three runs, same three utterances, measured from the bot's `Stopwatch` observer as the gap
between `VADUserStoppedSpeakingFrame` and `UserStoppedSpeakingFrame`.

| Utterance | Smart Turn, `stop_secs=1.5` | Smart Turn, `stop_secs=3.0` | `SpeechTimeout(0.6)` |
|---|---|---|---|
| `"Yes."` alone | **0.455 s** | 0.442 s | 0.971 s |
| `"My salary is forty-five thousand rupees."` | **0.235 s** | 0.341 s | 0.600 s |
| `"My EMI is, um, forty-two hundred."` | split, see below | split, see below | split, answered early |

**The bare `"yes"` did not hang.** The 5 s stall reported in issues #3643/#3988 did not
reproduce: Smart Turn closed the turn in 0.455 s and first audio came back 1.818 s after the
person stopped speaking. Smart Turn beat the timeout strategy on both clean utterances, by
roughly 0.4 s each, which is the whole of the timeout strategy's fixed wait.

**The mid-number pause splits into two turns under every strategy**, and the cause is not the
stop strategy. Aura-2 renders ", um," as a real pause; Deepgram finalises `"My EMI is"` during
it, and `"4200."` arrives as a separate final afterwards:

```
22:00:08.627 transcript (+0.329s after VAD stop) 'My EMI is'
22:00:10.439 user_turn_stop (+0.149s after VAD stop)
22:00:10.650 transcript (+0.360s after VAD stop) '4200.'
22:00:10.807 user_turn_stop (+0.517s after VAD stop)
```

With Smart Turn the two halves land 0.31-0.37 s apart, so both reach the LLM before it speaks
and the tool still fires with the right number — `record_number(4200)` in every run. With the
timeout strategy the bot started answering `"Please…"` before the number arrived, which is the
failure this whole check was about. That alone settles the choice.

`stop_secs=3.0` bought nothing over `1.5` (within noise on turn end, and 0.4 s *slower* to first
token) so the lower value stays.

**No change made.** `turn_strategy` stays `"smart"` with `smart_turn_stop_secs=1.5`, and
`TURN_STRATEGY=timeout` remains the one-env-var escape hatch.

**Caveat that still stands:** Smart Turn classifies **prosody**, and Aura-2 speech is cleaner
and more evenly paced than a person's. A real hesitation is longer and messier than `", um,"`,
so the split above may be worse with a human, and the encouraging `"yes"` result may be
optimistic. One human call should confirm both before the demo.

## 2. Cards frame: generic vs Daily-specific urgent frame — **the generic frame works**

`OutputTransportMessageUrgentFrame(message={...})` pushed from inside a tool handler arrives at
the remote participant intact, through `DailyTransport`, with **no Daily-specific subclass**.
From the fake user's log, payload byte-for-byte as pushed:

```
[21:57:01] APP app-message: {"type": "spike", "value": 4200}
[21:57:27] APP app-message: {"type": "spike", "value": 45000}
non-RTVI app-messages received: 2
```

Two tool calls, two messages, zero lost, in every run that made tool calls. `DailyTransport`
also confirmed the RTVI traffic prediction: the same channel carries a stream of
`label: "rtvi-ai"` messages (`user-transcription`, `bot-llm-started`, `metrics`, …), so the
frontend must filter on that label, exactly as `protocol/parse.ts` is specified to do.

**No change made.** `session.CardsFrame = OutputTransportMessageUrgentFrame` stands, and
`DailyOutputTransportMessageUrgentFrame` is not needed.

## 3. LLM service: `OpenAIResponsesLLMService` with `gpt-5.6-luna` — **CONFIRMED, keep it**

`spike/probe.py` sends the exact tool schema Pipecat derives from a direct function to
`/v1/responses`, streaming, `reasoning.effort = "none"`:

```
output item: {"type": "function_call", "status": "completed",
              "arguments": "{\"value\":4200}", "name": "record_number"}
time to first streamed event: 0.702s
total: 1.193s, 12 events
```

Direct function calling works, and "forty-two hundred" arrived at the tool as `4200`. The 0.70 s
first-token figure matches research 05's "reasoning none, ~0.7 s" claim exactly. The
`OpenAILLMService` + `extra={"reasoning_effort": "none"}` fallback is **not needed**.

**No change made.** `pipeline._build_llm` keeps `OpenAIResponsesLLMService`.

## 4. Strict mode on the derived schema — **ANSWERED: no, `strict` is null**

The schema Pipecat's Responses adapter emits for a direct function, verbatim from
`get_llm_invocation_params`:

```json
{
  "type": "function",
  "name": "record_number",
  "parameters": {
    "type": "object",
    "properties": {"value": {"type": "number", "description": "The number, as a plain number."}},
    "required": ["value"]
  },
  "strict": null,
  "description": "Record a number the person said out loud."
}
```

Direct functions do **not** carry `strict: true`. The docstring becomes the description and the
type hint becomes the JSON type, both correctly, and luna produced well-formed arguments anyway.

Research C5 said: switch a tool to an explicit `FunctionSchema` if strict cannot be expressed
through direct functions. That decision belongs to `agent/tools.py`, which is **Session B's
file** — raised with the orchestrator rather than changed here. The evidence is that direct
functions are good enough for a single numeric argument; the six real tools have enums and
optional fields, where strict matters more.

## 5. Deepgram `language="en-IN"` on nova-3 — **ACCEPTED**, and numerals work

Both variants open the socket and report the **same** model, so `en-IN` is not silently
rejected or downgraded:

```
model_info: {"40bd3654-...": {"name": "general-nova-3", "version": "2025-04-17.21547", "arch": "nova-3"}}
```

Aura-2 speech through `spike/probe_stt.py`, `smart_format=true`, `numerals=true`:

| said | heard (`en`) | heard (`en-IN`) |
|---|---|---|
| My EMI is, um, forty-two hundred. | `My EMI is 4,200.` | `My EMI is 4,200.` |
| My salary is forty-five thousand rupees and rent is eleven thousand. | `My salary is 45,000 rupees. And rent is 11,000.` | `My salary is 45,000 rupees and rent is 11,000.` |
| Yes. | `Yes` | `Yes.` |
| The electricity bill is around one thousand two hundred, due on the fifteenth. | `The electricity bill is around 1,200. Due on the 15th.` | `The electricity bill is around 1,200 due on the 15th.` |

"forty-two hundred" becomes `4,200` under both, the filler "um" is dropped, and "the fifteenth"
becomes `the 15th`. `en-IN` never did worse and split sentences less eagerly.

**Changed:** `pipeline.STT_LANGUAGE` flipped from `"en"` to `"en-IN"`. Honest limit on that
evidence: the speech was synthetic and American-accented, so this shows *acceptance and no
regression*, not a demonstrated win for Indian speakers. Re-check with a human once joins work.

## 6. Daily room DELETE right after the call — **WORKS**

```
created https://ledgerline.daily.co/1C9LUgTvN4fVdlFLeWOp
DELETE -> HTTP 200 {"deleted":true,"name":"1C9LUgTvN4fVdlFLeWOp"}
```

The "cannot delete until 24 h after expiry" changelog note does not apply to this account.
Already implemented: `transport.delete_room`, called from `run_session`'s `finally` after the
worker is cancelled, wrapped so a failure can never break teardown. `exp` ≈ 1 h plus
`eject_at_room_exp=True` remain the real guarantee.

## What is in `spike/`

| File | What it does |
|---|---|
| `spike_bot.py` | the real pipeline, one `record_number` direct function, one urgent frame, a `Stopwatch` observer; honours `TTS_PROVIDER`, `TURN_STRATEGY`, `STT_LANGUAGE` |
| `index.html` | bare daily-js 0.92.2 page; joins a room, attaches bot audio, logs every app-message and flags `rtvi-ai` |
| `drive.py` | fake user: joins over `daily-python`, speaks Aura-2 audio through a virtual mic, logs app-messages. Removes the need for a human for items 1 and 2 |
| `probe.py` | headless items 4, 5a, 3, 6 |
| `probe_stt.py` | headless item 5b, `en` vs `en-IN` transcripts |
| `rooms.py` | `GET /v1/rooms`, to prove nothing leaked |
| `run_once.sh` | one call end to end: bot, driver, teardown, room-delete check, `exp` forced to 10 min |

Nothing deleted, per the brief; the orchestrator decides what survives.

### `spike/drive.py` is worth keeping as a voice smoke test

It is a headless second participant. `Daily.init()`, a `VirtualMicrophoneDevice` at 16 kHz mono,
`CallClient.join(room_url)`, and an `EventHandler` whose `on_app_message` prints every message
and tags anything with `label: "rtvi-ai"` so our own card frames stand out. The utterances in
`UTTERANCES` are synthesised once up front with Deepgram Aura-2 (`POST /v1/speak`,
`encoding=linear16&container=none`, so the response is raw PCM that goes straight into
`mic.write_frames`), then spoken one at a time with a 12 s gap for the bot to answer. Run it as
`PYTHONPATH=. uv run python spike/drive.py <room_url>` against a running bot and read the two
logs side by side: the driver's for what reached the browser side, the bot's `SPIKE-TIMING`
lines for `vad_stop → user_turn_stop → transcript → llm_response_start → first_token →
first_audio`. That combination is a complete end-to-end voice check with no human, no browser
and no Cartesia spend, so it can stand in for most of the manual `evals/SMOKE.md` checklist and
could later run under the `voice` pytest marker. Its one blind spot is prosody: Aura-2 speech is
cleaner than a person's, so Smart Turn's behaviour on a hesitant real speaker still needs one
human call to confirm.

## Net effect on the app

| Choice | Spike verdict | Action |
|---|---|---|
| LLM service | Responses + `effort="none"` works, 0.70 s TTFT | keep |
| Turn end | Smart Turn beats the timeout strategy by ~0.4 s and does not hang on "yes"; 3.0 s buys nothing over 1.5 s | keep smart, 1.5 s |
| Cards frame | generic urgent frame reaches the remote participant intact | keep generic urgent frame |
| Deepgram language | `en-IN` accepted, same model | **flipped to `en-IN`** |
| Strict schemas | direct functions send `strict: null` | Session B's call, raised with the orchestrator |
| Room DELETE | works immediately | already implemented |

## Latency, end to end, measured

From the person stopping speaking to the first byte of bot audio, Smart Turn at 1.5 s:

| Turn | Turn end | First token | First audio |
|---|---|---|---|
| `"Yes."`, no tool call | 0.455 s | 1.352 s | **1.818 s** |
| `"My salary is forty-five thousand rupees."`, one tool call | 0.235 s | 2.231 s | **2.651 s** |

The HLD targets transcript ~0.3 s, first tool call ~0.7 s, first audio ~1.4 s. Transcripts land
at 0.23-0.34 s, on target. First audio is 1.8 s with no tool call and 2.7 s with one, so the
tool round trip costs roughly 0.9 s and the target is missed by 0.4-1.3 s. Nothing here is a
blocker, but it is the number to watch if the plan explanation feels slow.

**TTS choice confirmed by measurement.** Cartesia `sonic-3.6` time to first byte **0.092 s**
against Deepgram Aura-2 **0.30-0.32 s**, from the `metrics` app-messages:

```
{"leading_silence": 0.15,  "model": "sonic-3.6", "processor": "CartesiaTTSService#0", "ttfb": 0.0921...}
{"leading_silence": 0.115, "model": "",          "processor": "DeepgramTTSService#0",  "ttfb": 0.3240...}
```

Cartesia is roughly 3x faster to first byte and streams word-level `bot-tts-text`, so it stays
primary and Aura-2 stays the free-tier fallback — which is what `tts_provider` already does.


---

# 2026-09-12 · Responses vs Chat Completions, and the duplicate tool calls

Prompted by the owner's second live call: first_token 2.9 s on an ordinary turn, spikes of 7.3 s
and 6.8 s, five `previous_response_not_found` retries, and every tool call appearing twice.

Method: the real app (`uvicorn ledgerline.main:app`), driven by `spike/drive.py` with the same
four-fact script both times, `TTS_PROVIDER=deepgram` so no Cartesia minutes were spent. Two
calls, two participants each, about 5 Daily participant-minutes. Rooms afterwards:
`GET /v1/rooms` returns `total_count=0`.

## The duplicate tool calls are Pipecat, not the model

Every duplicated pair shares **one** `tool_call_id`:

```
turn first_token=1.211 first_audio=2.03  tools=['upsert_item', 'upsert_item'] unique_ids=1/2
turn first_token=1.265 first_audio=2.264 tools=['upsert_item', 'upsert_item'] unique_ids=1/2
```

`LLMService` publishes the result with `broadcast_frame(FunctionCallResultFrame, ...)`, which
sends it **both upstream and downstream**. One call therefore arrives as two frames with
different frame ids and the same `tool_call_id`. It happens identically on Responses and on
Chat, so it is not endpoint-specific, and it is **not** luna emitting parallel duplicates —
research C1's worry does not apply here.

Two fixes in `recorder.py`: every recorded tool call now carries its `id`, and a call already
present under the same `tool_call_id` is not recorded twice.

The owner's "utilities once, food twice, travel twice" was a second bug of mine on top of this
one. The recorder closed an assistant turn on **every** `BotStoppedSpeakingFrame`, and the bot
stops speaking at more than one point in a turn, so a single exchange was split across several
assistant turns with the pair landing on either side of the split. Turns now close when the
next user turn starts; the INFO line still fires once, on the first stop.

## Latency: Responses still wins on the median, Chat on the tail

| | Responses | Chat Completions |
|---|---|---|
| first_token, median | **1.265 s** | 1.744 s |
| first_token, max | 3.299 s | **2.663 s** |
| first_audio, median | **2.264 s** | 2.863 s |
| first_audio, max | 4.162 s | **3.048 s** |
| `previous_response_not_found` | 1 | **0** |
| duplicate tool calls | same (framework) | same (framework) |

**No flip.** The instruction was to switch if Chat came out faster and duplicate-free. It is
neither: it is ~0.5 s slower at the median and the duplicates are identical because their cause
is in Pipecat, not the endpoint. Chat's only real win is the retry, which is the known
connection-local `previous_response_id` cost, and its flatter tail.

`settings.llm_api` (`responses` | `chat`, default `responses`) now selects the endpoint, so this
is one env var to re-test on a longer call rather than a code change.

**Read this with care.** One run each, four turns each, on synthetic speech. The median gap is
about half a second on samples of four and five — suggestive, not significant. The retry counts
(1 vs 0) are far too small to separate from chance; the owner's 24-turn call produced five. If
the tail matters more than the median for the demo, Chat is worth a longer trial before the
default is settled.


---

# 2026-09-12 · Why hesitation ended the turn, and what fixed it

After the owner's third live call (pauses and repeats). Method: `spike/drive.py` gained a
hesitant script that speaks one intended utterance as fragments with 1.6 s of real PCM silence
between them, driven against the running app, `TTS_PROVIDER=deepgram`, no Cartesia. The
transcripts it produced came back nearly word for word identical to the owner's — `'I have'` /
`'20,000 in cash and'` / `'20,000 in bank balance.'` — so the harness reproduces the real thing.

## The knobs are a dead end, and here is why

| `smart_turn_stop_secs` | bot responses for 3 utterances | retries |
|---|---|---|
| 1.5 (then-current) | 6, plus an idle nudge mid-sentence | 0 |
| 3.0 | 6 | 2 |

`SmartTurnParams.stop_secs` bounds how long an **INCOMPLETE** verdict holds a turn open. Smart
Turn v3 classifies `"I have"` and `"It is"` as **COMPLETE**, so the hold never engages and the
value is irrelevant. The aggregation timeout fails for the same reason: nothing is waiting.

## The fix: Pipecat's deferred slot plus a linguistic rule

`deferred(TurnAnalyzerUserTurnStopStrategy(...))` suppresses Smart Turn's own finalization, and
`ExternalUserTurnCompletionStopStrategy` finalizes when a `UserTurnInferenceCompletedFrame`
arrives. `voice/turn_gate.py` pushes that frame; `voice/turn_completeness.py` decides when.

The user-facing difference, verbatim from the two recordings:

```
BEFORE  BOT: I've recorded twenty thousand rupees in cash. How much is in your bank balance?
        BOT: I've recorded twenty thousand rupees in your bank balance. What income do you...
        BOT: Are you still there? There's no rush — what income do you expect...

AFTER   BOT: Got it: twenty thousand rupees in cash and twenty thousand rupees in your bank
             balance. What income might come in...
```

Three fragments, three interrupted answers and a spurious idle nudge, became one answer to the
whole sentence. The `"Got it:"` is the new pipeline filler.

## Two things I got wrong on the way, recorded so nobody repeats them

**The hold has to survive the gap between fragments.** The first version armed a 2.5 s hold from
each finalised transcript. Debug logging showed the gap between two fragments of one sentence
was **3.5 s** — the audio pause is 1.6 s, but the next fragment also has to be spoken and
finalised — so the hold fired mid-sentence and nothing changed:

```
20:03:28.766 turn released (held 2.5s): 'I have'
20:03:32.263 turn released (held 2.5s): 'I have thousand in cash and'
20:03:33.124 turn released (finished): 'I have ... 20,000 in bank balance.'
```

The fix is to cancel the hold on `InterimTranscriptionFrame`. VAD and the speaking frames come
from the user aggregator, which is **downstream** of the gate, so interim results are the only
"still talking" signal that reaches it. The 2.5 s bound then applies to genuine silence.

**My first metric measured the wrong thing.** I counted "user turns" from the recording, but the
recorder appends a user turn per `TranscriptionFrame`, so that number counts Deepgram
finalisations, not Pipecat turns. It stayed at 8 before and after the fix while the bot's actual
behaviour changed completely. Count bot responses per intended utterance instead, and read the
text.

## Caveat on the synthetic speech

Aura-2 renders `"I have"` with terminal falling intonation because it is synthesised as a
standalone sentence, where a person trails off. That biases Smart Turn towards COMPLETE, so the
harness may overstate how often this fires. It is not flattering the bug: the owner's live call
fragmented on the same words, from a real speaker, so the two agree. The remaining uncertainty
is frequency, not existence.


---

# 2026-09-12 (later) · The corrected metric, and where the gate stops helping

## The metric, fixed

A user turn is now the aggregated turn Pipecat hands the model, closed on
`UserStoppedSpeakingFrame` with the assistant's first action as a fallback. The raw Deepgram
finalisations are kept beside it as `finalisations`. The old count — one turn per
`TranscriptionFrame` — counted Deepgram finalisations and was flat at 8 across a change that
altered the bot's behaviour completely.

Re-derived, hesitant script, 3 intended utterances, one bot response each is the target:

| Configuration | user turns | bot responses |
|---|---|---|
| no gate (2026-09-12 morning) | not comparable, old metric | 6, plus a spurious idle nudge |
| gate, `turn_hold_secs=2.5` | 5, 7, 8 across three runs | 4, 5, 4 |
| gate, `turn_hold_secs=4.0` | 7 | 5 |

## Where it stops helping, and why I stopped

The gate reliably joins the fragments it is given time to see — `"20,000 in cash and"` +
`"20,000 in bank balance."` merged in most runs, and the owner's worst case (three separate
answers to one sentence, plus an idle nudge in the middle) does not reproduce. But it does not
reach one turn per utterance, and the run-to-run spread (5 to 8) is wider than the effect being
chased.

The stubborn case is `"I have"`, which released on its own in **every** run, at both 2.5 s and
4.0 s. The hold length is therefore not what releases it, so raising it further is not the
answer — and 4.0 s was reverted because it cost latency on every unfinished turn and measured no
better.

**The rule is not the limit; the timing is.** `looks_complete("I have")` is `False` and unit
tested, so the gate does hold it. What ends the turn anyway is something upstream of the rule,
and identifying it needs frame-level tracing of one live call rather than another end-to-end
run. Seven live runs in, with each iteration about two minutes and the variance as wide as the
signal, the next live call with a real speaker is the better instrument — real hesitation has
different prosody and different Deepgram finalisation timing, and both of those are inputs here.

## The rule now also holds

Added after the second round, with unit tests for each: a month on its own (`"September."`,
`"It is September."`) but not a month with a day (`"September 18."`, `"the eighteenth of
September."`); a bare amount with punctuation (`"20,000."`, `"twenty thousand."`) but not one
with a noun after it (`"20,000 in bank balance."`); and spoken hesitation (`"like,"`, `"um,"`,
`"so,"`), which Deepgram punctuates and which would otherwise release on the punctuation alone.


---

# 2026-09-12 (later still) · What actually releases "I have"

One traced call, `LOG_LEVEL=DEBUG`, with the new `voice/trace.py` observer logging every
turn-relevant frame and its source processor.

## The answer: the LLM service ends most turns, not our gate

```
UserTurnInferenceCompletedFrame from=OpenAILLMService#0   x4
UserTurnInferenceCompletedFrame from=TurnCompletionGate#0 x1
```

`OpenAILLMService` carries Pipecat's turn-completion mixin and broadcasts
`UserTurnInferenceCompletedFrame` itself. `ExternalUserTurnCompletionStopStrategy` finalises on
**any** frame of that type, whatever emitted it, so the model ended four turns to our gate's
one. `"I have"` never got a gate release at all — its turn was over before the hold mattered.

That kills the four hypotheses on the table. Not (a): the first turn is not special. Not (c):
the `UserStoppedSpeakingFrame`s all follow a completion frame rather than preceding one. Not
(d): the interim path works, and the one gate release in the call was correct and well timed
(`'20,000 in cash and 20,000 in bank balance.'`). Hypothesis (b) was right in spirit — something
else is authoritative — but wrong about which component: it is the LLM, not Smart Turn.

Also checked and **not** a bug: `MinWordsUserTurnStartStrategy` logs `min_words=1` where we pass
3. That is documented behaviour — the threshold only applies while the bot is speaking, and the
log line shows `bot_speaking=False`.

## The obvious fix was tried and reverted

Stamping our completion frames and subclassing the strategy to ignore everyone else's is about
fifteen lines, and it works as designed — but the live run was worse, not better. The bot began
speaking marker fragments:

```
BOT '0 rupees. How much money do you have right now, counting cash and your bank balance?'
BOT '20,000 rupees. What would you like to tell me?'
```

The LLM's completion protocol is load-bearing: swallowing its frames breaks the contract the
mixin has with `filter_incomplete_user_turns`, and the marker text leaks into speech. Reverted
in full; `ExternalUserTurnCompletionStopStrategy` is back.

## What a real fix would need

Turn completion has to be resolved at one place. Either the LLM's protocol is disabled properly
at the source (`set_user_turn_completion_config(None)` and whatever enables it, so no frames are
emitted rather than being filtered downstream), or our linguistic rule moves inside that
protocol instead of competing with it. Both are bigger than the loop this was scoped as, and
both want a live call to validate. The trace observer stays in at DEBUG for that call.


---

# 2026-09-12 (final) · One judge: Pipecat's LLM turn completion

The trace above showed `OpenAILLMService` broadcasting `UserTurnInferenceCompletedFrame` itself,
four times to our processor's once, and `ExternalUserTurnCompletionStopStrategy` finalising on
any of them. A downstream gate cannot win that: the model had already ended the turn.

So the gate is gone. `voice/turn_gate.py` and `voice/turn_completeness.py` are deleted, and the
chain is Pipecat's documented pairing:

```python
stop=[deferred(TurnAnalyzerUserTurnStopStrategy(...)), LLMTurnCompletionUserTurnStopStrategy(config=...)]
```

`UserTurnCompletionConfig` takes an `instructions` string, and the config exposes the rendered
default as `completion_instructions`, so our rule survives as **guidance inside the model's
brief** rather than as a competing judge:

```python
base = UserTurnCompletionConfig()
UserTurnCompletionConfig(instructions=base.completion_instructions + TURN_COMPLETION_HINTS)
```

The hints are the word list turned into prose — function words, bare amounts, bare months,
spoken hesitation, short answers — appended to Pipecat's own COMPLETE / INCOMPLETE SHORT /
INCOMPLETE LONG framework.

## Result: one bot response per intended utterance

| Configuration | bot responses for 3 utterances |
|---|---|
| our gate, `turn_hold_secs=2.5` | 4, 5, 4 across three runs |
| our gate, `turn_hold_secs=4.0` | 5 |
| **LLM completion + our hints** | **3** |

No marker text reached speech (zero assistant turns contain `●`, `◐` or `○`), and no idle nudge
fired mid-sentence.

## The honest cost

First token moved from roughly 1.2-2.4 s to 3.7-4.6 s. Read that carefully before calling it a
regression: the clock is anchored to the VAD stop of the **first** fragment, so the time the
person spent speaking fragments two and three is counted as latency. The model is now waiting
for the sentence to finish, which is the entire point. Whether it *feels* slow is a question for
a live call with a real speaker, not for this harness — the fragments here are synthetic and
evenly spaced.


## The latency number, read properly

The 3.7-4.6 s reported above was anchored to the VAD stop of the **first** fragment, so it
counted the seconds the person spent finishing their own sentence. The recorder now anchors
`first_token` and `first_audio` to the **last** fragment — the part we are responsible for —
and keeps `first_token_from_turn_start` / `first_audio_from_turn_start` and `user_speaking_secs`
beside them.

Re-measured with single-word answers added to the script:

| Turn | first audio |
|---|---|
| `"Yes."` | **1.805 s** |
| `"20,000 in bank balance."` (end of a three-fragment sentence) | 2.173 s |
| `"18th."` | 9.272 s |

**Single-word answers cost nothing.** `"Yes."` at 1.805 s sits inside the 1.4-1.8 s band it had
before the completion judge existed, so the extra round trip is not charged to an obviously
complete answer. That was the main worry and it does not reproduce.

`UserTurnCompletionConfig` has no short-circuit to propose: its fields are `instructions`, the
three markers, and `incomplete_short_timeout` / `incomplete_long_timeout`, which apply *after*
an incomplete verdict rather than capping the completion inference. Nothing needs proposing —
the measurement says the fast path is already fast.

The 9.272 s on `"18th."` is a single outlier in one run and I am not going to explain it from
one sample; it is the kind of thing the next live call will either show repeatedly or not at all.

One honest limitation of the new fields: in this run `user_speaking_secs` was 0.0 on every turn,
because each recorded turn contained a single VAD stop, so the two anchors coincided. The
separation is implemented and unit tested, but this data had nothing to separate. A turn that
genuinely spans fragments is what will show the difference.

# 2026-09-13 · Phase 0 spikes S1 to S3: tracing shape, read from the source

Pipecat 1.9.0, langfuse 4.15.2, opentelemetry-sdk 1.44.0. S1 to S3 are answered by reading the
installed packages rather than by a call: each one is a question about an API surface, and the
source is the authority. S4 (hobby unit count) needs a real call and rides along with the phase 1
live call. No Daily minutes spent.

## S1 — the parent for a tool span is public API. No fallback needed.

`PipelineWorker` exposes `turn_trace_observer` as a property
(`pipecat/pipeline/worker.py:669`), and `TurnTraceObserver.get_current_turn_context()`
(`utils/tracing/turn_trace_observer.py:236`) returns the current turn's `SpanContext`, documented
as "can be used by services to create child spans". So `tool_trace.py` parents its span with:

```python
ctx = observer.get_current_turn_context()          # SpanContext | None
parent = set_span_in_context(NonRecordingSpan(ctx)) if ctx else None
span = tracer.start_span(tool_name, context=parent)
```

The HLD's fallback (tool spans under the conversation span with a `turn` attribute) is still the
behaviour when `get_current_turn_context()` returns `None` — between turns, or with tracing off —
and needs no separate code path: `context=None` means the ambient context, and the turn attribute
is worth setting either way.

Two facts worth having beside that:

- `TracingContext` (`utils/tracing/tracing_context.py`) is pipeline-scoped, created by
  `PipelineWorker` and handed to services through `FrameProcessorSetup`. It is the same span
  context by another route, but it reaches the worker only as the private `_tracing_context`, so
  the observer property is the cleaner hold.
- **The HLD is wrong about one default.** It says both `enable_tracing` and `enable_turn_tracking`
  default to False. In 1.9.0 `enable_tracing: bool = False` but `enable_turn_tracking: bool = True`
  (`worker.py:296-297`), and the tracing branch is `if self._enable_tracing and
  self._turn_tracking_observer`. Turn tracking is already on in our build; only `enable_tracing=True`
  is missing. Passing `enable_turn_tracking=True` explicitly is still worth it as documentation.

## S2 — trace id is readable after the call, from a public method

`_handle_turn_started` stores every turn's span context in `_trace_context_map` and never clears
it, and `get_turn_context(turn_number)` (`turn_trace_observer.py:249`) is public. So after the
call, when the conversation span has already ended:

```python
ctx = worker.turn_trace_observer.get_turn_context(1)
trace_id = format(ctx.trace_id, "032x") if ctx else None
```

Turn 1 is a child of the conversation span, so its trace id *is* the trace id. This survives
`end_conversation_tracing()`, which clears the spans but not the map — which matters, because
`aftercall` needs the id after the pipeline is gone. Neither HLD fallback (our own id, or a
lookup by `metadata.session_id`) is needed. A call with zero turns has no trace id and no trace
worth scoring; `aftercall` treats `None` as "no trace" and still writes its row.

## S3 — one provider, but not the way the HLD assumed

The HLD proposed a Langfuse client with `tracing_enabled=False` for scores and prompts, beside our
own OTLP exporter. **That silently loses every score.** `Langfuse.create_score` opens with
`if not self._tracing_enabled: return` (`_client/client.py:2017`), as do the other score entry
points; with tracing disabled the client keeps only its REST surface (`langfuse.api`).

The provider question itself is benign: `_init_tracer_provider`
(`_client/resource_manager.py:668`) creates and installs a provider **only** when the global one is
still a `ProxyTracerProvider`; otherwise it reuses whatever is registered. It never installs a
second one. But it then calls `tracer_provider.add_span_processor(langfuse_processor)`
(`resource_manager.py:265`) on that reused provider — so a Langfuse client with tracing enabled
*plus* our own OTLP exporter on the same provider exports every span twice, once through each.

So the shape for phase 1 is one provider and one exporter, and Langfuse's own:

```python
provider = TracerProvider(resource=Resource.create({"service.name": "ledgerline", ...}))
trace.set_tracer_provider(provider)          # before any Langfuse client exists
client = Langfuse(tracer_provider=provider)  # adds its processor to ours; tracing_enabled stays True
```

We do not call Pipecat's `setup_tracing()`: it builds a provider and calls `set_tracer_provider`
itself (`utils/tracing/setup.py:74`), and OTel refuses a second registration with a warning rather
than an error, so whichever ran first wins silently. Building the provider ourselves keeps the
resource attributes and the ordering explicit. Pipecat's spans need nothing else — they come from
`trace.get_tracer("pipecat.turn")`, which resolves to the global provider.

What this buys beyond a raw OTLP exporter: the SDK owns the auth header, the `environment`,
masking and media handling, and `create_score` works. What it costs: our exporter choice is
Langfuse's, so the "Langfuse does not accept gRPC" trap in the HLD stops being ours to fall into.

**Verification owed.** All three answers are read from source, not observed. The phase 1 in-memory
exporter test over one recorded call is where S1 and S2 are proven — span names, types, parents and
the trace id read back the way `aftercall` will read it — and the first live call is where S3's
single export path is confirmed by the absence of duplicate traces in the project.

# 2026-09-13 · What four live calls taught us about Langfuse ingestion

Phase 1's self-audit, in the loop the Langfuse skill asks for: make a call, fetch the trace,
read it against `https://langfuse.com/docs/observability/best-practices` (fetched fresh), fix,
repeat. Four headless calls with `TTS_PROVIDER=deepgram`; every one found something no test had.

## The SDK's default filter drops almost everything we emit

The first call arrived in Langfuse as **32 loose generations and no tree at all**: no
`conversation`, no `turn`, no tool spans, and every generation's parent pointing at an
observation that was never ingested. Nothing in any log said so.

`langfuse._client.span_filter.is_default_export_span` keeps a span only if it came from the
Langfuse SDK's own tracer, carries a `gen_ai.*` attribute, or comes from a scope on the SDK's
list of known LLM instrumentors. Pipecat's `stt`, `llm` and `tts` spans set `gen_ai.*`, so they
survived; `conversation`, `turn` and our tool spans have none of the three and were dropped
before export. The fix is the SDK's documented extension point:

```python
Langfuse(..., should_export_span=should_export_span)   # ours, in observability/tracing.py
```

which is `is_default_export_span(span) or scope.startswith(("pipecat", "ledgerline"))`. Widening
it to *our* scopes and no further keeps unrelated HTTP and database spans out.

## An observer sees a frame once per processor, not once per frame

The third call recorded **four tool calls and produced twenty-four tool observations**, six per
call. `on_push_frame` fires for every hop a frame makes through the pipeline, and
`broadcast_frame` sends the result both ways, so deduplicating only against the spans still open
lets a late in-progress hop — arriving after the result closed the span — open another. The
recorder learned this in September with `_is_new(frame)`; the tool tracer had to learn it again
as "one tool_call_id is one span, ever", including after the span is closed.

## Trace input and output need a span, and that span renames the trace

Pipecat's conversation span is closed before we know how the call ended, and Langfuse 4.15.2 has
no `update_trace` on the client (that was v3) and no `start_as_current_span` either — the first
version of this code called it and the only sign was one warning line in a live call. What works
is a short span of our own, parented to turn 1 (whose context Pipecat keeps for the life of the
observer, spike S2), carrying `langfuse.trace.input` and `langfuse.trace.output`.

Langfuse then marks that span an application root as well, and the trace read from it came back
named `call` with no session and no tags, while the same trace read from the conversation span
was `coach-call` with both. Two roots, two answers. The fix is to repeat the conversation
attributes on the `call` span so the two agree whichever one Langfuse resolves the trace from.

## What the fourth call looks like

One trace: `conversation` -> 4 x `turn` -> 13 `llm` + 6 `stt` + 7 `tts` generations and 5 `TOOL`
spans (exactly the five tool calls in the recording), plus the `call` span. Both roots read
`coach-call`, session `441e8d2391cb`, tags `prompt:v1, tts:deepgram, llm_api:chat, source:voice`.
LLM generations carry the model (`gpt-5.6-luna`), token usage including cached tokens, and a
computed cost. STT and TTS carry no usage and the TTS model reads `unknown` — Pipecat sets no
model attribute on the Deepgram TTS span, which is the known limit the HLD already accepts.

## Attribute names the HLD had wrong

From `langfuse._client.attributes` in 4.15.2: the user and session attributes are **`user.id`**
and **`session.id`**, not `langfuse.user.id` / `langfuse.session.id`. Trace metadata is
`langfuse.trace.metadata.<key>`, as the HLD said. A wrong name here is silent: the span exports
and the field is simply never populated.
