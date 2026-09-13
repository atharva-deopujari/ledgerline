import { isNotKnownRow } from '../protocol/markers'
import type { Card } from '../protocol/types'

/**
 * What the bot still needs, as chips across the foot of the ledger — short enough to read
 * while it is asking, and amber rather than red, because a gap is not yet a problem.
 *
 * A row the person has said they do not know is parked, not outstanding, so it is shown
 * quietly and says so: the bot will not keep asking, and the board should not keep nagging.
 */
export function MissingChips({ card }: { card: Card | undefined }) {
  if (!card || card.rows.length === 0) return null
  return (
    <section className="missing" aria-label={card.title}>
      <h2 className="missing__title">{card.title}</h2>
      <ul className="missing__chips">
        {card.rows.map((row, i) => {
          const [label, hint = ''] = row
          const parked = isNotKnownRow(row)
          return (
            <li className="chip" data-known={parked ? 'false' : undefined} key={`${label}-${i}`}>
              <span className="chip__label">{label}</span>
              {parked ? (
                <span className="chip__hint">not known</span>
              ) : (
                hint && <span className="chip__hint">{hint}</span>
              )}
            </li>
          )
        })}
      </ul>
      {card.note && <p className="missing__note">{card.note}</p>}
    </section>
  )
}
