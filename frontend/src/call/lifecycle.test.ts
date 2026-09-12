/**
 * The lifecycle rules on their own, with no React and no Daily. Each of these encodes a
 * defect that reached a live call; the hook tests cover the same ground through the UI, and
 * these pin the rules where they are now written.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CallLifecycle } from './lifecycle'
import type { DailyCall } from './types'

/** Enough of a call object for the lifecycle to leave and destroy. */
function fakeCall(): DailyCall & { left: number; destroyed: number } {
  const call = {
    left: 0,
    destroyed: 0,
    on: () => call,
    join: async () => ({}),
    leave: async () => {
      call.left += 1
    },
    destroy: async () => {
      call.destroyed += 1
    },
    localAudio: () => true,
    setLocalAudio: () => undefined,
  }
  return call as unknown as DailyCall & { left: number; destroyed: number }
}

let life: CallLifecycle

beforeEach(() => {
  life = new CallLifecycle()
})
afterEach(() => vi.unstubAllGlobals())

describe('the attempt guard', () => {
  it('is free to begin, then claimed', () => {
    expect(life.starting).toBe(false)
    expect(life.begin()).toBe(true)
    expect(life.starting).toBe(true)
  })

  it('refuses a second attempt while one is in flight', () => {
    life.begin()
    expect(life.begin()).toBe(false)
  })

  it('refuses a new attempt while a call is up', async () => {
    life.begin()
    life.adopt(fakeCall())
    await life.end()
    expect(life.starting).toBe(false)
    expect(life.begin()).toBe(false)
  })

  it('is free again once the call has been retired', async () => {
    life.begin()
    const call = fakeCall()
    life.adopt(call)
    await life.end()
    await life.retire(call)
    expect(life.begin()).toBe(true)
  })

  it('forgets the previous attempt having joined', async () => {
    life.begin()
    life.markJoined()
    expect(life.joined).toBe(true)
    await life.end()
    life.begin()
    expect(life.joined).toBe(false)
  })
})

describe('which call is current', () => {
  it('only the adopted one', () => {
    const first = fakeCall()
    const second = fakeCall()
    life.begin()
    life.adopt(first)
    expect(life.isCurrent(first)).toBe(true)
    expect(life.isCurrent(second)).toBe(false)
  })

  it('forget reports whether it dropped the call, and only drops the current one', () => {
    const first = fakeCall()
    const second = fakeCall()
    life.begin()
    life.adopt(first)
    expect(life.forget(second)).toBe(false)
    expect(life.isCurrent(first)).toBe(true)
    expect(life.forget(first)).toBe(true)
    expect(life.call).toBeNull()
  })
})

describe('retiring a call', () => {
  it('leaves then destroys it, and runs the callback only if it was current', async () => {
    const call = fakeCall()
    const onForgotten = vi.fn()
    life.begin()
    life.adopt(call)

    await life.retire(call, onForgotten)

    expect(call.left).toBe(1)
    expect(call.destroyed).toBe(1)
    expect(onForgotten).toHaveBeenCalledTimes(1)
    expect(life.call).toBeNull()
  })

  it('retires a call that is no longer current without touching the current one', async () => {
    const stale = fakeCall()
    const live = fakeCall()
    const onForgotten = vi.fn()
    life.begin()
    life.adopt(stale)
    life.forget(stale)
    life.adopt(live)

    await life.retire(stale, onForgotten)

    expect(stale.destroyed).toBe(1)
    expect(live.destroyed).toBe(0)
    expect(onForgotten).not.toHaveBeenCalled()
    expect(life.isCurrent(live)).toBe(true)
  })

  it('does nothing at all for a null call', async () => {
    const onForgotten = vi.fn()
    await life.retire(null, onForgotten)
    expect(onForgotten).not.toHaveBeenCalled()
  })

  it('destroys even when leaving throws', async () => {
    const call = fakeCall()
    call.leave = async () => {
      throw new Error('already gone')
    }
    life.begin()
    life.adopt(call)
    await expect(life.retire(call)).rejects.toThrow('already gone')
    expect(call.destroyed).toBe(1)
  })

  it('awaitTeardown waits for a retire that is still running', async () => {
    const call = fakeCall()
    let release: () => void = () => {}
    call.destroy = () =>
      new Promise<void>((resolve) => {
        release = () => {
          call.destroyed += 1
          resolve()
        }
      })
    life.begin()
    life.adopt(call)

    const retiring = life.retire(call)
    let waited = false
    const waiting = life.awaitTeardown().then(() => {
      waited = true
    })
    await Promise.resolve()
    expect(waited).toBe(false)

    release()
    await retiring
    await waiting
    expect(waited).toBe(true)
  })
})

describe('cancelling a server session', () => {
  const stubFetch = () => {
    const calls: string[] = []
    let release: () => void = () => {}
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        calls.push(String(input))
        await gate
        return new Response(null, { status: 204 })
      }),
    )
    return { calls, release }
  }

  it('issues one DELETE and reuses its promise for a repeat call', async () => {
    const { calls, release } = stubFetch()
    const first = life.cancelSession('sess-1')
    const second = life.cancelSession('sess-1')
    expect(second).toBe(first)
    release()
    await first
    expect(calls).toEqual(['/api/sessions/sess-1'])
  })

  it('escapes the id in the path', async () => {
    const { calls, release } = stubFetch()
    const work = life.cancelSession('a/b c')
    release()
    await work
    expect(calls).toEqual(['/api/sessions/a%2Fb%20c'])
  })

  it('does nothing without an id', async () => {
    const { calls, release } = stubFetch()
    await life.cancelSession(undefined)
    release()
    expect(calls).toEqual([])
  })

  it('swallows a failed DELETE, because the user needs the real reason instead', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch')
      }),
    )
    await expect(life.cancelSession('sess-1')).resolves.toBeUndefined()
  })

  it("end() waits for this attempt's own cancellation before freeing the guard", async () => {
    const { release } = stubFetch()
    life.begin()
    life.noteSession('sess-1')
    void life.cancelSession('sess-1')

    let ended = false
    const ending = life.end().then(() => {
      ended = true
    })
    for (let i = 0; i < 5; i += 1) await Promise.resolve()
    expect(ended).toBe(false)
    expect(life.starting).toBe(true)

    release()
    await ending
    expect(life.starting).toBe(false)
  })

  it('end() does not wait for a cancellation belonging to another attempt', async () => {
    const { release } = stubFetch()
    void life.cancelSession('someone-else')
    life.begin()
    life.noteSession('sess-1')

    await life.end()
    expect(life.starting).toBe(false)
    release()
  })

  it('awaitCancellations waits for every outstanding DELETE', async () => {
    const { release } = stubFetch()
    void life.cancelSession('sess-1')
    void life.cancelSession('sess-2')

    let settled = false
    const waiting = life.awaitCancellations().then(() => {
      settled = true
    })
    for (let i = 0; i < 5; i += 1) await Promise.resolve()
    expect(settled).toBe(false)

    release()
    await waiting
    expect(settled).toBe(true)
  })
})
