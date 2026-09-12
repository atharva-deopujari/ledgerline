/**
 * F8: POST /api/sessions commits a server-side session before the browser has joined
 * anything. Every failure between that 201 and `joined` must hand the slot back with
 * DELETE /api/sessions/{session_id}, or the next attempt gets 409 until the room expires.
 */
import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SessionAction } from '../state/sessionReducer'
import { FakeDaily, FakeMediaStream } from './testDouble'
import { useDailyCall } from './useDailyCall'

const SESSION = { room_url: 'https://x.daily.co/room', token: 'tok', session_id: 'sess-1' }

let daily: FakeDaily
let dispatched: SessionAction[]
const dispatch = (a: SessionAction) => {
  dispatched.push(a)
}
const errorText = () => {
  const e = [...dispatched].reverse().find((a) => a.type === 'error')
  return e && e.type === 'error' ? e.message : undefined
}

/** Records every call so we can assert the DELETE and its method. */
function trackedFetch(body: unknown = SESSION) {
  const calls: { url: string; method: string }[] = []
  const impl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : String(input)
    calls.push({ url, method: init?.method ?? 'GET' })
    if (init?.method === 'DELETE') return new Response(null, { status: 204 })
    return new Response(JSON.stringify(body), { status: 201 })
  })
  return { impl, calls }
}

const deletes = (calls: { url: string; method: string }[]) =>
  calls.filter((c) => c.method === 'DELETE')

function hookWith(fetchImpl: ReturnType<typeof vi.fn>) {
  vi.stubGlobal('fetch', fetchImpl)
  const hook = renderHook(() => useDailyCall(dispatch))
  hook.result.current.audioRef.current = {
    srcObject: null,
    play: vi.fn(async () => {}),
  } as unknown as HTMLAudioElement
  return hook
}

beforeEach(() => {
  daily = new FakeDaily()
  dispatched = []
  vi.stubGlobal('Daily', daily)
  vi.stubGlobal('MediaStream', FakeMediaStream)
})
afterEach(() => vi.unstubAllGlobals())

describe('handing the session back', () => {
  it('cancels the session when daily-js never loaded', async () => {
    const { impl, calls } = trackedFetch()
    const hook = hookWith(impl)
    vi.stubGlobal('Daily', undefined)

    await act(async () => {
      await hook.result.current.start()
    })

    await waitFor(() => expect(deletes(calls)).toHaveLength(1))
    expect(deletes(calls)[0].url).toBe('/api/sessions/sess-1')
    expect(errorText()).toMatch(/could not load/i)
  })

  it('cancels the session when the call object cannot be created', async () => {
    const { impl, calls } = trackedFetch()
    const hook = hookWith(impl)
    daily.createCallObject = () => {
      throw new Error('Duplicate DailyIframe instances are not allowed')
    }

    await act(async () => {
      await hook.result.current.start()
    })

    await waitFor(() => expect(deletes(calls)).toHaveLength(1))
    expect(errorText()).toBeTruthy()
  })

  it('cancels the session when the join is rejected', async () => {
    const { impl, calls } = trackedFetch()
    const hook = hookWith(impl)
    const realCreate = daily.createCallObject.bind(daily)
    daily.createCallObject = (opts: unknown) => {
      const call = realCreate(opts)
      call.joinImpl = async () => {
        throw new Error('room expired')
      }
      return call
    }

    await act(async () => {
      await hook.result.current.start()
    })

    await waitFor(() => expect(deletes(calls)).toHaveLength(1))
    expect(deletes(calls)[0].url).toBe('/api/sessions/sess-1')
    expect(errorText()).toMatch(/could not join/i)
    expect(daily.last.destroyed).toBe(1)
  })

  it('leaves the session alone once the call is up', async () => {
    const { impl, calls } = trackedFetch()
    const hook = hookWith(impl)

    await act(async () => {
      await hook.result.current.start()
    })

    expect(deletes(calls)).toHaveLength(0)
    expect(errorText()).toBeUndefined()
  })

  it('does not cancel anything when the POST itself failed', async () => {
    const calls: { url: string; method: string }[] = []
    const impl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), method: init?.method ?? 'GET' })
      return new Response('busy', { status: 409 })
    })
    const hook = hookWith(impl)

    await act(async () => {
      await hook.result.current.start()
    })

    expect(deletes(calls)).toHaveLength(0)
    expect(errorText()).toMatch(/already running/i)
  })

  it('still reports the real error when the cancel itself fails', async () => {
    // The DELETE is best effort: the user must see why the call did not start, not why
    // the cleanup did not.
    const impl = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'DELETE') throw new TypeError('Failed to fetch')
      return new Response(JSON.stringify(SESSION), { status: 201 })
    })
    const hook = hookWith(impl)
    vi.stubGlobal('Daily', undefined)

    await act(async () => {
      await hook.result.current.start()
    })

    expect(errorText()).toMatch(/could not load/i)
  })

  it('starts cleanly on the very next attempt', async () => {
    const { impl, calls } = trackedFetch()
    const hook = hookWith(impl)
    const realCreate = daily.createCallObject.bind(daily)
    let firstJoin = true
    daily.createCallObject = (opts: unknown) => {
      const call = realCreate(opts)
      if (firstJoin) {
        firstJoin = false
        call.joinImpl = async () => {
          throw new Error('room expired')
        }
      }
      return call
    }

    await act(async () => {
      await hook.result.current.start()
    })
    await waitFor(() => expect(deletes(calls)).toHaveLength(1))

    await act(async () => {
      await hook.result.current.start()
    })
    expect(dispatched.filter((a) => a.type === 'joined')).toHaveLength(1)
  })

  it('skips the cancel when the server did not name the session', async () => {
    // Without a session_id there is nothing to address; the call must still work.
    const { impl, calls } = trackedFetch({ room_url: 'https://x.daily.co/r', token: 't' })
    const hook = hookWith(impl)
    vi.stubGlobal('Daily', undefined)

    await act(async () => {
      await hook.result.current.start()
    })

    expect(deletes(calls)).toHaveLength(0)
    expect(errorText()).toMatch(/could not load/i)
  })
})

