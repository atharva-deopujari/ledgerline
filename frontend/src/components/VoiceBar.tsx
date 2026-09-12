import type { SpeakState } from '../protocol/types'

const PILL: Record<SpeakState, string> = {
  idle: 'Idle',
  listening: 'Listening',
  speaking: 'Speaking',
  thinking: 'Thinking',
}

interface Props {
  speak: SpeakState
  micOn: boolean
  onToggleMic: () => void
  onEnd: () => void
}

export function VoiceBar({ speak, micOn, onToggleMic, onEnd }: Props) {
  return (
    <div className="voicebar">
      <button type="button" className="voicebar__mic" onClick={onToggleMic} aria-pressed={!micOn}>
        {micOn ? 'Mute' : 'Unmute mic'}
      </button>
      <span
        className="voicebar__pill"
        data-testid="state-pill"
        data-state={speak}
        role="status"
        aria-live="polite"
      >
        <span className="voicebar__dot" aria-hidden="true" />
        {PILL[speak]}
      </span>
      <button type="button" className="voicebar__end" onClick={onEnd}>
        End call
      </button>
    </div>
  )
}
