# Documentation

Reading order for someone new to the codebase. Each step is short and points at the longer
material behind it.

| # | Read | What it settles |
|---|---|---|
| 1 | `../README.md` | How to run it, what it does, current test and eval numbers |
| 2 | `architecture/01-tech-stack.md` | Every stack choice in one line each, with what was rejected and why |
| 3 | `architecture/02-hld.md` | The design: components, one user turn, state, tools, plan engine, cards, prompt, lifecycle |
| 4 | `architecture/03-folder-structure.md` | Where everything lives and the import direction that is enforced |
| 4b | `architecture/04-observability-hld.md` | Tracing to Langfuse, sessions and memory in Postgres, the end-of-call judge, the review page |
| 4c | `research/13-agent-design.md` | Goal versus rules, instruction overload, and what the literature does and does not support about results beating prompts |
| 5 | `research/00-index.md` | What was verified against source before any code, and where docs and framework disagreed; report 12 is the observability survey, report 13 the agent-design survey |
| 6 | `research/prior-art/00-index.md` | What other people built, ranked list of what was adopted |
| 7 | `process/README.md` | How the build was run: sessions, briefs, ledgers, reviews, the cut |
| 8 | `process/cut-brief.md` | The current line between what code decides and what the model decides |
| 8b | `process/observability-brief.md` | The work split and acceptance line for the observability phase |
| 8c | `process/agent-redesign-brief.md` | Why the agent layer was rebuilt: identity over prohibition, plain-word tools, results that state facts |
| 8d | `process/owner-call-1-report.md` | The owner's own call re-run before and after the redesign, the two transcripts side by side |
| 9 | `../evals/REPORT.md` | What is measured, how, and what the measurements found |
| 10 | `../JOURNAL.md` | The owner's decision journal |

## Folders

- `architecture/` — decisions. Tech stack, high level design, folder structure, tooling that was set up on the
  dev machine and why.
- `research/` — thirteen reports written against live vendor docs and the Pipecat 1.9 source, the first eleven before the build,
  each with a claim-by-claim verification appendix. `prior-art/` is a second pass, after the first working
  build, over what other people had built.
- `reference/` — vendor material kept verbatim for diffing against: Pipecat's own agent guide and the scaffold
  its CLI generates for this exact stack.
- `process/` — how the build was run. Orchestration rules, one brief per layer, one status ledger per layer,
  the cross-layer requests ledger, spike measurements, the cut brief, prompt rule provenance. See its README.

Two things are deliberately not here. `evals/REPORT.md` sits with the evaluation code it describes. `JOURNAL.md`
sits at the repository root and is written by hand.
