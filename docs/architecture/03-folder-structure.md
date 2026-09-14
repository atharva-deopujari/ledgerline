# Folder structure

Revised 2026-09-11 after review. The first draft (Appendix A) recommended Pipecat's flat seven-file layout.
We rejected it: the repo must read the way a senior engineer lays out a new service, so that a
second feature, a new card, a swapped TTS or a persistence layer has an obvious home. This version keeps
every verified fact from the research (pytest `pythonpath`, `addopts` markers, NLTK prebake, `uv sync --locked`,
`evals/` split, `JOURNAL.md` at root) and changes the shape.

## Decision summary

- **One Python package `ledgerline/` split by concern, imports flow one way:** `domain` ← `agent` ← `voice` ← `api`.
  `domain` imports nothing of ours and nothing of Pipecat or OpenAI. Enforced with an `import-linter` contract.
- **Frontend is a real project:** React 19 + Vite + TypeScript in `frontend/`, built in a Node stage of the same
  Dockerfile, `dist/` served by FastAPI. Still one compose service, one command, one port.
- **Tests mirror the package:** `tests/domain`, `tests/agent`, `tests/judge`, `tests/memory`, `tests/store`, `tests/voice`, `tests/api`, `tests/e2e`. Free tests run
  on plain `uv run pytest`; paid and browser tests are opt-in markers.
- **`evals/` is separate from `tests/`:** paid, non-deterministic, produces reports into `docs/eval-results/`.
- **Config is typed:** `ledgerline/config.py` with pydantic-settings, validated at boot, names the missing variable.
- **No folder holds one file for ceremony.** No `infrastructure/`, `services/`, `workers/`. Folders are added when
  a second file needs them. This is the line between "senior" and "enterprise" for a 1,500-line service.
- **Names a Pipecat developer expects:** `pipeline.py` builds the `PipelineWorker`, `session.py` runs one call,
  `agent/tools/` holds function handlers, `domain/engine/` holds plan math, `policy.py` holds the priority tiers.

## Recommended tree

