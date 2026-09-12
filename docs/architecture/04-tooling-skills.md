# Tooling: Claude Code skills, plugins, and MCP servers

Researched 2026-09-11. Every URL was fetched live and every repo checked via the GitHub API for stars and
`pushed_at`. The filter was deliberate: this build must be defended line by line, so the test was **"does this
raise correctness or let me verify a claim?"** — not "does this generate code faster". Seven installs.

The most valuable find: **Pipecat publishes first-party agent guidance**, including a local MCP server that
AST-indexes the framework source at a pinned version.

## Install these

| # | Name | Source | What it does | Why this build | Install | Maintained? |
|---|---|---|---|---|---|---|
| 1 | **pipecat-context-hub** (MCP) | https://github.com/pipecat-ai/pipecat-context-hub | Local MCP server that indexes docs.pipecat.ai (200+ pages), the framework's Python API via AST, and `pipecat-examples`; returns answers with source citations | Our main risk is stale Pipecat API knowledge. `check_deprecation` verifies an import across versions and searches take a `pipecat_version` arg — exactly the `PipelineTask`→`PipelineWorker` / `PipelineRunner`→`WorkerRunner` error class that would sink a live defence. | `uv tool install pipecat-ai-context-hub`<br>`pipecat-context-hub refresh --framework-version v1.9.0`<br>`pipecat-context-hub install --client claude-code` | Official `pipecat-ai` org. **Pushed 2026-09-11 (today)**, v0.7.0 on PyPI. Only 8★ — new, not unmaintained. |
| 2 | **evals-skills** (Hamel Husain) | https://github.com/hamelsmu/evals-skills | 7 skills: `write-judge-prompt`, `validate-evaluator`, `error-analysis`, `eval-audit`, `generate-synthetic-data` | *Methodology, not a framework* — fits our "no eval framework to defend" decision. `write-judge-prompt` enforces binary pass/fail per failure mode; `validate-evaluator` makes us split human labels train/dev/test and hit TPR/TNR >90% before trusting the judge. Turns "we have a judge" into a defensible claim. | `/plugin marketplace add hamelsmu/evals-skills`<br>`/plugin install evals-skills@hamelsmu-evals-skills` | 1,664★, pushed 2026-08-16. By the author of the "AI Evals for Engineers & PMs" course. Hand-written, verified 7 non-empty SKILL.md. |
| 3 | **pyright-lsp** | anthropics/claude-plugins-official | Registers Pyright as a language server so Claude sees live type diagnostics on every `.py` edit | Catches `Decimal`/`float` mixing, wrong Pydantic field types, and bad Pipecat async signatures *at edit time* rather than at runtime in a voice call. Pipecat's own repo ships a `pyrightconfig.json`, so we inherit their standard. | `/plugin install pyright-lsp@claude-plugins-official` | Anthropic-authored, in the official directory (36,134★, pushed today). |
| 4 | **pipecat** (`/pipecat:init`) | https://github.com/pipecat-ai/skills | Official Pipecat skill that drives `pipecat init` from `--list-options` instead of hardcoded service lists | Generates a **reference scaffold for our exact stack** to diff hand-written code against — ground truth for the Dockerfile, `bot.py` wiring, and service names. | `/plugin marketplace add pipecat-ai/skills`<br>`/plugin install pipecat@pipecat-skills` | Official org, 25★, pushed 2026-07-13. Small but first-party. |
| 5 | **pydantic** | https://github.com/pydantic/skills | Pydantic v2 modelling: constraints, validators, coercion, discriminated unions | Our entire call state is one Pydantic object. The skill is unusually honest — it argues *against* using Pydantic for internally-constructed classes, which is precisely the kind of trade-off a operator will probe. | `/plugin marketplace add pydantic/skills`<br>`/plugin install pydantic@pydantic-skills` | Pydantic org's own repo. 133★ but pushed **2026-09-11**. Skip the `ai` / `pydantic-ai-harness` plugins. |
| 6 | **webapp-testing** | https://github.com/anthropics/skills/tree/main/skills/webapp-testing | Native Python Playwright scripts plus `scripts/with_server.py`, which manages backend+frontend server lifecycle | The only way to prove the vanilla-JS + daily-js page really joins a room and renders cards. Needs **no MCP** — ours is disconnected. Copy the one folder; the full `example-skills` bundle duplicates `frontend-design` and `skill-creator`. | `git clone --depth 1 https://github.com/anthropics/skills /tmp/askills`<br>`cp -r /tmp/askills/skills/webapp-testing .claude/skills/` | Anthropic, 175,782★, pushed 2026-09-10. |
| 7 | **Vendor docs MCPs** (no auth) | see URLs | JSON-RPC docs search for Daily and OpenAI | Daily publishes *no* skill or plugin anywhere, so its docs MCP is the only agent-shaped Daily artifact that exists. Useful for `app-message` size limits and token/`exp` semantics. | `claude mcp add --transport http daily-docs https://docs.daily.co/mcp`<br>`claude mcp add --transport http openai-docs https://developers.openai.com/mcp` | Both verified `POST 200` today; OpenAI's reports `serverInfo: openai-docs-mcp v1.0.0`. |

