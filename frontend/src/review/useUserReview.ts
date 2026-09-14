import { useEffect, useState } from 'react'
import type { UserReview } from '../protocol/review'

type ReviewState =
  | { phase: 'loading'; review: null }
  | { phase: 'ready'; review: UserReview }
  | { phase: 'failed'; review: null }

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)

/**
 * Enough of a check that the page cannot be handed a 404 page or another endpoint's body and
 * try to map over it. The field-level shape is the contract's to guarantee.
 */
const isReview = (body: unknown): body is UserReview =>
  isRecord(body) &&
  typeof body.phone === 'string' &&
  typeof body.memory_read === 'boolean' &&
  Array.isArray(body.active) &&
  Array.isArray(body.history) &&
  Array.isArray(body.notes) &&
  Array.isArray(body.calls)

/** One read of `GET /api/review/users/{phone}`; the page is a snapshot, not a live view. */
export function useUserReview(phone: string): ReviewState {
  const [state, setState] = useState<ReviewState>({ phase: 'loading', review: null })

  useEffect(() => {
    let live = true
    const load = async () => {
      try {
        const response = await fetch(`/api/review/users/${encodeURIComponent(phone)}`)
        if (!response.ok) throw new Error(String(response.status))
        const body: unknown = await response.json()
        if (!isReview(body)) throw new Error('malformed review')
        if (live) setState({ phase: 'ready', review: body })
      } catch {
        if (live) setState({ phase: 'failed', review: null })
      }
    }
    void load()
    return () => {
      live = false
    }
  }, [phone])

  return state
}
