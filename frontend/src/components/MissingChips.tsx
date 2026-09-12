import { isNotKnownRow } from '../protocol/markers'
import type { Card } from '../protocol/types'

/** What the bot still needs, as chips — short enough to scan while it asks. */
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
