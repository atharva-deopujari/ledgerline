# Ledgerline

A real-time voice assistant that helps a person plan the next thirty days of their money. You talk; it asks
about what comes in and what goes out and when; it records every fact; a deterministic engine computes a
day-by-day plan; live cards update the moment you correct anything; and you hear the two actions that matter
most, with their consequences. Built on Pipecat 1.9 and Daily, with OpenAI `gpt-5.6-luna`, Deepgram Nova-3
and Cartesia Sonic. FastAPI backend, React + Vite + TypeScript frontend, one Docker image.

**The one rule: the model never computes.** Every number the bot speaks came back in a tool result, and an
evaluation check fails any run where that is not true.

## Run it

Requirements: Docker with Compose, and four API keys (below).

```bash
cp .env.example .env      # fill in the four keys
docker compose up --build
```

Open **http://localhost:7860** in Chrome or Edge, click Start, allow the microphone, and talk.

First build takes 3 to 5 minutes (Node build of the frontend, Python dependencies, model files). Later starts
take seconds. Use `localhost`, not `127.0.0.1`: browsers only grant microphone access on a secure context, and
`localhost` is exempt from HTTPS. Every call, real or simulated, is recorded as JSON under `evals/runs/`, which
is mounted into the container.

To see the interface without keys or a call, open `http://localhost:7860/?mock=1`: a scripted conversation
replays through the real components from generated snapshots.

## Environment variables

| Variable | Required | Used for | Where to get it |
|---|---|---|---|
| `OPENAI_API_KEY` | yes | the conversation model | https://platform.openai.com/api-keys |
| `DAILY_API_KEY` | yes | WebRTC audio between browser and bot, and the data channel that carries cards | https://dashboard.daily.co, Developers. A card must be on file; 10,000 minutes a month are free |
| `DEEPGRAM_API_KEY` | yes | speech to text (Nova-3); also text to speech when `TTS_PROVIDER=deepgram` | https://console.deepgram.com. $200 free credit |
| `CARTESIA_API_KEY` | unless `TTS_PROVIDER=deepgram` | text to speech (Sonic) | https://play.cartesia.ai, API Keys. 20,000 free credits a month, about 27 minutes |
| `OPENAI_MODEL` | no | model id, default `gpt-5.6-luna`. Bare `gpt-5.6` is a different, pricier model | |
| `LLM_API` | no | `chat` (default) or `responses`; see `docs/process/spike-findings.md` for the measured difference | |
| `TTS_PROVIDER` | no | `cartesia` (default) or `deepgram` | |
| `CARTESIA_VOICE_ID`, `CARTESIA_SPEED`, `CARTESIA_EMOTION` | no | voice, speaking rate 0.6 to 1.5, optional emotion tag; three voices documented in `.env.example` | |
| `TURN_STRATEGY`, `SMART_TURN_STOP_SECS` | no | `smart` (default, Smart Turn model) or `timeout`; how long a turn stays open after a hesitation, default 1.5 | |
| `PROMPT_VERSION` | no | which file under `ledgerline/agent/prompts/` to load, default `v1` | |
| `ROOM_EXPIRY_SECS` | no | Daily room lifetime, default 3600; rooms are private, self-clean, and are deleted after each call | |
| `IDLE_TIMEOUT_SECS` | no | cancel a call after this much silence, default 300 | |
| `JOIN_TIMEOUT_SECS` | no | free the call slot if the browser never joins, default 45 | |
| `END_GRACE_SECS` | no | after the goodbye, hang up when speech ends or after this many seconds, default 6 | |
| `HOST`, `PORT` | no | server bind, default `0.0.0.0` and `7860`; keep `0.0.0.0` inside Docker | |
| `LOG_LEVEL` | no | default `INFO` | |
| `ENABLE_TRACING`, `OTEL_EXPORTER_OTLP_ENDPOINT` | no | OpenTelemetry spans per turn to any OTLP endpoint, off by default | |

Keys are read from `.env` by Compose and validated at boot; a missing required key stops the container with a
message naming every missing variable. Never commit `.env`.

## What it does

1. You click Start. The server creates a private Daily room, joins the bot to it, and hands your browser a
   token.
2. You speak. Deepgram transcribes; turn end is judged once, by the model's own turn-completion protocol with
   a few domain hints appended, so "I have..." followed by a pause does not end your turn.
3. For every fact you state the model calls a tool silently (`upsert_item`, `remove_item`, `mark_unknown`),
   the tool writes into one `FinancialState` object, and the result string comes back as compact facts with
   the numbers already computed: `rent: 12,000 -> 14,000; confirm which is right before moving on`. The
   model speaks once, after the result.
4. Every tool call re-runs the plan engine and pushes a full card snapshot to the browser over Daily's data
   channel. Correct a number and every affected card changes, because there is only one copy of the truth.
5. When nothing blocks it, the model calls `finalize_plan`. The engine simulates each of the thirty days,
   classifies the result (fine, timing shortfall, structural shortfall, unsolvable), proposes actions in a
   fixed priority order, and says plainly what stays unpaid if nothing works. It never proposes new borrowing.
