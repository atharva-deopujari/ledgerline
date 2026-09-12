/**
 * A typed front door to daily-js's event surface.
 *
 * `DailyCall.on` is declared `(ev: never) => void` because the SDK's payload type varies per
 * event and we only model the six events we consume. Rather than cast at every call site,
 * the cast lives here once and every handler below is properly typed.
 */
import type {
  AppMessageEvent,
  CameraErrorEvent,
  DailyCall,
  FatalErrorEvent,
  ParticipantEvent,
  TrackEvent,
} from './types'

export interface DailyHandlers {
  trackStarted(ev: TrackEvent): void
  appMessage(ev: AppMessageEvent): void
  participantLeft(ev: ParticipantEvent): void
  leftMeeting(): void
  cameraError(ev: CameraErrorEvent): void
  error(ev: FatalErrorEvent): void
}

/** The daily-js event name behind each handler. */
const EVENT_NAMES: Record<keyof DailyHandlers, string> = {
  trackStarted: 'track-started',
  appMessage: 'app-message',
  participantLeft: 'participant-left',
  leftMeeting: 'left-meeting',
  cameraError: 'camera-error',
  error: 'error',
}

/**
 * Bind every handler to `call`. The one cast in this file is the only place the app pretends
 * to know daily-js's payload types.
 */
export function bindDailyHandlers(call: DailyCall, handlers: DailyHandlers): DailyCall {
  for (const [key, event] of Object.entries(EVENT_NAMES) as [keyof DailyHandlers, string][]) {
    const handler = handlers[key] as (ev: unknown) => void
    call.on(event, ((ev: unknown) => handler(ev)) as (ev: never) => void)
  }
  return call
}
