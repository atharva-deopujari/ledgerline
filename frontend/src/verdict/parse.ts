/**
 * A body is a verdict or it is not. The poll runs against a server that answers several
 * shapes under `/api/sessions`, so a wrong one must read as "not yet", never as a verdict.
 * The types are the contract's; only the checking is here.
 */
import type {
  CriterionResult,
  Outcome,
  RuleResult,
  Verdict,
  VerdictStatus,
} from '../protocol/verdict'

const STATUSES: VerdictStatus[] = ['pending', 'ready', 'failed']
const OUTCOMES: Outcome[] = ['pass', 'fail', 'not_applicable']

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)

const isRule = (v: unknown): v is RuleResult =>
  isRecord(v) &&
  typeof v.rule === 'string' &&
  typeof v.passed === 'boolean' &&
  (v.detail === null || typeof v.detail === 'string')

const isCriterion = (v: unknown): v is CriterionResult =>
  isRecord(v) &&
  typeof v.criterion === 'string' &&
  OUTCOMES.includes(v.outcome as Outcome) &&
  typeof v.reason === 'string' &&
  (v.turn === null || typeof v.turn === 'number')

export function isVerdict(body: unknown): body is Verdict {
  return (
    isRecord(body) &&
    typeof body.session_id === 'string' &&
    STATUSES.includes(body.status as VerdictStatus) &&
    (body.summary === null || typeof body.summary === 'number') &&
    Array.isArray(body.deterministic) &&
    body.deterministic.every(isRule) &&
    Array.isArray(body.intent) &&
    body.intent.every(isCriterion) &&
    (body.judge_model === null || typeof body.judge_model === 'string') &&
    (body.trace_url === null || typeof body.trace_url === 'string')
  )
}
