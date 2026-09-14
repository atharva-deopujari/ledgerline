# Brief: the console — everything the product does, on screen

Decided by the owner on 14 Sep after the commits: the frontend is the surface the product is shown on, so
every capability the backend has (memory across calls, recordings with tool calls, the end-of-call
verdict, the eval matrix, the report) gets a screen, reached from the start page. The start page becomes a
console with tabs; a new call is one of them. No authentication: this is a personal product run on one
machine; the README says so.

## Tabs and routes

| tab | route | shows |
|---|---|---|
| New call | `/` | the start form as today, laid out for a desktop viewport (centred, max width ~1100px; copy left, phone and action right; the phone-width column stays for phones) |
| Callers | `/callers` | every phone that has called: number, calls, last call date, facts remembered, last verdict summary, two headline facts (rent, salary or the two most recent). Click a row → `/callers/<phone>`. Empty store → "No one has called yet" |
| Caller | `/callers/<phone>` | the existing review page (facts with history, notes, calls) plus a "Call as this number" action that fills the form on `/` |
| Calls | `/calls` | every recording under `evals/runs`, live and simulated, filterable by source and scenario/phone: started, turns, plan reached, ended by, prompt version, verdict summary, one dot per deterministic check. Click → `/calls/<id>` |
| Call | `/calls/<id>` | the transcript: person and coach turns; under a coach turn, its tool calls with arguments and the result string, collapsed by default; the verdict panel (three checks with reasons, four criteria); the final state and cards; Langfuse trace link when configured |
| Evals | `/evals` | the scenarios (name, what the person does, runs on disk) and the matrix: pass rate per deterministic check per scenario, computed by replaying the checks over the saved runs; the four judge criteria named as advisory with a pointer to the report |
| Report | `/report` | `evals/REPORT.md` rendered |

## Wire contracts (orchestrator owns the TypeScript mirrors and samples; C owns the Python models)

```
GET /api/review/users
{ "users": [ { "phone": "9869101897", "calls": 3, "last_call_at": "2026-09-14T10:02:11Z",
               "facts": 7, "last_summary": 0.86,
               "headline": [ { "name": "rent", "value": "13,000 on the 7th" }, { "name": "salary", "value": "30,000 on the 30th" } ] } ] }

GET /api/review/calls?source=live|simulated&scenario=<name>
{ "calls": [ { "id": "voice-9869101897-20260913T194053Z", "source": "live", "label": "9869101897",
               "scenario": null, "started_at": "...", "turns": 48, "plan_final": true, "ended_by": "done",
               "prompt_version": "v2@7", "summary": 0.86,
               "checks": { "money_traceable": true, "state_matches_call": true, "speakable": false },
               "trace_url": null } ] }
   id = recording file basename without .json; label = phone for live, scenario for simulated.

GET /api/review/calls/{id}
{ "call": <the recording JSON as saved>, "verdict": <Verdict> }
   Live: verdict from the recording. Simulated: deterministic checks run now, intent [] , judge_model null.
   id must be a basename of an existing file under the recordings directory; anything else is 404.

GET /api/review/evals
{ "scenarios": [ { "name": "owner_call_1", "runs": 15, "persona": "<one line from the yaml>" } ],
  "checks": [ "money_traceable", "state_matches_call", "speakable" ],
  "criteria": [ "coverage_before_plan", "low_point_explained", "challenge_answered_without_computing", "led_like_a_coach" ],
  "matrix": { "owner_call_1": { "money_traceable": 1.0, "state_matches_call": 0.93, "speakable": 1.0 } },
  "computed_at": "...", "runs_total": 449 }
   Computed by replaying CHECKS over every simulated run, cached in process, recomputed when the directory's file count changes.

GET /api/review/report
{ "markdown": "<contents of evals/REPORT.md>" }
```

All five are read-only, bounded, and never touch the call path; a missing store returns empty lists, a
missing recordings directory returns empty lists, never an error.

## The look

The owner's word: beautiful and presentable, proper fonts and spacing. The console extends the board's
design system rather than starting a second one: the same tokens, Source Serif 4 for headings and
figures, Archivo for labels and controls, the dark ground with the light theme still complete. Rules D
holds to: one type scale with no more than five sizes on a screen; a consistent 8px spacing rhythm and a
single content max-width; tables that read as ledgers (right-aligned figures, tabular numerals, hairline
rules, no zebra); one accent colour reserved for the thing to look at (a failed check, a superseded
value, the action); empty states written as sentences; every screen composed for a 1440px viewport
first and checked at phone width. Motion only where state changes (a row appearing, a check resolving).
Screenshots of every tab go into docs/process/screens and are how the owner judges the result before
the commit.

## Ownership

- A: `Store.list_users()` (phone, calls, last_call_at, facts, last verdict summary) in one query; `NullStore` returns `[]`; db tests.
- C: `api/review.py` models and the five endpoints; recording directory read through settings; replay cache; path guard; tests with a fake store and a temp recordings directory.
- Orchestrator: `frontend/src/protocol/review.ts` extended, `review.sample.json` and new samples generated from C's models; README "Where it stands" and the folder tree.
- D: routes, the tab shell, the desktop layout of the start page, six screens, contract parsing at the boundary, vitest per screen, e2e journeys for callers → caller and calls → call over the mock, screenshots. Markdown rendering: one small dependency is allowed if a twenty-line renderer for headings, paragraphs, lists, tables and code is not enough; say which in the ledger.

Acceptance: every capability in README "What it does" is reachable from `/` in two clicks or fewer. Gates as always; one commit `feat(frontend): the console` when the owner says.