## Already have, do not reinstall

`superpowers` (brainstorming, TDD, systematic-debugging, writing/executing-plans, verification-before-completion,
code review) · MCP: `context7`, `langfuse-docs`, `github`, `claude-in-chrome`, `playwright` (disconnected) ·
`code-review` · `simplify` · `security-review` · `frontend-design` · `dataviz` · `artifact-design` ·
`claude-api` · `skill-creator` · all `gsd-*` · `vercel` · `caveman` · `ponytail`.

Superpowers already covers red/green TDD and verification-before-completion better than anything in the
community sweep — which is why no TDD or testing skill appears above.

## Evaluated and rejected

**Vendor**
- `deepgram/skills` (17★, 2026-08-13) — real and official, but Pipecat wraps the Deepgram params we care about; `03-stt.md` already pins `nova-3-general` / `smart_format` / `numerals` / `keyterm`.
- `cartesia-ai/skills` (5★) and the Cartesia MCP — the MCP needs an OAuth sign-in and the skill adds nothing over `04-tts.md`. Its rules prompt at https://docs.cartesia.ai/tools/ai/agent-guide is worth reading once, not installing.
- `deepgram/mcp` (1★) — stale, superseded by `dg mcp` in the CLI.
- `pipecat-cloud` / `pipecat-mcp-server` — we self-host in Docker; `/talk` (voice-control Claude) is a demo.
- `pipecat-dev-skills` — workflow skills for *contributing to* Pipecat, not consuming it.
- No Daily-owned skill/plugin exists in `daily-co`; no OpenAI Claude Code skill exists.

**Official marketplace**
- `deepeval`, `mlflow`, `langfuse` — external eval frameworks with dashboards; already rejected in `01-tech-stack.md`, and we have the langfuse-docs MCP.
- `pydantic-ai`, `logfire` — the Pydantic *agent framework* and a vendor observability SaaS. Neither is in the stack.
- `mattpocock-skills` — good TDD content, fully overlaps superpowers.
- `code-simplifier`, `pr-review-toolkit`, `code-review` — duplicates of `simplify` / `code-review`.
- `chrome-devtools-mcp` — duplicates claude-in-chrome.

**Community mega-repos** (all rejected for volume-over-quality; stars are SEO, not signal)
- `alirezarezvani/claude-skills` (25,835★) — 380 generated skills, no quality gate.
- `wshobson/agents` (39,567★) — real and maintained, but breadth-first and duplicates every pick above.
- `Jeffallan/claude-skills` (11,418★) — "expert persona" skills; persona-shaped, not procedure-shaped.
- `addyosmani/agent-skills` (93,502★) — 25 hand-written skills, genuinely decent, but its TDD/code-review/debugging skills collide head-on with superpowers. Cherry-pick by name only if a gap appears.
- `yonatangross/orchestkit`, `laurigates/claude-plugins` (435 skills / 58★), `TheBushidoCollective/han`, `manutej/luxor-claude-marketplace`, `Mindrally/skills` — volume signals; the last is auto-converted Cursor rules.
- `softaworks/agent-toolkit` — `skill-judge` judges *skills*, not model output; 6 months stale. `Gentleman-Programming/Gentleman-Skills` — its pytest skill 404s at the documented path.
- `astral-sh/claude-code-plugins` (307★) — first-party `uv`/`ruff`/`ty` skills, but **no commit since 2026-02-27** and our uv surface is three commands in a Dockerfile.
- `awesome-claude-skills` lists (ComposioHQ, travisvn, BehiSecc, karanb192) — link directories, nothing installable.

**Gaps with no credible skill** — write these as project-local `CLAUDE.md` rules instead: `Decimal` money math
(every hit was crypto token decimals or FP&A), Docker Compose, vanilla JS without a framework, and pytest
specifically.

## Official vendor agent guidance found

Pipecat is the standout: it is the only vendor in this stack shipping a complete agent toolchain.

