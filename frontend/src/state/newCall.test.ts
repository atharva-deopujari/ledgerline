/**
 * F1: the backend's `cards_version` restarts at 0 for every call. Carrying the previous
 * call's snapshot across `connect` meant the monotonic-version guard then discarded the new
 * call's first snapshots, leaving the old plan on screen until the new call overtook it.
 */
import { describe, expect, it } from 'vitest'
import sampleJson from '../protocol/sample.json'
import { parseIncoming } from '../protocol/parse'
import type { CardsMessage } from '../protocol/types'
import {
  initialSession,
  sessionReducer,
  type SessionAction,
  type SessionState,
} from './sessionReducer'

const at = (v: number): CardsMessage => ({ ...(parseIncoming(sampleJson) as CardsMessage), v })

const run = (actions: SessionAction[], from: SessionState = initialSession): SessionState =>
  actions.reduce(sessionReducer, from)

describe('starting a second call', () => {
  it('accepts v=1 from the new call after the previous one reached v=4', () => {
    const afterFirstCall = run([
      { type: 'connect' },
      { type: 'joined' },
      { type: 'cards', message: at(1) },
      { type: 'cards', message: at(2) },
      { type: 'cards', message: at(3) },
      { type: 'cards', message: at(4) },
      { type: 'left' },
    ])
    expect(afterFirstCall.cards?.v).toBe(4)

    const reconnecting = sessionReducer(afterFirstCall, { type: 'connect' })
    expect(reconnecting.cards).toBeNull()

    const fresh = at(1)
    const secondCall = sessionReducer(reconnecting, { type: 'cards', message: fresh })
    expect(secondCall.cards).toBe(fresh)
    expect(secondCall.cards?.v).toBe(1)
  })

  it('clears the question and error from the previous call too', () => {
    const after = run([
      { type: 'connect' },
      { type: 'joined' },
      { type: 'botText', text: 'What is your rent?' },
      { type: 'botStopped' },
      { type: 'error', message: 'The call stopped: room expired' },
    ])
    expect(after.lastQuestion).not.toBe('')

    const reconnecting = sessionReducer(after, { type: 'connect' })
    expect(reconnecting).toEqual({ ...initialSession, call: 'connecting' })
  })

  it('still drops a stale version inside one call', () => {
    const live = run([{ type: 'connect' }, { type: 'joined' }, { type: 'cards', message: at(4) }])
    expect(sessionReducer(live, { type: 'cards', message: at(3) })).toBe(live)
    expect(sessionReducer(live, { type: 'cards', message: at(4) })).toBe(live)
    expect(sessionReducer(live, { type: 'cards', message: at(5) }).cards?.v).toBe(5)
  })
})
