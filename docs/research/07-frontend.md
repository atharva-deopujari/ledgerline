# 07 — Frontend approach: voice + generative cards UI

Researched 2026-09-11 against live docs, npm registry, CDN responses and Pipecat `main` source. Versions verified today: `@daily-co/daily-js` **0.92.2**, `@pipecat-ai/client-js` **1.13.1**, `@pipecat-ai/daily-transport` **1.6.8** (peer: `client-js ~1.13.0`, dep: `daily-js ^0.90.0`), `@pipecat-ai/client-react` **1.8.2** (peer: React >= 18), `pipecat-ai` **1.9.0**.

## Decision summary

- **Pick Option A**: one `frontend/index.html` (+ optional `app.js`, `style.css`), vanilla JS, `daily-js` UMD from a pinned CDN URL, cards rendered from JSON by small template functions. No Node, no build stage, one Docker image (Python).
- **Message protocol**: bot pushes `OutputTransportMessageUrgentFrame(message={type:"cards", seq, cards:[...]})` from any processor; Daily delivers it to the browser as the `app-message` event with `ev.data` = that dict. Send a **full snapshot** every time; the render loop reconciles DOM by `card.id`.
- **Audio**: `Daily.createCallObject({url, token, videoSource:false})` → `join()` → on `track-started` with `type==='audio'` and `!participant.local`, set `audio.srcObject = new MediaStream([track])` and `play()`. Everything is triggered from the Start button click, so autoplay policy is satisfied.
- **RTVI is optional but present anyway**: Pipecat 1.9 `PipelineWorker` auto-adds `RTVIProcessor` + `RTVIObserver` (`enable_rtvi=True` default). The vanilla client just ignores messages with `label:"rtvi-ai"`. If we later want the client SDK, the backend needs zero changes.
- **Transcript**: skip in v1; if wanted, either read the RTVI `user-transcription` / `bot-output` app-messages the observer already emits (free, ~15 lines), or send our own `{type:"transcript"}` message.
- **Serving**: FastAPI mounts `StaticFiles(directory="frontend", html=True)` at `/`; `POST /start` creates a Daily room + token, spawns the bot, returns `{room_url, token}`.

## Comparison

| | A. Vanilla + daily-js CDN | B. Pipecat client-js + daily-transport | C. React/Vite + client-react |
|---|---|---|---|
| Build step | None | None if loaded via `https://cdn.jsdelivr.net/npm/@pipecat-ai/daily-transport@1.6.8/+esm` (verified: bundle has only absolute `/npm/...` imports, so it runs as a browser ES module). Official docs show npm only. | Yes: Node multi-stage in Dockerfile or a second compose service; adds ~1-2 min build, `node_modules`, Vite config, TS. |
| Free from the SDK | Nothing; ~40 lines of glue | `onBotReady`, `onUserTranscript`, `onBotOutput`, `onBotTtsText`, `onServerMessage`, `onTrackStarted`, `onError`, `onDeviceError`, mic enable/mute helpers, `startBotAndConnect({endpoint})` which POSTs and expects `{url, token}` (note: `url`, not `room_url`) | Same as B plus `PipecatClientProvider`, `PipecatClientAudio` (audio element handled for you), `usePipecatConversation` |
| Backend needs | Nothing special. Push `OutputTransportMessageUrgentFrame` or `RTVIServerMessageFrame`. | `RTVIProcessor` in pipeline + `RTVIObserver` on the task. With `PipelineWorker` this is automatic; with legacy `PipelineTask` you add both yourself. Client sends `client-ready`, bot replies `bot-ready`. | Same as B |
| Legibility | Highest: everything readable in one file, editable live without tooling | Medium: SDK abstractions, version coupling (transport pins `client-js ~1.13.0`, its CDN bundle pulls `daily-js 0.90.0`) | Lowest for a 1-day project: JSX, hooks, provider, build config |
| Failure surface | CDN reachability only | CDN + jsDelivr ESM bundler quirks (unofficial path) | Node toolchain, Docker layer cache |

Verdict: A. B's real advantage (transcripts, bot-ready) can be reproduced in A by reading the RTVI app-messages the backend already emits. C only pays off with many interactive components.

## Deep-dive: Option A

### CDN and join

