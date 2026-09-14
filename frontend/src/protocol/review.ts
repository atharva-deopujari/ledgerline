/**
 * Wire contract for GET /api/review/users/{phone}, mirrored from `ledgerline/api/review.py`.
 * Datetimes are ISO 8601 strings, money is a string, never a float. `review.sample.json` is
 * generated from the Python models.
 */

/** One field of one item. `ended` is a tombstone: the person said there is no longer any. */
export interface ReviewFact {
  kind: string
  name: string
  field: string
  value: string | null
  certainty: string | null
  recorded_at: string
  last_confirmed_at: string
  source_session_id: string | null
  superseded: boolean
  ended: boolean
}

export interface ReviewNote {
  category: string
  text: string
  evidence_session_id: string | null
  evidence_turn: number | null
  recorded_at: string
  superseded: boolean
}

export interface ReviewCall {
  session_id: string
  started_at: string
  ended_at: string | null
  ended_by: string | null
  /** Null when LANGFUSE_PROJECT_ID is unset; never render a dead link. */
  trace_url: string | null
  recording_path: string | null
}

export interface UserReview {
  phone: string
  /** False when the store could not answer in time. Not the same as a first-time caller. */
  memory_read: boolean
  active: ReviewFact[]
  history: ReviewFact[]
  notes: ReviewNote[]
  calls: ReviewCall[]
}

/*
 * The console, added 14 Sep: five read-only pages under GET /api/review/..., mirrored from the
 * same module. Samples `users.sample.json`, `calls.sample.json`, `call.sample.json`,
 * `evals.sample.json` and `report.sample.json` are generated from the Python models.
 */

/** One caller on the Callers tab. `headline` holds up to two remembered facts, rent and salary first. */
export interface ReviewUser {
  phone: string
  calls: number
  last_call_at: string | null
  facts: number
  /** Null means "not judged": no live call of theirs carries a verdict yet. Never render it as zero. */
  last_summary: number | null
  headline: { name: string; value: string }[]
}

export interface UsersPage {
  users: ReviewUser[]
}

export type CallSource = 'live' | 'simulated'

/** One recording under evals/runs. `id` is the file's basename without .json; `label` is the phone
 *  for a live call and the scenario for a simulated one. `summary` is null for every simulated run:
 *  no judge scored it and a number made from three booleans would be arithmetic nobody asked for.
 *  `checks` always carries all three keys. `started_at` is the stamp in the filename. */
export interface CallSummary {
  id: string
  source: CallSource
  label: string
  scenario: string | null
  started_at: string
  turns: number
  plan_final: boolean
  ended_by: string | null
  prompt_version: string | null
  summary: number | null
  checks: { money_traceable: boolean; state_matches_call: boolean; speakable: boolean }
  trace_url: string | null
}

export interface CallsPage {
  calls: CallSummary[]
}

/** The recording as saved (shape owned by the recorder; render defensively) plus its verdict:
 *  stored for a live call, deterministic checks only for a simulated run (intent [], judge_model null). */
export interface CallDetail {
  call: Record<string, unknown>
  verdict: import('./verdict').Verdict
}

export interface EvalScenario {
  name: string
  runs: number
  persona: string
}

/** `matrix[scenario][check]` is a pass rate 0 to 1 over every simulated run of that scenario,
 *  replayed with today's checks, so it is like-for-like across eras. */
export interface EvalsPage {
  scenarios: EvalScenario[]
  checks: string[]
  criteria: string[]
  matrix: Record<string, Record<string, number>>
  runs_total: number
  computed_at: string
}

export interface ReportPage {
  markdown: string
}
