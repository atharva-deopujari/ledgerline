# 02 — Daily as the WebRTC transport (server + browser)

Researched 2026-09-11. Verified against live docs and the Pipecat source at tag **v1.9.0** (latest on PyPI, published 2026-09; `requires-python >=3.11`). daily-js latest is **0.92.2** (published 2026-08-19).

---

## Decision summary

- **Use Pipecat `DailyTransport` + `DailyRESTHelper`, not hand-rolled REST.** `DailyRESTHelper` lives at `pipecat.transports.daily.utils` and covers create-room, get-token, delete-room. The module path changed in Pipecat 1.x (was `pipecat.transports.services.helpers.daily_rest` in 0.0.x) — that old path 404s now.
- **⚠️ Pipecat 1.x is a different API from every 0.0.x tutorial you will find.** `vad_analyzer` is **no longer a `TransportParams` field**. It now goes on `LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer())`. `PipelineTask`/`PipelineRunner` are **deprecated since 1.3.0** in favour of `PipelineWorker` + `WorkerRunner`. Budget time for this.
- **Set `transcription_enabled=False`** (it is already the `DailyParams` default) since Deepgram STT runs as a pipeline service, not via Daily's built-in transcription.
- **Send cards over Daily app-message**, via `DailyOutputTransportMessageUrgentFrame` pushed to `transport.output()`. Urgent = out-of-band, delivered immediately; the non-urgent variant queues behind TTS audio. **4 KB hard payload limit** — send card deltas/ids, never a whole plan blob.
- **Skip RTVI** for Ledgerline. `RTVIProcessor` + `RTVIObserver` + `RTVIServerMessageFrame` buys you a typed client protocol and `onServerMessage` on `@pipecat-ai/client-js`, but costs an extra processor, an observer and a client SDK. Raw app-message with a `{type, payload}` envelope is ~20 lines of vanilla JS.
- **Browser: `daily-js` from unpkg, pinned.** In 0.92.x the UMD global is **`window.Daily`**, not `DailyIframe` (the docs' prose is stale here — verified against the bundle).
- **Audio-only in call-object mode means you must attach the bot's audio track to an `<audio>` element yourself.** There is no automatic playback; `createCallObject` renders no UI at all.
- **Free tier: 10,000 free minutes/month.** ⚠️ **(corrected via context7)** The "no credit card required" claim is contradicted by Daily's own docs, which say a card *is* required on the account. Still free for dev + demo. See §5.
- **Docker: outbound-only, no gotchas** — but the egress ranges are wide (UDP 23000–26999 and 40000–49999), not just 443.

---

## 1. Daily REST API

### Create room — `POST https://api.daily.co/v1/rooms`

Auth: `Authorization: Bearer $DAILY_API_KEY`. Body: `{ name?, privacy, properties }`.

Verified properties and their documented defaults (from the OpenAPI spec served at `create-room.md`):

| Property | Default | Notes |
|---|---|---|
| `exp` | — | unix seconds. "Users cannot join a meeting in this room after this time." Does **not** kick people already in. |
| `nbf` | — | not-before unix seconds |
| `eject_at_room_exp` | `false` | ends the meeting at `exp` by kicking everyone |
| `eject_after_elapsed` | — | seconds after *a participant joins* before they are ejected |
| `enable_chat` | `false` | already off; Prebuilt-only anyway |
| `max_participants` | `200` | **(corrected via context7)** Not paid-only. Docs: "The maximum number of participants allowed in a room defaults to 200. Users on paid plans can contact support if they require a limit higher than this default." Setting a *lower* value works on any plan. |
| `start_video_off` | `false` | suppresses camera on a direct `join()` |
| `start_audio_off` | `false` | leave `false` — we want the mic |
| `enable_prejoin_ui` | — | Prebuilt only, irrelevant for call-object mode |
| `geo` | — | see §7 |

Recommended body for a 30-minute finance-planning call:

```jsonc
{
  "privacy": "public",
  "properties": {
    "exp": 1789000000,            // now + 30*60
    "eject_at_room_exp": true,
    "eject_after_elapsed": 1800,
    "enable_chat": false,
    "start_video_off": true,
    "max_participants": 2         // fine on any plan; only raising it >200 needs a paid plan
  }
}
```

Response includes `id`, `name`, `url`, `created_at`, `config`.

### Create meeting token — `POST /v1/meeting-tokens`

Body is `{"properties": {...}}`. Relevant properties: `room_name`, `exp`, `nbf`, `is_owner`, `user_name`, `user_id` (≤36 chars), `eject_at_token_exp`, `eject_after_elapsed`, `start_video_off`, `start_audio_off`, `enable_screenshare`, `permissions`. Response is `{"token": "<jwt>"}`.

Token properties `eject_at_token_exp` and `eject_after_elapsed` **override** the corresponding room properties when both are set (context7, meeting-tokens overview).

Give the **bot** `is_owner: true` (so it can eject / admin if needed) and the **browser user** a non-owner token or no token at all on a public room.

### `DailyRESTHelper` — it exists, use it

`from pipecat.transports.daily.utils import DailyRESTHelper, DailyRoomParams, DailyRoomProperties, DailyMeetingTokenParams, DailyMeetingTokenProperties`

```python
helper = DailyRESTHelper(
    daily_api_key=os.environ["DAILY_API_KEY"],
    daily_api_url="https://api.daily.co/v1",
    aiohttp_session=session,          # aiohttp.ClientSession, required
)

room = await helper.create_room(DailyRoomParams(
    privacy="public",
    properties=DailyRoomProperties(
        exp=time.time() + 1800,
        eject_at_room_exp=True,
        enable_chat=False,
        start_video_off=True,
        max_participants=2,
    ),
))

bot_token = await helper.get_token(
    room.url, expiry_time=30 * 60, eject_at_token_exp=True, owner=True
)
await helper.delete_room_by_url(room.url)   # also delete_room_by_name()
```

`get_token` **overrides** `room_name`, `exp`, `is_owner` and `eject_at_token_exp` on any `params` you pass — those four come from the function arguments regardless.

`DailyRoomProperties` is `ConfigDict(extra="allow")`, so undeclared Daily properties (e.g. `start_audio_off`, `enable_knocking`) can still be passed through and will serialise.

`pipecat.runner.daily.configure(session, ...)` creates room + owner token in one call (2-hour defaults) and returns a `DailyRoomConfig` that tuple-unpacks as `room_url, token`. But it reuses `DAILY_ROOM_URL` from the env if set — for per-session rooms use `DailyRESTHelper` directly.

### Rate limits

Documented at `docs.daily.co/docs/rest-api`:

- Most endpoints incl. `POST /rooms` and `POST /meeting-tokens`: **20 req/s, or 100 requests per 5-second window**
- `DELETE /rooms/:name` and `GET /recordings`: **~2 req/s, or 50 per 30-second window**
- Start recording / livestream / PSTN / SIP: ~1 req/s, 5 per 5s
- Over limit → **HTTP 429**, `error: "rate-limit-error"`; back off exponentially
- ⚠️ context7 note: a 2023 changelog entry caps **`POST /rooms` *and* `DELETE /rooms/:name` at 50 requests per 30 seconds** — i.e. room *creation* may sit in the stricter bucket, not the 20 req/s one. Not a problem at demo scale; do not batch-create rooms.

### Cleanup

Rooms **do not auto-delete**. `exp` only blocks new joins; the room object persists as a "zombie" (expired rooms are excluded from the list-rooms endpoint). Because DELETE is the tightly rate-limited endpoint, the practical strategy is: short `exp` + `eject_at_room_exp: true`, and delete opportunistically in `on_participant_left` rather than in a bulk sweep.

⚠️ **context7 caveat:** a 2023 changelog entry states `DELETE /rooms/:name` "can now only be deleted if it has been expired for more than 24 hours." If that still holds, an immediate post-call delete will fail and cleanup must be a delayed sweep. Verify against a live 400 before relying on eager deletion.

Max-rooms limits: current docs state none. A 2019 Daily blog post cites 5 simultaneously-available rooms on free / 10,000 on paid — **UNVERIFIED / likely stale**, do not design around it, but do delete rooms after calls in case it still applies.

---

## 2. Pipecat `DailyTransport`

```python
from pipecat.transports.daily.transport import DailyParams, DailyTransport

DailyTransport(
    room_url: str,
    token: str | None,
    bot_name: str,
    params: DailyParams | None = None,
    input_name: str | None = None,
    output_name: str | None = None,
)
```

Positional, not keyword-only. `DailyParams` extends `TransportParams`:

```python
DailyParams(
    audio_in_enabled=True,        # TransportParams, default False
    audio_out_enabled=True,       # TransportParams, default False
    transcription_enabled=False,  # DailyParams default — keep off, Deepgram does STT
    camera_out_enabled=False,     # DailyParams default is True; turn off for audio-only
    video_in_enabled=False,       # default
    audio_in_user_tracks=True,    # per-participant audio tracks, default True
)
```

**There is no `vad_analyzer` field on `TransportParams` in 1.9.0.** Confirmed by grepping the v1.9.0 tag of `src/pipecat/transports/base_transport.py`. The current canonical wiring, from `examples/transports/transports-daily.py` at v1.9.0:

```python
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair, LLMUserAggregatorParams,
)

user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
    context,
    user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
)
```

`transport.input()` returns a `DailyInputTransport`, `transport.output()` a `DailyOutputTransport`; both are memoised, so repeated calls are safe. Standard pipeline order: `[transport.input(), user_agg, stt?, llm, tts, transport.output(), assistant_agg]`.

### Event handlers

Registered names (verbatim from `DailyTransport.__init__`): `on_active_speaker_changed`, `on_connected`, `on_joined`, `on_left`, `on_error`, `on_app_message`, `on_call_state_updated`, `on_client_connected`, `on_client_disconnected`, `on_dialin_*`, `on_dialout_*`, `on_dtmf_event`, `on_first_participant_joined`, `on_participant_joined`, `on_participant_left`, `on_participant_updated`, `on_transcription_message`, `on_recording_*`, `on_before_leave` (sync).

Signatures that matter:

- `on_first_participant_joined(transport, participant: dict)` — fires once, from inside `_on_participant_joined`, before `on_participant_joined`. This is where you kick off the greeting.
- `on_participant_left(transport, participant: dict, reason: str)` — takes **three** args.
- `on_client_disconnected(transport, participant: dict)` — an alias fired immediately after `on_participant_left`, with **two** args (no reason). Same for `on_client_connected` ↔ `on_participant_joined`.
- `on_call_state_updated(transport, state: str)`.

### Ending the pipeline when the user leaves

The v1.9.0 example cancels the runner:

```python
@transport.event_handler("on_participant_left")
async def on_participant_left(transport, participant, reason):
    await runner.cancel()
```

Alternatives: `await worker.stop_when_done()` for a graceful drain (lets queued TTS finish), or push an `EndFrame` via `worker.queue_frames([EndFrame()])`. `WorkerRunner` also exposes `end()` and `stop_when_done()`. With `auto_end=True` (default) the runner exits once every root worker finishes. `PipelineWorker` has `on_pipeline_finished` and `on_idle_timeout` handlers, which are a good safety net for a call where the user just closes the tab.

---

## 3. Bot → browser data

### Mechanism

`DailyTransportClient.send_message(frame)` ultimately calls **`daily-python`'s `CallClient.send_app_message(frame.message, participant_id, completion=...)`**. So it is exactly Daily's app-message channel; there is no separate data channel.

Two frame types, and the difference is load-bearing:

```python
from pipecat.transports.daily.transport import (
    DailyOutputTransportMessageFrame,          # queued
    DailyOutputTransportMessageUrgentFrame,    # out-of-band
)
```

In `BaseOutputTransport.process_frame`, `OutputTransportMessageUrgentFrame` is intercepted and sent **immediately** (line ~362). `OutputTransportMessageFrame` falls through to `_handle_frame`, which runs on the media-ordered path — it is delivered **after the audio queued ahead of it** (line ~816). For live-updating cards you almost always want the **Urgent** variant, so a card lands the moment the plan engine recomputes rather than after the bot finishes speaking. Use the non-urgent one only if you deliberately want the card to appear in sync with the narration.

Both carry an optional `participant_id`; leave it `None` to broadcast.

```python
await task_or_processor.push_frame(
    DailyOutputTransportMessageUrgentFrame(
        message={"type": "cards.update", "cards": [...]},
    )
)
```

If the bot is not yet joined, `send_message` buffers the frame into `_join_message_queue` and flushes on join — no silent drop.

### Daily app-message characteristics

- **Size limit: 4 KB** (4,096 bytes), confirmed on `sendAppMessage()` and in the "Custom messages and shared data" comparison table.
- **Ephemeral.** "Messages are not stored and not delivered to the sender. Participants who join after a message is sent will not receive it." No replay for late joiners, no reconnect recovery.
- **Rate limiting: "None"** per the docs table.
- Payload must be JSON-serialisable.
- **Ordering and reliability: UNVERIFIED.** Daily's docs do not state delivery or ordering guarantees anywhere I could find. Treat it as best-effort. → Design the card protocol as **idempotent full-state-per-card with a monotonically increasing `version`**, so a dropped or reordered message self-heals on the next update. Do not send incremental diffs.
- If the 4 KB limit is exceeded, the documented behaviour is **UNVERIFIED**. Guard it in code: `len(json.dumps(msg).encode()) < 4096`, and split across multiple messages with a `seq`/`total` if needed.

Escape hatch if 4 KB or the no-replay behaviour bites: `setMeetingSessionData()` — room-wide, **100 KB**, persists for late joiners, ~1 update/sec, call-object mode only. Good for a plan snapshot a refreshing browser can pick up. (`setUserData()` is the per-participant equivalent: 4 KB, persists, eventually consistent.)

### RTVI as an alternative

Available at `pipecat.processors.frameworks.rtvi` (`processor.py`, `observer.py`, `frames.py`). You add `RTVIProcessor()` to the pipeline and `RTVIObserver()` to the worker's observers. `RTVIServerMessageFrame(data=...)` is a `SystemFrame` that the observer converts to an RTVI `ServerMessage`, which surfaces on the client as **`onServerMessage`** in `@pipecat-ai/client-js`. `RTVIProcessor.send_server_message(data)` does it directly. You also get, for free: bot/user speaking events, transcription events, metrics, and a `client-ready` handshake (with `audio_in_stream_on_start=False` you can gate audio until the browser is actually ready).

Note `RTVIProcessor(transport=...)` is **deprecated since 1.4.0 and ignored** — construct it with no arguments.

**Verdict for Ledgerline: not worth it.** RTVI's value is the bidirectional typed protocol and the client SDK's lifecycle handling. We need one-directional `bot → cards`, we're writing vanilla JS anyway, and RTVI still rides on app-message underneath so it inherits the same 4 KB limit. The `client-ready` gating is the one genuinely nice feature; it can be approximated with a single app-message from the browser that the bot waits for in `on_app_message`.

---

## 4. daily-js in the browser

### Loading

```html
<script src="https://unpkg.com/@daily-co/daily-js@0.92.2/dist/daily.js"></script>
```

jsDelivr works too (`https://cdn.jsdelivr.net/npm/@daily-co/daily-js@0.92.2/dist/daily.js`, verified 200). **Pin the version** — Daily ships breaking changes on a 0.x line.

⚠️ **Global name.** The installation doc's prose says "`DailyIframe` is available as a global on `window`", but its own code sample uses `Daily`, and the 0.92.2 UMD wrapper resolves to `e.Daily = t()`. **`window.Daily` is correct**; `window.DailyIframe` is not set in 0.92.2. Legacy snippets using `DailyIframe.createCallObject()` will throw.

### Audio-only call object

```js
const call = Daily.createCallObject({
  audioSource: true,
  videoSource: false,
  subscribeToTracksAutomatically: true,
});

await call.join({ url: ROOM_URL, token: TOKEN, startVideoOff: true, userName: 'You' });
```

`join()` returns `Promise<DailyParticipants>` resolving with the local participant, equivalent to the `joined-meeting` event. `DailyCallOptions` accepts `url`, `token`, `startVideoOff`, `startAudioOff`, `userName`, `userData`, `audioSource`, `videoSource`, `subscribeToTracksAutomatically`, `inputSettings`, `receiveSettings`, `micAudioMode`.

### Playing the bot's audio

`createCallObject` is headless — "Daily manages WebRTC and media internally but renders no UI". **You must attach the track.** Docs recommend `persistentTrack` over `track` ("a proactive defense against black frames during call disruptions and helps avoid browser bugs related to auto-playing media tracks"), but `track-started` is the recommended attach trigger:

```js
const botAudio = document.getElementById('bot-audio'); // <audio autoplay playsinline></audio>

call.on('track-started', ({ participant, track, type }) => {
  if (type === 'audio' && !participant.local) {
    botAudio.srcObject = new MediaStream([track]);
    botAudio.play().catch(() => {/* needs a user gesture — see gotchas */});
  }
});

call.on('track-stopped', ({ participant, type }) => {
  if (type === 'audio' && !participant?.local) botAudio.srcObject = null;
});
```

`type` is one of `'audio' | 'video' | 'screenAudio' | 'screenVideo'` or a custom track name. The event object is `{ action, callClientId, participant, track, type }` where `track` is a real `MediaStreamTrack`.

### Receiving cards

```js
call.on('app-message', ({ data, fromId }) => {
  if (data.type === 'cards.update') renderCards(data.cards);
});
```

Event shape: `{ action: 'app-message', callClientId, data: any, fromId: string }`. `fromId` is the sender's `session_id`.

### Participants and teardown

`participant-joined` / `participant-left` both emit `{ action, callClientId, participant: DailyParticipant }`; `participant-left` has an optional `reason` that equals `'hidden'` when a participant loses presence rather than truly disconnecting.

```js
await call.leave();    // call object stays reusable; 'left-meeting' also fires on eject/fatal error
await call.destroy();  // frees everything; leaves automatically if still joined; later calls throw
```

`destroy()` alone is enough — it leaves first. Creating a second call object without destroying the first **throws** unless you opt into multi-instance mode.

### Mic permission

The prompt fires on `join()` (or `startCamera()` if you build a pre-join screen). Handle the rejection: a `NotAllowedError` leaves the audio track in state `blocked` with `blocked.byPermissions` set. Reading `participant.tracks.audio.state` gives you `blocked | off | sendable | loading | interrupted | playable` — surface "mic blocked" in the UI from that rather than from the raw promise rejection.

### `@pipecat-ai/client-js` + `@pipecat-ai/daily-transport` — worth it?

Current: `@pipecat-ai/client-js` **1.13.1** (2026-09-04), `@pipecat-ai/daily-transport` **1.6.8** (2026-07-16).

```js
import { PipecatClient } from "@pipecat-ai/client-js";
import { DailyTransport } from "@pipecat-ai/daily-transport";

const pcClient = new PipecatClient({
  transport: new DailyTransport({ bufferLocalAudioUntilBotReady: true }),
  enableCam: false,
  enableMic: true,
});
await pcClient.connect({ url: ROOM_URL, token: TOKEN });
```

**Buys:** automatic audio-element management, `onServerMessage`, bot-speaking/transcript callbacks, `bufferLocalAudioUntilBotReady` (avoids the "first utterance eaten" bug). **Costs:** requires RTVI server-side, is ESM-only so you need a bundler (breaking "vanilla JS + one compose service"), and hides the transport you were asked to demonstrate.

**Recommendation: raw daily-js.** `createCallObject` → `join` → `track-started` → `app-message` shows the transport instead of abstracting it. Replicate `bufferLocalAudioUntilBotReady` manually: browser sends `{type:"client.ready"}` via `sendAppMessage` after join; bot waits for it in `on_app_message` before greeting.

---

## 5. Free tier

- **10,000 free participant-minutes per month**, all accounts (daily.co/pricing/video-sdk).
- **Credit card — CONTRADICTED (corrected via context7).** `docs.daily.co/reference/daily-js` (Getting started → Prerequisites) states: "To use Daily services, you must create an account and add a credit card to your dashboard. While a card is required to enable usage, all accounts receive 10,000 free minutes every month, with charges only applying to usage exceeding that limit." Assume a card is needed; the pricing page's "start free" wording is about cost, not about card-free signup.
- Overage with a card on file: **$0.0040/participant-minute** video, **$0.00099/participant-minute** audio-only. Since we're audio-only, real cost is negligible even past the free tier.
- Metrics/log retention: 1 day without a card, 3 days with.
- **Behaviour when free minutes run out with no card on file is UNVERIFIED** (hard cutoff vs. grace period is not documented).
- **Concurrency on the free/no-card tier is UNVERIFIED.** The pricing page only states "up to 100,000 simultaneous calls or sessions" *with a card on file*. Third-party sources repeating "50 rooms / 20 participants free" are not on any current Daily page — treat as unverified.
- Nothing on the free tier restricts server-side SDK use, so local Docker dev is unaffected. A 30-minute demo call with 2 participants burns 60 participant-minutes.

---

## 6. Local dev / Docker

The bot connects **outbound only** — Daily is the SFU, nothing dials into your container. No port publishing, no host networking, no STUN/TURN of your own. Bridge networking is fine.

Egress requirements (docs.daily.co/guides/privacy-and-security/corporate-firewalls-nats-allowed-ip-list):

- **TCP 443** — signalling/web: `*.daily.co`, `*.dailywebrtc.com`, `*.dailywebrtc.net`, `*.wss.daily.co`, `*-wss.daily.co`, `b.daily.co`, `c.daily.co`, `gs.daily.co`, `prod-ks.pluot.blue`
- **Media to SFUs: UDP 23000–26999, UDP 40000–49999, TCP 40000–49999, TCP 443**
- **STUN:** `stun.cloudflare.com` UDP 3478 and UDP 53
- **TURN:** `turn.cloudflare.com` UDP/TCP 3478, UDP 53, TCP 80, TCP 5349, **TCP/TLS 443**

So **TURN-over-TLS-443 fallback exists** — a container restricted to 443 will still connect, with worse media quality and higher latency. On a corporate network, exempt STUN/TURN from deep packet inspection; a TLS-intercepting proxy breaks WebRTC media.

Docker gotchas in practice:
- Slim base images sometimes lack CA certs, breaking the `api.daily.co` TLS handshake — `ca-certificates` must be installed.
- `daily-python` ships native wheels; build on `python:3.11-slim` (glibc), not Alpine/musl.
- Clock skew inside a long-lived container makes `exp`/`nbf` tokens fail confusingly. Generate tokens server-side from the same container that issues them.

**Browser HTTPS:** `getUserMedia` is secure-context-only, and **`localhost` is exempt**. Daily documents this explicitly: "Pages loaded from `localhost` are allowed to access the camera and microphone… but *not* from any other address or alias for your local machine." So `http://localhost:8000` works; `http://127.0.0.1:8000` and `http://192.168.x.x:8000` do **not** (Chrome treats `127.0.0.1` as potentially-trustworthy in practice, but Daily's doc is explicit about the alias caveat — use `localhost` and don't argue with it).

---

## 7. Latency and region selection

When `geo` is unset, Daily picks a call server via **Amazon Route 53 latency-based DNS resolution, at the moment the first participant joins**. The room is then pinned to that region for the whole session. Daily's own doc calls out the failure mode: "if one person joins in London, and then ten more people join from Cape Town, the call will still be hosted out of `eu-west-2`."

**For a bot call this matters more than usual**, because whichever of {bot container, browser} joins first decides the region. If your bot runs in one region and your user is elsewhere, first-join order silently determines whose latency is good. Pin it explicitly with the `geo` room property.

Selectable regions: `af-south-1` (Cape Town), `ap-northeast-2` (Seoul), `ap-southeast-1` (Singapore), `ap-southeast-2` (Sydney), `ap-south-1` (Mumbai), `eu-central-1` (Frankfurt), `eu-west-2` (London), `sa-east-1` (São Paulo), `us-east-1` (N. Virginia), `us-west-2` (Oregon). Daily runs additional media regions not selectable via `geo` (enterprise, via support).

For India-based dev with US-hosted STT/TTS/LLM, `ap-south-1` (Mumbai) minimises the mic→SFU→bot leg; the bot→Deepgram/OpenAI/Cartesia legs dominate total latency regardless. **Numeric per-region RTT figures: UNVERIFIED** — Daily publishes no latency table.

---

## Gotchas

1. **Pipecat 1.x ≠ 0.0.x.** `vad_analyzer` moved off `TransportParams` onto `LLMUserAggregatorParams`. `PipelineTask`/`PipelineRunner` deprecated since 1.3.0 → `PipelineWorker` + `WorkerRunner`. `LLMContext` + `LLMContextAggregatorPair` replaced `OpenAILLMContext`. Almost every blog post and LLM-generated snippet you'll find is 0.0.x.
2. **`DailyRESTHelper` import path changed** to `pipecat.transports.daily.utils`. The old `pipecat.transports.services.helpers.daily_rest` 404s.
3. **`window.Daily`, not `window.DailyIframe`** in daily-js 0.92.x (docs prose is stale; verified against the bundle).
4. **4 KB app-message limit, silent failure mode.** Guard the size in code; design cards as versioned full-state, not diffs.
5. **No ordering/reliability guarantee is documented** for app-message. Do not build a state machine that assumes exactly-once in-order delivery.
6. **Urgent vs non-urgent transport message frames.** `DailyOutputTransportMessageFrame` is queued behind TTS audio. If your cards appear seconds late, this is why — use the Urgent variant.
7. ~~**`max_participants` is flagged `x-paidPlan: paid`.**~~ **(corrected via context7)** `max_participants` is settable on any plan; only raising the ceiling *above* the 200 default requires a paid plan plus a support request. `max_participants: 2` is safe.
8. **Audio does not play itself.** Call-object mode attaches nothing; and `audioEl.play()` can be blocked by autoplay policy until a user gesture — put the "Start call" button *before* `join()` so the gesture is already banked.
9. **`on_participant_left` takes 3 args, `on_client_disconnected` takes 2.** Both fire, in that order, for the same departure. Registering cleanup on both double-fires the teardown.
10. **Rooms never auto-delete.** `exp` only blocks joins. DELETE is rate-limited to ~2 req/s, so clean up per-call, not in bulk.
11. **`localhost` only** for mic without HTTPS; `127.0.0.1` / LAN IP are not guaranteed.
12. **`daily-python` needs glibc** — no Alpine.

---

## Sources

- Daily create room — https://docs.daily.co/reference/rest-api/rooms/create-room (and `.md` OpenAPI variant)
- Daily create meeting token — https://docs.daily.co/reference/rest-api/meeting-tokens/create-meeting-token
- Daily delete room — https://docs.daily.co/reference/rest-api/rooms/delete-room
- Daily REST API rate limits — https://docs.daily.co/docs/rest-api
- Daily pricing (free tier, overage) — https://www.daily.co/pricing/video-sdk/
- Custom messages & shared data (4 KB / 100 KB table) — https://docs.daily.co/docs/daily-js/guides/custom-messages
- `sendAppMessage()` — https://docs.daily.co/reference/daily-js/instance-methods/send-app-message
- Messaging events (`app-message` shape) — https://docs.daily.co/reference/daily-js/events/messaging-events
- Media events (`track-started` shape) — https://docs.daily.co/reference/daily-js/events/media-events
- Participant events — https://docs.daily.co/reference/daily-js/events/participant-events
- Tracks & media concepts — https://docs.daily.co/docs/daily-js/concepts/tracks
- Audio & video controls — https://docs.daily.co/docs/daily-js/guides/audio-video
- `Daily.createCallObject()` — https://docs.daily.co/reference/daily-js/factory-methods/create-call-object
- `join()` — https://docs.daily.co/reference/daily-js/instance-methods/join
- `leave()` — https://docs.daily.co/reference/daily-js/instance-methods/leave
- `destroy()` — https://docs.daily.co/reference/daily-js/instance-methods/destroy
- daily-js installation / CDN — https://docs.daily.co/docs/daily-js/installation
- `DailyCallOptions` — https://docs.daily.co/reference/daily-js/types/daily-call-options
- Firewalls / allowed IPs / ports — https://docs.daily.co/guides/privacy-and-security/corporate-firewalls-nats-allowed-ip-list
- Device permissions — https://docs.daily.co/docs/daily-js/guides/device-permissions
- localhost getUserMedia exemption — https://www.daily.co/blog/setting-up-a-local-webrtc-development-environment/
- MDN getUserMedia (secure context) — https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia
- Pipecat `DailyTransport` source — https://github.com/pipecat-ai/pipecat/blob/v1.9.0/src/pipecat/transports/daily/transport.py
- Pipecat `DailyRESTHelper` source — https://github.com/pipecat-ai/pipecat/blob/v1.9.0/src/pipecat/transports/daily/utils.py
- Pipecat `TransportParams` / `BaseOutputTransport` — https://github.com/pipecat-ai/pipecat/blob/v1.9.0/src/pipecat/transports/base_transport.py , `.../base_output.py`
- Pipecat Daily example — https://github.com/pipecat-ai/pipecat/blob/v1.9.0/examples/transports/transports-daily.py
- Pipecat `runner.daily.configure` — https://github.com/pipecat-ai/pipecat/blob/v1.9.0/src/pipecat/runner/daily.py
- Pipecat RTVI — https://github.com/pipecat-ai/pipecat/tree/v1.9.0/src/pipecat/processors/frameworks/rtvi , https://reference-server.pipecat.ai/en/stable/api/pipecat.processors.frameworks.rtvi.html
- Pipecat JS Daily transport — https://docs.pipecat.ai/client/js/transports/daily
- npm versions — https://registry.npmjs.org/@daily-co/daily-js , /@pipecat-ai/client-js , /@pipecat-ai/daily-transport ; https://pypi.org/pypi/pipecat-ai/json

---

## Context7 cross-check (2026-09-11)

Re-verified against context7 MCP documentation, which the user treats as authoritative and current. Direct source/bundle verification recorded in the body above is retained where it is more specific than context7; disagreements are noted per row.

### Libraries resolved

| Query | Context7 library ID | Notes |
|---|---|---|
| `daily.co REST API` / `daily api` | `/websites/daily_co` | 4488 snippets, High reputation, benchmark 79.41. Primary source for REST + daily-js reference docs. |
| `@daily-co/daily-js` | `/daily-co/daily-js` | 563 snippets, High, 77.27. Repo-side autodocs + `test/README.md`. |
| `daily-python` | `/daily-co/daily-python` | 88 snippets, High, 62.72. Thin coverage. |
| `pipecat` | `/pipecat-ai/docs` | 6869 snippets, High, 78.01. Used for DailyTransport / RTVI / migration-1.0. |
| (alt, unused) | `/pipecat-ai/pipecat`, `/websites/pipecat_ai`, `/websites/reference-server_pipecat_ai_en`, `/llmstxt/pipecat_ai_llms_txt` | — |

No version-pinned variants were offered by `resolve-library-id` for any of these; context7 serves the current docs snapshot only. **Package versions (daily-js 0.92.2, pipecat-ai 1.9.0, client-js 1.13.1) are NOT COVERED by context7** — they came from the npm/PyPI registries and stand.

### Claims table

| # | Claim | Status | Evidence |
|---|---|---|---|
| 1 | `POST https://api.daily.co/v1/rooms`, Bearer auth, `{name?, privacy, properties}` | VERIFIED | "## POST /rooms … Creates a new Daily room"; OpenAPI `servers: https://api.daily.co/v1`, `bearerAuth` |
| 2 | `exp` = unix seconds, blocks joins after that time | VERIFIED | "exp (integer) — Unix timestamp indicating when the room expires. Participants cannot join after this time." |
| 3 | `nbf` = not-before | VERIFIED | "nbf … Participants cannot join before this time." |
| 4 | `eject_at_room_exp` ends the meeting at `exp` | VERIFIED | `will_eject_at` "indicates the timestamp when a participant will be ejected if the token or room has an expiration configured with `eject_at_token_exp` or `eject_at_room_exp` set to `true`" |
| 5 | `eject_after_elapsed` = seconds after a participant joins | VERIFIED | "`eject_after_elapsed` sets a maximum duration in seconds after joining" |
| 6 | `max_participants` default `200` | VERIFIED | "The maximum number of participants allowed in a room defaults to 200." |
| 7 | `max_participants` is paid-plan-only (`x-paidPlan: paid`), may 400 on free | **CONTRADICTED** | Same doc: paid plans "can contact support if they require a limit **higher** than this default." Paid-ness gates raising the ceiling, not setting the property. **Corrected inline.** |
| 8 | `POST /v1/meeting-tokens`, body `{"properties": {...}}`, response `{"token": "<jwt>"}` | VERIFIED | cURL example posts `'{"properties":{"room_name":…,"exp":…}}'`; `create_token` returns `token["token"]` |
| 9 | Token `eject_*` override room `eject_*` | VERIFIED (new) | "These token properties override corresponding room properties (`eject_at_room_exp` and `eject_after_elapsed`) if set." **Added inline.** |
| 10 | `DailyRESTHelper` at `pipecat.transports.daily.utils` | VERIFIED | `from pipecat.transports.daily.utils import DailyRoomParams, DailyRoomProperties` |
| 11 | `DailyRESTHelper(daily_api_key=…, aiohttp_session=…)`; `delete_room_by_url()` | VERIFIED | `helper = DailyRESTHelper(daily_api_key=…, aiohttp_session=session)`; `await helper.delete_room_by_url(…)` |
| 12 | `get_token` overrides `room_name`/`exp`/`is_owner`/`eject_at_token_exp` | NOT COVERED | Source-verified in body; context7 has no per-argument detail. Body stands. |
| 13 | Rate limit: most endpoints 20 req/s | VERIFIED | "Most endpoints allow 20 requests per second" |
| 14 | `POST /rooms` in the 20 req/s bucket (100 per 5 s) | **CONTRADICTED (partial)** | 2023 changelog: "capping POST /rooms and DELETE /rooms/:name at **50 requests per 30 seconds**." Room creation may be in the stricter bucket. **Caveat added inline.** |
| 15 | `DELETE /rooms/:name` ~2 req/s, 50 per 30 s | VERIFIED | "specific resource-intensive endpoints … stricter limits of 2 or 1 requests per second"; changelog 50/30 s |
| 16 | Over limit → 429, `error: "rate-limit-error"` | VERIFIED | "`429` Too Many Requests — rate limit exceeded"; "`rate-limit-error` — Too many requests in too short a window" |
| 17 | Rooms never auto-delete; delete opportunistically per call | NOT COVERED / **CAVEAT** | 2023 changelog: a room "can now only be deleted if it has been expired for more than 24 hours." If current, eager per-call deletion fails. **Caveat added inline.** |
| 18 | `DailyTransport(room_url, token, bot_name, params=…)` positional | VERIFIED | `DailyTransport(room_url, token, "Bot", params=DailyParams(...))` |
| 19 | `DailyParams` fields `audio_in_enabled`, `audio_out_enabled`, `transcription_enabled` | VERIFIED | `DailyParams(audio_in_enabled=True, audio_out_enabled=True, transcription_enabled=True, transcription_settings=…)` |
| 20 | `transcription_enabled=False` is the `DailyParams` default | NOT COVERED | Docs show it being switched on explicitly, never state the default. Source-verified value stands. |
| 21 | `camera_out_enabled` / `video_in_enabled` / `audio_in_user_tracks` defaults | NOT COVERED | context7 shows `video_out_enabled`, not `camera_out_enabled`, in the 1.x param example — worth re-grepping the tag before relying on the field name. |
| 22 | No `vad_analyzer` on `TransportParams` in 1.x; it moves to `LLMUserAggregatorParams` | VERIFIED | migration-1.0: "VAD is now configured on the aggregator"; `LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer())`; param list carries `vad_analyzer (VADAnalyzer)` |
| 23 | (new) Leftover 0.0.x params are silently dropped | VERIFIED (new) | "Removed parameters in TransportParams and PipelineParams are **silently ignored** … leftover 0.0.x parameters will be dropped without warning" — strengthens Gotcha 1. |
| 24 | Event handler name list | VERIFIED | context7's DailyTransport event list matches the report's names 1:1, including `on_before_leave` (sync), `on_dtmf_event`, `on_client_connected/disconnected`, all `on_dialin_*`/`on_dialout_*`/`on_recording_*`. |
| 25 | Handler arities (`on_participant_left` 3 args, `on_client_disconnected` 2) | NOT COVERED | Docs only give "first parameter is the emitting object, subsequent parameters vary by event type." Source-verified body stands. |
| 26 | `send_message` → daily-python `CallClient.send_app_message(...)` | NOT COVERED | `/daily-co/daily-python` coverage is thin (88 snippets) and returned no `send_app_message` entry. Body stands (source-verified). |
| 27 | Urgent frame is out-of-band / immediate; non-urgent queues behind audio | VERIFIED | "an urgent variant designed to bypass the standard queue for immediate delivery"; `OutputTransportMessageFrame` documented under **data-frames**, urgent under **system-frames** |
| 28 | app-message **4 KB** limit | VERIFIED | "data (object) — Required — A JSON-serializable object. Must be within the **4KB size limit**." |
| 29 | Ephemeral; not delivered to sender; no replay for late joiners | VERIFIED | "Messages are delivered only to participants currently in the call — they are not stored or replayed for late joiners. Broadcast messages are not delivered to the sender." |
| 30 | `setMeetingSessionData` **100 KB**, room-wide, ~1 update/sec | VERIFIED | "max payload size of 100KB"; comparison table: "setMeetingSessionData supports a larger 100KB limit, persists for late joiners, and is limited to approximately one update per second." |
| 31 | `setUserData` 4 KB, per-participant, persists | VERIFIED | "Any JSON-serializable value with a max payload size of 4KB." |
| 32 | app-message rate limiting: "None" | NOT COVERED | Comparison table returned by context7 does not restate a rate-limit column for `sendAppMessage`. |
| 33 | app-message ordering/reliability undocumented | VERIFIED (by absence) | No ordering or delivery guarantee appears anywhere in the returned reference. Versioned-full-state design stands. |
| 34 | RTVI at `pipecat.processors.frameworks.rtvi`; `RTVIServerMessageFrame(data=…)` → client `onServerMessage` | VERIFIED | "`RTVIServerMessageFrame` … This frame is a `SystemFrame` and is delivered via the high-priority lane"; "Client-side Handling `pcClient.onServerMessage(...)`" |
| 35 | `client-ready` handshake exists | VERIFIED | "`client-ready` and `bot-ready` messages exchange versioning and metadata"; `@rtvi.event_handler("on_client_ready")` → `await rtvi.set_bot_ready()` |
| 36 | `RTVIProcessor(transport=…)` deprecated since 1.4.0 | NOT COVERED | context7 shows `RTVIProcessor()` constructed with no args everywhere, consistent with the report. |
| 37 | RTVI rides on app-message, inherits 4 KB | NOT COVERED | Not stated; plausible but unconfirmed. |
| 38 | daily-js UMD global is `window.Daily`, not `window.DailyIframe` | VERIFIED | daily-js `test/README.md`: "Loading the library via a traditional `<script>` tag makes the **`Daily` class accessible through the `window` variable**." No doc asserts `window.DailyIframe` on the current line. (context7's prose examples still *name* the variable `DailyIframe`, which is exactly the stale-prose trap the report flags.) |
| 39 | `Daily.createCallObject({...})` options incl. `subscribeToTracksAutomatically` (default `true`) | VERIFIED | "subscribeToTracksAutomatically (boolean) — Optional — Auto-subscribe to all participant tracks (**default: true**)"; also `url`, `token`, `userName`, `userData` (max 4KB), `startAudioOff`, `startVideoOff`, `audioSource`, `videoSource` |
| 40 | `join()` returns `Promise<DailyParticipants>` | NOT COVERED | Not in the returned reference. Body stands. |
| 41 | `createCallObject` is headless / renders no UI | VERIFIED | "Creates a call object for programmatic control **without an iframe UI**. Useful for custom UI implementations." |
| 42 | `track-started` attach pattern + payload `{action, callClientId, participant, track, type}` | VERIFIED | Full payload example returned; "type (string) — One of `'audio'`, `'video'`, `'screenAudio'`, `'screenVideo'`, or a custom track name"; official snippet uses `el.srcObject = new MediaStream([track])` |
| 43 | `app-message` payload shape `{action, callClientId, data, fromId}`, `fromId` = sender session_id | VERIFIED | Example event object returned verbatim; `call.on('app-message', ({ data, fromId }) => …)` |
| 44 | `leave()` reusable / `destroy()` frees and leaves first / second `createCallObject` throws | NOT COVERED | Method references not returned. Body stands. |
| 45 | Mic-blocked track states (`blocked`, `blocked.byPermissions`) | NOT COVERED (partially corroborated) | `camera-error` handler documents `error.type === 'permissions'` and `error.blockedBy`; the `participant.tracks.audio.state` enum was not returned, though `"state": "playable"` appears in the track-started example. |
| 46 | Free tier: 10,000 free minutes/month | VERIFIED (wording) | "all accounts receive 10,000 free minutes every month, with charges only applying to usage exceeding that limit." Docs say "minutes", not "participant-minutes". |
| 47 | **No credit card required** to sign up | **CONTRADICTED** | "To use Daily services, you must create an account and **add a credit card** to your dashboard. While a card is required to enable usage…" **Corrected inline (§5 and Decision summary).** |
| 48 | Overage $0.0040 / $0.00099 per participant-minute | NOT COVERED | Pricing page only; context7 carries no price table. |
| 49 | Egress UDP **23000–26999** and **40000–49999** to SFU IPs | VERIFIED | "adds direct UDP access to SFU IPs on ports **23000-26999 and 40000-49999**" |
| 50 | STUN/TURN via Cloudflare; TURN-over-TLS-443 fallback | VERIFIED (partial) | "it is recommended to allow traffic to **Cloudflare and Twilio** STUN/TURN services"; TURN-over-443 corroborated by the `iceConfig` example (`turns:…:443?transport=tcp`). Report omits Twilio — minor gap, not an error. |
| 51 | `proxyUrl` / custom ICE need the Advanced Firewall Control add-on | VERIFIED (new) | "Requires the Advanced Firewall Control add-on." Relevant if a corporate-network fallback is ever needed. |
| 52 | `localhost` is a secure context for `getUserMedia`; `127.0.0.1` is not exempt per Daily | NOT COVERED | Neither the Daily blog claim nor a device-permissions page was returned. Body stands (MDN-backed). |
| 53 | `geo` region list and Route 53 latency-based selection | NOT COVERED | Not returned by context7. Body stands. |

### Corrections applied

1. **`max_participants` is not paid-plan-gated** (§1 table, §1 JSON comment, Gotcha 7). Context7: the 200 default is universal; paid plans only matter for raising the ceiling *above* 200. The "may be rejected on a free account" warning was wrong and is struck.
2. **"No credit card required" removed** (Decision summary, §5). Context7's `reference/daily-js` prerequisites explicitly require a card on the account; the 10,000 free minutes are a usage allowance, not a card-free tier.
3. **Rate-limit caveat added** (§1 Rate limits): a 2023 changelog puts `POST /rooms` alongside `DELETE /rooms/:name` at 50 req / 30 s, which conflicts with the report's placement of `POST /rooms` to the general 20 req/s bucket.
4. **Room-deletion caveat added** (§1 Cleanup): a 2023 changelog states a room can only be deleted once it has been expired for >24 h — this would break the recommended "delete in `on_participant_left`" strategy. Flagged as needing a live check rather than rewritten, since the current REST reference does not repeat it.
5. **Token-vs-room `eject_*` precedence added** (§1 meeting tokens): token `eject_at_token_exp` / `eject_after_elapsed` override the room-level equivalents.

### Where the report's own verification is kept over context7

- **daily-js UMD global (§4, Gotcha 3).** Context7's daily-js API prose still writes `DailyIframe.createCallObject(...)`, but its `test/README.md` documents `Daily` as the `window` global. The report's direct 0.92.2 bundle inspection (`e.Daily = t()`) is the more current and more specific evidence; body unchanged.
- **Pipecat 1.9.0 tag details** — `get_token` argument overrides, `ConfigDict(extra="allow")` on `DailyRoomProperties`, handler arities, `DailyTransportClient.send_message` → `CallClient.send_app_message`, `camera_out_enabled` naming, `transcription_enabled` default. Context7's Pipecat docs are version-agnostic and thinner than the tagged source; the source reading stands.
- **Package versions** (daily-js 0.92.2, pipecat-ai 1.9.0, `@pipecat-ai/client-js` 1.13.1, `@pipecat-ai/daily-transport` 1.6.8). Context7 does not carry registry versions; the npm/PyPI checks stand.