```
ledgerline/
├── README.md                     Docker setup, env table, exact command, exact URL, results, AI honesty section
├── JOURNAL.md                    hand-written decision journal, dated entries, root-level on purpose
├── pyproject.toml                deps, dev group, pytest config, ruff, import-linter contracts (4)
├── uv.lock                       committed; Docker installs with --locked
├── .python-version               3.11
├── .env.example                  every variable, commented, required vs optional
├── .gitignore  .dockerignore
├── Dockerfile                    stage 1 node:22 builds frontend; stage 2 python:3.11-slim + uv, NLTK prebaked
├── docker-compose.yml            ONE service, port 7860, env_file .env
├── docker-compose.dev.yml        overlay: source mounted, uvicorn --reload; pair with `npm run dev` for frontend HMR
│
├── ledgerline/                   the Python package. import root: `from ledgerline.domain.engine import build_plan`
│   ├── config.py                 Settings(BaseSettings); TtsProvider, TurnStrategy, LlmApi enums
│   ├── main.py                   builds the FastAPI app, lifespan, mounts frontend/dist. `uvicorn ledgerline.main:app`
│   │
│   ├── domain/                   PURE. no I/O, no Pipecat, no OpenAI. internal layers: cards -> engine -> state -> policy -> models. No conflict or outlier state: the model judges corrections (docs/process/cut-brief.md)
│   │   ├── models.py             FinancialState and item models; enums PlanStatus, Phase, ActionType, RowKind, UnknownReason, OutcomeStatus
│   │   ├── policy.py             Policy: TierKey enum, tier order, consequence and ask text, allowed action types
│   │   ├── cards.py              (state, plan) -> CardsMessage; CardId and CardStatus enums; 4 KB guard. no transport
│   │   ├── rupees.py             whole(), reconciled(), in_rupees(summary): one rounding rule, totals derived from rounded parts
│   │   ├── state/                the fact store. public API re-exported from __init__ (upsert, remove, mark_unknown, ...)
│   │   │   ├── names.py          normalise_name, possessive_of, label_for, field_of, group_inr, resolve_day
│   │   │   ├── items.py          upsert overwrites and reports Outcome.changes (old -> new, speakable); remove
│   │   │   ├── unknowns.py       mark_unknown (UNKNOWN | NOT_APPLICABLE), missing_fields
│   │   │   └── readiness.py      blockers() shared with the engine; readiness(): phase, blockers, missing_fields
│   │   └── engine/               the plan maths. build_plan re-exported from __init__
│   │       ├── events.py         state -> dated events, one builder per item kind, exclusions and warnings
│   │       ├── simulate.py       day-by-day balance run
│   │       ├── settle.py         ranked reserve, settle passes, fixed point over hopeless obligations
│   │       ├── actions.py        defer, cut, pay-minimum, prune no-op optionals, ask-lender rows
│   │       └── plan.py           build_plan as an ordered orchestration of the steps above; summary
│   │
│   ├── agent/                    talks to the LLM. imports domain only, never pipecat
│   │   ├── prompt.py             load prompts/<version>.md; per-turn block: today and window, then the coverage lines
│   │   ├── prompts/v2.md         the base prompt (package data): who you are, what you are here to do, money, how you sound
│   │   └── tools/                build_tools(ctx, version), re-exported with ToolContext and facts
│   │       ├── context.py        ToolContext: state, cards version, replay guard, push
│   │       ├── coercion.py       argument coercion and allowed-value validation
│   │       ├── plain.py          note, forget, nothing_more, show_month, what_if, done. Names and arguments a person would say
│   │       ├── facts.py          result strings: facts and options, no orders; coverage lines, the lowest point a step per line
│   │       └── phrases.py        every result-string fragment and template as a named constant
│   │
│   ├── judge/                    recording in, Verdict out. imports agent (phrases) + domain; never infra (docs/architecture/04-observability-hld.md)
│   │   ├── checks/               the three deterministic checks (checks.py; spoken_numbers.py, provenance.py as helpers): money_traceable, state_matches_call, speakable
│   │   ├── criteria.py           four intent criteria with applies_when predicates in code
│   │   ├── llm.py                one structured-output call; model and reasoning effort supplied by the caller
│   │   ├── judge.py              run(recording) -> Verdict: deterministic first, then intent; never raises
│   │   └── models.py             Verdict, RuleResult, CriterionResult, Outcome (CONTRACT, mirrored in protocol/verdict.ts)
│   │
│   ├── memory/                   recording + existing notes in, soft notes out. imports judge.checks (amount parser) + domain
│   │   ├── vocabulary.py         NoteCategory StrEnum compiled into the structured-output schema
│   │   ├── extractor.py          one call at session end; notes with amounts, invented turns or bad indexes dropped in code
│   │   └── models.py             Note, NewNote, ExtractedNotes
│   │
│   ├── observability/            OpenTelemetry + Langfuse. imports config + domain only; Null twins when keys are empty
│   │   ├── tracing.py            one TracerProvider with the resource attributes, handed to Langfuse(tracer_provider=...); should_export_span keeps pipecat and ledgerline scopes
│   │   ├── attributes.py         StrEnum of every span attribute we set (user.id, session.id, langfuse.trace.*, ledgerline.*)
│   │   └── langfuse.py           LangfuseClient protocol, RealLangfuse (scores, prompts, trace url), NullLangfuse
│   │
│   ├── store/                    Postgres. imports domain.models + psycopg only; never config (open_store takes the dsn)
│   │   ├── schema.sql            users, sessions (slim), profile_facts, profile_notes; CREATE TABLE IF NOT EXISTS; money as text
│   │   ├── db.py                 async pool, schema at boot, Store protocol, PostgresStore, NullStore, open_store(dsn)
│   │   ├── models.py             SessionRow, ProfileFact, ProfileNote
│   │   ├── sessions.py           create, end, get
│   │   ├── profile.py            load_active(phone, deadline) -> facts | None; record_call(loaded=) diff + supersession; hydrate; history; forget
│   │   └── notes.py              same shape for soft notes
│   │
│   ├── voice/                    touches Pipecat and Daily. imports agent + domain
│   │   ├── pipeline.py           build_worker(state, settings) -> PipelineWorker. STT, LLM, TTS, VAD, aggregators, observers
│   │   ├── session.py            run_session(room_url, token): ordered steps; join, greeting, card push, prompt refresh, teardown
│   │   ├── lifecycle.py          GoodbyeWatcher, JoinWatchdog, CallEnder, Teardown
│   │   ├── recorder.py           per-call transcript to evals/runs; EndedBy, Role, LlmWarning enums; the `call` span with trace input and output
│   │   ├── tool_trace.py         observer: one `tool` span per executed function call, keyed by tool_call_id, under the current turn
│   │   └── transport.py          Daily room (private), tokens, transport; REST client bounded at 10 s
│   │
│   └── api/                      HTTP surface. imports voice
│       ├── routes.py             POST /api/sessions {phone} -> {room_url, token, session_id}; DELETE /api/sessions/{id}; GET /api/health;
│       │                         GET /api/sessions/{id}/verdict (202 while pending); DELETE /api/users/{phone}; GET /api/review/users/{phone};
│       │                         the console's five reads: GET /api/review/users, /calls?source&scenario, /calls/{id}, /evals, /report
│       ├── review.py             UserReview, ReviewFact, ReviewNote, ReviewCall and the console pages UsersPage, CallsPage, CallDetail, EvalsPage,
│       │                         ReportPage (CONTRACTS, mirrored in protocol/review.ts); recordings read once per (path, mtime), ids never become paths
│       ├── aftercall.py          the post-call task: end the session row, record_call(loaded=), extractor, judge, scores, verdict held in process
│       └── sessions.py           SessionRegistry: single slot reserved before the first await, cancel awaits teardown
│
├── frontend/                     React + Vite + TypeScript. built into the image, never served by Vite in prod
│   └── src/
│       ├── main.tsx  App.tsx  phone.ts (validate and remember the number)  route.ts (useRoute over location.pathname, no router dependency)
│       ├── call/                 useDailyCall.ts (thin hook) over lifecycle.ts (CallLifecycle class), dailyEvents.ts (typed adapter),
│       │                         types.ts, constants.ts, messages.ts, testDouble.ts; the POST carries {phone}, 422 is PHONE_REJECTED
│       ├── protocol/             types.ts, verdict.ts, review.ts (CONTRACTS) with sample.json, verdict.sample.json, review.sample.json and the console's
│       │                         users/calls/call/evals/report.sample.json, all generated from Python;
│       │                         parse.ts, markers.ts (untyped marker words, one definition each), fixtures.test.ts (every sample survives its type)
│       ├── console/              ConsoleShell + tabs, CallersScreen, CallsScreen, CallScreen, EvalsScreen, ReportScreen, useFetched(url, guard),
│       │                         guards.ts (every page parsed at the boundary), markdown.tsx (about 150 lines, React elements, no HTML string)
│       ├── state/sessionReducer.ts
│       ├── mock/                 install.ts (answers only the POST and DELETE that start and cancel a call), script.ts, snapshots.json (generated; five frames, `returning` first)
│       ├── components/           LedgerCard, CardRows, CardKv, CardStack, StatusBadge, PlanPanel, PhaseStrip, Timeline, TotalsBar, LowestPoint,
│       │                         MissingChips, QuestionHeadline, VoiceBar, ErrorBanner, VerdictPanel, ForgetButton, format.ts, useChangedRows.ts
│       ├── verdict/              useVerdict.ts (poll GET /api/sessions/{id}/verdict after `ended`, two seconds, one minute), parse.ts (type guard, a trust boundary)
│       ├── review/               ReviewPage.tsx (/review/users/{phone}: remembered, replaced, said in words, calls), useUserReview.ts
│       └── styles/
│
├── tests/                        free, offline, fast. `uv run pytest` runs exactly this
│   ├── conftest.py
│   ├── domain/                   state/ (mirrors the package), test_engine.py, test_cards.py, test_policy.py, fixtures/
│   ├── agent/                    test_plain.py, test_prompt.py, test_integration_domain.py, test_harness*.py, test_run_suite.py, test_managed_prompt.py
│   ├── judge/  memory/           checks/ moved with the code; criteria, llm (fake model), judge, extractor
│   ├── observability/            in-memory exporter over a real TurnTraceObserver: tree, types, parents, attributes, trace id
│   ├── store/                    marker db: real Postgres from compose or the CI service container; NullStore tests always run
│   ├── voice/  api/
│   └── e2e/                      Playwright, marker e2e; static_server.py serves the built app for any path, shared by conftest.py and capture_screens.py
│
├── evals/                        paid, non-deterministic, opt-in
│   ├── harness.py  sim_user.py  checks.py  spoken_numbers.py  provenance.py   (the last three are shims over ledgerline/judge/checks)
│   ├── scenarios/*.yaml
│   └── runs/                     recorded calls, real and simulated
│
├── scripts/                      dump_mock_snapshots.py
├── spike/                        throwaway measurement scripts; drive.py is a headless second participant
└── docs/                         README.md (reading order)  research/  architecture/  reference/  process/
```

