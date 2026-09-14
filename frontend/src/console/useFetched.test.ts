import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useFetched } from './useFetched'

const isPage = (b: unknown): b is { rows: number[] } =>
  typeof b === 'object' && b !== null && Array.isArray((b as { rows?: unknown }).rows)

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  fetchMock = vi.fn(async () => new Response(JSON.stringify({ rows: [1] }), { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => vi.unstubAllGlobals())

describe('useFetched', () => {
  it('reads the url it is given and hands over what came back', async () => {
    const { result } = renderHook(() => useFetched('/api/review/users', isPage))
    await waitFor(() => expect(result.current.phase).toBe('ready'))
    expect(fetchMock).toHaveBeenCalledWith('/api/review/users')
    expect(result.current.data).toEqual({ rows: [1] })
  })

  it('fails on a body that is not the shape asked for', async () => {
    // The app is served for any path, so a wrong URL answers with the page's own HTML.
    fetchMock.mockImplementation(async () => new Response('<!doctype html>', { status: 200 }))
    const { result } = renderHook(() => useFetched('/api/review/users', isPage))
    await waitFor(() => expect(result.current.phase).toBe('failed'))
  })

  it('fails on a status the server refused with', async () => {
    fetchMock.mockImplementation(async () => new Response(null, { status: 404 }))
    const { result } = renderHook(() => useFetched('/api/review/calls/x', isPage))
    await waitFor(() => expect(result.current.phase).toBe('failed'))
  })
})