6. The model explains the top two actions with their consequences, checks that you have understood, records
   that, says one goodbye and ends the call.

Code owns what must be correct: money (`Decimal`), dates, priority order, what is missing, what blocks the
plan, every figure in a result. The model owns what needs understanding: whether a new number is a correction
or a contradiction, whether an amount sounds implausible, what to ask next and how, whether you have
understood. `docs/process/cut-brief.md` is that line written down.

## Repository layout

```
ledgerline/            Python package; imports flow one way: domain <- agent <- voice <- api (enforced)
  domain/              pure: models (contract), policy, state/ (fact store), engine/ (plan maths), cards
  agent/               tools/ the model calls, result strings, system prompt, prompts/v1.md
  voice/               Pipecat pipeline, one call's lifecycle, filler, recorder, Daily transport
  api/                 FastAPI routes and the single-slot session registry
frontend/              React + Vite + TypeScript; protocol/types.ts mirrors domain/cards.py
tests/                 offline and fast, mirrors the package tree; paid or networked tests carry markers
evals/                 text-only conversation harness, simulated user, checks, scenarios, recordings, REPORT.md
spike/                 headless measurement scripts (a fake participant drives the real pipeline)
scripts/               dump_mock_snapshots.py regenerates the frontend's mock feed from the domain layer
docs/                  research, architecture, process; start at docs/README.md
```

## Develop and test

```bash
uv sync                                      # Python 3.11 environment
uv run pytest                                # offline suite, a few seconds
uv run ruff check . && uv run ruff format --check . && uv run lint-imports   # lint, format, four import contracts
cd frontend && npm ci && npm run lint && npm run format:check && npm run typecheck && npm run test -- --run && npm run build
uv run pytest -m e2e tests/e2e               # Playwright journey over the mock feed (needs frontend/dist)
uv run uvicorn ledgerline.main:app --reload --port 7860    # backend; serves frontend/dist if built
cd frontend && npm run dev                   # frontend with hot reload, proxies /api to :7860
```

Every push and pull request runs the same gates on GitHub Actions (`.github/workflows/ci.yml`): the Python job
(ruff check and format, import contracts, pytest), the frontend job (eslint, prettier, tsc, vitest, build), the
browser job (the Playwright journey against the built frontend) and a Docker image build. Nothing in CI needs an
API key.

Paid or networked work is opt in, so plain `uv run pytest` never spends anything:

```bash
uv run pytest -m llm tests/agent                            # one real conversation through the tool handlers
PYTHONPATH=. uv run python -m evals.run_suite --runs 5      # simulated calls, all scenarios, about $0.45
TTS_PROVIDER=deepgram ./spike/run_once.sh <name>            # headless voice check, no Cartesia minutes spent
```

## Where it stands

| Gate | Result |
|---|---|
| `uv run pytest` | 871 passed |
| `npm run test` | 252 passed, 25 files |
| `uv run pytest -m e2e tests/e2e` | 7 passed |
| `ruff check`, `ruff format --check`, `lint-imports` | clean, 4 contracts kept |
| `eslint`, `prettier`, `tsc` | clean |
| system prompt | under a 620-token ceiling, measured with a tokenizer in the test suite |

The evaluation report is `evals/REPORT.md`. It records every simulation matrix in run order, replays the
current checks over 300 saved transcripts split by era, and states what the checks found and what they cannot
see. Three results from it:

- Across every measured change, an instruction that lived only in the prompt held between 0 and 80 percent of
  the time; the same instruction carried in the tool result string held between 96 and 100. The result string
  is where the model is certainly reading at the moment it has to act.
- The last full matrix after the domain cut: 24 of 25 simulated calls clean of every rule; the goodbye that
  had been at 28 percent went to 100 once its two instructions stopped contradicting each other.
- The check that compares recorded state to what the person said found a defect every other check had
  passed: a balance given in two fragments was stored as half its value. It is open, with a code-side fix
  and a result-string fix both specified and the measurement that decides between them named.

Open, in order of risk: the dropped half of the balance above; one recorded case of the model doing
arithmetic (14,000 minus 1,000 spoken as "thirteen thousand short"), fixed offline by always emitting surplus
and shortfall as a pair, not yet measured live; first audio at 1.8 to 2.2 seconds against a 1.4 second target;
one unexplained 9.3 second outlier in a single headless run; no live call yet on the post-cut build.

## How this was built

One person owned every decision. The typing was done by AI coding sessions under a fixed division of labour:
an orchestrator that verified and integrated, four worker sessions with one layer each and no rights over
anyone else's files, and a read-only reviewer on a different vendor's model that ran thirteen times and
raised 65 findings, each verified against the code before anything was dispatched. Test first throughout.
Research against source before any code; a prior-art pass after the first working build; a deliberate cut
when the review record showed where the defects clustered. The briefs, the per-layer ledgers, the requests
between layers, the review artifacts and the measurements are all in the repository:
`docs/README.md` gives the reading order, `docs/process/README.md` explains the method, and `JOURNAL.md` is
the owner's own account of the decisions.