## Dependency contract

```toml
[tool.importlinter]
root_package = "ledgerline"

[[tool.importlinter.contracts]]
name = "layers"
type = "layers"
layers = ["ledgerline.api", "ledgerline.voice", "ledgerline.agent", "ledgerline.domain"]

[[tool.importlinter.contracts]]
name = "domain is pure"
type = "forbidden"
source_modules = ["ledgerline.domain"]
forbidden_modules = ["pipecat", "openai", "fastapi", "httpx"]
```

`uv run lint-imports` in CI and before every commit. This is the one-line proof that the engine is testable in
isolation and that swapping Pipecat for another transport would touch only `voice/`.

## Frontend build and serve

- Dev: `npm run dev` in `frontend/` proxies `/api` to `localhost:7860` (vite.config.ts `server.proxy`). Backend
  runs with `uv run uvicorn ledgerline.main:app --reload`.
- Prod (Docker): stage 1 `node:22-alpine` runs `npm ci && npm run build`; stage 2 copies `frontend/dist` to
  `/app/frontend/dist`; `ledgerline/main.py` mounts it with `StaticFiles(html=True)` after the API router so `/api/*`
  wins. One image, one process, one port.
- The card protocol is typed twice on purpose: Pydantic in `domain/cards.py`, TypeScript in `protocol/types.ts`.
  A test in `tests/domain/test_cards.py` dumps a sample `CardsMessage` to `frontend/src/protocol/sample.json`;
  a Vitest test parses it with `parse.ts`. If the shapes drift, one side fails.

