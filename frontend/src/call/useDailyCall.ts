/**
 * The React glue over a call. Everything the hook learns becomes a SessionAction, so the
 * rest of the app never sees a Daily object.
 *
 * The lifecycle rules live in `CallLifecycle`, the event typing in `dailyEvents`, the
 * sentences in `messages` and the timings in `constants`. What is left here is the order
 * things happen in, and the React bindings.
 */
import { useCallback, useEffect, useRef, useState, type Dispatch, type RefObject } from 'react'
import { parseIncoming } from '../protocol/parse'
import type { SessionStartResponse } from '../protocol/types'
import type { SessionAction } from '../state/sessionReducer'
import {
  CALL_OPTIONS,
  HTTP_CONFLICT,
  HTTP_UNPROCESSABLE,
  JOIN_TIMEOUT_MS,
  THINKING_DELAY_MS,
} from './constants'
import { bindDailyHandlers } from './dailyEvents'
import { CallLifecycle } from './lifecycle'
import {
  AUDIO_BLOCKED,
  CALL_ALREADY_RUNNING,
  CALL_OBJECT_FAILED,
  JOIN_FAILED,
  LIBRARY_MISSING,
  PHONE_REJECTED,
  SERVER_UNREACHABLE,
  callStopped,
  micErrorSentence,
} from './messages'
import type { AppMessageEvent, DailyCall, TrackEvent } from './types'

interface DailyCallApi {
  start: (phone: string) => Promise<void>
  /**
   * An attempt is still in flight. It stays true after a terminal event until the pending
   * join settles or times out, because until then `start()` will refuse — and a control the
   * user can press into silence is worse than one that is visibly unavailable.
   */
  starting: boolean
  stop: () => Promise<void>
  toggleMic: () => void
  micOn: boolean
  /** The call the server is running or has just run, for the verdict poll. */
  sessionId: string | null
  audioRef: RefObject<HTMLAudioElement | null>
}

/**
 * Reject once `ms` has passed, whatever the underlying promise does afterwards. Daily can
 * leave a join pending indefinitely after a terminal event, and `start()` must still settle
 * or the guard that blocks a retry would never lift.
 */
function withTimeout<T>(work: Promise<T>, ms: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('join timed out')), ms)
    work.then(
      (value) => {
        clearTimeout(timer)
        resolve(value)
      },
      (error: unknown) => {
        clearTimeout(timer)
        reject(error instanceof Error ? error : new Error(String(error)))
      },
    )
  })
}

function isSessionResponse(x: unknown): x is SessionStartResponse {
  if (typeof x !== 'object' || x === null) return false
  const o = x as Record<string, unknown>
  return typeof o.room_url === 'string' && typeof o.token === 'string'
}

