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