## Config skeletons

### pyproject.toml

```toml
[project]
name = "ledgerline"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "pipecat-ai[daily,deepgram]==1.9.0",
  "fastapi",
  "uvicorn[standard]",
  "pydantic>=2",
  "pydantic-settings",
  "python-dotenv",
  "loguru",
]

[dependency-groups]
dev = ["pytest", "pytest-asyncio", "pytest-httpx", "ruff", "import-linter", "playwright", "pyyaml"]
evals = ["openai", "pyyaml"]

[tool.pytest.ini_options]
pythonpath = ["."]
asyncio_mode = "auto"
markers = [
  "llm: calls a paid LLM, needs OPENAI_API_KEY",
  "e2e: drives a browser with Playwright",
]
addopts = "-m 'not llm and not e2e'"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]
```

### Dockerfile

```dockerfile
# stage 1: frontend
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# stage 2: app
FROM python:3.11-slim-bookworm
ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 NLTK_DATA=/opt/nltk_data
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
RUN uv run python -c "import nltk; nltk.download('punkt_tab', download_dir='/opt/nltk_data')"
COPY ledgerline/ ./ledgerline/
COPY --from=web /web/dist ./frontend/dist
RUN useradd -m app && chown -R app /app
USER app
EXPOSE 7860
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:7860/api/health')"
CMD ["uv", "run", "--no-sync", "uvicorn", "ledgerline.main:app", "--host", "0.0.0.0", "--port", "7860"]
```

