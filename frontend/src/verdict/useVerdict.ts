import { useEffect, useState } from 'react'
import type { Verdict } from '../protocol/verdict'
import { isVerdict } from './parse'

/** Every two seconds, for one minute: the judge's own budget is five to fifteen seconds. */
const POLL_EVERY_MS = 2000
const POLL_FOR_MS = 60_000

/**
 * `reviewing` from the moment the call ends until the judge answers; `done` with the
 * verdict; `gave-up` if a minute passes without one, because a line saying the review did
 * not come back is honest and a spinner for ever is not.
 */
export type VerdictState =
  { phase: 'idle' | 'reviewing' | 'gave-up'; verdict: null } | { phase: 'done'; verdict: Verdict }

/**
 * What the poll has come back with, for one (session, ended) pair. Held with its key rather
 * than reset from inside the effect: a synchronous setState there costs a second render pass
 * and the linter is right to refuse it.
 */
interface Outcome {
  key: string
  verdict: Verdict | null
  gaveUp: boolean
}

/**
 * Poll `GET /api/sessions/{id}/verdict` while the judge is still working. The deterministic
 * checks take under a second and the intent judge five to fifteen, so this waits rather than
 * asking the person to refresh.
 */
export function useVerdict(sessionId: string | null, ended: boolean): VerdictState {
  const [outcome, setOutcome] = useState<Outcome | null>(null)
  const key = `${sessionId ?? ''}|${String(ended)}`
  // Anything the last call's poll returned belongs to the last call.
  const current = outcome?.key === key ? outcome : null

  useEffect(() => {
    if (!ended || !sessionId) return

    let live = true
    const startedAt = Date.now()
    let timer: ReturnType<typeof setTimeout> | null = null

    const stop = () => {
      live = false
      if (timer) clearTimeout(timer)
    }

    const poll = async () => {
      try {
        const response = await fetch(`/api/sessions/${sessionId}/verdict`)
        // 202 is the judge still working. Anything else that is not a verdict — an error
        // page, another endpoint's body — is treated the same way: not yet.
        if (response.ok) {
          const body: unknown = await response.json()
          if (isVerdict(body) && body.status !== 'pending') {
            if (live) setOutcome({ key, verdict: body, gaveUp: false })
            stop()
            return
          }
        }
      } catch {
        // A dropped request is not an answer; the next tick asks again.
      }
      if (!live) return
      if (Date.now() - startedAt >= POLL_FOR_MS) {
        setOutcome({ key, verdict: null, gaveUp: true })
        stop()
        return
      }
      timer = setTimeout(() => void poll(), POLL_EVERY_MS)
    }

    void poll()
    return stop
  }, [ended, key, sessionId])

  if (!ended || !sessionId) return { phase: 'idle', verdict: null }
  if (current?.verdict) return { phase: 'done', verdict: current.verdict }
  if (current?.gaveUp) return { phase: 'gave-up', verdict: null }
  return { phase: 'reviewing', verdict: null }
}
