/**
 * F1: a terminal event during a pending join retired the call and let the UI offer Start
 * again, but the committed server session was only cancelled in the branches that run after
 * `join()` settles. In between, the single server slot was still held — a retry got 409 for
 * the user's own dead call — and if `join()` never settled the slot was never returned.
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
let deletes: string[]

const dispatch = (a: SessionAction) => {
  dispatched.push(a)
}
const kinds = () => dispatched.map((a) => a.type)
const finalState = () => dispatched.reduce(sessionReducer, initialSession)

function hook() {
  posts = 0
  deletes = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'DELETE') {
        deletes.push(String(input))
        return new Response(null, { status: 204 })
      }
      posts += 1
      // The server keeps one call at a time: a second POST while a session is live is 409.
      if (posts > 1 && deletes.length === 0) return new Response('busy', { status: 409 })
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

/** Next call object created will hang in join() until `open()` is called. */
function gateNextJoin() {
  let open: () => void = () => {}
  const gate = new Promise<void>((resolve) => {
    open = resolve
  })
  const realCreate = daily.createCallObject.bind(daily)
  daily.createCallObject = (opts: unknown) => {
    daily.createCallObject = realCreate
    const call: FakeCall = realCreate(opts)
    call.emitsLeftOnLeave = false
    call.joinImpl = async () => {
      await gate
      return { local: {} }
    }
    return call
  }
  return { open }
}

beforeEach(() => {
  daily = new FakeDaily()
  dispatched = []
  vi.stubGlobal('Daily', daily)
  vi.stubGlobal('MediaStream', FakeMediaStream)
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('retrying in the window before the join settles', () => {
  it('returns the server slot the moment the call is retired, not when join settles', async () => {
    const h = hook()
    const { open } = gateNextJoin()
    const starting = act(async () => {
      await h.result.current.start()
    })
    await waitFor(() => expect(daily.calls).toHaveLength(1))

    await act(async () => {
      daily.last.emit('participant-left', { participant: { local: false } })
    })

    // The UI already says the call is over, so the slot must already be back.
    expect(finalState().call).toBe('ended')
    await waitFor(() => expect(deletes).toEqual(['/api/sessions/sess-1']))

    await act(async () => {
      open()
    })
    await starting
  })

  it('reports itself as still starting, so the UI can disable the control', async () => {
    const h = hook()
    const { open } = gateNextJoin()

    // A synchronous act() so the setStarting(true) that happens before start()'s first
    // await is flushed and visible on result.current.
    let attempt!: Promise<void>
    act(() => {
      attempt = h.result.current.start()
    })
    await waitFor(() => expect(daily.calls).toHaveLength(1))
    expect(h.result.current.starting).toBe(true)

    await act(async () => {
      daily.last.emit('error', { errorMsg: 'Meeting has ended' })
    })
    // The reducer already says the call is over, but the attempt has not settled: the hook
    // must say so rather than letting an enabled control be pressed into silence.
    expect(finalState().call).toBe('error')
    expect(h.result.current.starting).toBe(true)

    await act(async () => {
      open()
      await attempt
    })
    expect(h.result.current.starting).toBe(false)
  })

  it('refuses a retry while the first attempt is still in flight, so no 409 is shown', async () => {
    const h = hook()
    const { open } = gateNextJoin()
    const starting = act(async () => {
      await h.result.current.start()
    })
    await waitFor(() => expect(daily.calls).toHaveLength(1))

    await act(async () => {
      daily.last.emit('error', { errorMsg: 'Meeting has ended' })
    })

    // The user presses Try again while join() is still hanging.
    await act(async () => {
      await h.result.current.start()
    })

    expect(posts).toBe(1)
    expect(daily.calls).toHaveLength(1)
    expect(finalState().error).toMatch(/meeting has ended/i)
    expect(finalState().error).not.toMatch(/already running/i)

    await act(async () => {
      open()
    })
    await starting
  })

  it('cancels the session exactly once across the whole sequence', async () => {
    const h = hook()
    const { open } = gateNextJoin()
    const starting = act(async () => {
      await h.result.current.start()
    })
    await waitFor(() => expect(daily.calls).toHaveLength(1))
    await act(async () => {
      daily.last.emit('participant-left', { participant: { local: false } })
    })
    await waitFor(() => expect(deletes).toHaveLength(1))

    // The stale-join branch runs later and must not cancel a second time.
    await act(async () => {
      open()
    })
    await starting
    expect(deletes).toEqual(['/api/sessions/sess-1'])
  })

  it('lets a fresh call start once the first attempt has settled', async () => {
    const h = hook()
    const { open } = gateNextJoin()
    const starting = act(async () => {
      await h.result.current.start()
    })
    await waitFor(() => expect(daily.calls).toHaveLength(1))
    await act(async () => {
      daily.last.emit('participant-left', { participant: { local: false } })
    })
    await act(async () => {
      open()
    })
    await starting

    await act(async () => {
      await h.result.current.start()
    })
    expect(posts).toBe(2)
    expect(daily.calls).toHaveLength(2)
    expect(finalState().call).toBe('live')
  })
})

describe('a join that never settles', () => {
  it('gives up, tells the user, and returns the slot', async () => {
    vi.useFakeTimers()
    const h = hook()
    const realCreate = daily.createCallObject.bind(daily)
    daily.createCallObject = (opts: unknown) => {
      const call: FakeCall = realCreate(opts)
      call.emitsLeftOnLeave = false
      call.joinImpl = () => new Promise<never>(() => {})
      return call
    }

    let settled = false
    const starting = h.result.current.start().then(() => {
      settled = true
    })

    await vi.advanceTimersByTimeAsync(1_000)
    expect(settled).toBe(false)

    await vi.advanceTimersByTimeAsync(30_000)
    await starting

    expect(settled).toBe(true)
    expect(kinds()).not.toContain('joined')
    expect(finalState().call).toBe('error')
    expect(deletes).toEqual(['/api/sessions/sess-1'])
  })
})
