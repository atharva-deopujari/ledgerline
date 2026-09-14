/**
 * The judge runs after the call, so the screen has to wait for it: poll every two seconds,
 * give up after a minute, and never leave the person looking at a panel that says nothing.
 */
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Verdict } from '../protocol/verdict'
import sample from '../protocol/verdict.sample.json'
import { useVerdict } from './useVerdict'

/** The sample generated from the Python model; the endpoint answers this shape. */
const READY = sample as Verdict

let fetchMock: ReturnType<typeof vi.fn>

const pending = () => new Response('', { status: 202 })
const ready = () => new Response(JSON.stringify(READY), { status: 200 })

/**
 * Advance the fake clock and let the promises the response resolves through run.
 * `waitFor` is no use here: it waits on a clock this test controls.
 */
const tick = async (ms = 2000) => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

/** Just the microtasks: the first poll fires on mount, not on a timer. */
const settle = () => tick(0)

beforeEach(() => {
  vi.useFakeTimers()
  fetchMock = vi.fn(async () => pending())
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('useVerdict', () => {
  it('asks for nothing while the call is still running', async () => {
    renderHook(() => useVerdict('s1', false))
    await tick(10_000)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('asks for nothing when there is no session to ask about', async () => {
    renderHook(() => useVerdict(null, true))
    await tick(10_000)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('says it is reviewing from the moment the call ends', () => {
    const { result } = renderHook(() => useVerdict('s1', true))
    expect(result.current.phase).toBe('reviewing')
    expect(result.current.verdict).toBeNull()
  })

  it('polls every two seconds while the server answers 202', async () => {
    renderHook(() => useVerdict('s1', true))
    await settle()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledWith('/api/sessions/s1/verdict')

    await tick()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    await tick()
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('stops the moment a verdict arrives and hands it over', async () => {
    fetchMock.mockImplementation(async () =>
      fetchMock.mock.calls.length >= 2 ? ready() : pending(),
    )
    const { result } = renderHook(() => useVerdict('s1', true))

    await settle()
    await tick()
    expect(result.current.phase).toBe('done')
    expect(result.current.verdict).toEqual(READY)

    const settled = fetchMock.mock.calls.length
    await tick(20_000)
    expect(fetchMock).toHaveBeenCalledTimes(settled)
  })

  it('keeps polling through a network error rather than giving up on one', async () => {
    fetchMock.mockImplementation(async () => {
      if (fetchMock.mock.calls.length === 1) throw new Error('offline')
      return ready()
    })
    const { result } = renderHook(() => useVerdict('s1', true))

    await settle()
    await tick()
    expect(result.current.phase).toBe('done')
  })

  it('gives up after a minute, and says so rather than reviewing for ever', async () => {
    const { result } = renderHook(() => useVerdict('s1', true))
    await settle()
    await tick(60_000)
    expect(result.current.phase).toBe('gave-up')

    const settled = fetchMock.mock.calls.length
    await tick(10_000)
    expect(fetchMock).toHaveBeenCalledTimes(settled)
  })

  it('ignores a body that is not a verdict and keeps waiting', async () => {
    fetchMock.mockImplementation(async () => {
      if (fetchMock.mock.calls.length === 1) {
        // What ?mock=1 answers today for anything under /api/sessions.
        return new Response(JSON.stringify({ room_url: 'x', token: 't', session_id: 's' }), {
          status: 200,
        })
      }
      return ready()
    })
    const { result } = renderHook(() => useVerdict('s1', true))

    await settle()
    await tick()
    expect(result.current.verdict).toEqual(READY)
  })
})
