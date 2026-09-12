/**
 * Everything the call lifecycle has to remember, in one object instead of five refs.
 *
 * The hard-won rules it encodes, each from a defect that reached a live call:
 *  - only the *current* call object may act on the app, because Daily delivers late events
 *    from calls that are already gone;
 *  - an attempt owns its guard from the first synchronous line until its cleanup has
 *    returned, not merely until its join settles;
 *  - the server keeps one session, and its DELETE means "the slot is back" only when it
 *    resolves — so the promise is what matters, not the request;
 *  - a call that reached `joined` is the server's to end, never ours to DELETE.
 *
 * Plain TypeScript with no React in it, so it can be tested directly.
 */
import type { DailyCall } from './types'

export class CallLifecycle {
  /** The call object the app is currently speaking for. */
  private current: DailyCall | null = null
  /** An attempt is between its first line and its cleanup returning. */
  private attemptInFlight = false
  /** That attempt reached a joined call. */
  private attemptJoined = false
  /** The session id the in-flight attempt committed, if it got that far. */
  private attemptSession: string | null = null
  /** The teardown still running, if any. A new attempt waits for it. */
  private teardown: Promise<void> | null = null
  /** Per session id: the DELETE in flight, or the settled one. */
  private cancellations = new Map<string, Promise<void>>()

  /** True while an attempt is in flight — what the Start controls are disabled by. */
  get starting(): boolean {
    return this.attemptInFlight
  }

  /** The call object in charge, if any. */
  get call(): DailyCall | null {
    return this.current
  }

  /** Is this the call the app is currently speaking for? */
  isCurrent(call: DailyCall): boolean {
    return this.current === call
  }

  /** Did the attempt that owns `call` reach a joined call? */
  get joined(): boolean {
    return this.attemptJoined
  }

  /**
   * Claim the attempt slot. Returns false when one is already in flight or a call is up —
   * Daily throws on a second call object and the server answers 409 for a second session.
   */
  begin(): boolean {
    if (this.attemptInFlight || this.current !== null) return false
    this.attemptInFlight = true
    this.attemptJoined = false
    this.attemptSession = null
    return true
  }

  /** Remember the session this attempt committed, so it can wait for its own cleanup. */
  noteSession(sessionId: string | undefined): void {
    this.attemptSession = sessionId ?? null
  }

  /** The call object this attempt created is now the current one. */
  adopt(call: DailyCall): void {
    this.current = call
  }

  /** The attempt reached a joined call. */
  markJoined(): void {
    this.attemptJoined = true
  }

  /** Drop `call` if it is current, and report whether it was. */
  forget(call: DailyCall): boolean {
    if (this.current !== call) return false
    this.current = null
    return true
  }

  /**
   * Leave and destroy one specific call object, and track it so a later attempt can wait.
   * Takes the instance rather than reading the current call because a late event from a
   * replaced call must never tear down its replacement.
   */
  async retire(call: DailyCall | null, onForgotten?: () => void): Promise<void> {
    if (!call) return
    if (this.forget(call)) onForgotten?.()
    const finished = (async () => {
      try {
        await call.leave()
      } finally {
        await call.destroy()
      }
    })()
    this.teardown = finished
    try {
      await finished
    } finally {
      if (this.teardown === finished) this.teardown = null
    }
  }

  /** Wait for any teardown still running, so two Daily objects never coexist. */
  async awaitTeardown(): Promise<void> {
    const pending = this.teardown
    if (pending) await pending.catch(() => {})
  }

  /**
   * Hand a committed server session back, once. The returned promise resolves when the
   * server has answered, which is when the slot is genuinely free — it awaits the whole
   * run_session teardown. A repeat call for the same id joins the first rather than issuing
   * a second DELETE.
   *
   * Best effort: the user needs to see why the call did not start, not why the cleanup
   * did not.
   */
  cancelSession(sessionId: string | undefined): Promise<void> {
    if (!sessionId) return Promise.resolve()
    const inFlight = this.cancellations.get(sessionId)
    if (inFlight) return inFlight
    const work = (async () => {
      try {
        await fetch(`/api/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' })
      } catch {
        // nothing useful to do, and nothing worth showing the user
      }
    })()
    this.cancellations.set(sessionId, work)
    return work
  }

  /** Every cleanup still outstanding. A new attempt waits for these before it posts. */
  async awaitCancellations(): Promise<void> {
    await Promise.allSettled([...this.cancellations.values()])
  }

  /**
   * Release the attempt slot, but only once this attempt's own cleanup has returned: until
   * the server answers, the slot it committed is still held.
   */
  async end(): Promise<void> {
    const id = this.attemptSession
    const cleanup = id ? this.cancellations.get(id) : undefined
    if (cleanup) await cleanup.catch(() => {})
    this.attemptInFlight = false
  }
}
