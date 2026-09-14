import { useEffect, useState } from 'react'

/** One read of one endpoint. The console's screens are snapshots, not live views. */
export type Fetched<T> =
  { phase: 'loading'; data: null } | { phase: 'ready'; data: T } | { phase: 'failed'; data: null }

/**
 * `guard` is not ceremony: the app is served for any path, so a wrong URL answers with the
 * page's own HTML, and a body that is not the shape asked for must read as a failure rather
 * than be handed to a screen that will map over it.
 */
export function useFetched<T>(url: string, guard: (body: unknown) => body is T): Fetched<T> {
  const [state, setState] = useState<Fetched<T>>({ phase: 'loading', data: null })

  useEffect(() => {
    let live = true
    const load = async () => {
      try {
        const response = await fetch(url)
        if (!response.ok) throw new Error(String(response.status))
        const body: unknown = await response.json()
        if (!guard(body)) throw new Error('unexpected shape')
        if (live) setState({ phase: 'ready', data: body })
      } catch {
        if (live) setState({ phase: 'failed', data: null })
      }
    }
    void load()
    return () => {
      live = false
    }
    // `guard` is a module-level function in every call site; the URL is the dependency.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url])

  return state
}
