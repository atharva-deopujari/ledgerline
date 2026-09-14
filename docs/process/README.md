# How the build was run

This folder is the working record of the build: the rules the sessions worked under, the brief each
one received, the ledger each one kept, and the decisions that changed direction. Nothing here is
polished after the fact; the status ledgers are appended in the order the work happened, and where a
session got something wrong the correction sits next to it.

## Shape of the work

One person owned the product and every decision in it. The typing was done by AI coding sessions
under a fixed division of labour:

| Role | Session | Owns |
|---|---|---|
| Orchestrator | one session, renamed as it was replaced | verification, integration, contracts (`models.py`, `types.ts`), `pyproject.toml`, Docker, README, `docs/**` |
| A | domain | `ledgerline/domain/**`, `tests/domain/**` |
| B | agent and evals | `ledgerline/agent/**`, `evals/**`, `tests/agent/**`; a fresh B took the layer over for the redesign, onboarded from `status-B.md` alone |
| C | voice and api | `ledgerline/voice/**`, `ledgerline/api/**`, `config.py`, `main.py`, `spike/**`, their tests |
| D | frontend | `frontend/**` except the contract files, `tests/e2e/**`; a later frontend session rebuilt the board from the design canvas and kept its own ledger, `status-frontend.md` |
| Reviewer | Kiro, a different vendor's model, read-only | nothing; it produces findings |

Rules every session worked under are in `00-orchestration.md`: nobody commits, nobody edits another
session's files, contracts are frozen and changed only through the orchestrator, test first and watch it
fail, verify framework APIs against source rather than tutorials, hand bounded work to subagents to
protect context, write a status ledger before stopping. Cross-session requests went through
`requests.md` so one place held the whole picture. Worker sessions were rotated once when two ran out
of context mid-task; the incoming sessions were onboarded from the ledgers alone, which is the test of
whether the ledgers are good enough.

## Independent review

Kiro ran as a read-only reviewer with a different model (`gpt-5.6-sol`) so that the code was never
checked only by the model that wrote it. The mechanism is two Claude Code hooks in `.claude/hooks/`:
the orchestrator arms a review by writing a flag file, the Stop hook runs one headless review over
every project file changed since the last review, validates the output against a fixed JSON schema,
and writes an immutable artifact under `.review-channel/reviews/`; the next prompt injects that artifact
into the orchestrator's context. Thirteen reviews ran across 11 and 12 September 2026, 65 findings in
total. Every finding was verified against the code before anything was dispatched, and each ledger
records the disposition: fixed with a test, not reproducible, or judged not a defect and why. The last
review's four findings are held for after the first commits and are recorded, with the workers'
verdicts, at the end of `status-A.md` and `status-B.md`.

The reviewer's configuration is in `.kiro/`: a read-only tool set, a steering file that names the
yardstick (README, HLD, cut brief) and forbids it from touching the decision journal.

## Timeline

