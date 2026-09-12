/**
 * F3: a lifecycle handler can retire the call while start() is still awaiting join().
 * When join() then resolves, the success path used to run unconditionally — reading
 * localAudio() off a destroyed object and flipping the UI back to `live` with no call
 * behind it and Start disabled.
 */
import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { initialSession, sessionReducer, type SessionAction } from '../state/sessionReducer'
import { FakeCall, FakeDaily, FakeMediaStream } from './testDouble'
import { useDailyCall } from './useDailyCall'

const SESSION = { room_url: 'https://x.daily.co/room', token: 'tok', session_id: 'sess-1' }

let daily: FakeDaily
let dispatched: SessionAction[]
const dispatch = (a: SessionAction) => {
  dispatched.push(a)
}
const kinds = () => dispatched.map((a) => a.type)
/** Where the real reducer lands after this sequence — the UI the user would see. */
const finalState = () => dispatched.reduce(sessionReducer, initialSession)

let deletes: string[] = []

function hook() {
  deletes = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'DELETE') {
        deletes.push(String(input))
        return new Response(null, { status: 204 })
      }
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

/** Start a call whose join() hangs until the returned resolver is called. */
function gatedJoin() {
  let open: () => void = () => {}
  const gate = new Promise<void>((resolve) => {
    open = resolve
  })
  const realCreate = daily.createCallObject.bind(daily)
  daily.createCallObject = (opts: unknown) => {
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
afterEach(() => vi.unstubAllGlobals())

describe('a terminal event arrives while join() is still pending', () => {
  it('never reports joined when the bot leaves first', async () => {
    const h = hook()
    const { open } = gatedJoin()

    const starting = act(async () => {
      await h.result.current.start()
    })
    await waitFor(() => expect(daily.calls).toHaveLength(1))

    await act(async () => {
      daily.last.emit('participant-left', { participant: { local: false } })
    })
    expect(kinds()).toContain('left')

    await act(async () => {
      open()
    })
    await starting

    expect(kinds()).not.toContain('joined')
    expect(finalState().call).toBe('ended')
  })

  it('never reports joined when the call errors first', async () => {
    const h = hook()
    const { open } = gatedJoin()

    const starting = act(async () => {
      await h.result.current.start()
    })
    await waitFor(() => expect(daily.calls).toHaveLength(1))

    await act(async () => {
      daily.last.emit('error', { errorMsg: 'Meeting has ended' })
    })
    await act(async () => {
      open()
    })
    await starting

    expect(kinds()).not.toContain('joined')
    expect(finalState().call).toBe('error')
    expect(finalState().error).toMatch(/meeting has ended/i)
  })

  it('never reports joined when the microphone is refused first', async () => {
    const h = hook()
    const { open } = gatedJoin()

    const starting = act(async () => {
      await h.result.current.start()
    })
    await waitFor(() => expect(daily.calls).toHaveLength(1))

    await act(async () => {
      daily.last.emit('camera-error', { error: { type: 'permissions', blockedBy: 'user' } })
    })
    await act(async () => {
      open()
    })
    await starting

    expect(kinds()).not.toContain('joined')
    expect(finalState().call).toBe('error')
    expect(finalState().error).toMatch(/microphone/i)
  })

  it('does not leave the message it already showed overwritten by a later one', async () => {
    const h = hook()
    const { open } = gatedJoin()
    const starting = act(async () => {
      await h.result.current.start()
    })
    await waitFor(() => expect(daily.calls).toHaveLength(1))
    await act(async () => {
      daily.last.emit('camera-error', { error: { type: 'not-found' } })
    })
    await act(async () => {
      open()
    })
    await starting

    // the handler's sentence stands; no generic "could not join" on top of it
    expect(finalState().error).toMatch(/no microphone/i)
    expect(dispatched.filter((a) => a.type === 'error')).toHaveLength(1)
  })

  it('hands the server session back, since the call never came up', async () => {
    const h = hook()
    const { open } = gatedJoin()
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

    await waitFor(() => expect(deletes).toEqual(['/api/sessions/sess-1']))
  })

  it('lets the user start a working call straight afterwards', async () => {
    const h = hook()
    const { open } = gatedJoin()
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

    // a plain call object for the retry
    daily.createCallObject = FakeDaily.prototype.createCallObject.bind(daily)
    await act(async () => {
      await h.result.current.start()
    })

    expect(daily.calls).toHaveLength(2)
    expect(kinds().filter((k) => k === 'joined')).toHaveLength(1)
    expect(finalState().call).toBe('live')
  })
})

describe('the ordinary case still works', () => {
  it('reports joined when nothing interrupts the join', async () => {
    const h = hook()
    const { open } = gatedJoin()
    const starting = act(async () => {
      await h.result.current.start()
    })
    await waitFor(() => expect(daily.calls).toHaveLength(1))
    await act(async () => {
      open()
    })
    await starting

    expect(kinds()).toEqual(['connect', 'joined'])
    expect(finalState().call).toBe('live')
    expect(deletes).toEqual([])
  })
})
