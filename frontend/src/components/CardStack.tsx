import type { Card, CardId } from '../protocol/types'
import { CARDS_SHOWN_ELSEWHERE, oneLineSummary } from './format'
import { StatusBadge } from './StatusBadge'

interface Props {
  cards: Card[]
  focus: CardId | null
  onFocus: (id: CardId) => void
}

/**
 * Everything not in focus, collapsed to one line each, so a correction upstream is
 * visibly a correction to the whole picture rather than to one card.
 */
export function CardStack({ cards, focus, onFocus }: Props) {
  const rest = cards.filter((c) => c.id !== focus && !CARDS_SHOWN_ELSEWHERE.includes(c.id))
  if (rest.length === 0) return null
  return (
    <ul className="stack">
      {rest.map((card) => (
        <li key={card.id}>
          <button
            type="button"
            className="card card--collapsed"
            data-status={card.status}
            data-card={card.id}
            onClick={() => onFocus(card.id)}
          >
            <span className="card__head">
              <span className="card__title">{card.title}</span>
              <StatusBadge status={card.status} />
            </span>
            <span className="card__summary">{oneLineSummary(card.rows, card.kv)}</span>
          </button>
        </li>
      ))}
    </ul>
  )
}
