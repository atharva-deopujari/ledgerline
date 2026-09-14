import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useUserReview } from './useUserReview'
import sample from '../protocol/review.sample.json'

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  fetchMock = vi.fn(async () => new Response(JSON.stringify(sample), { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => vi.unstubAllGlobals())

describe('useUserReview', () => {
  it('reads the endpoint for that number, with the plus escaped', async () => {
    renderHook(() => useUserReview('+919876543210'))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/review/users/%2B919876543210'))
  })

  it('hands the page what the server sent', async () => {
    const { result } = renderHook(() => useUserReview('9876543210'))
    await waitFor(() => expect(result.current.phase).toBe('ready'))
    expect(result.current.review).toEqual(sample)
  })

  it('fails rather than rendering a 404 page as a person', async () => {
    fetchMock.mockImplementation(
      async () => new Response('<html>not found</html>', { status: 404 }),
    )
    const { result } = renderHook(() => useUserReview('9876543210'))
    await waitFor(() => expect(result.current.phase).toBe('failed'))
  })

  it('fails on a body that is not a review', async () => {
    fetchMock.mockImplementation(
      async () => new Response(JSON.stringify({ phone: 'x' }), { status: 200 }),
    )
    const { result } = renderHook(() => useUserReview('9876543210'))
    await waitFor(() => expect(result.current.phase).toBe('failed'))
  })
})
