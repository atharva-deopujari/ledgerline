import { describe, expect, it } from 'vitest'
import sample from './sample.json'
import snapshots from '../mock/snapshots.json'
import { isNoneRow } from './markers'
import { parseIncoming } from './parse'
import type { CardsMessage } from './types'

describe('parseIncoming: cards', () => {
  it('accepts the sample snapshot and preserves its fields', () => {
    const got = parseIncoming(sample) as CardsMessage | null
    expect(got).not.toBeNull()
    expect(got!.type).toBe('cards')
    expect(got!.v).toBe(7)
    expect(got!.phase).toBe('gathering')
    expect(got!.focus).toBe('essentials')
    expect(got!.cards).toHaveLength(7)
    expect(got!.timeline).toHaveLength(6)
  })

  it('accepts a null focus', () => {
    const got = parseIncoming({ ...sample, focus: null })
    expect(got).not.toBeNull()
  })

  it('rejects a snapshot with a missing field', () => {
    for (const key of ['v', 'phase', 'cards', 'timeline', 'focus'] as const) {
      const broken: Record<string, unknown> = { ...sample }
      delete broken[key]
      expect(parseIncoming(broken)).toBeNull()
    }
  })

  it('rejects a card with a missing field', () => {
    const broken = {
      ...sample,
      cards: [{ id: 'income', title: 'Income', status: 'ok', rows: [['Salary', '1', '']] }],
    }
    expect(parseIncoming(broken)).toBeNull()
  })

  it('rejects an unknown card id, phase or status', () => {
    expect(parseIncoming({ ...sample, phase: 'chatting' })).toBeNull()
    expect(parseIncoming({ ...sample, focus: 'nonsense' })).toBeNull()
    expect(
      parseIncoming({
        ...sample,
        cards: [{ id: 'bogus', title: 'X', status: 'ok', rows: [], kv: {}, note: null }],
      }),
    ).toBeNull()
    expect(
      parseIncoming({
        ...sample,
        cards: [{ id: 'income', title: 'X', status: 'neon', rows: [], kv: {}, note: null }],
      }),
    ).toBeNull()
  })

  it('keeps a carried card: figures from the last call, not yet confirmed', () => {
    const parsed = parseIncoming({
      ...sample,
      cards: [{ id: 'income', title: 'Income', status: 'carried', rows: [], kv: {}, note: null }],
    }) as CardsMessage | null
    expect(parsed?.cards[0]?.status).toBe('carried')
  })

  it('rejects malformed rows, kv and timeline points', () => {
    const base = { id: 'income', title: 'X', status: 'ok', kv: {}, note: null }
    expect(parseIncoming({ ...sample, cards: [{ ...base, rows: [['a', 2, 'c']] }] })).toBeNull()
    expect(parseIncoming({ ...sample, cards: [{ ...base, rows: 'nope' }] })).toBeNull()
    expect(parseIncoming({ ...sample, cards: [{ ...base, rows: [], kv: { a: 1 } }] })).toBeNull()
    expect(parseIncoming({ ...sample, timeline: [{ d: '2026-09-11' }] })).toBeNull()
    expect(parseIncoming({ ...sample, timeline: [{ d: 1, b: 2 }] })).toBeNull()
  })

  it('accepts a timeline point with and without an event label', () => {
    const got = parseIncoming({
      ...sample,
      timeline: [
        { d: '2026-09-11', b: 100, e: 'start' },
        { d: '2026-09-12', b: 90, e: null },
        { d: '2026-09-13', b: 80 },
      ],
    }) as CardsMessage
    expect(got.timeline).toHaveLength(3)
  })
})

describe('parseIncoming: low_point', () => {
  it('accepts a null low_point: the plan is blocked, there is no lowest day yet', () => {
    const got = parseIncoming({ ...sample, low_point: null }) as CardsMessage | null
    expect(got).not.toBeNull()
    expect(got!.low_point).toBeNull()
  })

  it('treats a message without the key as a message without a low point', () => {
    const without: Record<string, unknown> = { ...sample }
    delete without.low_point
    const got = parseIncoming(without) as CardsMessage | null
    expect(got).not.toBeNull()
    expect(got!.low_point).toBeNull()
  })

  it('keeps the derivation of the plan snapshot, both identities intact', () => {
    const got = parseIncoming(snapshots.plan) as CardsMessage | null
    expect(got).not.toBeNull()
    const low = got!.low_point
    expect(low).not.toBeNull()
    const sum = (lines: { amt: number }[]) => lines.reduce((total, l) => total + l.amt, 0)
    expect(low!.opening + sum(low!.before)).toBe(low!.b)
    expect(low!.b + sum(low!.after)).toBe(low!.closing)
    expect(low!.before[0]!.spread).toBe(true)
  })

  it('rejects the whole message when a low_point field is off contract', () => {
    const low = snapshots.plan.low_point!
    for (const broken of [
      'nope',
      { ...low, d: 20260930 },
      { ...low, b: '2,000' },
      { ...low, opening: 8000.5 },
      { ...low, before: 'none' },
      { ...low, before: [{ ...low.before[0], amt: '-6,000' }] },
      { ...low, after: [{ ...low.after[0], spread: 'no' }] },
      { ...low, after: [{ d: '2026-10-01', label: 'Salary', amt: 72000 }] },
    ]) {
      expect(parseIncoming({ ...sample, low_point: broken })).toBeNull()
    }
  })
})

describe('isNoneRow', () => {
  it('reads a None label with an empty value as "there are none of these"', () => {
    expect(isNoneRow(['None', '', ''])).toBe(true)
    expect(isNoneRow(['none', '1,200', ''])).toBe(false)
  })
})

describe('parseIncoming: rtvi', () => {
  it('accepts the four messages we consume', () => {
    expect(
      parseIncoming({ label: 'rtvi-ai', type: 'bot-transcription', data: { text: 'hello' } }),
    ).toEqual({ label: 'rtvi-ai', type: 'bot-transcription', data: { text: 'hello' } })
    for (const type of [
      'bot-started-speaking',
      'bot-stopped-speaking',
      'user-started-speaking',
    ] as const) {
      expect(parseIncoming({ label: 'rtvi-ai', type })).not.toBeNull()
    }
  })

  it('tolerates the id and data fields RTVI adds to the speaking events', () => {
    expect(
      parseIncoming({ id: 'abc', label: 'rtvi-ai', type: 'bot-started-speaking', data: {} }),
    ).not.toBeNull()
  })

  it('drops RTVI traffic of any other type', () => {
    for (const type of ['user-transcription', 'bot-ready', 'server-message', 'bot-output']) {
      expect(parseIncoming({ label: 'rtvi-ai', type, data: { text: 'x' } })).toBeNull()
    }
  })

  it('rejects a bot-transcription without text', () => {
    expect(parseIncoming({ label: 'rtvi-ai', type: 'bot-transcription' })).toBeNull()
    expect(parseIncoming({ label: 'rtvi-ai', type: 'bot-transcription', data: {} })).toBeNull()
    expect(
      parseIncoming({ label: 'rtvi-ai', type: 'bot-transcription', data: { text: 7 } }),
    ).toBeNull()
  })
})

describe('parseIncoming: everything else', () => {
  it('returns null for non-objects and unrelated messages', () => {
    for (const raw of [null, undefined, 7, 'cards', [], { type: 'transcript' }, { label: 'x' }]) {
      expect(parseIncoming(raw)).toBeNull()
    }
  })
})
