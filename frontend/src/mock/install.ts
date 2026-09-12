/**
 * `?mock=1`: replace daily-js and the session endpoint with stand-ins that replay
 * MOCK_SCRIPT. The app keeps using the real hook, parser and reducer, so this reviews the
 * actual code path — it just never joins a room or spends a voice minute.
 *
 * Dev-only. Nothing imports this unless the flag is present.
 */
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

export const isMockMode = (search: string = window.location.search): boolean =>
  new URLSearchParams(search).get('mock') === '1'

export function installMock(): void {
  const realFetch = globalThis.fetch.bind(globalThis)
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    if (url.includes('/api/sessions')) {
      return new Response(
        JSON.stringify({ room_url: 'mock://room', token: 'mock', session_id: 'mock' }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      )
    }
    return realFetch(input, init)
  }) as typeof fetch

  globalThis.Daily = { createCallObject: () => new MockCall() } as never
}
