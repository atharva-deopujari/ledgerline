# Dev tooling setup (done 2026-09-11)

What was installed on the dev machine so Claude Code has current Pipecat knowledge and live type checks.
None of this is needed to run the app; the app runs from `docker compose up --build` alone.

## Installed

| Tool | Command used | Purpose |
|---|---|---|
| Python 3.11.14 | `uv python install 3.11` | matches `requires-python` of pipecat-ai 1.9.0 and the Docker base image |
| pipecat-context-hub v0.7 | `uv tool install pipecat-ai-context-hub` then `pipecat-context-hub refresh --framework-version v1.9.0` then `pipecat-context-hub install --client claude-code` | local MCP: AST index of Pipecat 1.9.0 API, 478 doc pages, examples. `check-deprecation` catches removed names |
| Pipecat CLI 1.9.0 | `uv tool install "pipecat-ai[cli]"` | `pipecat init` reference scaffold, `pipecat eval` later |
| pyright 1.1.414 | `npm i -g pyright` plus plugin `pyright-lsp@claude-plugins-official` | live type diagnostics on every edit |
| evals-skills | `claude plugin marketplace add hamelsmu/evals-skills`, `claude plugin install evals-skills@hamelsmu-evals-skills` | judge-prompt and evaluator-validation methodology for the eval suite |
| pipecat skill | `claude plugin marketplace add pipecat-ai/skills`, `claude plugin install pipecat@pipecat-skills` | drives `pipecat init` from live option lists |
| pydantic skill | `claude plugin marketplace add pydantic/skills`, `claude plugin install pydantic@pydantic-skills` | Pydantic v2 modelling guidance |
| webapp-testing skill | copied from `anthropics/skills` into `.claude/skills/webapp-testing/` | Playwright scripts with server lifecycle helper, no MCP needed |
| daily-docs MCP | `claude mcp add --transport http daily-docs https://docs.daily.co/mcp` | Daily REST and daily-js docs search |
| openai-docs MCP | `claude mcp add --transport http openai-docs https://developers.openai.com/mcp` | OpenAI API docs search |

## Reference material fetched

- `docs/reference/pipecat-AGENTS.md`: Pipecat's own coding-agent guide, verbatim from `pipecat-ai/pipecat` main.
- `docs/reference/pipecat-scaffold/`: the bot, Dockerfile, pyproject, client that `pipecat init` generates for
  our exact stack (Daily, Deepgram, OpenAI, Cartesia, vanilla client). For diffing against, not for importing.

## Verify

```bash
pipecat-context-hub status
pipecat-context-hub check-deprecation PipelineTask
pipecat-context-hub search-api PipelineWorker
claude mcp list          # pipecat-context-hub, daily-docs, openai-docs should show Connected
claude plugin list       # pyright-lsp, evals-skills, pipecat, pydantic
pyright --version
```

## Not installed, on purpose

- Anthropic `example-skills` bundle: duplicates skills already present (frontend-design, skill-creator).
- Pydantic `ai` and `pydantic-ai-harness` plugins: we are not using Pydantic AI.
- Any eval framework (DeepEval, promptfoo, Braintrust): see `docs/research/11-testing-evals.md`.
