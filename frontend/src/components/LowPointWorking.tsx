import type { LowPointLine, LowPointView } from '../protocol/types'
import { groupIndian, shortDate } from './format'

const sum = (lines: LowPointLine[]): number => lines.reduce((total, line) => total + line.amt, 0)

function Line({ line }: { line: LowPointLine }) {
  return (
    <li className="working__line">
      <span className="working__label">{line.label}</span>
      {/* A spread item is a running total up to its day, not a payment on it. */}
      <span className="working__when">
        {line.spread ? `to ${shortDate(line.d)}` : shortDate(line.d)}
      </span>
      <span className="working__amt">{groupIndian(line.amt)}</span>
    </li>
  )
}

/**
 * The arithmetic behind the lowest day, under the figure itself, so the screen and the voice
 * explain the month the same way. The totals are added up here from the movements shown: a
 * total the reader cannot check is a number they have to believe.
 */
export function LowPointWorking({ low }: { low: LowPointView | null }) {
  if (!low) return null
  const atLow = low.opening + sum(low.before)
  const atClose = low.b + sum(low.after)
  const agrees = atLow === low.b && atClose === low.closing

  return (
    <section className="working" aria-label="How the lowest day is reached">
      <p className="working__line working__line--total">
        <span className="working__label">Starting balance</span>
        <span className="working__amt" data-testid="low-opening">
          {groupIndian(low.opening)}
        </span>
      </p>

      <ul className="working__list" data-testid="low-before">
        {low.before.map((line, i) => (
          <Line key={`${line.label}-${line.d}-${i}`} line={line} />
        ))}
      </ul>

      <p className="working__line working__line--total">
        <span className="working__label">Lowest, {shortDate(low.d)}</span>
        <span className="working__amt" data-testid="low-total" data-agrees={agrees}>
          {groupIndian(atLow)}
        </span>
      </p>

      <ul className="working__list" data-testid="low-after">
        {low.after.map((line, i) => (
          <Line key={`${line.label}-${line.d}-${i}`} line={line} />
        ))}
      </ul>

      <p className="working__line working__line--total">
        <span className="working__label">Then, by {shortDate(low.after.at(-1)?.d ?? low.d)}</span>
        <span className="working__amt" data-testid="low-closing">
          {groupIndian(atClose)}
        </span>
      </p>

      {/* Say it rather than print a total that looks like arithmetic and is not. The plan's
          own figure is named, so the reader knows which number the plan actually used. */}
      {!agrees && (
        <p className="working__warning" role="note">
          {`These do not add up: the plan's lowest day is ${groupIndian(low.b)}.`}
        </p>
      )}
    </section>
  )
}
