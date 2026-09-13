import type { Phase } from '../protocol/types'
import { PHASE_LABEL, PHASE_ORDER } from './format'

/**
 * The three words across the masthead, set in the serif when the bot is in that phase and
 * ruled under once it is past it. `done` is not a fourth word: it rules all three and
 * leaves none current, so the strip reads as finished rather than as a step further along.
 */
export function PhaseStrip({ phase }: { phase: Phase }) {
  const finished = phase === 'done'
  const current = finished ? -1 : PHASE_ORDER.indexOf(phase)
  return (
    <ol className="phases" aria-label="Progress">
      {PHASE_ORDER.map((name, i) => (
        <li
          key={name}
          className="phases__step"
          data-filled={finished || i <= current}
          data-current={i === current}
          aria-current={i === current ? 'step' : undefined}
        >
          <span className="phases__word">{PHASE_LABEL[name]}</span>
        </li>
      ))}
    </ol>
  )
}
