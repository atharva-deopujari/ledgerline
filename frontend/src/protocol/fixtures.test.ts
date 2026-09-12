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
