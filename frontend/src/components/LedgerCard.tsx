import type { Card } from '../protocol/types'
import { CardRows } from './CardRows'
import { StatusBadge } from './StatusBadge'

interface Props {
  card: Card
  /** The card the bot's last tool call touched. It is marked, not opened: nothing is hidden. */
  focused?: boolean
  /** For this card's rows that moved: the figure the last snapshot replaced, by label. */
  retired?: Map<string, string>
}

/**
 * One account on the ledger, open. Every card the snapshot sends is on the board with all of
 * its rows — there is nothing to expand and nothing behind a hover, because a figure the
 * person gave and cannot see is a figure they cannot correct.
 *
 * Focus is the bot's, not the reader's: the rule down the left says which card the last
 * thing it did landed on, so the board answers "did it hear me?" without being touched.
 */
export function LedgerCard({ card, focused = false, retired }: Props) {
  return (
    <article
      className="card"
      data-card={card.id}
      data-status={card.status}
      data-focused={focused || undefined}
      aria-label={card.title}
    >
      <div className="card__head">
        <h2 className="card__title">{card.title}</h2>
        <StatusBadge status={card.status} />
      </div>
      <CardRows rows={card.rows} retired={retired} />
      {card.note && <p className="card__note">{card.note}</p>}
    </article>
  )
}
