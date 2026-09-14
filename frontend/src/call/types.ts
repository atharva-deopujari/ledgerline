/**
 * The slice of daily-js this app uses, typed by hand.
 *
 * daily-js is read off `window.Daily` (main.tsx puts it there) rather than imported, so the
 * call modules stay free of the SDK at test time and a fake global is the whole harness.
 * These declarations are what keep that fake honest.
 */
export interface DailyCall {
  on(event: string, handler: (ev: never) => void): DailyCall
  join(options: { url: string; token?: string }): Promise<unknown>
  leave(): Promise<unknown>
  destroy(): Promise<unknown>
  localAudio(): boolean
  setLocalAudio(on: boolean): unknown
}

interface DailyFactory {
  createCallObject(options: Record<string, unknown>): DailyCall
}

declare global {
  var Daily: DailyFactory | undefined
}

export interface TrackEvent {
  type: string
  participant: { local: boolean }
  track: MediaStreamTrack
}

export interface AppMessageEvent {
  data: unknown
}

export interface ParticipantEvent {
  participant?: { local?: boolean }
}

export interface CameraErrorEvent {
  error?: { type?: string; msg?: string; blockedBy?: string }
}

export interface FatalErrorEvent {
  error?: { msg?: string }
  errorMsg?: string
}
