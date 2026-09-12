import { describe, expect, it } from 'vitest'
import sample from '../protocol/sample.json'
import { parseIncoming } from '../protocol/parse'
import type { CardsMessage } from '../protocol/types'
import {
  initialSession,
  sessionReducer,
  type SessionAction,
  type SessionState,
} from './sessionReducer'

const snapshot = parseIncoming(sample) as CardsMessage

const run = (actions: SessionAction[], from: SessionState = initialSession): SessionState =>
  actions.reduce(sessionReducer, from)

describe('call lifecycle', () => {
  it('starts idle with no cards and no error', () => {
    expect(initialSession.call).toBe('idle')
    expect(initialSession.speak).toBe('idle')
    expect(initialSession.cards).toBeNull()
    expect(initialSession.error).toBeNull()
  })

  it('walks idle -> connecting -> live -> ended', () => {
    expect(run([{ type: 'connect' }]).call).toBe('connecting')
    expect(run([{ type: 'connect' }, { type: 'joined' }]).call).toBe('live')
    expect(run([{ type: 'connect' }, { type: 'joined' }, { type: 'left' }]).call).toBe('ended')
  })

  it('goes live listening and ends idle', () => {
    expect(run([{ type: 'connect' }, { type: 'joined' }]).speak).toBe('listening')
    const ended = run([
      { type: 'connect' },
      { type: 'joined' },
      { type: 'botSpeaking' },
      { type: 'left' },
    ])
    expect(ended.speak).toBe('idle')
  })

  it('records an error and clears it on the next connect', () => {
    const failed = run([{ type: 'connect' }, { type: 'error', message: 'Microphone blocked' }])
    expect(failed.call).toBe('error')
    expect(failed.error).toBe('Microphone blocked')
    expect(failed.speak).toBe('idle')

    const retried = sessionReducer(failed, { type: 'connect' })
    expect(retried.call).toBe('connecting')
    expect(retried.error).toBeNull()
  })

  it('keeps the cards already on screen when the call ends or errors', () => {
    const live = run([
      { type: 'connect' },
      { type: 'joined' },
      { type: 'cards', message: snapshot },
    ])
    expect(sessionReducer(live, { type: 'left' }).cards).toBe(snapshot)
    expect(sessionReducer(live, { type: 'error', message: 'boom' }).cards).toBe(snapshot)
  })
})

describe('cards snapshots', () => {
  it('stores the first snapshot', () => {
    const next = sessionReducer(initialSession, { type: 'cards', message: snapshot })
    expect(next.cards).toBe(snapshot)
  })

  it('ignores a snapshot whose v is stale or a repeat', () => {
    const live = sessionReducer(initialSession, { type: 'cards', message: snapshot })
    const stale = { ...snapshot, v: 6, focus: 'income' } as CardsMessage
    const repeat = { ...snapshot, focus: 'income' } as CardsMessage
    expect(sessionReducer(live, { type: 'cards', message: stale })).toBe(live)
    expect(sessionReducer(live, { type: 'cards', message: repeat })).toBe(live)
  })

  it('accepts a newer v', () => {
    const live = sessionReducer(initialSession, { type: 'cards', message: snapshot })
    const newer = { ...snapshot, v: 8, focus: 'summary' } as CardsMessage
    expect(sessionReducer(live, { type: 'cards', message: newer }).cards).toBe(newer)
  })
})

describe('question assembly', () => {
  it('appends bot text chunks into the streaming question', () => {
    const s = run([
      { type: 'botSpeaking' },
      { type: 'botText', text: 'What do you ' },
      { type: 'botText', text: 'pay for rent?' },
    ])
    expect(s.question).toBe('What do you pay for rent?')
    expect(s.lastQuestion).toBe('')
  })

  it('settles the question when the bot stops speaking', () => {
    const s = run([
      { type: 'botSpeaking' },
      { type: 'botText', text: 'What do you pay for rent?' },
      { type: 'botStopped' },
    ])
    expect(s.lastQuestion).toBe('What do you pay for rent?')
    expect(s.question).toBe('')
  })

  it('starts a fresh question on the next turn and keeps the old one until it settles', () => {
    const s = run([
      { type: 'botSpeaking' },
      { type: 'botText', text: 'First question?' },
      { type: 'botStopped' },
      { type: 'botSpeaking' },
      { type: 'botText', text: 'Second ' },
    ])
    expect(s.lastQuestion).toBe('First question?')
    expect(s.question).toBe('Second ')
  })

  it('joins chunks that arrive without their own spacing', () => {
    const s = run([
      { type: 'botText', text: 'Got it.' },
      { type: 'botText', text: 'Anything else?' },
    ])
    expect(s.question).toBe('Got it. Anything else?')
  })

  it('keeps the settled question when the bot stops without saying anything new', () => {
    const s = run([
      { type: 'botSpeaking' },
      { type: 'botText', text: 'Only question?' },
      { type: 'botStopped' },
      { type: 'botSpeaking' },
      { type: 'botStopped' },
    ])
    expect(s.lastQuestion).toBe('Only question?')
  })
})

describe('speak state', () => {
  it('follows the bot and user turn events', () => {
    let s = run([{ type: 'connect' }, { type: 'joined' }])
    expect(s.speak).toBe('listening')
    s = sessionReducer(s, { type: 'botSpeaking' })
    expect(s.speak).toBe('speaking')
    s = sessionReducer(s, { type: 'botStopped' })
    expect(s.speak).toBe('listening')
    s = sessionReducer(s, { type: 'userSpeaking' })
    expect(s.speak).toBe('listening')
    s = sessionReducer(s, { type: 'thinking' })
    expect(s.speak).toBe('thinking')
    s = sessionReducer(s, { type: 'botSpeaking' })
    expect(s.speak).toBe('speaking')
  })

  it('never leaves the pill mid-turn once the call is over', () => {
    const s = run([
      { type: 'connect' },
      { type: 'joined' },
      { type: 'botSpeaking' },
      { type: 'left' },
    ])
    expect(sessionReducer(s, { type: 'thinking' }).speak).toBe('idle')
    expect(sessionReducer(s, { type: 'botSpeaking' }).speak).toBe('idle')
  })
})