### docker-compose.yml

```yaml
services:
  ledgerline:
    build: .
    ports: ["7860:7860"]
    env_file: .env
    restart: "no"
```

### .dockerignore

```
.git
.venv
node_modules
frontend/node_modules
frontend/dist
docs
tests
evals
.env
*.md
!README.md
```

## Why this and not a larger service's shape

A production multi-agent chat service the owner has worked on has `graph/ supervisor/ agents/ nodes/ tools/
models/ services/ api/ workers/ infrastructure/ config/ prompts/ observability/ migrations/`. That is right for a
service with Redis checkpoints, Alembic and 243 test files. Here it would mean fourteen folders for eight
modules, and the first live question becomes "why is there an `infrastructure/` package with one file". The
four-concern split keeps the property that matters from that shape (one-way imports, tests mirroring code,
typed config) and drops the folders that have not earned a second file yet. Persistence arrived on 13 Sep as
`ledgerline/store/` and `domain` still does not know about it.

## Appendix A. Original flat-layout research: why flat and not src/

**Flat root modules, not `app/`, not `src/`.** All three work. The tiebreaker is the live session: with
root modules the operator's `ls` is the module list, imports in `bot.py` read `from engine import
build_plan`, and there is no `__init__.py` re-export layer to explain. `src/` buys import isolation that
only matters when the project is also installed as a distribution, and it requires a `[build-system]`
plus an editable install before anything runs.
The cost of flat is real but small: `tests/` cannot import root modules by default. **(verified locally)**
`uv run pytest` on `tests/test_engine.py` doing `from engine import add` fails with
`ModuleNotFoundError` because pytest's prepend import mode inserts `tests/`, not the rootdir, into
`sys.path`. Two one-line fixes both work **(verified locally)**: an empty `conftest.py` at the root, or
`pythonpath = ["."]` in `[tool.pytest.ini_options]`. We use `pythonpath = ["."]` because it is declared
where a reader is already looking, and it survives someone deleting a mysteriously empty file.

**`tests/` flat, not `tests/unit/ + tests/conversation/ + tests/voice/`.** Six test files do not need
three subdirectories. The split that matters is cost and determinism, and that is a directory boundary
(`tests/` vs `evals/`) plus one marker, not a tree. Moving the text harness out of `tests/` also fixes a
real import problem: harness modules importing each other inside `tests/` needs `__init__.py` files or an
extra pythonpath entry. In `evals/` with `pythonpath = ["."]`, everything imports it the same way.

**`evals/` at the root, not `tests/conversation/`.** Pipecat 1.4+ ships its own eval runner and the CLI
scaffold creates `evals/` next to `bot.py`. Putting our text harness anywhere else means two eval
directories, and the first question in the live session becomes "why are there two?".

**`evals/SMOKE.md`, not `tests/voice/SMOKE.md`.** It is a human checklist, not a collected test.
Under `tests/` it would be the only file pytest never runs.

**Prompt files, not Python constants.** `git log -p prompts/v2.md` is a one-line answer to "show me what
changed in the prompt", and a second file beside it is how a new version starts. Constants force a git-history diff, which is
slower to produce on a shared screen. The `prompts/` directory costs one `COPY` line in the Dockerfile.

**`engine.py`, not `planner.py`.** "Planner" in agent vocabulary means an LLM that decides steps; this
file is arithmetic. `engine.py` matches "plan engine" in `01-tech-stack.md` and the module docstring
removes any remaining ambiguity. **`tools.py`, not `functions.py`** — Pipecat's API is `FunctionSchema`
/ `ToolsSchema` and the docs say "tools"; `functions.py` reads like a utility grab-bag.

**One `frontend/index.html`.** Pipecat examples do both `daily-custom-tracks/index.html` and
`code-helper/client/index.html`; `frontend/` names the thing without implying a build output directory
the way `dist/` or `static/` would. Serve it with
`app.mount("/", StaticFiles(directory="frontend", html=True))` registered **after** the API routes —
Starlette matches mounts in registration order. (FastAPI now also has `app.frontend("/", directory=...)`,
which is checked only after normal routes; `StaticFiles` is the form that is stable across versions.)

**No Makefile.** Four commands, all short: `docker compose up --build`, `uv run pytest`,
`uv run pytest -m llm`, `uv run pipecat eval suite evals/manifest.yaml`. A Makefile would add a file
whose only content is those four strings with worse error messages.

**Docker COPY list.** The image needs: `pyproject.toml`, `uv.lock`, `*.py`, `prompts/`, `frontend/`.
It does not need `tests/`, `evals/`, `docs/`, `JOURNAL.md`. `uv.lock` goes in and is installed with
`uv sync --locked --no-dev` so the operator's build resolves to the versions we tested —
this is the pattern in Pipecat's own `Dockerfile.jinja2` and in `p2p-webrtc/docker/Dockerfile`.
**NLTK is a hard dependency of `pipecat-ai`** (`nltk>=3.10.0,<4`), and `pipecat/utils/string.py` states
verbatim that `punkt_tab` "load[s] on first use, and the data is downloaded if it isn't already present.
Deployments that build their own image should bundle it at build time (`python -m nltk.downloader
punkt_tab`) or point `NLTK_DATA` at a directory that already has it, so that a slow or unavailable
network can't delay the first bot turn." So: prebake into `/opt/nltk_data` and set `NLTK_DATA`.
Silero VAD and Smart Turn v3 ship inside the wheel and need no prebake.

## Appendix B. Original config skeletons (flat layout, superseded by the skeletons above)

### `pyproject.toml`

```toml
[project]
name = "finance-voice"
version = "0.1.0"
description = "Real-time voice finance planner (Pipecat + Daily)"
requires-python = ">=3.11"
dependencies = [
    "pipecat-ai[daily,deepgram,cartesia,openai,silero,turn-detector-v3]==1.9.0",
    "fastapi>=0.141,<1",
    "uvicorn[standard]>=0.38",
    "pydantic>=2.12,<3",
    "python-dotenv>=1.1",
    "pyyaml>=6.0",
]

