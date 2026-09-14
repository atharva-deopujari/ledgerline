/** Timings and limits for a call. Named so a number never sits inline in the logic. */

/** How long after the user starts talking we admit the bot is thinking. */
export const THINKING_DELAY_MS = 1200

/**
 * How long to wait for Daily to join before giving up and handing the slot back. Daily can
 * leave a join pending indefinitely after a terminal event, and `start()` must still settle
 * or the guard that blocks a retry would never lift.
 */
export const JOIN_TIMEOUT_MS = 20_000

/** The server answers 409 while a call is already registered. */
export const HTTP_CONFLICT = 409

/** The server validates the phone number too, and refuses the body when it disagrees. */
export const HTTP_UNPROCESSABLE = 422

/** Daily is asked for microphone only; the camera is never touched. */
export const CALL_OPTIONS = { videoSource: false } as const
