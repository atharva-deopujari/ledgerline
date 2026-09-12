/**
 * Review 11 F1: when the browser blocks autoplay the message tells the user to start the
 * call again — but the old call object was left in `callRef`, so `start()` returned at its
 * guard and that click did nothing, while the old call and its server session stayed live.
 */
import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { initialSession, sessionReducer, type SessionAction } from '../state/sessionReducer'
import { FakeDaily, FakeMediaStream } from './testDouble'
import { useDailyCall } from './useDailyCall'

const SESSION = { room_url: 'https://x.daily.co/room', token: 'tok', session_id: 'sess-1' }

let daily: FakeDaily
let dispatched: SessionAction[]
let posts: number
let deletes: number

const dispatch = (a: SessionAction) => {
  dispatched.push(a)
}
const finalState = () => dispatched.reduce(sessionReducer, initialSession)
const errorText = () => finalState().error ?? ''

function hook() {
  posts = 0
  deletes = 0
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'DELETE') {
        deletes += 1
        return new Response(null, { status: 204 })
      }
      posts += 1
      return new Response(JSON.stringify(SESSION), { status: 201 })
    }),
  )
  const h = renderHook(() => useDailyCall(dispatch))
  return h
}

/** An audio element whose play() rejects the way a blocked autoplay does. */
function blockedAudio() {
  return {
    srcObject: null,
    play: vi.fn(async () => {
      throw Object.assign(new Error('blocked'), { name: 'NotAllowedError' })
    }),
  } as unknown as HTMLAudioElement
}

beforeEach(() => {
  daily = new FakeDaily()
  dispatched = []
  vi.stubGlobal('Daily', daily)
  vi.stubGlobal('MediaStream', FakeMediaStream)
})
afterEach(() => vi.unstubAllGlobals())

describe('the browser blocks the bot audio', () => {
  it('says so, and the sentence describes a call that is over', async () => {
    const h = hook()
    h.result.current.audioRef.current = blockedAudio()
    await act(async () => {
      await h.result.current.start()
    })

    await act(async () => {
      daily.last.emit('track-started', {
        type: 'audio',
        participant: { local: false },
        track: {},
      })
    })

    await waitFor(() => expect(errorText()).toMatch(/blocked audio/i))
    expect(errorText()).toMatch(/start the call again/i)
    // It no longer promises that clicking will resume the call in progress.
    expect(errorText()).not.toMatch(/let the plan speak/i)
  })

  it('retires the call, so the server sees the disconnect', async () => {
    const h = hook()
    h.result.current.audioRef.current = blockedAudio()
    await act(async () => {
      await h.result.current.start()
    })
    const first = daily.last

    await act(async () => {
      first.emit('track-started', { type: 'audio', participant: { local: false }, track: {} })
    })

    await waitFor(() => expect(first.destroyed).toBe(1))
    expect(first.left).toBe(1)
    // The call was live, so ending it is the server's business, not a DELETE from here.
    expect(deletes).toBe(0)
  })

  it('does not destroy it twice if more tracks arrive', async () => {
    const h = hook()
    h.result.current.audioRef.current = blockedAudio()
    await act(async () => {
      await h.result.current.start()
    })
    const first = daily.last

    await act(async () => {
      first.emit('track-started', { type: 'audio', participant: { local: false }, track: {} })
    })
    await waitFor(() => expect(first.destroyed).toBe(1))
    await act(async () => {
      first.emit('track-started', { type: 'audio', participant: { local: false }, track: {} })
    })
    expect(first.destroyed).toBe(1)
  })

  it('performs the restart the message asks for', async () => {
    const h = hook()
    h.result.current.audioRef.current = blockedAudio()
    await act(async () => {
      await h.result.current.start()
    })
    await act(async () => {
      daily.last.emit('track-started', {
        type: 'audio',
        participant: { local: false },
        track: {},
      })
    })
    await waitFor(() => expect(daily.calls[0].destroyed).toBe(1))
    await waitFor(() => expect(h.result.current.starting).toBe(false))

    // This time the audio plays.
    h.result.current.audioRef.current = {
      srcObject: null,
      play: vi.fn(async () => {}),
    } as unknown as HTMLAudioElement

    await act(async () => {
      await h.result.current.start()
    })

    expect(posts).toBe(2)
    expect(daily.calls).toHaveLength(2)
    expect(finalState().call).toBe('live')
  })
})

describe('a play() that rejects only after the call has been replaced', () => {
  it('leaves the replacement call alone', async () => {
    const h = hook()

    // An audio element whose play() stays pending until we reject it by hand.
    let rejectPlay: () => void = () => {}
    const pending = new Promise<void>((_resolve, reject) => {
      rejectPlay = () => reject(Object.assign(new Error('blocked'), { name: 'NotAllowedError' }))
    })
    pending.catch(() => {})
    h.result.current.audioRef.current = {
      srcObject: null,
      play: vi.fn(() => pending),
    } as unknown as HTMLAudioElement

    await act(async () => {
      await h.result.current.start()
    })
    const first = daily.last

    // The bot's track arrives, so play() is called and stays pending.
    await act(async () => {
      first.emit('track-started', { type: 'audio', participant: { local: false }, track: {} })
    })
    expect(first.destroyed).toBe(0)

    // The first call ends and a replacement joins, with working audio.
    await act(async () => {
      first.emit('participant-left', { participant: { local: false } })
    })
    await waitFor(() => expect(first.destroyed).toBe(1))
    await waitFor(() => expect(h.result.current.starting).toBe(false))

    h.result.current.audioRef.current = {
      srcObject: null,
      play: vi.fn(async () => {}),
    } as unknown as HTMLAudioElement
    await act(async () => {
      await h.result.current.start()
    })
    const second = daily.last
    expect(second).not.toBe(first)
    expect(finalState().call).toBe('live')

    // Only now does the old element's play() reject.
    await act(async () => {
      rejectPlay()
      await Promise.resolve()
    })

    // The replacement is untouched: still live, never torn down, no error on screen.
    expect(finalState().call).toBe('live')
    expect(finalState().error).toBeNull()
    expect(second.destroyed).toBe(0)
    expect(second.left).toBe(0)
    expect(first.destroyed).toBe(1)
  })

  it('still ends the call when the rejection belongs to the current one', async () => {
    const h = hook()
    h.result.current.audioRef.current = blockedAudio()
    await act(async () => {
      await h.result.current.start()
    })
    await act(async () => {
      daily.last.emit('track-started', {
        type: 'audio',
        participant: { local: false },
        track: {},
      })
    })
    await waitFor(() => expect(daily.calls[0].destroyed).toBe(1))
    expect(errorText()).toMatch(/blocked audio/i)
  })
})