# No [build-system]: this is an application, not a distribution. uv will not
# try to install the project itself, and `uv run` still uses the locked venv.

[dependency-groups]
dev = [
    "pytest>=9.1",
    "pytest-asyncio>=1.3",
    "hypothesis>=6.140",
    "ruff>=0.16",
]

[tool.pytest.ini_options]
# Flat layout: put the repo root on sys.path so tests can `from engine import ...`
pythonpath = ["."]
testpaths = ["tests"]
# Default run is free and offline. -m on the CLI overrides this line.
addopts = "-q --strict-markers -m 'not llm'"
asyncio_mode = "auto"
markers = [
    "llm: hits a paid LLM API; excluded by default, run with `uv run pytest -m llm`",
    "slow: takes more than a second",
]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "ASYNC"]
```

Marker behaviour **(verified locally, pytest 9.1.1)**: `uv run pytest` → paid tests deselected;
`uv run pytest -m llm` → only paid tests run (the CLI `-m` replaces the one in `addopts`).

### `.dockerignore`

```
.git
.gitignore
.venv
__pycache__/
*.py[cod]
.pytest_cache/
.ruff_cache/
.hypothesis/

# Secrets must never enter the build context
.env
*.env
!.env.example

# Not needed at runtime
docs/
tests/
evals/
JOURNAL.md
*.md
!README.md

