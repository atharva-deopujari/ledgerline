/**
 * Every sentence the call surface can put in front of a person, in one place.
 *
 * They are written as whole sentences rather than assembled from fragments: each one has to
 * say what happened and what to do next, and that reads badly when it is glued together at
 * the call site.
 */
import type { CameraErrorEvent } from './types'

export const SERVER_UNREACHABLE =
  'Could not reach the server. Check that it is running, then try again.'

/** The server keeps one call at a time and answers 409 while one is still registered. */
export const CALL_ALREADY_RUNNING = 'A call is already running. End it first, then start a new one.'

/** The client checks the number first, so this is the case where client and server disagree. */
export const PHONE_REJECTED = 'That number was not accepted. Check it and try again.'

export const LIBRARY_MISSING = 'Could not load the call library. Reload the page and try again.'

/** Daily throws if an earlier call object was never destroyed. */
export const CALL_OBJECT_FAILED =
  'Could not start the call in this tab. Reload the page and try again.'

export const JOIN_FAILED = 'Could not join the call room. It may have expired — start again.'

/**
 * The call has to actually end when this is shown, or the click it asks for hits the start
 * guard and does nothing.
 */
export const AUDIO_BLOCKED = 'The browser blocked audio. Start the call again to hear the plan.'

const CALL_STOPPED = 'The call stopped unexpectedly.'

export const callStopped = (detail: string): string =>
  detail ? `The call stopped: ${detail}` : CALL_STOPPED

export function micErrorSentence(error: CameraErrorEvent['error']): string {
  switch (error?.type) {
    case 'permissions':
      return error.blockedBy === 'browser'
        ? 'Microphone access is blocked by your browser. Allow it in the address bar, then start again.'
        : 'Microphone permission was denied. Allow the microphone, then start again.'
    case 'not-found':
      return 'No microphone found. Plug one in or pick another input, then start again.'
    case 'undefined-mediadevices':
      return 'The microphone needs a secure page. Open this over https or on localhost.'
    case 'mic-in-use':
    case 'cam-mic-in-use':
      return 'Your microphone is in use by another app. Close it, then start again.'
    default:
      return `The microphone could not be opened${error?.msg ? ` (${error.msg})` : ''}.`
  }
}
