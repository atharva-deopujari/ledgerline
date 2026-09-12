/**
 * The whole client state machine. One reducer, no store library: the call is a single
 * session and every input is either a Daily lifecycle event or a parsed app-message.
 */
import type { CardsMessage, SpeakState } from '../protocol/types'

export type CallState = 'idle' | 'connecting' | 'live' | 'ended' | 'error'

export interface SessionState {
  call: CallState
  speak: SpeakState
  /** Latest accepted snapshot. Kept after the call ends so the plan stays readable. */
  cards: CardsMessage | null
  /** Bot text for the turn in progress, still streaming. */
  question: string
  /** The last question the bot finished asking. This is the headline. */
  lastQuestion: string
  error: string | null
}

export type SessionAction =
  | { type: 'connect' }
  | { type: 'joined' }
  | { type: 'left' }
  | { type: 'error'; message: string }
  | { type: 'cards'; message: CardsMessage }
  | { type: 'botText'; text: string }
  | { type: 'botSpeaking' }
  | { type: 'botStopped' }
  | { type: 'userSpeaking' }
  | { type: 'thinking' }

export const initialSession: SessionState = {
  call: 'idle',
  speak: 'idle',
  cards: null,
  question: '',
  lastQuestion: '',
  error: null,
}

/** Chunks arrive without reliable spacing; only insert one where neither side has it. */
function appendChunk(question: string, chunk: string): string {
  if (!question) return chunk
  const needsSpace = !/\s$/.test(question) && !/^\s/.test(chunk)
  return question + (needsSpace ? ' ' : '') + chunk
}

const isOver = (call: CallState): boolean => call === 'ended' || call === 'error'

export function sessionReducer(state: SessionState, action: SessionAction): SessionState {
  switch (action.type) {
    case 'connect':
      // Nothing from the previous call survives. The backend's cards_version restarts at 0
      // for every call, so keeping the old snapshot would make the guard below discard the
      // new call's first messages and leave the old plan on screen. The start screen shows
      // no cards while connecting, so nothing is lost.
      return { ...initialSession, call: 'connecting' }

    case 'joined':
      return { ...state, call: 'live', speak: 'listening', error: null }

    case 'left':
      return { ...state, call: 'ended', speak: 'idle', question: '' }

    case 'error':
      return { ...state, call: 'error', speak: 'idle', error: action.message }

    case 'cards':
      // Snapshots are self-sufficient and monotonic; late or duplicated ones are dropped.
      if (state.cards && action.message.v <= state.cards.v) return state
      return { ...state, cards: action.message }

    case 'botText':
      if (isOver(state.call)) return state
      return { ...state, question: appendChunk(state.question, action.text) }

    case 'botSpeaking':
      if (isOver(state.call)) return state
      return { ...state, speak: 'speaking' }

    case 'botStopped': {
      if (isOver(state.call)) return state
      // A turn with no new text (a filler noise, a barge-in) leaves the headline alone.
      const settled = state.question.trim() === '' ? state.lastQuestion : state.question
      return { ...state, speak: 'listening', lastQuestion: settled, question: '' }
    }

    case 'userSpeaking':
      if (isOver(state.call)) return state
      return { ...state, speak: 'listening' }

    case 'thinking':
      if (isOver(state.call)) return state
      return { ...state, speak: 'thinking' }

    default:
      return state
  }
}