Verified 200 today: `https://unpkg.com/@daily-co/daily-js@0.92.2/dist/daily.js` (also `/dist/daily-esm.js`, and the same paths on `cdn.jsdelivr.net/npm/`). The UMD bundle sets `window.Daily`. **(corrected via context7)** The parenthetical "and legacy `window.DailyIframe`" is dropped: daily-js `test/README.md` documents only "traditional `<script>` tags making `Daily` available on `window`", and doc 02's inspection of the 0.92.2 bundle (`e.Daily = t()`) found `DailyIframe` is *not* set. Use `window.Daily` only. Pin the version; do not use `@latest`.

```html
<script src="https://unpkg.com/@daily-co/daily-js@0.92.2/dist/daily.js"></script>
<button id="start">Start call</button>
<button id="mute" disabled>Mute</button>
<button id="end" disabled>End</button>
<p id="status" role="status" aria-live="polite"></p>
<audio id="bot-audio" autoplay playsinline></audio>
<main id="cards" aria-live="polite"></main>
```

```js
let call = null;

async function start() {
  setStatus('Creating room…');
  const r = await fetch('/start', { method: 'POST' });
  if (!r.ok) return setStatus('Could not start bot: ' + await r.text(), true);
  const { room_url, token } = await r.json();

  call = Daily.createCallObject({ url: room_url, token, videoSource: false, subscribeToTracksAutomatically: true });
  call.on('track-started', onTrack)
      .on('app-message', onAppMessage)
      .on('participant-left', (e) => { if (!e.participant.local) setStatus('Bot left'); })
      .on('camera-error', (e) => setStatus('Microphone error: ' + (e.errorMsg?.errorMsg || 'permission denied'), true))
      .on('error', (e) => setStatus('Call error: ' + e.errorMsg, true))
      .on('left-meeting', cleanup);

  setStatus('Requesting microphone…');           // browser permission prompt appears here
  await call.join();                              // Promise<DailyParticipants>
  setStatus('Connected. Say hello.');
  enable('#mute', '#end');
}

function onTrack({ participant, track, type }) {
  if (type !== 'audio' || participant.local) return;
  const el = document.getElementById('bot-audio');
  el.srcObject = new MediaStream([track]);
  el.play().catch(err => { if (err.name === 'NotAllowedError') setStatus('Click anywhere to enable audio', true); });
}

function toggleMute() {
  const on = call.localAudio();                   // true = mic sending
  call.setLocalAudio(!on);
  document.getElementById('mute').textContent = on ? 'Unmute' : 'Mute';
}

async function end() {
  if (!call) return;
  await call.leave();                             // fires 'left-meeting'
}
function cleanup() {
  call?.destroy();                                // must destroy before creating another call object
  call = null;
  disable('#mute', '#end');
  setStatus('Call ended. Review your plan below.');
}
```

