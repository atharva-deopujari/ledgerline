import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import sample from '../protocol/sample.json'
import type { SessionAction } from '../state/sessionReducer'
import { FakeDaily, FakeMediaStream } from './testDouble'
import { useDailyCall } from './useDailyCall'

const SESSION = { room_url: 'https://x.daily.co/room', token: 'tok', session_id: 's1' }

let daily: FakeDaily
let dispatched: SessionAction[]
const dispatch = (a: SessionAction) => {
  dispatched.push(a)
}
const kinds = () => dispatched.map((a) => a.type)
const errorText = () => {
  const e = dispatched.find((a) => a.type === 'error')
  return e && e.type === 'error' ? e.message : undefined
}

function okFetch(body: unknown = SESSION) {
  return vi.fn(async () => new Response(JSON.stringify(body), { status: 200 }))
}

async function startedHook(fetchImpl = okFetch()) {
  vi.stubGlobal('fetch', fetchImpl)
  const hook = renderHook(() => useDailyCall(dispatch))
  const audio = { srcObject: null as unknown, play: vi.fn(async () => {}) }
  hook.result.current.audioRef.current = audio as unknown as HTMLAudioElement
  await act(async () => {
    await hook.result.current.start()
  })
  return { hook, audio }
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

describe('start', () => {
  it('posts to /api/sessions and joins the room it returns', async () => {
    const fetchImpl = okFetch()
    await startedHook(fetchImpl)

    expect(fetchImpl).toHaveBeenCalledWith(
      '/api/sessions',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(daily.options[0]).toMatchObject({ videoSource: false })
    expect(daily.last.joined).toMatchObject({ url: SESSION.room_url, token: SESSION.token })
    expect(kinds()).toEqual(['connect', 'joined'])
  })

  it('refuses to create a second call object while one is live', async () => {
    const { hook } = await startedHook()
    await act(async () => {
      await hook.result.current.start()
    })
    expect(daily.calls).toHaveLength(1)
  })
})

describe('bot audio', () => {
  it('attaches a remote audio track to the audio element and plays it', async () => {
    const { audio } = await startedHook()
    const track = { id: 't1' }
    act(() => {
      daily.last.emit('track-started', { type: 'audio', participant: { local: false }, track })
    })
    expect(audio.srcObject).toBeInstanceOf(FakeMediaStream)
    expect((audio.srcObject as FakeMediaStream).tracks).toEqual([track])
    expect(audio.play).toHaveBeenCalled()
  })

  it('ignores the local track and any video track', async () => {
    const { audio } = await startedHook()
    act(() => {
      daily.last.emit('track-started', { type: 'audio', participant: { local: true }, track: {} })
      daily.last.emit('track-started', { type: 'video', participant: { local: false }, track: {} })
    })
    expect(audio.srcObject).toBeNull()
    expect(audio.play).not.toHaveBeenCalled()
  })

  it('surfaces a blocked autoplay as a human sentence', async () => {
    const { hook, audio } = await startedHook()
    audio.play = vi.fn(async () => {
      throw Object.assign(new Error('blocked'), { name: 'NotAllowedError' })
    })
    await act(async () => {
      daily.last.emit('track-started', { type: 'audio', participant: { local: false }, track: {} })
    })
    await waitFor(() => expect(errorText()).toMatch(/audio/i))
    expect(hook.result.current).toBeTruthy()
  })
})

describe('app messages', () => {
  it('dispatches a parsed cards snapshot', async () => {
    await startedHook()
    act(() => {
      daily.last.emit('app-message', { data: sample, fromId: 'bot' })
    })
    const cards = dispatched.find((a) => a.type === 'cards')
    expect(cards).toBeTruthy()
    expect(cards!.type === 'cards' && cards!.message.v).toBe(7)
  })

  it('maps the four RTVI messages onto reducer actions', async () => {
    await startedHook()
    act(() => {
      daily.last.emit('app-message', {
        data: { label: 'rtvi-ai', type: 'bot-transcription', data: { text: 'Rent?' } },
      })
      daily.last.emit('app-message', { data: { label: 'rtvi-ai', type: 'bot-started-speaking' } })
      daily.last.emit('app-message', { data: { label: 'rtvi-ai', type: 'bot-stopped-speaking' } })
      daily.last.emit('app-message', { data: { label: 'rtvi-ai', type: 'user-started-speaking' } })
    })
    expect(kinds()).toEqual([
      'connect',
      'joined',
      'botText',
      'botSpeaking',
      'botStopped',
      'userSpeaking',
    ])
    const text = dispatched.find((a) => a.type === 'botText')
    expect(text!.type === 'botText' && text!.text).toBe('Rent?')
  })

  it('drops traffic the parser rejects', async () => {
    await startedHook()
    act(() => {
      daily.last.emit('app-message', { data: { label: 'rtvi-ai', type: 'bot-ready' } })
      daily.last.emit('app-message', { data: { type: 'cards', v: 'nope' } })
      daily.last.emit('app-message', { data: 'hello' })
    })
    expect(kinds()).toEqual(['connect', 'joined'])
  })

  it('shows thinking once the user has spoken and the bot has not replied yet', async () => {
    vi.useFakeTimers()
    await startedHook()
    act(() => {
      daily.last.emit('app-message', { data: { label: 'rtvi-ai', type: 'user-started-speaking' } })
    })
    expect(kinds()).not.toContain('thinking')
    act(() => {
      vi.advanceTimersByTime(2000)
    })
    expect(kinds()).toContain('thinking')
  })

  it('does not show thinking if the bot starts speaking first', async () => {
    vi.useFakeTimers()
    await startedHook()
    act(() => {
      daily.last.emit('app-message', { data: { label: 'rtvi-ai', type: 'user-started-speaking' } })
      daily.last.emit('app-message', { data: { label: 'rtvi-ai', type: 'bot-started-speaking' } })
      vi.advanceTimersByTime(5000)
    })
    expect(kinds()).not.toContain('thinking')
  })
})

describe('leaving', () => {
  it('dispatches left when the bot leaves', async () => {
    await startedHook()
    act(() => {
      daily.last.emit('participant-left', { participant: { local: false } })
    })
    expect(kinds()).toContain('left')
  })

  it('ignores a local participant-left', async () => {
    await startedHook()
    act(() => {
      daily.last.emit('participant-left', { participant: { local: true } })
    })
    expect(kinds()).not.toContain('left')
  })

  it('stop() leaves and destroys the call object', async () => {
    const { hook } = await startedHook()
    const call = daily.last
    await act(async () => {
      await hook.result.current.stop()
    })
    expect(call.left).toBe(1)
    expect(call.destroyed).toBe(1)
    expect(kinds()).toContain('left')
  })

  it('start() works again after stop()', async () => {
    const { hook } = await startedHook()
    await act(async () => {
      await hook.result.current.stop()
    })
    await act(async () => {
      await hook.result.current.start()
    })
    expect(daily.calls).toHaveLength(2)
  })
})

describe('mic', () => {
  it('toggles the local audio track and reports its state', async () => {
    const { hook } = await startedHook()
    expect(hook.result.current.micOn).toBe(true)
    act(() => {
      hook.result.current.toggleMic()
    })
    expect(daily.last.audioOn).toBe(false)
    await waitFor(() => expect(hook.result.current.micOn).toBe(false))
    act(() => {
      hook.result.current.toggleMic()
    })
    await waitFor(() => expect(hook.result.current.micOn).toBe(true))
  })
})

describe('errors', () => {
  it('says the server could not be reached when the POST fails', async () => {
    await startedHook(
      vi.fn(async () => {
        throw new TypeError('Failed to fetch')
      }),
    )
    expect(errorText()).toMatch(/could not reach the server/i)
    expect(daily.calls).toHaveLength(0)
  })

  it('says the server could not be reached on a non-2xx', async () => {
    await startedHook(vi.fn(async () => new Response('no keys', { status: 500 })))
    expect(errorText()).toMatch(/could not reach the server/i)
  })

  it('rejects a malformed session response', async () => {
    await startedHook(okFetch({ nope: true }))
    expect(errorText()).toMatch(/could not reach the server/i)
    expect(daily.calls).toHaveLength(0)
  })

  it('says the room could not be joined when join() rejects', async () => {
    vi.stubGlobal('fetch', okFetch())
    const hook = renderHook(() => useDailyCall(dispatch))
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
    expect(errorText()).toMatch(/could not join/i)
    expect(daily.last.destroyed).toBe(1)
  })

  it('translates every camera-error type into its own sentence', async () => {
    const cases: [Record<string, unknown>, RegExp][] = [
      [{ type: 'permissions', blockedBy: 'user' }, /microphone.*(denied|blocked)/i],
      [{ type: 'not-found' }, /no microphone/i],
      [{ type: 'undefined-mediadevices' }, /https|localhost/i],
      [{ type: 'unknown', msg: 'NotReadableError' }, /microphone/i],
    ]
    for (const [error, pattern] of cases) {
      dispatched = []
      daily = new FakeDaily()
      vi.stubGlobal('Daily', daily)
      await startedHook()
      act(() => {
        daily.last.emit('camera-error', { error })
      })
      expect(errorText()).toMatch(pattern)
    }
  })

  it('surfaces a fatal call error', async () => {
    await startedHook()
    act(() => {
      daily.last.emit('error', {
        error: { msg: 'Meeting has ended' },
        errorMsg: 'Meeting has ended',
      })
    })
    expect(errorText()).toMatch(/meeting has ended/i)
  })

  it('says so when daily-js never loaded', async () => {
    vi.stubGlobal('Daily', undefined)
    await startedHook()
    expect(errorText()).toMatch(/could not (load|start)/i)
  })
})
