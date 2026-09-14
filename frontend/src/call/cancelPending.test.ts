/**
 * F1: the browser's DELETE is not instant. The server awaits the whole run_session teardown
 * — bounded worker cancellation then room deletion — before answering, so the slot is still
 * held while that request is in flight. The controls must not re-enable until it returns,
 * and a new attempt must not POST into the occupied slot.
 *
 * Every earlier test used a DELETE that resolved immediately, which is exactly why none of
 * them could see this.
 */
import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { initialSession, sessionReducer, type SessionAction } from '../state/sessionReducer'
import { FakeCall, FakeDaily, FakeMediaStream } from './testDouble'
import { useDailyCall } from './useDailyCall'

const SESSION = { room_url: 'https://x.daily.co/room', token: 'tok', session_id: 'sess-1' }

let daily: FakeDaily
let dispatched: SessionAction[]
let posts: number
let deleteCalls: number
let releaseDelete: () => void

const dispatch = (a: SessionAction) => {
  dispatched.push(a)
}
const finalState = () => dispatched.reduce(sessionReducer, initialSession)

/** DELETE hangs until `releaseDelete()` is called, the way the real teardown does. */
function hook() {
  posts = 0
  deleteCalls = 0
  let open: () => void = () => {}
  const gate = new Promise<void>((resolve) => {
    open = resolve
  })
  releaseDelete = open
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'DELETE') {
        deleteCalls += 1
        await gate
        return new Response(null, { status: 204 })
      }
      posts += 1
      return new Response(JSON.stringify(SESSION), { status: 201 })
    }),
  )
  const h = renderHook(() => useDailyCall(dispatch))
  h.result.current.audioRef.current = {
    srcObject: null,
    play: vi.fn(async () => {}),
  } as unknown as HTMLAudioElement
  return h
}

/** The next call object rejects its join, as a destroyed one does. */
function failNextJoin() {
  const realCreate = daily.createCallObject.bind(daily)
  daily.createCallObject = (opts: unknown) => {
    daily.createCallObject = realCreate
    const call: FakeCall = realCreate(opts)
    call.emitsLeftOnLeave = false
    call.joinImpl = async () => {
      throw new Error('call destroyed')
    }
    return call
  }
}

beforeEach(() => {
  daily = new FakeDaily()
  dispatched = []
  vi.stubGlobal('Daily', daily)
  vi.stubGlobal('MediaStream', FakeMediaStream)
})
afterEach(() => vi.unstubAllGlobals())

describe('while the DELETE is still in flight', () => {
  it('keeps reporting itself as starting, so the controls stay disabled', async () => {
    const h = hook()
    failNextJoin()

    let attempt!: Promise<void>
    act(() => {
      attempt = h.result.current.start('9876543210')
    })
    await waitFor(() => expect(deleteCalls).toBe(1))

    // The join has already rejected and the reducer has its message, but the slot is not
    // back until the server answers.
    await waitFor(() => expect(finalState().call).toBe('error'))
    expect(h.result.current.starting).toBe(true)

    await act(async () => {
      releaseDelete()
      await attempt
    })
    await waitFor(() => expect(h.result.current.starting).toBe(false))
  })

  it('only lets the next attempt post once the slot has actually come back', async () => {
    const h = hook()
    failNextJoin()

    let attempt!: Promise<void>
    act(() => {
      attempt = h.result.current.start('9876543210')
    })
    await waitFor(() => expect(deleteCalls).toBe(1))

    // While the DELETE hangs the hook is still starting, so the UI keeps every control
    // disabled (App.busy.test.tsx) and no retry can be issued.
    expect(h.result.current.starting).toBe(true)
    expect(posts).toBe(1)

    await act(async () => {
      releaseDelete()
      await attempt
    })
    await waitFor(() => expect(h.result.current.starting).toBe(false))

    // Now the slot is back, and a fresh attempt posts exactly once.
    await act(async () => {
      await h.result.current.start('9876543210')
    })
    expect(posts).toBe(2)
    expect(finalState().call).toBe('live')
  })
})

describe('repeat cancellations', () => {
  /**
   * The genuine double-cancel: a terminal event retires the call (cancel #1) and the pending
   * join then resolves into the stale-call branch, which cancels the same id again (#2).
   * The second must join the first request, not issue another DELETE.
   */
  it('join the in-flight request instead of issuing a second one', async () => {
    const h = hook()

    let openJoin: () => void = () => {}
    const joinGate = new Promise<void>((resolve) => {
      openJoin = resolve
    })
    const realCreate = daily.createCallObject.bind(daily)
    daily.createCallObject = (opts: unknown) => {
      daily.createCallObject = realCreate
      const call: FakeCall = realCreate(opts)
      call.emitsLeftOnLeave = false
      call.joinImpl = async () => {
        await joinGate
        return { local: {} }
      }
      return call
    }

    let attempt!: Promise<void>
    act(() => {
      attempt = h.result.current.start('9876543210')
    })
    await waitFor(() => expect(daily.calls).toHaveLength(1))

    // #1 — the handler retires a call that never joined.
    await act(async () => {
      daily.last.emit('participant-left', { participant: { local: false } })
    })
    await waitFor(() => expect(deleteCalls).toBe(1))

    // #2 — the join now resolves into the stale-call branch, with the DELETE still pending.
    await act(async () => {
      openJoin()
      releaseDelete()
      await attempt
    })

    expect(deleteCalls).toBe(1)
    expect(finalState().call).toBe('ended')
  })
})

describe('the reason is never held hostage to the cleanup', () => {
  /**
   * Every branch that both reports a failure and hands the slot back must report first: the
   * DELETE can take as long as the server's teardown, and the user should not stare at a
   * disabled control with no explanation for that whole time.
   */
  it('shows why daily-js could not load before the DELETE returns', async () => {
    const h = hook()
    vi.stubGlobal('Daily', undefined)

    let attempt!: Promise<void>
    act(() => {
      attempt = h.result.current.start('9876543210')
    })

    await waitFor(() => expect(deleteCalls).toBe(1))
    // The DELETE is still open, and the message is already on screen.
    await waitFor(() => expect(finalState().error).toMatch(/could not load/i))
    expect(h.result.current.starting).toBe(true)

    await act(async () => {
      releaseDelete()
      await attempt
    })
    await waitFor(() => expect(h.result.current.starting).toBe(false))
  })

  it('shows why the call object could not be created before the DELETE returns', async () => {
    const h = hook()
    daily.createCallObject = () => {
      throw new Error('Duplicate DailyIframe instances are not allowed')
    }

    let attempt!: Promise<void>
    act(() => {
      attempt = h.result.current.start('9876543210')
    })

    await waitFor(() => expect(deleteCalls).toBe(1))
    await waitFor(() => expect(finalState().error).toMatch(/could not start the call/i))

    await act(async () => {
      releaseDelete()
      await attempt
    })
  })
})
