/**
 * Regressions from the owner's first live call: one POST /api/sessions 201, then fifteen
 * more from the same page, all answered 409. Covers how many times start() may post, what
 * a 409 says to the user, and whether a call can be started again after it ends.
 */
import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SessionAction } from '../state/sessionReducer'
import { FakeDaily, FakeMediaStream } from './testDouble'
import { useDailyCall } from './useDailyCall'

const SESSION = { room_url: 'https://x.daily.co/room', token: 'tok', session_id: 's1' }

let daily: FakeDaily
let dispatched: SessionAction[]
const dispatch = (a: SessionAction) => {
  dispatched.push(a)
}
const errorText = () => {
  const e = [...dispatched].reverse().find((a) => a.type === 'error')
  return e && e.type === 'error' ? e.message : undefined
}

const ok = () => new Response(JSON.stringify(SESSION), { status: 201 })

/** Retiring a call now also DELETEs its session, so count starts, not every request. */
const posts = (fetchImpl: ReturnType<typeof vi.fn>) =>
  fetchImpl.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === 'POST')
    .length
const conflict = () => new Response('a session is already running', { status: 409 })

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

describe('start posts exactly once per gesture', () => {
  it('does not post twice when two gestures land inside the same fetch', async () => {
    // The guard used to read a ref that start() only sets after awaiting the POST, so two
    // clicks a few milliseconds apart both got through.
    let release: (r: Response) => void = () => {}
    const pending = new Promise<Response>((resolve) => {
      release = resolve
    })
    const fetchImpl = vi.fn(() => pending)
    const hook = hookWith(fetchImpl)

    await act(async () => {
      void hook.result.current.start()
      void hook.result.current.start()
      void hook.result.current.start()
      release(ok())
      await pending
    })

    expect(fetchImpl).toHaveBeenCalledTimes(1)
    expect(daily.calls).toHaveLength(1)
    expect(dispatched.filter((a) => a.type === 'connect')).toHaveLength(1)
  })

  it('still refuses to post while a call is live', async () => {
    const fetchImpl = vi.fn(async () => ok())
    const hook = hookWith(fetchImpl)
    await act(async () => {
      await hook.result.current.start()
    })
    await act(async () => {
      await hook.result.current.start()
      await hook.result.current.start()
    })
    expect(fetchImpl).toHaveBeenCalledTimes(1)
  })
})

describe('a 409 is its own message', () => {
  it('says a call is already running instead of blaming the network', async () => {
    const fetchImpl = vi.fn(async () => conflict())
    const hook = hookWith(fetchImpl)
    await act(async () => {
      await hook.result.current.start()
    })
    expect(errorText()).toMatch(/already running/i)
    expect(errorText()).not.toMatch(/could not reach/i)
    expect(daily.calls).toHaveLength(0)
  })

  it('reports the 201 then 409 sequence the live call produced', async () => {
    const fetchImpl = vi.fn(async () => (fetchImpl.mock.calls.length === 1 ? ok() : conflict()))
    const hook = hookWith(fetchImpl)
    await act(async () => {
      await hook.result.current.start()
    })
    expect(errorText()).toBeUndefined()

    // End the call, so the client is willing to start another one.
    await act(async () => {
      await hook.result.current.stop()
    })
    await act(async () => {
      await hook.result.current.start()
    })
    expect(fetchImpl).toHaveBeenCalledTimes(2)
    expect(errorText()).toMatch(/already running/i)
  })
})

describe('the call object is released whenever the call is over', () => {
  it('lets the user start again after the bot leaves', async () => {
    const fetchImpl = vi.fn(async () => ok())
    const hook = hookWith(fetchImpl)
    await act(async () => {
      await hook.result.current.start()
    })
    const first = daily.last

    await act(async () => {
      daily.last.emit('participant-left', { participant: { local: false } })
    })
    await waitFor(() => expect(first.destroyed).toBe(1))

    await act(async () => {
      await hook.result.current.start()
    })
    expect(posts(fetchImpl)).toBe(2)
    expect(daily.calls).toHaveLength(2)
  })

  it('lets the user start again after a fatal call error', async () => {
    const fetchImpl = vi.fn(async () => ok())
    const hook = hookWith(fetchImpl)
    await act(async () => {
      await hook.result.current.start()
    })
    await act(async () => {
      daily.last.emit('error', { errorMsg: 'Meeting has ended' })
    })
    await waitFor(() => expect(daily.calls[0].destroyed).toBe(1))

    await act(async () => {
      await hook.result.current.start()
    })
    expect(posts(fetchImpl)).toBe(2)
  })

  it('lets the user start again after the microphone was blocked', async () => {
    const fetchImpl = vi.fn(async () => ok())
    const hook = hookWith(fetchImpl)
    await act(async () => {
      await hook.result.current.start()
    })
    await act(async () => {
      daily.last.emit('camera-error', { error: { type: 'permissions', blockedBy: 'user' } })
    })
    await waitFor(() => expect(daily.calls[0].destroyed).toBe(1))

    await act(async () => {
      await hook.result.current.start()
    })
    expect(posts(fetchImpl)).toBe(2)
  })
})