| When (IST) | What | Where recorded |
|---|---|---|
| 11 Sep, afternoon | Research: eleven reports against live docs and the Pipecat 1.9 source; stack chosen; HLD approved | `docs/research/`, `docs/architecture/` |
| 11 Sep, evening | Four worker sessions started against frozen contracts; spike measured turn end, cards frame, LLM service, room lifecycle; first two live calls | `session-*.md`, `spike-findings.md`, `status-C.md` |
| 11 to 12 Sep | Reviews 1 to 12, each verified and closed with tests; prior-art survey absorbed | `status-*.md`, `docs/research/prior-art/` |
| 12 Sep, afternoon | Behaviour-preserving maintainability refactor: enums over strings, packages over god modules, walked line by line | `status-*.md` "refactor" sections |
| 12 Sep, evening | Third live call went badly: doubled questions, fragments ending turns. Text simulation built to reproduce it; turn end reworked to a single judge | `session-B-simulation.md`, `spike-findings.md`, `evals/REPORT.md` §3 |
| 12 Sep, late | The cut: the state layer stopped re-implementing judgement the model already has. Forty of the first fifty-five review findings had been in that machinery | `cut-brief.md`, `status-A.md`, `status-B.md` |
| 13 Sep, early | Agent layer of the cut landed; eval matrix rerun; instruments audited and three found wrong; `state_matches_facts` added and found the dropped half of a balance | `evals/REPORT.md` §5 to §10, `prompt-provenance.md` |
| 13 Sep | Tree frozen for the first commits | end of each `status-*.md` |
| 13 Sep, later | Observability phase: every call traced to Langfuse, sessions and facts in Postgres keyed by phone, a soft-notes extractor bounded in code, an end-of-call judge | `observability-brief.md`, `docs/architecture/04-observability-hld.md`, `evals/REPORT.md` §10.6 to §10.8 |
| 14 Sep, early | The owner's live call of the evening before was read as a bot rather than a coach. A census of the 109 mechanisms shaping the model found 54 with no recorded failing case, and every check a hard gate, so nothing could push a constraint back off | `agent-redesign-brief.md`, `luna-capabilities.md`, `docs/research/13-agent-design.md` |
| 14 Sep | Agent layer redesigned: prompt v2 (identity and goal, not prohibitions), six plain-word tools, results that state facts instead of issuing orders, checks split into gates and advisory. The owner's call re-run five times before and five after; the before-and-after table and both transcripts are in the report | `owner-call-1-report.md`, `evals/REPORT.md` §10.13 to §10.15, `status-B.md`, `status-C.md` |
| 14 Sep, later | The owner read the after table and ordered the cleanup: the v1 tools, prompt and result strings deleted, then a dead-code census per layer, each removal with the grep that proved it had no caller and the snapshots byte-identical throughout. The twenty deterministic checks folded into three (money, state, speakable) and the nine advisory rules deleted, accepted by replaying all 448 saved runs with zero mismatches; the judge keeps its four criteria. Cost named: the before column of §10.13 can never be re-run | `status-A.md`, `status-B.md`, `status-C.md`, `status-D.md` (cleanup censuses), `evals/REPORT.md` §10.16 |
| 14 Sep, evening | The console: the start page becomes five tabs (New call, Callers, Calls, Evals, Report) so memory, every recording with its tool calls and verdict, the eval matrix replayed over the saved runs, and the report are two clicks from `/`; five read-only endpoints, no schema change; the start page laid out for a desktop viewport | `admin-panel-brief.md`, `status-A.md`, `status-C.md`, `status-D.md`, `docs/process/screens/13` to `18` |

## Files

| File | What it is |
|---|---|
| `00-orchestration.md` | The rules and the ownership table every session read first |
| `session-A-domain.md`, `session-B-agent.md`, `session-C-voice-api.md`, `session-D-frontend.md` | The brief each layer started from |
| `session-B-simulation.md` | The handover brief for the voice-shaped text simulation after the third live call |
| `status-A.md`, `status-B.md`, `status-C.md`, `status-D.md` | Each layer's ledger, appended in order: what was built, what was decided, every review finding and its disposition, what was assumed, what is left |
| `requests.md` | Cross-layer requests and contract changes, numbered per session, with the answer next to each |
| `spike-findings.md` | Measurements: turn end strategies, first-audio latency, Responses vs Chat, room lifecycle, the turn-end investigation |
| `cut-brief.md` | The decision that moved language judgement to the model and kept arithmetic in code; the contract after it; acceptance |
| `prompt-provenance.md` | One row per prompt rule: the named case that fails without it, or the mark that says it is a cut candidate |
| `luna-capabilities.md` | What the model does by default at the effort setting used, and which prompt lines that makes redundant |
| `observability-brief.md` | The work split, the order and the acceptance line per phase for tracing, sessions, memory and the judge |
| `agent-redesign-brief.md` | The decision to rebuild the agent layer as a coach: the prompt, the plain-word tool set, results as facts, the checks split, the order of work and the acceptance line |
| `owner-call-1-report.md` | The owner's own call scripted as a scenario and run five times on each build: the two transcripts side by side, the check table, and a plain reading of where it still does not sound like an expert |
| `status-frontend.md` | The ledger of the board rebuild, kept separately from `status-D.md` |
| `design/` | The design canvas the board was drawn from, with a README saying which parts were built and which were canvas fiction |
| `screens/` | Screenshots of the interface at each phase, regenerated from the mock feed |

## Where the numbers are

Test counts and eval pass rates quoted anywhere in these files are as of the moment they were written
and are superseded by later sections of the same file. Current numbers are in the root README and
`evals/REPORT.md`.
