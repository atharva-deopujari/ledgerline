# Ledgerline

A real-time voice assistant that helps a person plan the next thirty days of their money. You talk; it asks
about what comes in and what goes out and when; it records every fact; a deterministic engine computes a
day-by-day plan; live cards update the moment you correct anything; and it walks you through the month in
plain words, with what you could do about it and what each thing costs. Built on Pipecat 1.9 and Daily,
with OpenAI `gpt-5.6-luna`, Deepgram Nova-3 and Cartesia Sonic. FastAPI backend, React + Vite + TypeScript
frontend, one Docker image.

**The one rule: the model never computes.** Every number the bot speaks came back in a tool result or was
just said by the person, and an evaluation check fails any run where that is not true. The one licence beyond
that is a reading offered as a question when an amount is implausibly small ("twelve rupees, or twelve
thousand?"), in the turn whose result asked for it.

## Run it

Requirements: Docker with Compose, and four API keys (below).

```bash
cp .env.example .env      # fill in the four keys
docker compose up --build
```

Open **http://localhost:7860** in Chrome or Edge, type a phone number, click Start, allow the microphone, and
talk. The phone number is the person's identity: the facts they state are remembered against it and read back,
as provisional, at the start of their next call. Compose also starts a Postgres container for that; without it,
or without `DATABASE_URL`, calls still work and nothing is remembered.

First build takes 3 to 5 minutes (Node build of the frontend, Python dependencies, model files). Later starts
take seconds. Use `localhost`, not `127.0.0.1`: browsers only grant microphone access on a secure context, and
`localhost` is exempt from HTTPS. Every call, real or simulated, is recorded as JSON under `evals/runs/`, which
is mounted into the container.

To see the interface without keys or a call, open `http://localhost:7860/?mock=1`: a scripted conversation
replays through the real components from generated snapshots.

With Langfuse keys in `.env`, every call is one trace in Langfuse: turns, each tool call with its arguments and
result, latency and tokens per service, the judge's scores. When a call ends the screen shows the judge's
verdict within about twenty seconds. `http://localhost:7860/review/users/<phone>` shows what is remembered
about a number, with the history of every changed figure and a forget button. The design is in
`docs/architecture/04-observability-hld.md`.

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
| `PROMPT_VERSION` | no | which file under `ledgerline/agent/prompts/` to load, default `v2`, the only version shipped since the redesign; it also names the prompt in Langfuse and is recorded against each call as `v2@N` | |
| `ROOM_EXPIRY_SECS` | no | Daily room lifetime, default 3600; rooms are private, self-clean, and are deleted after each call | |
| `IDLE_TIMEOUT_SECS` | no | cancel a call after this much silence, default 300 | |
| `JOIN_TIMEOUT_SECS` | no | free the call slot if the browser never joins, default 45 | |
| `END_GRACE_SECS` | no | after the goodbye, hang up when speech ends or after this many seconds, default 6 | |
| `LOG_LEVEL` | no | default `INFO` | |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` | no | tracing of every call (turns, tool calls, latency, tokens), prompt versions, judge scores; the keys' presence turns it on | https://cloud.langfuse.com, project settings, API Keys. Hobby plan is free, 50k units a month, 30 days retention |
| `LANGFUSE_ENVIRONMENT`, `LANGFUSE_PROJECT_ID` | no | `production`, `development` (default) or `simulation`; the project id only builds the trace link shown after a call | |
| `DATABASE_URL` | no | Postgres for who called and the facts they stated, so the next call from the same phone starts from them; Compose sets it for the app container; empty means no memory | the `postgres` service in `docker-compose.yml` |
| `PROFILE_MAX_AGE_DAYS` | no | facts older than this are history and never carried into a call, default 60 | |
| `PROMPT_SOURCE` | no | `langfuse` (default, versions with the `production` label, the file as fallback) or `file` | |
| `JUDGE_MODEL`, `JUDGE_REASONING_EFFORT`, `NOTES_MODEL` | no | the end-of-call judge and the soft-notes extractor; empty disables each; effort default `low` | |

Keys are read from `.env` by Compose and validated at boot; a missing required key stops the container with a
message naming every missing variable. Never commit `.env`.

## What it does

1. You click Start. The server creates a private Daily room, joins the bot to it, and hands your browser a
   token.
2. You speak. Deepgram transcribes; turn end is judged once, by the model's own turn-completion protocol with
   a few domain hints appended, so "I have..." followed by a pause does not end your turn.
3. For every fact you state the model calls a tool silently, in the words a person would use: `note`,
   `forget`, `nothing_more`. The tool writes into one `FinancialState` object, and the result comes back as
   facts with the numbers already computed: `rent 12,000 before, now 14,000`, then a line saying which
   categories are on the books, which you have said there are none of, and which have not come up yet. The
   model speaks once, after the result.
4. Every tool call re-runs the plan engine and pushes a full card snapshot to the browser over Daily's data
   channel. Correct a number and every affected card changes, because there is only one copy of the truth.
5. `show_month` can be called at any point and returns the whole picture. The engine simulates each of the
   thirty days, classifies the result (fine, timing shortfall, structural shortfall, unsolvable), proposes
   actions in a fixed priority order, and says plainly what stays unpaid if nothing works. It never proposes
   new borrowing. The result also carries the lowest point written out as a line per step, so when you ask
   why a figure is what it is the coach reads you the arithmetic rather than doing any of its own.
   `what_if` reruns the same engine over a copy for "skip the gym" or "pay the card in full" and reports
   what moved.
6. The model explains what you could do and what each thing costs, and when you agree it marks the plan
   final and calls `done` with whether you understood. The goodbye is its own words.

Code owns what must be correct: money (`Decimal`), dates, priority order, what has not come up yet, what
blocks the plan, every figure in a result. The model owns what needs understanding: whether a new number is a
correction or a contradiction, whether an amount sounds implausible, what to ask next and in what order,
when it knows enough to plan, whether you have understood. The coach leads the conversation; code informs it
with facts and commands only where a wrong move loses money. `docs/process/cut-brief.md` is that line written
down and `docs/process/agent-redesign-brief.md` is where it was redrawn.

## Repository layout

```
ledgerline/            Python package; imports flow one way: domain <- agent <- voice <- api (enforced)
  domain/              pure: models (contract), policy, state/ (fact store), engine/ (plan maths), cards
  agent/               tools/ the model calls (plain.py) and the result strings (facts.py), prompt, prompts/v2.md
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

Hot reload while developing, two ways:

```bash
# backend in the container restarts on any change under ledgerline/
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
# frontend with hot module reload, proxying /api to that container
cd frontend && npm run dev            # http://localhost:5173
```

The dev overlay mounts the source over the image copy and runs uvicorn with `--reload`; it also mounts
`frontend/dist`, so `npm run build -- --watch` refreshes what the container serves at 7860 if you would
rather not run Vite.

Paid or networked work is opt in, so plain `uv run pytest` never spends anything:

```bash
uv run pytest -m llm tests/agent                            # one real conversation through the tool handlers
PYTHONPATH=. uv run python -m evals.run_suite --runs 5      # simulated calls, all scenarios, about $0.45
TTS_PROVIDER=deepgram ./spike/run_once.sh <name>            # headless voice check, no Cartesia minutes spent
```

## Where it stands

| Gate | Result |
|---|---|
| `uv run pytest` | 1148 passed offline; 31 more with `DATABASE_URL` set (the store, against a real Postgres, as CI runs it) |
| `npm run test` | 357 passed, 38 files |
| `uv run pytest -m e2e tests/e2e` | 16 passed |
| `ruff check`, `ruff format --check`, `lint-imports` | clean, 7 contracts kept |
| `eslint`, `prettier`, `tsc` | clean |
| system prompt | about 330 tokens, under a 400-token ceiling measured with a tokenizer in the test suite |

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

Since then (13 Sep): the balance defect is closed (0 to 100 percent on `state_matches_facts`, both fixes needed
and the cell showed why), the arithmetic case is closed by the surplus and shortfall pair, and the observability
phase landed: every call traced to Langfuse with its tool calls, a Postgres memory keyed by phone that the next
call reads back as provisional until confirmed (ten of ten simulated returning calls clean, a carried rent giving
way to the newly spoken one in five of five), a soft-notes extractor bounded in code, and an end-of-call judge.
The judge is advisory: its first two calibration tables (`evals/REPORT.md` sections 10.6 to 10.8) show it
punishing deliberate brevity until its criterion was rewritten, missing the money defects the deterministic
rules caught, and never failing a register criterion the owner judges the model holds by default.

Since then (14 Sep): the owner's live call read as a bot working through a form, so the agent layer was
rebuilt as a coach that leads. The owner's own call was scripted from the recording and run five times on
each build (`docs/process/owner-call-1-report.md`): planning before a whole category had been raised went
from every run to none, traceable numbers from 60 to 100 percent, values claimed but never recorded from 80
to 100, and a decimal spoken aloud from 80 to 100 percent clean. The honest other half: two of the five
after runs never reached a plan at all, because the same instinct that stops premature planning has no brake
on it, and the run that states the lowest point still recites it rather than reading out the derivation the
result handed it.

Open, in order of risk: first audio at 1.8 to 2.2 seconds against a 1.4 second target; one unexplained 9.3
second outlier in a single headless run; the judge's agreement with human readings is measured on thirteen
runs and not yet trusted as a gate; knowing when to stop gathering, which is the cause of the runs that end
with nothing decided; no live call yet on the redesigned build.

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