export function useDailyCall(dispatch: Dispatch<SessionAction>): DailyCallApi {
  // One lifecycle per mounted hook, created once. `useState` rather than a ref because it
  // is read during render (in the dependency arrays below) and refs must not be.
  const [life] = useState(() => new CallLifecycle())

  const audioRef = useRef<HTMLAudioElement | null>(null)
  const thinkingTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [micOn, setMicOn] = useState(true)
  // The lifecycle owns the guard; this mirrors it for the UI. Both move together.
  const [starting, setStarting] = useState(false)
  // Kept after the call ends: the verdict poll asks about the call that just finished.
  const [sessionId, setSessionId] = useState<string | null>(null)

  const clearThinking = useCallback(() => {
    if (thinkingTimer.current !== null) {
      clearTimeout(thinkingTimer.current)
      thinkingTimer.current = null
    }
  }, [])

  const fail = useCallback(
    (message: string) => {
      clearThinking()
      dispatch({ type: 'error', message })
    },
    [clearThinking, dispatch],
  )

  const onAppMessage = useCallback(
    (ev: AppMessageEvent) => {
      const message = parseIncoming(ev?.data)
      if (message === null) return
      if (message.type === 'cards') {
        dispatch({ type: 'cards', message })
        return
      }
      switch (message.type) {
        case 'bot-transcription':
          dispatch({ type: 'botText', text: message.data.text })
          break
        case 'bot-started-speaking':
          clearThinking()
          dispatch({ type: 'botSpeaking' })
          break
        case 'bot-stopped-speaking':
          dispatch({ type: 'botStopped' })
          break
        case 'user-started-speaking':
          dispatch({ type: 'userSpeaking' })
          // The user's turn ends with no event of its own, so assume the pause that
          // follows is the bot working, until it actually starts speaking.
          clearThinking()
          thinkingTimer.current = setTimeout(() => {
            thinkingTimer.current = null
            dispatch({ type: 'thinking' })
          }, THINKING_DELAY_MS)
          break
      }
    },
    [clearThinking, dispatch],
  )

  const onTrackStarted = useCallback(
    (ev: TrackEvent, call: DailyCall, onBlocked: () => void) => {
      if (ev.type !== 'audio' || ev.participant?.local) return
      const el = audioRef.current
      if (!el) return
      el.srcObject = new MediaStream([ev.track])
      void Promise.resolve(el.play()).catch(() => {
        // `play()` can still be pending when this call ends and another one joins, so the
        // instance is checked again here and not only before the handler ran. A rejection
        // belonging to a retired call must not put the replacement into error or tear
        // anything down.
        if (!life.isCurrent(call)) return
        // A call whose audio cannot play is no use, and the message tells the user to start
        // again — so the call has to actually end, or that click hits the guard and does
        // nothing while the old call and its server session stay live.
        fail(AUDIO_BLOCKED)
        onBlocked()
      })
    },
    [fail, life],
  )

  /** Leave and destroy one call, clearing the thinking timer if it was the current one. */
  const retireCall = useCallback(
    (call: DailyCall | null) => life.retire(call, clearThinking),
    [clearThinking, life],
  )

  const start = useCallback(
    async (phone: string) => {
      if (!life.begin()) return
      setStarting(true)
      try {
        dispatch({ type: 'connect' })

        // Daily throws on a second call object, so the previous one must be fully destroyed
        // before this one is created.
        await life.awaitTeardown()
        // The server keeps one call at a time and only answers a DELETE once it has finished
        // tearing the previous one down. Posting before that returns is what gets a 409.
        await life.awaitCancellations()

        let response: Response
        try {
          response = await fetch('/api/sessions', {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ phone }),
          })
        } catch {
          fail(SERVER_UNREACHABLE)
          return
        }

        if (response.status === HTTP_CONFLICT) {
          fail(CALL_ALREADY_RUNNING)
          return
        }

        if (response.status === HTTP_UNPROCESSABLE) {
          fail(PHONE_REJECTED)
          return
        }

        let session: SessionStartResponse
        try {
          if (!response.ok) throw new Error(String(response.status))
          const body: unknown = await response.json()
          if (!isSessionResponse(body)) throw new Error('malformed session response')
          session = body
          life.noteSession(session.session_id)
          setSessionId(session.session_id)
        } catch {
          fail(SERVER_UNREACHABLE)
          return
        }

        const factory = globalThis.Daily
        if (!factory) {
          // Report first, hand the slot back after: `end()` waits for the DELETE, so the
          // message must not.
          fail(LIBRARY_MISSING)
          void life.cancelSession(session.session_id)
          return
        }

        let call: DailyCall
        try {
          call = factory.createCallObject({ ...CALL_OPTIONS })
        } catch {
          fail(CALL_OBJECT_FAILED)
          void life.cancelSession(session.session_id)
          return
        }

        life.adopt(call)
        /**
         * Retire this call.
         *
         * The session is cancelled here rather than after `join()` settles, so that the slot
         * is back before the user can press Start again — but only for an attempt that never
         * reached a joined call. Once the bot is in the room the session is the server's to
         * end: its DELETE cancels the asyncio task, and by the time the bot leaves
         * `run_session` is already in its `finally` writing the transcript, which is the eval
         * corpus. A CancelledError landing on an await there would lose it.
         */
        const retire = () => {
          if (!life.joined) void life.cancelSession(session.session_id)
          void retireCall(call)
        }
        // Every handler is bound to `call`. Anything arriving from a call that is no longer
        // current is a straggler from a finished session: it must not reach the reducer and
        // must not tear down whatever replaced it.
        bindDailyHandlers(call, {
          trackStarted: (ev) => {
            if (life.isCurrent(call)) onTrackStarted(ev, call, retire)
          },
          appMessage: (ev) => {
            if (life.isCurrent(call)) onAppMessage(ev)
          },
          participantLeft: (ev) => {
            if (!life.isCurrent(call) || ev?.participant?.local) return
            dispatch({ type: 'left' })
            retire()
          },
          leftMeeting: () => {
            if (!life.isCurrent(call)) return
            dispatch({ type: 'left' })
            retire()
          },
          cameraError: (ev) => {
            if (!life.isCurrent(call)) return
            fail(micErrorSentence(ev?.error))
            retire()
          },
          error: (ev) => {
            if (!life.isCurrent(call)) return
            const detail = ev?.error?.msg ?? (typeof ev?.errorMsg === 'string' ? ev.errorMsg : '')
            fail(callStopped(detail))
            retire()
          },
        })

        try {
          await withTimeout(
            call.join({ url: session.room_url, token: session.token }),
            JOIN_TIMEOUT_MS,
          )
        } catch {
          // A handler may have retired this call while the join was in flight; if so it has
          // already destroyed it and told the reducer why, and a second sentence on top would
          // replace the specific reason with a generic one.
          if (life.forget(call)) {
            await call.destroy()
            fail(JOIN_FAILED)
          }
          void life.cancelSession(session.session_id)
          return
        }

        // Same race on the success path: a terminal event can land while join() is pending.
        // The call object is gone and Daily throws on a destroyed instance, so this must not
        // touch it or report a call that is not there.
        if (!life.isCurrent(call)) {
          void life.cancelSession(session.session_id)
          return
        }

        setMicOn(call.localAudio())
        life.markJoined()
        dispatch({ type: 'joined' })
      } finally {
        await life.end()
        setStarting(false)
      }
    },
    [dispatch, fail, life, onAppMessage, onTrackStarted, retireCall],
  )

  const stop = useCallback(async () => {
    // Pressing End is the decision itself, so say so rather than waiting for Daily to echo
    // `left-meeting` back — by the time it arrives this call is no longer the current one
    // and its handlers deliberately ignore it.
    if (life.call) dispatch({ type: 'left' })
    await retireCall(life.call)
  }, [dispatch, life, retireCall])

  const toggleMic = useCallback(() => {
    const call = life.call
    if (!call) return
    const next = !call.localAudio()
    call.setLocalAudio(next)
    setMicOn(next)
  }, [life])

  // A closed tab should not leave a room occupied.
  useEffect(() => () => void retireCall(life.call), [life, retireCall])

  return { start, starting, stop, toggleMic, micOn, sessionId, audioRef }
}
