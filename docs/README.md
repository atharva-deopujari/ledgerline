# Documentation

Reading order for someone new to the codebase. Each step is short and points at the longer
material behind it.

| # | Read | What it settles |
|---|---|---|
| 1 | `../README.md` | How to run it, what it does, current test and eval numbers |
| 2 | `architecture/01-tech-stack.md` | Every stack choice in one line each, with what was rejected and why |
| 3 | `architecture/02-hld.md` | The design: components, one user turn, state, tools, plan engine, cards, prompt, lifecycle |
| 4 | `architecture/03-folder-structure.md` | Where everything lives and the import direction that is enforced |
| 5 | `research/00-index.md` | What was verified against source before any code, and where docs and framework disagreed |
| 6 | `research/prior-art/00-index.md` | What other people built, ranked list of what was adopted |
| 7 | `process/README.md` | How the build was run: sessions, briefs, ledgers, reviews, the cut |
| 8 | `process/cut-brief.md` | The current line between what code decides and what the model decides |
| 9 | `../evals/REPORT.md` | What is measured, how, and what the measurements found |
| 10 | `../JOURNAL.md` | The owner's decision journal |

## Folders

- `architecture/` — decisions. Tech stack, high level design, folder structure, tooling that was set up on the
  dev machine and why.
- `research/` — eleven reports written before the build against live vendor docs and the Pipecat 1.9 source,
  each with a claim-by-claim verification appendix. `prior-art/` is a second pass, after the first working
  build, over what other people had built.
- `reference/` — vendor material kept verbatim for diffing against: Pipecat's own agent guide and the scaffold
  its CLI generates for this exact stack.
- `process/` — how the build was run. Orchestration rules, one brief per layer, one status ledger per layer,
  the cross-layer requests ledger, spike measurements, the cut brief, prompt rule provenance. See its README.

Two things are deliberately not here. `evals/REPORT.md` sits with the evaluation code it describes. `JOURNAL.md`
sits at the repository root and is written by hand.