# Pipecat eval artifacts
*.eval.log
*.debug.log
```

### Dockerfile essentials (layout-relevant lines only)

```dockerfile
FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:0.10.0 /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy NLTK_DATA=/opt/nltk_data

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

# Pipecat's sentence splitter downloads punkt_tab on first use otherwise —
# that download would land on the user's first spoken turn.
RUN uv run python -m nltk.downloader -d /opt/nltk_data punkt_tab

COPY *.py ./
COPY prompts/ prompts/
COPY frontend/ frontend/

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 7860
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "7860"]
```

`docker-compose.yml` is one service (`build: .`, `ports: ["7860:7860"]`, `env_file: .env`), so
`docker compose up --build` then `http://localhost:7860` satisfies the one-command rule.

### `.env.example` shape

Group by vendor, one comment line per variable stating purpose and required/optional, values empty.
This mirrors Pipecat's `env.example.jinja2`, which groups as `# Daily (Transport)`,
`# Deepgram (STT)`, `# OpenAI (LLM)`, `# Cartesia (TTS)` with blank values and `# Optional:` prefixes.

## Sources

- Pipecat CLI server templates (`bot_cascade.py.jinja2`, `server_*.py.jinja2`, `Dockerfile.jinja2`, `env.example.jinja2`, `pyproject.toml.jinja2`, `evals/starter_text.yaml.jinja2`, `gitignore.jinja2`): https://github.com/pipecat-ai/pipecat/tree/main/src/pipecat/cli/templates
- Pipecat quickstart (`pipecat init quickstart`, `uv run bot.py`, `http://localhost:7860/client`): https://docs.pipecat.ai/pipecat/get-started/quickstart
- Pipecat CLI repo (`pipecat init` project structure, `server/bot.py`): https://github.com/pipecat-ai/pipecat-cli
- Pipecat examples repo tree (flat `bot.py` + `server.py` + `evals/` per example): https://github.com/pipecat-ai/pipecat-examples
- `ivr-navigation/evals/manifest.yaml` (`bots_dir`, `scenarios_dir`, `runs_dir`, `uv run pipecat eval suite`): https://github.com/pipecat-ai/pipecat-examples/blob/main/ivr-navigation/evals/manifest.yaml
- Pipecat Evals overview (text vs audio mode, `-t eval`): https://docs.pipecat.ai/pipecat/evals/overview
- `p2p-webrtc/docker/Dockerfile` (uv + `uv sync --locked --no-install-project --no-dev` + `uvicorn server:app`): https://github.com/pipecat-ai/pipecat-examples/blob/main/p2p-webrtc/docker/Dockerfile
- Pipecat NLTK `punkt_tab` prebake instruction (module docstring): https://github.com/pipecat-ai/pipecat/blob/main/src/pipecat/utils/string.py
- Pipecat root `pyproject.toml` (`nltk>=3.10.0,<4`, pytest `pythonpath`, ruff config): https://github.com/pipecat-ai/pipecat/blob/main/pyproject.toml
- uv project init (`--app` vs `--package` vs `--no-package`, src layout only when packaged): https://docs.astral.sh/uv/concepts/projects/init/
- uv in Docker (pinned uv binary, `--locked`, cache mounts): https://docs.astral.sh/uv/guides/integration/docker/
- PyPA src-layout vs flat-layout (scoped to distributable packages only): https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/
- pytest import modes and `pythonpath`: https://docs.pytest.org/en/stable/explanation/pythonpath.html
- pytest markers (`markers`, `-m` expressions, `--strict-markers`): https://docs.pytest.org/en/stable/example/markers.html
- FastAPI static files (`StaticFiles(html=True)`, `app.frontend()`): https://fastapi.tiangolo.com/tutorial/static-files
