/**
 * `?mock=1`: replace daily-js and the session endpoint with stand-ins that replay
 * MOCK_SCRIPT. The app keeps using the real hook, parser and reducer, so this reviews the
 * actual code path — it just never joins a room or spends a voice minute.
 *
 * Dev-only. Nothing imports this unless the flag is present.
 */
import callSample from '../protocol/call.sample.json'
import callsSample from '../protocol/calls.sample.json'
import evalsSample from '../protocol/evals.sample.json'
import reportSample from '../protocol/report.sample.json'
import reviewSample from '../protocol/review.sample.json'
import usersSample from '../protocol/users.sample.json'
import { MOCK_SCRIPT, type MockEvent } from './script'

type Handler = (ev: unknown) => void

class MockCall {
  private handlers = new Map<string, Handler[]>()
  private timers: ReturnType<typeof setTimeout>[] = []
  private audioOn = true

  on(event: string, handler: Handler): this {
    const list = this.handlers.get(event) ?? []
    list.push(handler)
    this.handlers.set(event, list)
    return this
  }

  private emit(event: string, payload: unknown): void {
    for (const handler of this.handlers.get(event) ?? []) handler(payload)
  }

  async join(): Promise<unknown> {
    let at = 0
    for (const step of MOCK_SCRIPT as MockEvent[]) {
      at += step.after
      this.timers.push(setTimeout(() => this.emit('app-message', { data: step.data }), at))
    }
    return { local: {} }
  }

  async leave(): Promise<void> {
    this.stopTimers()
    this.emit('left-meeting', {})
  }

  async destroy(): Promise<void> {
    this.stopTimers()
  }

  localAudio(): boolean {
    return this.audioOn
  }

  setLocalAudio(on: boolean): void {
    this.audioOn = on
  }

  private stopTimers(): void {
    for (const t of this.timers) clearTimeout(t)
    this.timers = []
  }
}

/**
 * The console's read-only endpoints, answered from the samples the orchestrator generates
 * from C's models. `?mock=1` is then the whole demo: every tab, the browser tests and the
 * screenshots need no backend. Longest path first, so a call's id is not read as the list.
 */
const REVIEW: [RegExp, unknown][] = [
  [/\/api\/review\/users\/[^/?]+$/, reviewSample],
  [/\/api\/review\/users$/, usersSample],
  [/\/api\/review\/calls\/[^/?]+$/, callSample],
  [/\/api\/review\/calls(\?.*)?$/, callsSample],
  [/\/api\/review\/evals$/, evalsSample],
  [/\/api\/review\/report$/, reportSample],
]

export function installMock(): void {
  const realFetch = globalThis.fetch.bind(globalThis)
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    const method = (init?.method ?? 'GET').toUpperCase()
    // Only the two requests a call makes. Anything else under /api/sessions — the verdict
    // poll, most of all — must reach the real fetch, or the mock answers a question it was
    // never asked with a room URL.
    const isStart = url.endsWith('/api/sessions') && method === 'POST'
    const isCancel = /\/api\/sessions\/[^/]+$/.test(url) && method === 'DELETE'
    if (isStart || isCancel) {
      return new Response(
        JSON.stringify({ room_url: 'mock://room', token: 'mock', session_id: 'mock' }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      )
    }
    if (method === 'GET') {
      const sample = REVIEW.find(([pattern]) => pattern.test(url))?.[1]
      if (sample !== undefined) {
        return new Response(JSON.stringify(sample), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        })
      }
    }

    return realFetch(input, init)
  }) as typeof fetch

  globalThis.Daily = { createCallObject: () => new MockCall() } as never
}
