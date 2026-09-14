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
