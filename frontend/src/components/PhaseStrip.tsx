import type { Phase } from '../protocol/types'
import { PHASE_LABEL, PHASE_ORDER } from './format'

/** Three segments filled up to the phase the bot computed from readiness. */
export function PhaseStrip({ phase }: { phase: Phase }) {
  // `done` is not a fourth segment: it fills all three, and nothing is still in progress.
  const finished = phase === 'done'
  const current = finished ? -1 : PHASE_ORDER.indexOf(phase)
  return (
    <ol className="phase-strip" aria-label="Progress">
      {PHASE_ORDER.map((name, i) => (
        <li
          key={name}
          data-filled={finished || i <= current}
          aria-current={i === current ? 'step' : undefined}
        >
          <span className="phase-strip__bar" />
          <span className="phase-strip__label">{PHASE_LABEL[name]}</span>
        </li>
      ))}
    </ol>
  )
}
