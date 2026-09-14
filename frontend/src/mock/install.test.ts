/**
 * The mock stands in for the call endpoints and nothing else. It used to answer any URL
 * containing `/api/sessions`, which swallowed `GET /api/sessions/{id}/verdict` and handed the
 * poll a room URL to read as a verdict.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { installMock } from './install'

let realFetch: ReturnType<typeof vi.fn>

beforeEach(() => {
  realFetch = vi.fn(async () => new Response('from the server', { status: 200 }))
  vi.stubGlobal('fetch', realFetch)
  installMock()
})

afterEach(() => vi.unstubAllGlobals())

const body = async (response: Response) => await response.text()

describe('the mock fetch', () => {
  it('answers the POST that starts a call', async () => {
    const response = await fetch('/api/sessions', { method: 'POST' })
    expect(await body(response)).toContain('mock://room')
    expect(realFetch).not.toHaveBeenCalled()
  })

  it('answers the DELETE that cancels one', async () => {
    await fetch('/api/sessions/sess-1', { method: 'DELETE' })
    expect(realFetch).not.toHaveBeenCalled()
  })

  it("answers the console's read-only endpoints from the samples", async () => {
    // ?mock=1 is the whole demo: every tab works with no backend behind it.
    for (const [url, marker] of [
      ['/api/review/users', '"users"'],
      ['/api/review/users/9876543210', '"memory_read"'],
      ['/api/review/calls', '"calls"'],
      ['/api/review/calls/voice-1', '"verdict"'],
      ['/api/review/evals', '"matrix"'],
      ['/api/review/report', '"markdown"'],
    ] as const) {
      expect(await body(await fetch(url))).toContain(marker)
    }
    expect(realFetch).not.toHaveBeenCalled()
  })

  it('lets the verdict poll through to the real fetch', async () => {
    const response = await fetch('/api/sessions/sess-1/verdict')
    expect(await body(response)).toBe('from the server')
    expect(realFetch).toHaveBeenCalledOnce()
  })
})
