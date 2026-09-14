/**
 * What the console will accept off the wire. The shapes are the contract's; these say only
 * "this body is that shape", so a 404 page or another endpoint's answer reads as a failure
 * rather than reaching a screen that maps over it.
 */
import type { CallDetail, CallsPage, EvalsPage, ReportPage, UsersPage } from '../protocol/review'

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)

const arrayOf = <T>(v: unknown, item: (x: unknown) => x is T): v is T[] =>
  Array.isArray(v) && v.every(item)

const isHeadline = (v: unknown): v is { name: string; value: string } =>
  isRecord(v) && typeof v.name === 'string' && typeof v.value === 'string'

const isUser = (v: unknown): v is unknown =>
  isRecord(v) &&
  typeof v.phone === 'string' &&
  typeof v.calls === 'number' &&
  typeof v.facts === 'number' &&
  (v.last_call_at === null || typeof v.last_call_at === 'string') &&
  (v.last_summary === null || typeof v.last_summary === 'number') &&
  arrayOf(v.headline, isHeadline)

export const isUsersPage = (b: unknown): b is UsersPage => isRecord(b) && arrayOf(b.users, isUser)

const isChecks = (v: unknown): boolean =>
  isRecord(v) &&
  typeof v.money_traceable === 'boolean' &&
  typeof v.state_matches_call === 'boolean' &&
  typeof v.speakable === 'boolean'

const isCall = (v: unknown): v is unknown =>
  isRecord(v) &&
  typeof v.id === 'string' &&
  (v.source === 'live' || v.source === 'simulated') &&
  typeof v.label === 'string' &&
  typeof v.started_at === 'string' &&
  typeof v.turns === 'number' &&
  typeof v.plan_final === 'boolean' &&
  (v.summary === null || typeof v.summary === 'number') &&
  isChecks(v.checks)

export const isCallsPage = (b: unknown): b is CallsPage => isRecord(b) && arrayOf(b.calls, isCall)

/** `call` is the recording as the recorder saved it; only its presence is a contract. */
export const isCallDetail = (b: unknown): b is CallDetail =>
  isRecord(b) && isRecord(b.call) && isRecord(b.verdict)

const isScenario = (v: unknown): v is unknown =>
  isRecord(v) &&
  typeof v.name === 'string' &&
  typeof v.runs === 'number' &&
  typeof v.persona === 'string'

const isStrings = (v: unknown): v is string[] =>
  arrayOf(v, (x): x is string => typeof x === 'string')

export const isEvalsPage = (b: unknown): b is EvalsPage =>
  isRecord(b) &&
  arrayOf(b.scenarios, isScenario) &&
  isStrings(b.checks) &&
  isStrings(b.criteria) &&
  isRecord(b.matrix) &&
  typeof b.runs_total === 'number' &&
  typeof b.computed_at === 'string'

export const isReportPage = (b: unknown): b is ReportPage =>
  isRecord(b) && typeof b.markdown === 'string'
