/**
 * Wire contract for GET /api/sessions/{id}/verdict, mirrored from
 * `ledgerline/judge/models.py` (`Verdict`). A field that moves there moves here too; the
 * Python side guards the key sets, `verdict.sample.json` is generated from the same model.
 */

export type VerdictStatus = 'pending' | 'ready' | 'failed'

/** Three-valued on purpose: a criterion that did not apply is not a pass. */
export type Outcome = 'pass' | 'fail' | 'not_applicable'

/** One deterministic check over the recording, three per call: `money_traceable`,
 *  `state_matches_call`, `speakable`. `detail` is the violating sentence and opens with the
 *  sub-rule that raised it: "no_spoken_decimals: 56,833.27 rupees". */
export interface RuleResult {
  rule: string
  passed: boolean
  detail: string | null
}

/** One intent criterion answered by the judge model; `turn` is where the answer rests. */
export interface CriterionResult {
  criterion: string
  outcome: Outcome
  reason: string
  turn: number | null
}

export interface Verdict {
  session_id: string
  status: VerdictStatus
  /** 0 to 1, computed in code from both layers with not-applicable excluded; null until ready. */
  summary: number | null
  deterministic: RuleResult[]
  intent: CriterionResult[]
  judge_model: string | null
  trace_url: string | null
}
