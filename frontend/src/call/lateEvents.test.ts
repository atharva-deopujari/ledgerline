/**
 * F3: every call object's handlers called a shared release() that tore down whatever was in
 * callRef at that moment. Real Daily delivers `left-meeting` some time after the call has
 * gone, so an old object's late event could leave and destroy the call that replaced it.
 * The old fake emitted `left-meeting` synchronously from leave(), which hid the ordering.
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
const count = (type: SessionAction['type']) => dispatched.filter((a) => a.type === type).length

function hook() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(SESSION), { status: 201 })),
  )
  const h = renderHook(() => useDailyCall(dispatch))
  h.result.current.audioRef.current = {
    srcObject: null,
    play: vi.fn(async () => {}),
  } as unknown as HTMLAudioElement
  return h
}

beforeEach(() => {
  daily = new FakeDaily()
  dispatched = []
  vi.stubGlobal('Daily', daily)
  vi.stubGlobal('MediaStream', FakeMediaStream)
})
afterEach(() => vi.unstubAllGlobals())

describe('a late event from the previous call', () => {
  it('does not tear down the call that replaced it', async () => {
    const h = hook()

    // First call joins, and holds its left-meeting back the way real Daily does.
    await act(async () => {
      await h.result.current.start()
    })
    const first = daily.last
    first.emitsLeftOnLeave = false

    // The bot leaves: the UI is told, and the old object is released.
    await act(async () => {
      first.emit('participant-left', { participant: { local: false } })
    })
    await waitFor(() => expect(first.destroyed).toBe(1))
    expect(count('left')).toBe(1)

    // The user starts another call, which joins.
    await act(async () => {
      await h.result.current.start()
    })
    const second = daily.last
    expect(daily.calls).toHaveLength(2)
    expect(second).not.toBe(first)

    // Now the first object finally emits the event it owed us.
    await act(async () => {
      first.emit('left-meeting', {})
    })

    expect(second.left).toBe(0)
    expect(second.destroyed).toBe(0)
    expect(count('left')).toBe(1)
  })

  it('ignores every late lifecycle event from a replaced call', async () => {
    const h = hook()
    await act(async () => {
      await h.result.current.start()
    })
    const first = daily.last
    first.emitsLeftOnLeave = false
    await act(async () => {
      first.emit('participant-left', { participant: { local: false } })
    })
    await waitFor(() => expect(first.destroyed).toBe(1))
    await act(async () => {
      await h.result.current.start()
    })
    const second = daily.last
    const errorsBefore = count('error')

    await act(async () => {
      first.emit('error', { errorMsg: 'the old room expired' })
      first.emit('camera-error', { error: { type: 'permissions', blockedBy: 'user' } })
      first.emit('participant-left', { participant: { local: false } })
    })

    expect(count('error')).toBe(errorsBefore)
    expect(count('left')).toBe(1)
    expect(second.destroyed).toBe(0)
  })

  it('still honours events from the call that is actually current', async () => {
    const h = hook()
    await act(async () => {
      await h.result.current.start()
    })
    await act(async () => {
      daily.last.emit('error', { errorMsg: 'Meeting has ended' })
    })
    expect(count('error')).toBe(1)
  })
})

describe('starting while the previous teardown is still running', () => {
  it('waits for it instead of putting two Daily objects in the air', async () => {
    const h = hook()
    await act(async () => {
      await h.result.current.start()
    })
    const first = daily.last
    first.emitsLeftOnLeave = false

    // Hold destroy() open so the teardown is observably pending.
    let release: () => void = () => {}
    first.destroyGate = new Promise<void>((resolve) => {
      release = resolve
    })

    act(() => {
      first.emit('participant-left', { participant: { local: false } })
    })
    await waitFor(() => expect(first.destroyed).toBe(1))
    // destroy() has been entered but has not resolved.

    let started = false
    const pending = act(async () => {
      await h.result.current.start()
      started = true
    })

    // Flush enough turns that an unguarded start() would have finished its POST and
    // created the second object by now; a single microtask tick would pass either way.
    for (let i = 0; i < 20; i += 1) await act(async () => {})
    expect(started).toBe(false)
    expect(daily.calls).toHaveLength(1)

    release()
    await pending

    expect(started).toBe(true)
    expect(daily.calls).toHaveLength(2)
  })
})
