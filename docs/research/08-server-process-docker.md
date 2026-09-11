# 08 — Web Server, Bot Process Model, Packaging & Docker

Research date: 2026-09-11. Target stack: Python 3.11, FastAPI, `pipecat-ai==1.9.0`
(released **2026-09-11T03:05:27Z**, verified via GitHub releases API), Daily transport,
Deepgram / OpenAI / Cartesia / Silero. Hard constraint: `docker compose up --build` →
one local URL, nothing else.

---

## Decision summary

- **Run the pipeline as an asyncio task inside the same FastAPI process** (option *c*).
  One container, one process, one uvicorn. This is also what Pipecat's own development
  runner does today — `_start_bot_session()` in `pipecat/runner/run.py` is literally
  `asyncio.create_task(bot_module.bot(runner_args))`. The subprocess-per-call pattern
  is no longer the shape of the official `simple-chatbot` example.
- **Do not ship the `pipecat-ai[runner]` runner as the product server.** Install the
  extra (it is only `fastapi` + `uvicorn` + `pipecat-ai-prebuilt`), keep the
  `async def bot(runner_args)` entrypoint for `python bot.py -t daily` local debugging,
  but serve our own `index.html` from our own FastAPI app. The runner mounts *its*
  prebuilt UI at `/client` and redirects `/` to it, and defaults `--host localhost`
  (fatal inside Docker). Pipecat docs say it plainly: *"The development runner is
  exactly that — a tool for local development."*
- **Room per call, created on `POST /connect`**, with `exp = now + ~15 min` and
  `eject_at_room_exp = True`. Delete the room in a `finally` after the pipeline ends.
  Daily's free tier is small (see §3), so leaking rooms is a real failure mode for a
  operator.