Notes verified in Daily docs: `join()` returns a Promise and is equivalent to waiting for `joined-meeting`; `destroy()` leaves automatically if still joined and "if you attempt to create a new call object without first destroying the old one, the factory method will throw"; `setLocalAudio(false)` keeps the device open for fast unmute (`forceDiscardTrack: true` releases hardware). `track-started` fires when a track becomes `playable`; attaching is `el.srcObject = new MediaStream([track])` (Daily's own snippet uses this pattern for video). Because `start()` runs inside a click handler, the user gesture satisfies autoplay; MDN documents `play()` rejecting with `NotAllowedError` otherwise, hence the catch.

### Receiving cards

Daily `app-message` event object: `{ action:'app-message', data:<your JSON>, fromId:<sender session_id> }`. Limit: 4 KB per message (`sendAppMessage` reference), which is plenty for ~8 cards but means: keep rows short, do not embed prose paragraphs.

Backend side (Pipecat 1.9.0 source, `transports/daily/transport.py`): `DailyOutputTransport.send_message(frame)` calls `self._client.send_app_message(frame.message, participant_id)`; messages queued before join are flushed after join. `OutputTransportMessageUrgentFrame` is a `SystemFrame` (jumps the audio queue, so cards appear during TTS, not after); `OutputTransportMessageFrame` is a `DataFrame` (arrives in order with audio). Use the urgent one for cards.

```python
from pipecat.frames.frames import OutputTransportMessageUrgentFrame

async def push_cards(processor, state):
    await processor.push_frame(OutputTransportMessageUrgentFrame(
        message={"type": "cards", "seq": state.seq, "cards": state.to_cards()}))
```

Alternative: `RTVIServerMessageFrame(data=...)` — the observer wraps it as `{label:"rtvi-ai", type:"server-message", data:...}`. Works with both vanilla (unwrap `data`) and the client SDK (`onServerMessage`). Choose one; the plain frame is one fewer indirection to explain.

Protocol (full snapshot, idempotent):

```json
{ "type": "cards", "seq": 12,
  "cards": [
    { "id": "income",   "kind": "income",   "title": "Income",  "status": "ok",
      "rows": [["Salary (net)", "₹85,000"], ["Freelance", "₹10,000"]] },
    { "id": "missing",  "kind": "missing",  "title": "Still need", "status": "pending",
      "body": "Rent amount, credit-card minimum due" },
    { "id": "shortfall","kind": "shortfall","title": "30-day shortfall", "status": "warn",
      "rows": [["Outflows", "₹1,12,000"], ["Gap", "-₹17,000"]] },
    { "id": "plan",     "kind": "plan",     "title": "Final plan", "status": "final",
      "rows": [["Wk 1", "Pay rent, defer gadget"], ["Wk 2", "Card minimum ₹4,000"]] }
  ] }
```

Why full snapshot: Daily app-messages are "transient signaling, not durable state" with no documented ordering guarantee; a snapshot with a monotonically increasing `seq` makes every message self-sufficient. Client drops `seq <= lastSeq`, so late or duplicate messages are harmless. Diffs would need per-card versioning and a delete op. Card order = array order; the bot decides the order.

Render loop (keyed reconciliation; the CSS transition fires only on cards whose content changed):

```js
let lastSeq = -1;
function onAppMessage({ data }) {
  if (!data || data.type !== 'cards') return;         // ignore rtvi-ai and other traffic
  if (data.seq <= lastSeq) return; lastSeq = data.seq;
  const root = document.getElementById('cards');
  const seen = new Set();
  data.cards.forEach((c, i) => {
    seen.add(c.id);
    let el = root.querySelector(`[data-id="${c.id}"]`);
    const html = renderCard(c);
    if (!el) { el = document.createElement('article'); el.dataset.id = c.id; el.className = 'card enter'; root.appendChild(el); }
    if (el.innerHTML !== html) { el.innerHTML = html; el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash'); }
    el.dataset.status = c.status; el.style.order = i;   // reorder via CSS order, no DOM moves
  });
  root.querySelectorAll('.card').forEach(el => { if (!seen.has(el.dataset.id)) el.remove(); });
}
const esc = s => String(s).replace(/[&<>"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[ch]));
function renderCard(c) {
  const rows = (c.rows || []).map(([k, v]) => `<tr><th scope="row">${esc(k)}</th><td>${esc(v)}</td></tr>`).join('');
  return `<h2>${esc(c.title)}</h2>${c.body ? `<p>${esc(c.body)}</p>` : ''}${rows ? `<table>${rows}</table>` : ''}`;
}
```

Escaping matters: card text is LLM-generated; never inject it as raw HTML.

### Live transcript (optional)

Because `PipelineWorker` auto-attaches `RTVIObserver`, the browser already receives `{label:"rtvi-ai", type:"user-transcription", data:{text, final,...}}` and `{type:"bot-output", data:{text,...}}` app-messages (models.py: `user-transcription`, `bot-output`, `bot-ready`). Reading them in vanilla JS is a second `if` in `onAppMessage`. UNVERIFIED: exact `data` field names for `bot-output` in the 1.9 wire format (observer has both 1.x and 2.0 client paths); log a message and read it before coding. If using the legacy `PipelineTask` without RTVI, send your own `{type:"transcript", role, text}` frame from a small processor that watches `TranscriptionFrame`. No RTVI client SDK is needed either way.

### Serving from FastAPI

```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

app = FastAPI()

@app.post("/start")
async def start():
    room_url, token = await create_room_and_token()   # DailyRESTHelper
    asyncio.create_task(run_bot(room_url, bot_token))
    return {"room_url": room_url, "token": token}

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")  # mount LAST
```

Starlette `StaticFiles(..., html=True)` serves `index.html` for the directory. Mount at `/` after all API routes so `/start` is not shadowed. Same origin, so no CORS. Compose: `ports: ["8000:8000"]`, open `http://localhost:8000`.

### Permissions, HTTPS, errors

- `http://localhost` is a secure context, so `getUserMedia` and WebRTC work without TLS. `http://<LAN-IP>` will not; document that.
- Permission prompt appears at `join()` (Daily acquires the mic). Show "Requesting microphone…" before, and handle `camera-error` (Daily's name for any device error) with a message plus a "Retry" that re-runs `start()`.
- Errors to surface: `/start` non-200 (missing API keys), `error` event (fatal: room expired, bad token), bot never joining (start a 20 s timer after `joined-meeting`; if no remote `participant-joined`, say "Bot did not join, check server logs").
- Autoplay fallback: if `play()` rejects, show a one-tap "Enable audio" button that calls `play()` again.

### Layout and accessibility

No framework. ~40 lines of CSS: `#cards { display:grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap:12px; padding:16px }` stacks to one column below ~560 px. `.card` gets a left border coloured by `[data-status]` (`ok`, `pending`, `warn`, `final`), `.enter` animates opacity/translateY, `.flash` briefly tints the background. Use `<article>` per card, `<h2>` titles, `<table>` with `<th scope="row">` for key/value rows, `aria-live="polite"` on `#cards` and `#status` so screen readers announce updates, real `<button>`s with visible focus, `prefers-reduced-motion` media query disabling transitions, and colour never as the only status signal (add the status word in the title or a small badge).

## Gotchas

- `@pipecat-ai/daily-transport` docs' `/connect` response shape is `{url, token}`; our vanilla endpoint can return `{room_url, token}` but if you ever switch to the SDK, rename to `url`.
- `RTVIProcessor` **consumes** `InputTransportMessageFrame` (client-to-bot app-messages); if the frontend later needs to send data to the bot (e.g. "confirm plan"), use `@transport.event_handler("on_app_message")` on `DailyTransport` rather than a downstream processor. UNVERIFIED whether non-RTVI messages are re-emitted downstream.
- App-message 4 KB cap: truncate rows server-side; do not send the bot's whole narrative in a card. If a snapshot ever outgrows 4 KB, `setMeetingSessionData()` is the 100 KB room-wide escape hatch (~1 update/sec, persists for late joiners) — see doc 02 §3.
- Daily throws if a second `createCallObject()` runs before `destroy()`; the End button must destroy, and a "Start again" path must wait for `left-meeting`.
- `subscribeToTracksAutomatically` defaults to `true`; leave it. Set `videoSource:false` so the browser does not ask for the camera.
- The jsDelivr `+esm` route for client-js is unofficial; it pins a *different* daily-js (0.90.0) than the CDN UMD you would otherwise load. Do not mix both on one page.
- `PipelineWorker` logs an error if you add only one of `RTVIProcessor`/`RTVIObserver` manually; add both or neither.
- Docs vs source: the "Your First Agent" page reads as if RTVI is opt-in, but `worker.py` defaults `enable_rtvi=True`. Trust the source.

## Sources

- npm registry: https://registry.npmjs.org/@daily-co/daily-js/latest (0.92.2), https://www.npmjs.com/package/@pipecat-ai/client-js (1.13.1), https://www.npmjs.com/package/@pipecat-ai/daily-transport (1.6.8), https://www.npmjs.com/package/@pipecat-ai/client-react (1.8.2), https://pypi.org/project/pipecat-ai/ (1.9.0)
- CDN checks: https://unpkg.com/@daily-co/daily-js@0.92.2/dist/daily.js ; https://cdn.jsdelivr.net/npm/@pipecat-ai/daily-transport@1.6.8/+esm
- Daily: https://docs.daily.co/reference/daily-js/factory-methods/create-call-object ; https://docs.daily.co/reference/daily-js/types/daily-call-options ; https://docs.daily.co/reference/daily-js/instance-methods/join ; https://docs.daily.co/reference/daily-js/instance-methods/destroy ; https://docs.daily.co/reference/daily-js/instance-methods/set-local-audio ; https://docs.daily.co/reference/daily-js/instance-methods/send-app-message ; https://docs.daily.co/docs/daily-js/concepts/events ; https://docs.daily.co/docs/daily-js/concepts/tracks ; https://docs.daily.co/docs/daily-js/guides/audio-video ; https://docs.daily.co/docs/daily-react/docs/app-messages
- Pipecat docs: https://docs.pipecat.ai/client/js/introduction ; https://docs.pipecat.ai/api-reference/client/js/callbacks ; https://docs.pipecat.ai/api-reference/client/js/transports/daily ; https://docs.pipecat.ai/client/react/introduction ; https://docs.pipecat.ai/server/frameworks/rtvi/introduction ; https://docs.pipecat.ai/api-reference/server/rtvi/rtvi-processor ; https://docs.pipecat.ai/pipecat/learn/your-first-agent
- Pipecat source (main, 2026-09-11): `src/pipecat/transports/daily/transport.py` (`send_message` → `send_app_message`), `src/pipecat/frames/frames.py` (`OutputTransportMessageFrame`, `OutputTransportMessageUrgentFrame`), `src/pipecat/processors/frameworks/rtvi/{frames,observer,models,processor}.py`, `src/pipecat/pipeline/worker.py` (`enable_rtvi=True`) — https://github.com/pipecat-ai/pipecat
- FastAPI/Starlette: https://fastapi.tiangolo.com/tutorial/static-files/ ; https://github.com/encode/starlette/blob/master/docs/staticfiles.md
- MDN autoplay: https://developer.mozilla.org/en-US/docs/Web/Media/Guides/Autoplay

---

## Context7 cross-check (2026-09-11)

Re-verified against context7 MCP documentation, treated as authoritative and current. Registry/CDN/bundle verification recorded in the body is retained where context7 is silent or version-agnostic.

### Libraries resolved

| Query | Context7 library ID | Notes |
|---|---|---|
| `@daily-co/daily-js` | `/daily-co/daily-js` | 563 snippets, High reputation, benchmark 77.27 |
| `daily.co REST API` / `daily api` | `/websites/daily_co` | 4488 snippets, High, 79.41 — carries the daily-js reference docs too |
| `daily-python` | `/daily-co/daily-python` | 88 snippets, High, 62.72 — thin |
| `pipecat` | `/pipecat-ai/docs` | 6869 snippets, High, 78.01 |
| (alternatives offered, unused) | `/pipecat-ai/pipecat`, `/websites/pipecat_ai`, `/websites/reference-server_pipecat_ai_en`, `/llmstxt/pipecat_ai_llms_txt`, `/daily-co/daily-react`, `/daily-co/react-native-daily-js` | — |

`resolve-library-id` offered **no version-pinned IDs** for any of these, so every context7 answer is "current docs snapshot", not a 0.92.2 / 1.9.0 pin.

### Claims table

| # | Claim | Status | Evidence |
|---|---|---|---|
| 1 | Versions: daily-js 0.92.2, client-js 1.13.1, daily-transport 1.6.8, client-react 1.8.2, pipecat-ai 1.9.0 | NOT COVERED | context7 serves no registry versions. npm/PyPI checks stand. |
| 2 | CDN 200s for `unpkg.com/@daily-co/daily-js@0.92.2/dist/daily.js`, jsDelivr `+esm` for daily-transport | NOT COVERED | context7 does not probe CDNs. Body stands. |
| 3 | UMD sets `window.Daily` **and legacy `window.DailyIframe`** | **CONTRADICTED (in part)** | daily-js `test/README.md`: "traditional `<script>` tags making **`Daily`** available on `window`." No doc asserts a `DailyIframe` global on the current line, and doc 02's 0.92.2 bundle read (`e.Daily = t()`) says it is absent. **Corrected inline: the legacy alias claim is removed.** (context7's API prose still *names the variable* `DailyIframe` in examples — stale prose, the exact trap doc 02 flags.) |
| 4 | `Daily.createCallObject({url, token, videoSource:false, subscribeToTracksAutomatically:true})` | VERIFIED | Option list returned: `url`, `token`, `userName`, `userData` (max 4KB), `startAudioOff`, `startVideoOff`, `audioSource`, `videoSource`, `subscribeToTracksAutomatically` |
| 5 | `subscribeToTracksAutomatically` defaults to `true` | VERIFIED | "Auto-subscribe to all participant tracks (**default: true**)" |
| 6 | `createCallObject` is headless (no UI) | VERIFIED | "Creates a call object for programmatic control **without an iframe UI**." |
| 7 | `join()` returns a Promise, equivalent to `joined-meeting` | NOT COVERED | `join()` reference not returned. Body stands. |
| 8 | `track-started` → `el.srcObject = new MediaStream([track])` for `type==='audio' && !participant.local` | VERIFIED | Official snippet: `el = document.createElement(track.kind === 'video' ? 'video' : 'audio'); … el.srcObject = new MediaStream([track]);` and `call.on('track-started', ({ participant, track, type }) => { if (type === 'video' && !participant.local) …` |
| 9 | `track-started` fires when a track becomes `playable` | VERIFIED (indirect) | "Fires when a participant's media track begins. Use this to attach the track to a media element"; example payload shows `"tracks": { "audio": { "state": "playable", … } }` |
| 10 | `app-message` event object is `{action:'app-message', data, fromId}`; `fromId` = sender `session_id` | VERIFIED | Verbatim example event object plus `call.on('app-message', ({ data, fromId }) => …)` |
| 11 | 4 KB per app-message | VERIFIED | `sendAppMessage`: "A JSON-serializable object. Must be within the **4KB size limit**." |
| 12 | App-messages are transient signalling with no durability/ordering guarantee → full snapshot + `seq` | VERIFIED | "Messages are delivered only to participants currently in the call — they are not stored or replayed for late joiners." No ordering guarantee stated anywhere. Snapshot protocol design is sound. |
| 13 | `destroy()` leaves automatically; a second `createCallObject()` before destroy throws | NOT COVERED | `destroy()` reference not returned. Body stands. |
| 14 | `setLocalAudio(false)` keeps device open; `forceDiscardTrack: true` releases hardware | NOT COVERED | `setLocalAudio` reference not returned. Body stands. |
| 15 | `camera-error` is Daily's name for any device error | VERIFIED | settings-events: `call.on('camera-error', ({ error }) => { if (error?.type === 'permissions') showPermissionsPrompt(error.blockedBy) … })` — note context7 shows the payload as `{ error }` with `error.type` / `error.blockedBy` / `error.msg`, which is more structured than the report's `e.errorMsg?.errorMsg`. Worth logging the real event before shipping the error string. |
| 16 | `error` event exposes `errorMsg` | VERIFIED | quickstart: `.on('error', (event) => console.error('Call error:', event.errorMsg))` |
| 17 | `participant-left` / `participant-joined` carry `event.participant` | VERIFIED | quickstart handlers use `event.participant.session_id` |
| 18 | `OutputTransportMessageUrgentFrame` is a `SystemFrame` that jumps the audio queue; `OutputTransportMessageFrame` is a `DataFrame` in order with audio | VERIFIED | system-frames: "an urgent variant designed to bypass the standard queue for immediate delivery"; `OutputTransportMessageFrame` is documented under **data-frames** ("send transport-specific message payloads through the output transport") |
| 19 | Pipecat `send_message` → `self._client.send_app_message(frame.message, participant_id)`; pre-join messages flushed after join | NOT COVERED | `/daily-co/daily-python` (88 snippets) returned no `send_app_message` entry; Pipecat docs do not expose the internal call. 1.9.0 source reading stands. |
| 20 | `PipelineWorker` auto-adds `RTVIProcessor` + `RTVIObserver`, `enable_rtvi=True` default | VERIFIED | "RTVI is **enabled by default** when creating a PipelineWorker. The system automatically adds RTVIProcessor to the pipeline and registers an RTVIObserver." Opt-out is `PipelineWorker(pipeline, enable_rtvi=False)`. Gotcha "docs read as if RTVI is opt-in; trust the source" is now moot — context7 docs agree with the source. |
| 21 | RTVI traffic is labelled `"rtvi-ai"` and the vanilla client can ignore it | VERIFIED | RTVI message format: `{ "id": string, "label": "rtvi-ai", "type": string, "data": unknown }`; "**label** (string) — Required — Must be set to 'rtvi-ai'." |
| 22 | `RTVIServerMessageFrame(data=…)` → `{label:"rtvi-ai", type:"server-message", data:…}`, client `onServerMessage` | VERIFIED | "`server-message` — An arbitrary message sent from the server to the client … **type**: 'server-message', **data**: any"; "Client-side Handling `pcClient.onServerMessage((message) => { … })`" |
| 23 | Default `on_client_ready` handler replies `bot-ready` | VERIFIED | "The default `on_client_ready` handler also automatically calls `set_bot_ready()`." |
| 24 | `PipelineWorker` errors if only one of processor/observer is added manually | NOT COVERED | Docs show `rtvi_processor=` and `rtvi_observer_params=` as the supported customisation path, which makes the warning plausible but unconfirmed. |
| 25 | RTVI emits `user-transcription` / `bot-output` app-messages; exact `data` field names UNVERIFIED | STILL UNVERIFIED | context7 returned the connection-management message set but not the `bot-output` wire schema. The report's "log a message and read it before coding" advice stands. |
| 26 | `new PipecatClient({ transport: new DailyTransport({ bufferLocalAudioUntilBotReady: true }), enableCam: false, enableMic: true })` | VERIFIED | Returned verbatim, including "`bufferLocalAudioUntilBotReady: true`, // Optional, **defaults to false**" |
| 27 | `startBotAndConnect({endpoint})` expects `{url, token}`, not `{room_url, token}` | VERIFIED | `await pcClient.startBotAndConnect({ endpoint: "/api/start" })`; `pcClient.connect({ url: "https://your-domain.daily.co/room", token: "your-daily-token" })`. ⚠️ Note: Pipecat's own **runner** guide shows a *third* shape, `{dailyRoom, dailyToken, sessionId}` — so the endpoint contract depends on which helper you adopt. |
| 28 | `@pipecat-ai/client-js` is ESM-only (needs a bundler) | NOT COVERED | Docs show only `import { PipecatClient } from "@pipecat-ai/client-js"`, consistent with ESM but not an explicit statement. Body stands. |
| 29 | `onBotReady`, `onUserTranscript`, `onBotOutput`, `onBotTtsText`, `onServerMessage`, `onTrackStarted` callbacks | VERIFIED (partial) | `onServerMessage` confirmed; the constructor takes a `callbacks: {}` block. Individual callback names beyond `onServerMessage` were not enumerated. |
| 30 | `RTVIProcessor` consumes `InputTransportMessageFrame`; use `on_app_message` for client→bot | STILL UNVERIFIED | Not addressed by context7. The report's own UNVERIFIED tag stands. |
| 31 | FastAPI `StaticFiles(directory="frontend", html=True)` mounted at `/` last | NOT COVERED | Out of scope for the libraries resolved here (no FastAPI/Starlette lookup was in the task list). Body stands. |
| 32 | `http://localhost` is a secure context; `http://<LAN-IP>` is not | NOT COVERED | Neither Daily's device-permissions page nor an MDN equivalent was returned. Body stands (MDN-backed). |
| 33 | `MediaStream` escape/XSS hygiene, card render loop, CSS/a11y guidance | N/A | Project-specific design, not a documentable library claim. |

### Corrections applied

1. **Dropped "(and legacy `window.DailyIframe`)"** from the CDN section. This was the one hard contradiction between the two reports; context7's daily-js `test/README.md` and doc 02's bundle inspection both point to `Daily` as the only global. The example code in the report already used `Daily.createCallObject(...)`, so no code changed.
2. **Added the 100 KB `setMeetingSessionData` escape hatch** to the 4 KB gotcha, cross-referencing doc 02 §3 (context7-verified: 100 KB, ~1 update/sec, persists for late joiners).

### Noted but not rewritten

- **`camera-error` payload shape.** The report reads `e.errorMsg?.errorMsg`; context7's settings-events reference destructures `{ error }` with `error.type` (`'permissions'` | `'not-found'`), `error.blockedBy`, and `error.msg`. Both may coexist (Daily has carried a legacy `errorMsg` alongside the structured `error`), so the body is left alone with this flagged — log the real event once before finalising the error copy.
- **Gotcha "Docs vs source: the 'Your First Agent' page reads as if RTVI is opt-in."** context7's current RTVI introduction now states RTVI is enabled by default, so docs and source agree; the gotcha is stale but harmless and is left in place as history.
- **`/connect` response shape.** The report notes `{url, token}` for the SDK path. Context7 confirms that for `connect()`, but Pipecat's runner guide documents `{dailyRoom, dailyToken, sessionId}` — flagged in row 27 rather than changing the body, since the vanilla `{room_url, token}` choice is unaffected.
- **Versions, CDN reachability, and the 1.9.0 source reads** (`send_message` → `send_app_message`, `worker.py` `enable_rtvi=True`, frame base classes) are more specific than context7's version-agnostic docs and are kept as-is.
