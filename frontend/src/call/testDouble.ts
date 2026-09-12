/** A hand-rolled stand-in for daily-js, good enough for the handlers the hook registers. */
export type Handler = (ev: unknown) => void

export class FakeCall {
  handlers = new Map<string, Handler[]>()
  joined: unknown = null
  left = 0
  destroyed = 0
  audioOn = true
  joinImpl: (opts: unknown) => Promise<unknown> = async (opts) => {
    this.joined = opts
    return { local: {} }
  }

  on(event: string, handler: Handler): this {
    const list = this.handlers.get(event) ?? []
    list.push(handler)
    this.handlers.set(event, list)
    return this
  }
  off(event: string, handler: Handler): this {
    this.handlers.set(
      event,
      (this.handlers.get(event) ?? []).filter((h) => h !== handler),
    )
    return this
  }
  join(opts: unknown) {
    return this.joinImpl(opts)
  }
  /**
   * Real Daily emits `left-meeting` some time after `leave()` resolves. Set this false to
   * hold it back and emit it by hand, which is how a delayed event from an old call object
   * arrives after a replacement call has already started.
   */
  emitsLeftOnLeave = true

  async leave() {
    this.left += 1
    if (this.emitsLeftOnLeave) this.emit('left-meeting', {})
  }
  /** Resolves immediately unless a test parks a promise here to keep teardown pending. */
  destroyGate: Promise<void> | null = null

  async destroy() {
    this.destroyed += 1
    if (this.destroyGate) await this.destroyGate
  }
  /**
   * Daily's own contract: "after destroy() completes ... any further method calls on the
   * instance will throw an error." Modelling that is what makes a stale join completion
   * touching a retired call object fail loudly instead of silently.
   */
  private assertAlive(method: string) {
    if (this.destroyed > 0) throw new Error(`${method}() called on a destroyed call object`)
  }
  localAudio() {
    this.assertAlive('localAudio')
    return this.audioOn
  }
  setLocalAudio(on: boolean) {
    this.assertAlive('setLocalAudio')
    this.audioOn = on
  }
  emit(event: string, payload: unknown) {
    for (const handler of this.handlers.get(event) ?? []) handler(payload)
  }
}

export class FakeDaily {
  calls: FakeCall[] = []
  options: unknown[] = []
  createCallObject(options: unknown): FakeCall {
    const call = new FakeCall()
    this.calls.push(call)
    this.options.push(options)
    return call
  }
  get last(): FakeCall {
    return this.calls[this.calls.length - 1]
  }
}

/** jsdom has no MediaStream; the hook only ever constructs one from a track. */
export class FakeMediaStream {
  tracks: unknown[]
  constructor(tracks: unknown[] = []) {
    this.tracks = tracks
  }
}