| Artifact | URL | Status |
|---|---|---|
| **Pipecat AGENTS.md** (canonical) | https://raw.githubusercontent.com/pipecat-ai/pipecat/main/AGENTS.md | ✅ `CLAUDE.md` is literally `@AGENTS.md`. Documents the frame/processor/worker architecture and the deprecations. |
| Pipecat coding-agent guide | https://docs.pipecat.ai/pipecat/get-started/ai-tools | ✅ "Build with a coding agent (recommended)" |
| Pipecat `llms.txt` | https://docs.pipecat.ai/llms.txt | ✅ 200, ~107 KB index |
| Pipecat `llms-full.txt` | https://docs.pipecat.ai/llms-full.txt | ✅ 200 but **3.6 MB** — too large to inline. Use the Context Hub instead; that is the point of it. |
| Pipecat docs MCP | https://docs.pipecat.ai/mcp | ✅ POST 200 (Mintlify) |
| **Pipecat Evals** | https://docs.pipecat.ai/pipecat/fundamentals/evaluations/overview | ✅ See note below |
| Daily | https://docs.daily.co/llms.txt · https://docs.daily.co/llms-full.txt (2.2 MB) · https://docs.daily.co/mcp | ✅ all 200. No skill/plugin. |
| Deepgram | https://developers.deepgram.com/llms.txt · https://developers.deepgram.com/_mcp/server | ✅. ⚠️ `llms-full.txt` is byte-identical to `llms.txt` — an alias, not a full dump. |
| Cartesia | https://docs.cartesia.ai/llms.txt · https://docs.cartesia.ai/llms-full.txt (642 KB) · https://docs.cartesia.ai/mcp | ✅ all 200 |
| OpenAI | https://developers.openai.com/llms.txt · https://platform.openai.com/docs/llms.txt · https://developers.openai.com/mcp | ✅. ⚠️ `platform.openai.com/llms.txt` is **404**; use the `/docs/` path. |
| AGENTS.md convention | https://agents.md/ (repo now `agentsmd/agents.md`, 24,285★) | ✅ site 200; `agents.md/AGENTS.md` is 404. |

### Two findings that touch the design, not just tooling

**1. `pipecat init` generates a reference implementation of our exact stack.** Run it in a throwaway
directory and diff, rather than adopting it:

```bash
uv tool install "pipecat-ai[cli]"
pipecat init ref-bot --bot-type web --transport daily --mode cascade \
  --stt deepgram_stt --llm openai_llm --tts cartesia_tts --client-framework vanilla
```

`--client-framework vanilla` matches our no-build-step frontend decision. It writes `AGENTS.md`, `CLAUDE.md`,
`GETTING_STARTED.md`, `server/bot.py`, `Dockerfile`, and `client/`. `--dry-run` previews without writing.

**2. Pipecat ships a behavioural eval framework with a text mode and an LLM judge** (since 1.4.0, in the
`pipecat-ai[evals]` extra — a dependency we already have, not a new one). Text mode skips STT/TTS entirely
while exercising the real pipeline and context handling, scenarios are YAML (`turns:`/`expect:` scripted, or
`persona:`/`goal:`/`success:`/`metrics:` simulated), function-call assertions are supported, and the judge runs
on Ollama by default or any OpenAI-compatible endpoint.

This **conflicts with our recorded decision** in `01-tech-stack.md` ("no eval framework to defend"). It is not
a free win — it is still a framework whose YAML semantics we would have to defend. Keep our own harness, but
read the scenario schema and steal its shape (`expect: [{event: response, eval: "..."}]`), so that "why not
`pipecat eval`?" has a considered answer rather than "I didn't know it existed."

## Sources

Pipecat: [skills](https://github.com/pipecat-ai/skills) · [context-hub](https://github.com/pipecat-ai/pipecat-context-hub) · [ai-tools](https://docs.pipecat.ai/pipecat/get-started/ai-tools) · [evals](https://docs.pipecat.ai/pipecat/fundamentals/evaluations/overview) · [AGENTS.md](https://raw.githubusercontent.com/pipecat-ai/pipecat/main/AGENTS.md) · [CLI init](https://docs.pipecat.ai/api-reference/cli/init.md).
Anthropic: [claude-plugins-official](https://github.com/anthropics/claude-plugins-official) · [skills](https://github.com/anthropics/skills).
Others: [hamelsmu/evals-skills](https://github.com/hamelsmu/evals-skills) · [pydantic/skills](https://github.com/pydantic/skills) · [deepgram/skills](https://github.com/deepgram/skills) · [cartesia-ai/skills](https://github.com/cartesia-ai/skills) · [agents.md](https://agents.md/) · [skills.sh](https://skills.sh).