describe("a call that actually went live is the server's to end", () => {
  /**
   * The server's DELETE cancels the asyncio task. Once the bot has joined, run_session is
   * already in its finally block writing the transcript — the eval corpus — and a
   * CancelledError landing on an await there skips that write. So the browser only hands
   * back a slot for a call that never reached live.
   */
  it('sends no DELETE when the bot leaves at the end of a live call', async () => {
    const { impl, calls } = trackedFetch()
    const hook = hookWith(impl)
    await act(async () => {
      await hook.result.current.start()
    })
    expect(dispatched.some((a) => a.type === 'joined')).toBe(true)

    await act(async () => {
      daily.last.emit('participant-left', { participant: { local: false } })
    })
    await waitFor(() => expect(daily.calls[0].destroyed).toBe(1))

    expect(deletes(calls)).toHaveLength(0)
  })

  it('sends no DELETE when a live call dies on a fatal error', async () => {
    const { impl, calls } = trackedFetch()
    const hook = hookWith(impl)
    await act(async () => {
      await hook.result.current.start()
    })
    await act(async () => {
      daily.last.emit('error', { errorMsg: 'Meeting has ended' })
    })
    await waitFor(() => expect(daily.calls[0].destroyed).toBe(1))

    expect(deletes(calls)).toHaveLength(0)
  })

  it('sends no DELETE when the user presses End on a live call', async () => {
    const { impl, calls } = trackedFetch()
    const hook = hookWith(impl)
    await act(async () => {
      await hook.result.current.start()
    })
    await act(async () => {
      await hook.result.current.stop()
    })
    expect(deletes(calls)).toHaveLength(0)
  })

  it('still cancels a call retired before it ever joined', async () => {
    const { impl, calls } = trackedFetch()
    const hook = hookWith(impl)
    const realCreate = daily.createCallObject.bind(daily)
    daily.createCallObject = (opts: unknown) => {
      const call = realCreate(opts)
      call.joinImpl = async () => {
        throw new Error('room expired')
      }
      return call
    }
    await act(async () => {
      await hook.result.current.start()
    })
    await waitFor(() => expect(deletes(calls)).toHaveLength(1))
  })
})
