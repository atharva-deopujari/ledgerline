import type { SpeakState } from '../protocol/types'
import { SPEAK_LABEL } from './format'

interface Props {
  speak: SpeakState
  micOn: boolean
  onToggleMic: () => void
  onEnd: () => void
}

/**
 * The call itself, along the foot of the board: what the bot is doing, and the two controls
 * that belong to the person rather than to the conversation.
 *
 * The wave is decoration and says so — the state is written out beside it, and announced,
 * so nothing here depends on seeing three bars move. Both buttons are named for what the
 * click will do, not for the state they are in, so "Mute" never has to be read twice.
 */
export function VoiceBar({ speak, micOn, onToggleMic, onEnd }: Props) {
  return (
    <div className="voicebar" data-state={speak}>
      <span className="voicebar__wave" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
      <span
        className="voicebar__state"
        data-testid="state-pill"
        data-state={speak}
        role="status"
        aria-live="polite"
      >
        {SPEAK_LABEL[speak]}
      </span>
      <span className="voicebar__spacer" />
      <button type="button" className="voicebar__mic" onClick={onToggleMic} aria-pressed={!micOn}>
        {micOn ? 'Mute' : 'Unmute mic'}
      </button>
      <button type="button" className="voicebar__end" onClick={onEnd}>
        End call
      </button>
    </div>
  )
}