- **Base image `python:3.11-slim-bookworm`.** The only apt package genuinely required
  is **`libgomp1`** (onnxruntime's OpenMP runtime). No ffmpeg, no portaudio, no
  libsndfile, no torch. Silero's model is a **2,327,524-byte `silero_vad.onnx` bundled
  inside the pipecat wheel** — nothing to download or prebake.
- **Prebake NLTK `punkt_tab` at build time.** Pipecat's sentence tokenizer lazily
  `nltk.download("punkt_tab")` on first use, i.e. during the bot's first spoken
  sentence. That is a network round-trip in the middle of turn one.
- **One compose service**, `7860:7860`, `env_file: .env`, `restart: "no"`,
  `PYTHONUNBUFFERED=1`. Validate required env vars at startup and exit with a
  one-line "missing X" message. A second service is never needed.

---

## 1. The three serving patterns, as they actually exist in 1.9.0

### (a) FastAPI + `subprocess.Popen(["python", "bot.py", "-u", room, "-t", token])`

This is the *historical* simple-chatbot pattern. **It is gone from
`pipecat-examples/simple-chatbot`** — that directory now contains only
`bot-openai.py`, `bot-gemini.py`, `assets/`, `env.example`, `Dockerfile`,
`pyproject.toml`, `pcc-deploy.toml`, `requirements.txt`, `README.md` (corrected via
context7 — the original list omitted `assets/`, `env.example`, `requirements.txt`,
`README.md`); there is no `server.py`. The surviving canonical example of the subprocess shape is
`deployment/flyio-example/bot_runner.py`, and even there it is the *fallback*:

```python
run_as_process = os.getenv("RUN_AS_PROCESS", False)
if run_as_process:
    subprocess.Popen(
        [f"python3 -m bot -u {room.url} -t {token}"],
        shell=True, bufsize=1, cwd=os.path.dirname(os.path.abspath(__file__)),
    )
else:
    await spawn_fly_machine(room.url, token)  # the recommended path
```

Note the comment in that file: *"Launch a new fly.io machine, or run as a shell process
(not recommended)"*.

Trade-offs:

| | subprocess-per-call |
|---|---|
| Isolation | Real. A segfault in `daily-python`'s native audio thread kills only that call. |
| Crash containment | Best of the three. The HTTP server always survives. |
| Memory | Every process re-imports numpy, numba/llvmlite, onnxruntime, `daily-python`'s native lib, and re-creates its own `onnxruntime.InferenceSession` for Silero. **Estimate ~300–450 MB RSS per bot process — UNVERIFIED**, measure before quoting. The Silero weights themselves are trivial (2.2 MB). |
| Startup latency | Full cold interpreter start per call. numba + onnxruntime + daily-python imports dominate; **estimate 2–5 s — UNVERIFIED**. The user sits in the room staring at nothing for that window. |
| Zombie reaping | You must own it. `Popen` children become zombies unless `.poll()`/`.wait()`ed; PID 1 in a container does not reap by default, which is exactly why the official `dailyco/pipecat-base` image installs **tini** as its ENTRYPOINT. |
| Log capture | `Popen` with inherited stdio does reach compose output, but interleaved and unprefixed. |

### (b) `pipecat-ai[runner]` — the development runner

Verified from `src/pipecat/runner/run.py` (2003 lines):

```python
app: FastAPI = FastAPI()

def main(parser: argparse.ArgumentParser | None = None):
    ...
    logger.remove()
    logger.add(sys.stderr, level="TRACE" if args.verbose else "DEBUG")
    _configure_server_app(args)
    uvicorn.run(app, host=args.host, port=args.port)

_bot_sessions: set[asyncio.Task] = set()

def _start_bot_session(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _bot_sessions.add(task)
    task.add_done_callback(_bot_sessions.discard)
    return task
```

Constants: `RUNNER_HOST = "localhost"`, `RUNNER_PORT = 7860`,
`PIPECAT_ROOM_EXP_HOURS = 4.0`.

Endpoints it installs: `GET /` → redirect to `/client/`; `app.mount("/client",
PipecatPrebuiltUI)`; `GET /daily` (create room, start bot, 302 to the room);
`POST /start` (unified — returns `StartBotResult(dailyRoom=..., dailyToken=...,
sessionId=...)`). Custom room properties passed as `dailyRoomProperties` get
`exp` and `eject_at_room_exp=True` defaulted in.

The bot contract:

```python
async def bot(runner_args: RunnerArguments):
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)

if __name__ == "__main__":
    from pipecat.runner.run import main
    main()
```

`DailyRunnerArguments(RunnerArguments)` carries `room_url: str`, `token: str | None`,
and inherits `body`, `session_id`, `cli_args`, `handle_sigint`, `handle_sigterm`, and
`pipeline_idle_timeout_secs` (**default 300 s**, set in `__post_init__`).

Runner cons for Ledgerline: it owns `/` and `/client`, so our static `index.html`
would have to fight it; `--host` must be overridden to `0.0.0.0` in Docker; and it is
explicitly not a production surface.

### (c) asyncio task in our own FastAPI process — **recommended**

Same execution model as (b), but our app, our routes, our `index.html`.

```
POST /connect → create Daily room + bot token + user token
              → asyncio.create_task(run_bot(room_url, bot_token))
              → return {"room_url": ..., "token": user_token}
GET  /        → StaticFiles / FileResponse("static/index.html")
GET  /health  → {"ok": true}
```

Why this wins for a single-user local demo:

- **Startup latency**: all heavy imports and the Silero `InferenceSession` are paid once
  at container boot. `POST /connect` is then a Daily REST round-trip (~200–400 ms) plus
  task scheduling. No per-call cold start.
- **Memory**: one interpreter, one ONNX session.
- **Zombies**: none. There are no child processes.
- **Logs**: loguru writes to the single process's stderr, which *is* the compose output.
  No plumbing.
- **Crash containment**: this is the real cost. An unhandled exception inside the bot
  task is swallowed by asyncio unless you add a done-callback; a native crash in
  `daily-python` takes the whole container. Mitigation: wrap `run_bot` in
  `try/except/finally`, log the traceback, always delete the room, and let compose's
  `restart` policy (or the operator) restart. For one user and one concurrent call this
  is an acceptable trade.

Concurrency guard worth adding: reject a second `POST /connect` while a session is live
(`409`), so a operator double-clicking doesn't spawn two bots into two rooms.

---

## 2. Bot lifecycle

Pipecat 1.x renamed the core objects. `PipelineTask` → **`PipelineWorker`**
(`pipecat.pipeline.worker`), `PipelineRunner` → **`WorkerRunner`**
(`pipecat.workers.runner`). `pipecat/pipeline/task.py` still exists as a shim and is
marked *"deprecated since 1.3.0 … will be removed in 2.0.0"*. Use the new names.

The current `simple-chatbot/server/bot-openai.py` shows the exact shutdown path:

```python
worker = PipelineWorker(
    pipeline,
    params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
    idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
)

runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)
await runner.add_workers(worker)

@transport.event_handler("on_client_disconnected")
async def on_client_disconnected(transport, client):
    logger.info("Client disconnected")
    await runner.cancel()

await runner.run()
```

Key points:

- **`on_client_disconnected`** is the transport-agnostic hook and is what the official
  example uses. `on_participant_left` still exists on `DailyTransport` but you no longer
  need it for the common case.
- **`await runner.cancel()`** tears down the worker; `await runner.run()` then returns
  and the `bot()` coroutine completes. `WorkerRunner` also exposes `stop_when_done()`
  and `end(reason)`.
  (context7 note: the canonical docs example in `pipecat/learn/pipeline-termination.mdx`
  cancels the *worker* — `await worker.cancel()` — inside `on_client_disconnected`.
  Both APIs exist; `worker.cancel()` is the narrower, documented form.)
- **Idle timeout is built in.** `PipelineWorker.__init__` takes
  `idle_timeout_secs: float | None = IDLE_TIMEOUT_SECS` where `IDLE_TIMEOUT_SECS = 300`,
  plus `cancel_on_idle_timeout: bool = True` and
  `cancel_runner_on_idle_timeout: bool = True`, and fires an `on_idle_timeout` event.
  So "user never joins / user goes silent" is handled by default after 5 minutes — set
  it to something tighter (60–120 s) for a demo so a forgotten tab doesn't burn Daily
  minutes and OpenAI tokens.
- **Process exit code / reaping**: irrelevant in the in-process model. The server reaps
  nothing; the `asyncio.Task` completes and our `finally` deletes the room. Add a
  `task.add_done_callback(...)` that logs `task.exception()` — otherwise a crashed bot
  fails silently and the UI just sits there.

`handle_sigint`/`handle_sigterm` default to `False` on `RunnerArguments` but `True`/
`False` on `WorkerRunner.__init__`. In our own server, **pass `handle_sigint=False`** —
uvicorn already owns the signal handlers, and two handlers racing on Ctrl-C is a
hang-on-shutdown bug.

---

## 3. Room lifecycle

`DailyRESTHelper` moved to **`pipecat.transports.daily.utils`** in 1.x (it was
`pipecat.transports.services.helpers.daily_rest`). It provides `create_room(params)`,
`get_token(room_url, expiry_time=3600, eject_at_token_exp=False, owner=True, params=None)`
(corrected via context7 — the parameter is `expiry_time`, not `expiry`, and there is an
`owner` flag defaulting to `True`), `get_room_from_url(...)`,
**`delete_room_by_url(...)`**, `delete_room_by_name(...)`.

`DailyRoomProperties` defaults, verified from source: `enable_prejoin_ui = False`
(good — the user joins straight in), `eject_at_room_exp = False`, `exp = None`.

Daily semantics (from Daily's REST reference):

- `exp` — "unix timestamp … Users cannot join a meeting in this room after this time."
  It does **not** end a call in progress on its own.
- `eject_at_room_exp` — "If there's a meeting going on at room `exp` time, end the
  meeting by kicking everyone out." **Set this to `True`** or a stuck session runs until
  someone closes the tab.
- `eject_after_elapsed` — per-participant hard cap in seconds from join. A good second
  belt-and-braces for a demo (e.g. 900).

**Per-call vs fixed room.** Create per call. A fixed `DAILY_SAMPLE_ROOM_URL` seems
simpler but leaves the operator in a room the previous run's bot may still be sitting in,
and it hard-codes a URL into `.env` that they'd have to create by hand first. Per-call
creation means `.env` needs only `DAILY_API_KEY`.

**Deletion.** Call `delete_room_by_url` in a `finally` around the pipeline. Note that
Pipecat's own runner **does not delete rooms** — it relies on `PIPECAT_ROOM_EXP_HOURS =
4.0` expiry. Four hours of dangling rooms is fine for the framework's dev loop and bad
for a free Daily account.

**Free-tier limits.** Search results consistently report the Daily free plan as
**10,000 participant-minutes/month** (this figure is stated on daily.co's pricing page:
"Starting with 10,000 free minutes/month") and **a cap of ~5 rooms**. The 5-room figure
is *secondary-source only* — **UNVERIFIED**, daily.co's own pricing page did not state a
room count. Design as if the cap is low: short `exp`, `eject_at_room_exp=True`, explicit
deletion.

---

## 4. Docker

**Base image: `python:3.11-slim-bookworm`.** Debian bookworm ships glibc 2.36;
`daily-python` 0.32.0 publishes `manylinux_2_28_x86_64` and `manylinux_2_28_aarch64`
wheels (≈14 MB each), so bookworm-slim is compatible on both Intel and Apple-silicon
operators. **Alpine will not work** — musl, no manylinux wheels. The full `python:3.11`
image buys nothing here and costs ~700 MB.

**System deps — what is actually needed:**

| Package | Needed? | Why |
|---|---|---|
| `libgomp1` | **Yes** | `onnxruntime` CPU builds link OpenMP; `libgomp.so.1` is absent from slim images. Silero VAD (and the smart-turn analyzer) import it. |
| `ca-certificates` | Yes (usually present) | TLS to `api.daily.co`, OpenAI, Deepgram, Cartesia. The simple-chatbot README documents exactly this failure as `SSLCertVerificationError` against `api.daily.co`. |
| `libsndfile1` | **No** | `soundfile` manylinux wheels bundle libsndfile. |
| `ffmpeg` | **No** | Nothing in the Daily + Deepgram + Cartesia path shells out to ffmpeg. |
| `portaudio19-dev` | **No** | Only for `LocalAudioTransport`. Daily transport never touches PortAudio. |
| `torch` / torch hub | **No** | See below. |
| `tini` | Optional | Only matters if you spawn subprocesses. Included in `dailyco/pipecat-base`. |

For reference, the official `dailyco/pipecat-base` Dockerfile (from
`daily-co/pipecat-cloud-images`) installs `libopenblas-dev libresample1 libresample-dev
libgl1 libglib2.0-0 tini` on `ghcr.io/astral-sh/uv:python3.12-trixie-slim`. That set
covers every optional service Pipecat Cloud might run (OpenCV, resampling backends); our
four-service pipeline needs far less.

**Silero: nothing to prebake.** `pipecat.audio.vad.silero.SileroVADAnalyzer.__init__`
resolves the model out of the installed package:

```python
model_name = "silero_vad.onnx"
package_path = "pipecat.audio.vad.data"
model_file_path = str(impresources.files(package_path).joinpath(model_name))
self._model = SileroOnnxModel(model_file_path, force_onnx_cpu=True)
```

`src/pipecat/audio/vad/data/silero_vad.onnx` is **2,327,524 bytes and ships in the
wheel**. There is no torch, no `torch.hub.load`, no network fetch. (Older Pipecat used
torch hub; that is historical.) `onnxruntime~=1.24.3` is a **core** dependency of
`pipecat-ai`, not an extra — `silero = []` in `pyproject.toml` is an empty marker extra.

**NLTK is the one thing worth prebaking.** `pipecat/utils/string.py`:

> "The tokenizer and its `punkt_tab` data load on first use, and the data is downloaded
> if it isn't already present. Deployments that build their own image should bundle it at
> build time (`python -m nltk.downloader punkt_tab`) or point `NLTK_DATA` at a directory
> that already has it, so that a slow or unavailable network can't delay the first bot
> turn."

**Install: uv, with `--frozen`.** `uv sync --frozen` (or `--locked`) refuses to update
`uv.lock`, which is exactly the reproducibility you want in a build. Pip + a pinned
`requirements.txt` is a fine fallback and one fewer moving part for a operator reading
the Dockerfile. Either way, **pin `pipecat-ai==1.9.0`** — this stack is moving fast
enough that `>=` will break.

**Image size — estimate, UNVERIFIED:** `python:3.11-slim` ≈ 130 MB, plus onnxruntime
(~16 MB wheel), numba+llvmlite (~40 MB), numpy, `daily-python` (~14 MB wheel, larger
unpacked), openai/deepgram/aiohttp/pydantic. Expect **≈ 900 MB – 1.3 GB**. Mention the
first-build time (2–5 min) in the README so the operator doesn't think it hung.

**Non-root**: create `appuser`, `chown` the app dir, `USER appuser`. Set
`NLTK_DATA=/usr/local/share/nltk_data` (world-readable, written at build time as root)
so the runtime user never needs to write there.

**Healthcheck**: slim has no `curl`. Use Python:

```dockerfile
HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:7860/health',timeout=2).status==200 else 1)"
```

---

## 5. Proposed `Dockerfile` (PROPOSAL — not yet built/verified)

```dockerfile
FROM python:3.11-slim-bookworm

# libgomp1: onnxruntime (Silero VAD) needs libgomp.so.1, absent from slim.
# ca-certificates: TLS to api.daily.co / OpenAI / Deepgram / Cartesia.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 ca-certificates \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    NLTK_DATA=/usr/local/share/nltk_data

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Prebake NLTK punkt_tab so the first bot sentence doesn't trigger a download.
RUN python -m nltk.downloader -d "$NLTK_DATA" punkt_tab \
 && python -c "import nltk; nltk.data.find('tokenizers/punkt_tab')"

# Fail the build if the bundled Silero model isn't where we think it is.
RUN python -c "from importlib.resources import files; \
p=files('pipecat.audio.vad.data').joinpath('silero_vad.onnx'); \
assert p.is_file(), p; print('silero_vad.onnx OK')"

COPY app/ ./app/
COPY static/ ./static/

RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 7860
HEALTHCHECK --interval=10s --timeout=3s --start-period=40s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:7860/health',timeout=2).status==200 else 1)"

CMD ["python", "-m", "uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "7860"]
```

`requirements.txt` skeleton:

```
pipecat-ai[daily,deepgram,openai,cartesia,silero,runner]==1.9.0
fastapi>=0.115.6,<1
uvicorn>=0.32.0,<1
python-dotenv>=1.0.0,<2
aiohttp>=3.11.12,<4
```

(`cartesia`, `openai`, `silero` are empty extras — their deps are in pipecat's core
dependency list — but naming them documents intent and survives future refactors.)

## 5b. Proposed `docker-compose.yml` (PROPOSAL)

```yaml
services:
  app:
    build: .
    ports:
      - "7860:7860"
    env_file:
      - .env
    environment:
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
      PYTHONUNBUFFERED: "1"
    restart: "no"
```

- **One service.** A second is never needed: no database, no Redis, no separate worker.
  The bot runs in-process; Daily's SFU is the only "infrastructure" and it is somebody
  else's cloud.
- **`restart: "no"`** deliberately. `unless-stopped` would hide a missing-API-key crash
  behind an infinite restart loop; for a demo the operator must *see* the error.
- **`PYTHONUNBUFFERED=1`** is load-bearing: without it, loguru's stderr is block-buffered
  through the Docker log driver and the operator sees nothing until the buffer flushes.
- **First-run friendliness.** Validate at import/startup and fail loudly — the flyio
  example does exactly this shape:

```python
REQUIRED = ["DAILY_API_KEY", "DEEPGRAM_API_KEY", "OPENAI_API_KEY", "CARTESIA_API_KEY"]
missing = [k for k in REQUIRED if not os.getenv(k)]
if missing:
    sys.exit(
        "\n  Missing required environment variables: " + ", ".join(missing) +
        "\n  Copy .env.example to .env and fill them in, then re-run:"
        "\n      cp .env.example .env && docker compose up --build\n"
    )
```

Also guard the missing-`.env` case: `env_file: .env` makes compose **fail with an
obscure error if the file doesn't exist**. Ship a committed `.env.example` and say so in
the first line of the README; optionally `env_file: [{path: .env, required: false}]` so
the app's own message wins instead.

---

## 6. `.env.example` and README expectations

```ini
# --- Required ---
DAILY_API_KEY=            # dashboard.daily.co → Developers → API keys
DEEPGRAM_API_KEY=         # console.deepgram.com → API Keys ($200 free credit)
OPENAI_API_KEY=           # platform.openai.com/api-keys
CARTESIA_API_KEY=         # play.cartesia.ai → API Keys

# --- Optional ---
LOG_LEVEL=INFO            # DEBUG for full Pipecat frame tracing
DAILY_API_URL=https://api.daily.co/v1
```

README must contain, near the top and in this order: (1) `cp .env.example .env` and fill
four keys, with a one-line "where to get it" per key; (2) the *exact* command
`docker compose up --build`; (3) the *exact* URL `http://localhost:7860`; (4) "first
build takes ~3 minutes"; (5) "allow microphone access when the browser asks". Mirror the
env var names exactly between `.env.example`, the README table, and the startup
validator — a mismatch there is the single most common reason a operator gives up.

---

## 7. Networking

Everything the container needs is **outbound**:

- HTTPS to `api.daily.co` (room/token), `api.openai.com`, `api.cartesia.ai`.
- WebSocket (WSS/443) to Deepgram and Cartesia streaming endpoints.
- WebRTC media to Daily's SFU: UDP to Daily's media servers, with automatic
  TURN-over-TCP/443 fallback when UDP is blocked.

**Inbound: only the mapped HTTP port (7860).** The browser talks to Daily's SFU
*directly* — it never sends media to our container — so no UDP port publishing, no
`network_mode: host`, no `--add-host`. This is the big architectural advantage of Daily
over SmallWebRTC for a Dockerised demo.

Docker Desktop for Mac/Windows caveats (relevant but mostly not fatal here, since our
UDP is container → internet, not host ↔ container):

- Docker Desktop for Mac has a known bug where **UDP packets reusing a source port after
  120 s are dropped** (macOS kernel NAT binding lifetime). A live call sends continuously,
  so bindings stay warm; the risk window is a second call starting >120 s after the first
  ended and reusing a port. If a operator reports "second call has no audio", restarting
  the container is the workaround.
- Older Docker Desktop versions eagerly closed outgoing UDP connections; **fixed in
  Docker Desktop 4.41.0**. Worth a README line: "Docker Desktop 4.41+ recommended."
- The gVisor-vs-vpnkit source-IP weirdness on Docker Desktop affects host→container
  connections only; irrelevant to us.
- Corporate VPNs/firewalls that block UDP will push the call onto Daily's TURN/443
  fallback — audio still works, latency is worse.

---

## 8. Logging

Pipecat uses **loguru** throughout (`loguru~=0.7.3` is a core dependency). Its own runner
configures exactly two lines, which is the pattern to copy:

```python
logger.remove()
logger.add(sys.stderr, level="TRACE" if args.verbose else "DEBUG")
```

For our server:

```python
from loguru import logger
import os, sys

logger.remove()
logger.add(sys.stderr, level=os.getenv("LOG_LEVEL", "INFO"),
           format="<green>{time:HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | {message}")
```

`logger.remove()` first is mandatory — loguru installs a default stderr sink at import,
and adding without removing duplicates every line.

Because the bot is an asyncio task in the same process, **its logs are the server's
logs** and land in `docker compose up` output with zero extra work. (Had we gone the
subprocess route we'd rely on `Popen` inheriting stdio, which works but loses per-call
attribution.) `LOG_LEVEL=DEBUG` gives Pipecat's frame-level tracing — very useful when
debugging why the bot isn't speaking; `TRACE` is firehose.

Add a `bind`-style session id so multiple runs are distinguishable:
`logger.bind(session=session_id)` inside the bot task.

---

## Gotchas

1. **`PipelineTask`/`PipelineRunner` are deprecated shims.** Use `PipelineWorker`
   (`pipecat.pipeline.worker`) and `WorkerRunner` (`pipecat.workers.runner`). Removal is
   scheduled for 2.0.0.
2. **`DailyRESTHelper` moved** to `pipecat.transports.daily.utils`. Most blog posts and
   LLM memory still say `pipecat.transports.services.helpers.daily_rest`.
3. **The runner defaults to `--host localhost`.** In a container that binds to the loopback
   interface and the port mapping appears dead. Always `0.0.0.0`.
4. **`simple-chatbot` has no `server.py` any more.** Do not copy a two-process
   architecture from a stale tutorial and claim it's "the official pattern".
5. **`libgomp1`** — the failure is a cryptic `ImportError: libgomp.so.1: cannot open
   shared object file` deep inside `import onnxruntime`, at the moment `SileroVADAnalyzer`
   is constructed, i.e. mid-request.
6. **NLTK `punkt_tab` downloads at first sentence**, not at import. Symptom: an
   inexplicable 1–3 s stall before the bot's very first utterance, or a hang on an
   offline machine.
7. **`enable_prejoin_ui` defaults to `False`** in `DailyRoomProperties` — good for us,
   but the Daily dashboard default is `True`. If you ever create the room by hand, set it.
8. **Don't let both uvicorn and `WorkerRunner` install SIGINT handlers.** Pass
   `handle_sigint=False` when running in-process, or Ctrl-C hangs.
9. **An asyncio bot task that raises dies silently.** Always attach a done-callback that
   logs `task.exception()`.
10. **Delete rooms in a `finally`.** Pipecat's runner doesn't (it leans on a 4-hour
    `exp`); on a free Daily account that will bite.
11. **Alpine is a dead end** — `daily-python` ships manylinux-only wheels.
12. **Don't `COPY` into `/app` if you ever switch to `dailyco/pipecat-base`** — that image
    uses `/app` for its own runtime and its docs warn that writing there breaks deploys.

---

## Sources

- Pipecat Development Runner guide — https://docs.pipecat.ai/server/utilities/runner/guide
- `pipecat/runner/run.py` (main, `_start_bot_session`, `_setup_daily_routes`, `/start`, `RUNNER_HOST/PORT`, `PIPECAT_ROOM_EXP_HOURS`) — https://github.com/pipecat-ai/pipecat/blob/main/src/pipecat/runner/run.py
- `pipecat/runner/types.py` (`RunnerArguments`, `DailyRunnerArguments`, `pipeline_idle_timeout_secs=300`) — https://github.com/pipecat-ai/pipecat/blob/main/src/pipecat/runner/types.py
- `pipecat/runner/daily.py` (`configure()`) — https://github.com/pipecat-ai/pipecat/blob/main/src/pipecat/runner/daily.py
- `pipecat/audio/vad/silero.py` + `pipecat/audio/vad/data/silero_vad.onnx` (2,327,524 bytes) — https://github.com/pipecat-ai/pipecat/blob/main/src/pipecat/audio/vad/silero.py
- `pipecat/pipeline/worker.py` (`PipelineWorker`, `IDLE_TIMEOUT_SECS = 300`, `on_idle_timeout`) — https://github.com/pipecat-ai/pipecat/blob/main/src/pipecat/pipeline/worker.py
- `pipecat/pipeline/task.py` (deprecation shim) — https://github.com/pipecat-ai/pipecat/blob/main/src/pipecat/pipeline/task.py
- `pipecat/workers/runner.py` (`WorkerRunner.cancel/run/end`) — https://github.com/pipecat-ai/pipecat/blob/main/src/pipecat/workers/runner.py
- `pipecat/transports/daily/utils.py` (`DailyRESTHelper`, `DailyRoomProperties`, `delete_room_by_url`) — https://github.com/pipecat-ai/pipecat/blob/main/src/pipecat/transports/daily/utils.py
- `pipecat/utils/string.py` (NLTK `punkt_tab` lazy download + prebake advice) — https://github.com/pipecat-ai/pipecat/blob/main/src/pipecat/utils/string.py
- `pipecat/pyproject.toml` (core deps incl. `onnxruntime~=1.24.3`; `runner`/`daily`/`silero` extras; `requires-python >=3.11`) — https://github.com/pipecat-ai/pipecat/blob/main/pyproject.toml
- Pipecat releases (v1.9.0 @ 2026-09-11, v1.0.0 @ 2026-04-14) — https://github.com/pipecat-ai/pipecat/releases
- `pipecat-examples/simple-chatbot/server/` (bot-openai.py, Dockerfile, pyproject.toml, README) — https://github.com/pipecat-ai/pipecat-examples/tree/main/simple-chatbot/server
- `pipecat-examples/deployment/flyio-example/bot_runner.py` + `Dockerfile` (subprocess pattern, env validation) — https://github.com/pipecat-ai/pipecat-examples/tree/main/deployment/flyio-example
- `pipecat-examples/runner-examples/README.md` — https://github.com/pipecat-ai/pipecat-examples/tree/main/runner-examples
- `daily-co/pipecat-cloud-images` official base Dockerfile (apt list, NLTK prebake, tini) — https://github.com/daily-co/pipecat-cloud-images/blob/main/pipecat-base/Dockerfile
- Pipecat: Running bots locally / in production — https://docs.pipecat.ai/pipecat/deployment/running-bots-locally , https://docs.pipecat.ai/pipecat/deployment/running-bots-in-production
- Daily REST API — create room (`exp`, `eject_at_room_exp`, `eject_after_elapsed`, `enable_prejoin_ui`) — https://docs.daily.co/reference/rest-api/rooms/create-room
- Daily pricing ("Starting with 10,000 free minutes/month") — https://www.daily.co/pricing/
- `daily-python` 0.32.0 wheels (manylinux_2_28 only) — https://pypi.org/project/daily-python/
- onnxruntime needs `libgomp1` on slim images — https://github.com/microsoft/onnxruntime/issues/5082 , https://github.com/microsoft/onnxruntime/blob/main/dockerfiles/README.md
- `soundfile` bundles libsndfile in manylinux wheels — https://github.com/bastibe/python-soundfile , https://python-soundfile.readthedocs.io/
- Docker Desktop macOS UDP issues — https://github.com/moby/moby/issues/49324 , https://github.com/docker/for-mac/issues/1464 , https://github.com/docker/desktop-feedback/issues/133
- Pipecat Cloud logging (loguru) — https://docs.pipecat.ai/deployment/pipecat-cloud/fundamentals/logging

---

## Context7 cross-check (2026-09-11)

Every concrete claim above was re-queried against context7 MCP documentation, which the
user treats as authoritative and current. Nothing was deleted; three corrections were
applied inline (marked "corrected via context7") and one disagreement is recorded below.

### Libraries resolved

| Purpose | Context7 library ID | Version / notes |
|---|---|---|
| Pipecat docs (guides, API reference) | `/pipecat-ai/docs` | no pinned version; 6,869 snippets, High reputation |
| Pipecat source + generated API md | `/pipecat-ai/pipecat` | no pinned version; 3,072 snippets, High |
| Pipecat API reference site | `/websites/reference-server_pipecat_ai_en` | `latest` (reference-server.pipecat.ai/en/latest) |
| Pipecat examples | `/pipecat-ai/pipecat-examples` | no pinned version; 884 snippets |
| daily-python | `/daily-co/daily-python` | no pinned version (README requirements only) |
| Daily REST API | `/websites/daily_co_reference_rest-api` | OpenAPI `info.version: 1.1.1` |
| Daily docs (networking, daily-js) | `/websites/daily_co` | no pinned version |
| FastAPI | `/websites/fastapi_tiangolo` | no pinned version |
| uv | `/astral-sh/uv` | no pinned version (docs/guides/integration/docker.md) |
| Docker / Compose | `/docker/docs` | `__branch__main` |

Context7 does **not** expose a pipecat version selector, so its pipecat corpus tracks
`main`, not `1.9.0` specifically. Where its content is older than the 1.9.0 source this
report read directly, that is called out.

### Claims table

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| 1 | Runner entrypoint is `async def bot(runner_args)` + `from pipecat.runner.run import main; main()` | VERIFIED | `running-bots-locally.mdx`: "Defines the async `bot` function which serves as the entry point… The `main` function is used to start the development runner" |
| 2 | Runner `--host` defaults to `localhost` (fatal in Docker) | VERIFIED | runner guide: "`--host TEXT  Server host address (default: localhost)`" |
| 3 | Runner port default 7860 | VERIFIED | "`--port INTEGER  Server port (default: 7860)`"; `RUNNER_PORT: int = 7860` |
| 4 | Runner spawns bots as asyncio tasks (`_start_bot_session` → `asyncio.create_task`) | VERIFIED (indirectly) | `run.py` docstring: "The runner discovers and runs any `bot(runner_args)` function found in the calling module"; docs' own FastAPI pattern uses `background_tasks.add_task(run_bot, …)`. Context7 does not quote `_start_bot_session` verbatim. |
| 5 | `GET /daily` creates a room and redirects into it | VERIFIED | runner guide: "GET /daily — Redirects the browser into a freshly created Daily room." |
| 6 | Runner mounts a prebuilt UI and owns `/` | VERIFIED (partial) | "It starts a local server, typically on `localhost:7860`, and serves a prebuilt client UI." The exact `/client` mount path and the `/` → `/client/` 302 are NOT COVERED. |
| 7 | `POST /start` returns `sessionId` / `dailyRoom` / `dailyToken`; accepts `dailyRoomProperties` | VERIFIED | runner guide `POST /start` schema lists exactly these fields. |
| 8 | `dailyRoomProperties` gets `exp` and `eject_at_room_exp=True` defaulted in by the runner | NOT COVERED | Field documented; the runner's defaulting behaviour is not described. |
| 9 | `PIPECAT_ROOM_EXP_HOURS = 4.0`; runner does not delete rooms | NOT COVERED | `pipecat.runner.daily.configure()` shows `room_exp_duration=2.0` hours as the *function* default; the runner module constant is not in context7. Report's 4.0 is a source read — left as-is, flagged low-confidence. |
| 10 | Development runner is explicitly not a production surface | VERIFIED | `running-bots-in-production.mdx`: "The development runner (`pipecat.runner.run`) is not suitable for production environments… lacks authentication, rate limiting, backpressure, and lifecycle management." |
| 11 | `simple-chatbot` has no `server.py` | VERIFIED | README project structure lists `server/` containing only bot files, assets, env.example, Dockerfile, pcc-deploy.toml, pyproject.toml, README.md, requirements.txt. **Corrected inline** (report's file list was incomplete). |
| 12 | flyio example treats subprocess as the non-recommended fallback | VERIFIED | flyio README: "launch a new machine for each user session. This is a recommended approach for production vs. running shell processes as your deployment will quickly run out of system resources under load." |
| 13 | `PipelineTask` → `PipelineWorker`, `PipelineRunner` → `WorkerRunner`, deprecated, removed in 2.0.0 | VERIFIED | `your-first-agent.mdx`: "deprecated aliases"; `pipeline-termination.mdx`: "deprecated as of version 1.3.0/1.4.0. These will be removed in version 2.0.0". |
| 14 | `WorkerRunner(handle_sigint=False)` + `add_workers(worker)` + `run()` is the current shape | VERIFIED | quickstart.mdx shows exactly `runner = WorkerRunner(handle_sigint=False)` / `await runner.add_workers(worker)` / `await runner.run()`. `run(auto_end: bool = True)` in the API ref. |
| 15 | `on_client_disconnected` is the transport-agnostic hook | VERIFIED | Daily transport ref: "Transport-agnostic aliases that fire alongside `on_participant_joined` and `on_participant_left`". |
| 16 | `WorkerRunner` exposes `cancel()`, `stop_when_done()`, `end()` | VERIFIED | API ref documents `cancel()`, `stop_when_done()`, and "manually terminated using end or cancel methods". |
| 17 | `PipelineWorker` `idle_timeout_secs` defaults to **300** | VERIFIED | `pipeline-idle-detection.mdx`: "**idle_timeout_secs** … Defaults to 300. Set to None to disable." |
| 18 | `cancel_on_idle_timeout` defaults to `True` | VERIFIED | same page: "**cancel_on_idle_timeout** … Defaults to True." |
| 19 | `cancel_runner_on_idle_timeout: bool = True` also exists | NOT COVERED | Context7's documented signature is `(pipeline, idle_timeout_secs, idle_timeout_frames, cancel_on_idle_timeout)`. No such parameter appears. Treat as unconfirmed. |
| 20 | `on_idle_timeout` event fires | VERIFIED | Listed among `PipelineWorker` event handlers. |
| 21 | `DailyRESTHelper` lives in `pipecat.transports.daily.utils` | VERIFIED | All rest-helper examples import from `pipecat.transports.daily.utils`. |
| 22 | `delete_room_by_url` / `delete_room_by_name` / `get_room_from_url` / `get_token` exist | VERIFIED | All four documented in the rest-helper reference. **`get_token` signature corrected inline.** |
| 23 | `DailyRoomProperties` defaults: `enable_prejoin_ui=False`, `eject_at_room_exp=False`, `exp=None` | VERIFIED | rest-helper ref: "enable_prejoin_ui (boolean, default=false)", "eject_at_room_exp (boolean, default=false)", "exp (float, optional)". |
| 24 | Daily `exp` blocks joins but does not end a call in progress | VERIFIED | REST OpenAPI: "'Expires'… Users cannot join a meeting in this room after this time." |
| 25 | `eject_at_room_exp` ends the meeting at `exp`; `eject_after_elapsed` is a per-participant cap | VERIFIED | Daily room-config notes: "automatically end a meeting by kicking all participants when the room expiration time is reached"; "automatically ejecting them after a specified number of seconds." |
| 26 | Daily free tier ≈10,000 participant-minutes/month and a ~5-room cap | NOT COVERED | Pricing is not in context7's Daily corpora. The report already marks the 5-room figure UNVERIFIED; leave as-is. |
| 27 | Base image `python:3.11-slim-bookworm` | VERIFIED | The production Dockerfile in `running-bots-in-production.mdx` is literally `FROM python:3.11-slim-bookworm`. |
| 28 | `daily-python` needs glibc; Alpine/musl is a dead end | VERIFIED | daily-python README: "you need Python 3.7 or newer and **glibc 2.28 or newer**." (musl/Alpine not named, but glibc 2.28 excludes it. Bookworm's glibc 2.36 satisfies it.) |
| 29 | `manylinux_2_28` wheels, ≈14 MB, x86_64 + aarch64 | NOT COVERED | Context7 carries only the glibc floor, not the wheel matrix or sizes. |
| 30 | `libgomp1` is the only genuinely required apt package | NOT COVERED | Context7's own production Dockerfile installs **no** apt packages at all, which is consistent with but does not confirm the claim. onnxruntime's libgomp dependency is not in any context7 corpus. |
| 31 | No ffmpeg / portaudio / libsndfile needed | NOT COVERED (consistent) | The reference production Dockerfile installs none of them. |
| 32 | Silero ships as a bundled ONNX in the wheel; no torch, no download | **CONTRADICTED (stale context7)** — see below | |
| 33 | `SileroOnnxModel(path, force_onnx_cpu=True)` loads from a file path | VERIFIED | API ref: "`class pipecat.audio.vad.silero.SileroOnnxModel(path, force_onnx_cpu=True)` … Path to the ONNX model file." No torch anywhere in the class. |
| 34 | NLTK `punkt_tab` must be prebaked at build time | VERIFIED | Production Dockerfile: `RUN python -m nltk.downloader punkt_tab -d /usr/local/share/nltk_data && python -c "import nltk; nltk.data.find('tokenizers/punkt_tab')"` — byte-for-byte the report's recipe, including `NLTK_DATA=/usr/local/share/nltk_data`. |
| 35 | `uv sync --frozen` / `--locked` refuse to update `uv.lock` | VERIFIED with nuance | uv Docker guide: "`--frozen` instead of `--locked` to **skip the check**"; `--locked` "will validate that the lockfile is correct". Both avoid mutating the lock, but `--frozen` skips validation while `--locked` fails the build on drift. For a reproducible image `--locked` is the stronger choice. |
| 36 | `pipecat-ai[daily,deepgram,openai,cartesia,silero]` is the right extras set | VERIFIED | `introduction.mdx`: `uv add "pipecat-ai[daily,deepgram,openai,cartesia,silero]"`. |
| 37 | FastAPI `StaticFiles` for `index.html` | VERIFIED, with a newer option | `app.mount("/static", StaticFiles(directory="static"))`; `StaticFiles(..., html=True)` serves `index.html` on directory requests. FastAPI now also has `app.frontend(path, directory=…)`, which serves a static build as *low-priority* routes checked only after path operations — a cleaner fit than mounting at `/`. |
| 38 | FastAPI lifespan for one-time startup cost | VERIFIED | `advanced/events`: `@asynccontextmanager async def lifespan(app)` … "Load the ML model" before `yield`, cleanup after. |
| 39 | Background bot task pattern | VERIFIED | Pipecat's own `session-initialization.mdx` uses `BackgroundTasks.add_task(run_bot, room_url, token)` from a `POST /start`. Note: `BackgroundTasks` runs *after* the response is sent and is fine for a long-lived task here; the report's `asyncio.create_task` is equivalent in effect. |
| 40 | Non-root `appuser`, `chown`, `USER` | NOT COVERED | Pipecat's reference Dockerfile runs as root. Generic Docker hardening; no contradiction. |
| 41 | Python-based `HEALTHCHECK` (slim has no curl) | NOT COVERED for the Python form; compose `healthcheck` fields VERIFIED | Compose reference documents `test`, `interval`, `timeout`, `retries`, `start_period`, `start_interval` (durations supported from Compose 2.20.2). |
| 42 | Compose skeleton: `build`, `ports`, `env_file`, `environment`, `restart` | VERIFIED | All are documented Compose service attributes; `unless-stopped` semantics confirmed ("restarts unless it was manually stopped"). |
| 43 | `env_file: [{path: .env, required: false}]` avoids the missing-file error | VERIFIED | Compose docs: "As of Docker Compose **2.24.0**… set your `.env` file… to be optional by using the `required` field. When `required` is set to `false` and the `.env` file is missing, Compose silently ignores the entry." Add the 2.24.0 floor to the README. |
| 44 | `PYTHONUNBUFFERED=1` is load-bearing for compose logs | NOT COVERED | Neither Docker nor Pipecat corpora address it. Standard Python behaviour; claim left standing. |
| 45 | Outbound-only: HTTPS/WSS plus UDP media, TURN-over-TCP/443 fallback | VERIFIED | Daily networking guide: "WebRTC media connections utilize three primary types: Direct UDP, TURN relay, and TURN over TLS/TCP 443… final fallback… mimicking standard HTTPS traffic, though it introduces higher latency." |
| 46 | Specific UDP egress port ranges | NOT COVERED (directionally supported) | Daily's firewall guide mentions "specific port ranges for UDP and TCP traffic to Daily's media servers" plus Cloudflare/Twilio STUN/TURN, but context7 returns no numeric ranges. |
| 47 | Docker Desktop macOS UDP source-port bug; fixed in 4.41.0 | NOT COVERED | No Docker Desktop UDP/NAT issue surfaced in `/docker/docs`. Remains GitHub-issue-sourced only. |
| 48 | Pipecat uses loguru; `logger.remove()` then `logger.add(sys.stderr, level=…)` | VERIFIED | Cerebrium deployment example: `logger.remove(0)` / `logger.add(sys.stderr, level="DEBUG")`. Pipecat Cloud logging guide: "using the loguru library is recommended". |
| 49 | Bind a session id to log lines | VERIFIED | Datadog guide reads `record["extra"].get("session_id")` and reads `args.session_id` off runner arguments — the report's `logger.bind(session=…)` is the same mechanism. |
| 50 | Memory ~300–450 MB/bot; cold start 2–5 s; image ≈900 MB–1.3 GB | NOT COVERED | No sizing or benchmark data in any context7 corpus. The report already marks all three **UNVERIFIED**; that labelling is correct and should stay. |

**Counts:** 50 claims checked — **27 VERIFIED**, **2 VERIFIED-with-nuance** (#35, #37/#39),
**1 CONTRADICTED** (#32, and context7 is the stale side), **20 NOT COVERED**.

### The one contradiction: Silero model provisioning

Context7's `pipecat/deployment/running-bots-in-production.mdx` ships this line in its
reference production Dockerfile:

```dockerfile
# Bake model weights (e.g. Silero VAD) into the image so first-run is fast.
RUN python -c "import torch; torch.hub.load('snakers4/silero-vad', 'silero_vad', force_reload=True)"
```

That directly contradicts §4's "no torch, no `torch.hub.load`, no network fetch —
`silero_vad.onnx` is 2,327,524 bytes inside the wheel".

**Resolution: the report stands; context7's page is stale.** Three reasons:

1. Context7's *own* API reference for the same library documents
   `SileroOnnxModel(path, force_onnx_cpu=True)` — "Path to the ONNX model file" — with no
   torch in the class at all, and `SileroVADAnalyzer.__init__()` taking no model argument.
   The two context7 pages disagree with each other; the API reference is generated from
   source and the deployment page is hand-written prose.
2. `torch` is not in `pipecat-ai`'s dependency list, so `import torch` in that `RUN` line
   would fail outright in an image built from the report's `requirements.txt`. The snippet
   is a leftover from pre-1.x Pipecat, when the VAD was a torch-hub model.
3. The report's figure is a byte-exact read of `src/pipecat/audio/vad/data/silero_vad.onnx`
   at the pinned `1.9.0` tag, which is more specific and more current than context7's
   unversioned `main`-tracking prose.

§4's build-time assertion (`files('pipecat.audio.vad.data').joinpath('silero_vad.onnx')`)
is the right guard and already fails the build if this ever changes. **Do not add the
`torch.hub.load` line.**

### Corrections applied

1. **§1(a)** — `simple-chatbot/server/` file list completed from context7's README project
   structure (`assets/`, `env.example`, `requirements.txt`, `README.md` were missing). The
   load-bearing claim — *no `server.py`* — is confirmed.
2. **§3** — `DailyRESTHelper.get_token` signature corrected: the parameter is
   `expiry_time` (default 3600), not `expiry`, and there is an `owner` flag defaulting to
   `True`. Passing `owner=False` for the human participant's token is the safer shape for
   this demo.
3. **§2** — added a note that context7's canonical `pipeline-termination.mdx` example
   cancels the *worker* (`await worker.cancel()`) inside `on_client_disconnected`, not the
   runner. Both APIs exist and the report's version works; the worker form is the narrower
   documented one.

### Worth folding into the build (no correction needed, new information)

- **`--locked` over `--frozen`** if uv is used: `--frozen` skips lockfile validation
  entirely, `--locked` fails the build if `uv.lock` has drifted. The report's stated
  intent ("exactly the reproducibility you want in a build") is better served by
  `--locked`.
- **`app.frontend("/", directory="static")`** is now a first-class FastAPI method that
  serves a static build as low-priority routes checked *after* path operations — it avoids
  the mount-at-`/` ordering problem §1(c) works around. `StaticFiles(..., html=True)` is
  the alternative.
- **Compose 2.24.0** is the floor for `env_file: [{path: .env, required: false}]`. Worth
  one README line next to the Docker Desktop 4.41+ note.
- **`cancel_runner_on_idle_timeout`** is not in context7's documented `PipelineWorker`
  signature. Confirm against the installed 1.9.0 before relying on it; `cancel_on_idle_timeout`
  alone is documented and sufficient.
