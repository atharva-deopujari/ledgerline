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
| B | agent and evals | `ledgerline/agent/**`, `evals/**`, `tests/agent/**` |
| C | voice and api | `ledgerline/voice/**`, `ledgerline/api/**`, `config.py`, `main.py`, `spike/**`, their tests |
| D | frontend | `frontend/**` except the contract files, `tests/e2e/**` |
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
| `screens/` | Screenshots of the interface at each phase, regenerated from the mock feed |

## Where the numbers are

Test counts and eval pass rates quoted anywhere in these files are as of the moment they were written
and are superseded by later sections of the same file. Current numbers are in the root README and
`evals/REPORT.md`.
