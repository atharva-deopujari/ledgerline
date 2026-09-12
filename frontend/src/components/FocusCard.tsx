import type { Card } from '../protocol/types'
import { CardKv } from './CardKv'
import { CardRows } from './CardRows'
import { StatusBadge } from './StatusBadge'

/** The card the last tool call touched, opened in full. */
export function FocusCard({ card }: { card: Card }) {
  return (
    <article className="card card--focus" data-status={card.status} data-card={card.id}>
      <header className="card__head">
        <h2 className="card__title">{card.title}</h2>
        <StatusBadge status={card.status} />
      </header>
      <CardRows rows={card.rows} />
      <CardKv kv={card.kv} />
      {card.note && <p className="card__note">{card.note}</p>}
    </article>
  )
}
