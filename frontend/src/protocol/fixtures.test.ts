/**
 * Every fixture the app ships has to survive its own parser.
 *
 * `parseIncoming` rejects a snapshot outright when any field is off-contract, and the mock
 * simply drops what it rejects — so a regenerated `snapshots.json` carrying a retired value
 * would vanish from the review journey in the browser while vitest stayed green. Nothing
 * caught that: `script.test.ts` reads the JSON directly for its number check, and the
 * component tests build their own fixtures. This is the gap.
 */
import { describe, expect, it } from 'vitest'
import { parseIncoming } from './parse'
import sample from './sample.json'
import snapshots from '../mock/snapshots.json'
import type { CardsMessage } from './types'
import verdictSample from './verdict.sample.json'
import type { Verdict } from './verdict'
import reviewSample from './review.sample.json'
import type { UserReview } from './review'
import usersSample from './users.sample.json'
import callsSample from './calls.sample.json'
import callSample from './call.sample.json'
import evalsSample from './evals.sample.json'
import reportSample from './report.sample.json'
import type { UsersPage, CallsPage, CallDetail, EvalsPage, ReportPage } from './review'

const fixtures: [string, unknown][] = [
  ['sample.json', sample],
  ...Object.entries(snapshots as Record<string, unknown>).map(
    ([name, snap]) => [`snapshots.json: ${name}`, snap] as [string, unknown],
  ),
]

describe('shipped fixtures parse', () => {
  it('covers every snapshot, so adding one cannot skip this check', () => {
    expect(fixtures.length).toBe(1 + Object.keys(snapshots).length)
    expect(fixtures.length).toBeGreaterThan(1)
  })

  it.each(fixtures)('%s is accepted by parseIncoming', (name, raw) => {
    const parsed = parseIncoming(raw) as CardsMessage | null
    // A null here means the fixture holds a value the contract no longer allows — an old
    // phase or card status, most likely. The browser would drop this snapshot silently.
    expect(parsed, `${name} was rejected by parseIncoming`).not.toBeNull()
    expect(parsed!.type).toBe('cards')
  })

  it.each(fixtures)('%s keeps every card it declares', (name, raw) => {
    const parsed = parseIncoming(raw) as CardsMessage | null
    expect(parsed, `${name} was rejected by parseIncoming`).not.toBeNull()
    const declared = (raw as CardsMessage).cards.length
    expect(parsed!.cards).toHaveLength(declared)
  })
})

describe('verdict sample matches the contract', () => {
  it('is a ready verdict with both layers and a summary', () => {
    const v = verdictSample as Verdict
    expect(v.status).toBe('ready')
    expect(v.summary).not.toBeNull()
    expect(v.deterministic.length).toBeGreaterThan(0)
    // Three rules, all gating: the advisory tier is gone from the judge.
    expect(v.deterministic.map((r) => r.rule)).toEqual([
      'money_traceable',
      'state_matches_call',
      'speakable',
    ])
    expect(v.intent.map((c) => c.outcome)).toEqual(['pass', 'fail', 'not_applicable'])
  })
})

describe('review sample matches the contract', () => {
  it('has active facts, a struck history row, a tombstone, a note and calls', () => {
    const r = reviewSample as UserReview
    expect(r.memory_read).toBe(true)
    expect(r.active.length).toBeGreaterThan(0)
    expect(r.history.some((f) => f.superseded)).toBe(true)
    expect(r.history.some((f) => f.ended && f.value === null)).toBe(true)
    expect(r.notes.length).toBe(1)
    expect(r.calls.map((c) => c.trace_url === null)).toEqual([false, true])
  })
})

describe('console samples match the contract', () => {
  it('users: every caller carries the counts and at most two headline facts', () => {
    const page = usersSample as UsersPage
    expect(page.users.length).toBeGreaterThan(0)
    for (const u of page.users) {
      expect(typeof u.phone).toBe('string')
      expect(typeof u.calls).toBe('number')
      expect(typeof u.facts).toBe('number')
      expect(u.headline.length).toBeLessThanOrEqual(2)
      for (const h of u.headline) expect(Object.keys(h).sort()).toEqual(['name', 'value'])
    }
  })
  it('calls: every row carries all three checks and a live/simulated source', () => {
    const page = callsSample as CallsPage
    for (const c of page.calls) {
      expect(['live', 'simulated']).toContain(c.source)
      expect(Object.keys(c.checks).sort()).toEqual([
        'money_traceable',
        'speakable',
        'state_matches_call',
      ])
      if (c.source === 'simulated') expect(c.summary).toBeNull()
    }
  })
  it('call: the detail carries the recording and a verdict with three rules', () => {
    const d = callSample as CallDetail
    expect(Array.isArray(d.call.turns)).toBe(true)
    expect(d.verdict.deterministic.map((r) => r.rule).sort()).toEqual([
      'money_traceable',
      'speakable',
      'state_matches_call',
    ])
  })
  it('evals: the matrix names every check for every scenario, rates within 0 and 1', () => {
    const e = evalsSample as EvalsPage
    for (const s of e.scenarios) {
      const row = e.matrix[s.name]
      expect(Object.keys(row).sort()).toEqual([...e.checks].sort())
      for (const rate of Object.values(row)) expect(rate >= 0 && rate <= 1).toBe(true)
    }
    expect(e.criteria).toHaveLength(4)
  })
  it('report: markdown is a non-empty string', () => {
    expect((reportSample as ReportPage).markdown.length).toBeGreaterThan(0)
  })
})
