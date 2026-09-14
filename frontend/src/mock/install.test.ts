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

  it('lets the verdict poll through to the real fetch', async () => {
    const response = await fetch('/api/sessions/sess-1/verdict')
    expect(await body(response)).toBe('from the server')
    expect(realFetch).toHaveBeenCalledOnce()
  })
})
