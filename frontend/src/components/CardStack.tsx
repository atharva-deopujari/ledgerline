import type { Card, CardId } from '../protocol/types'
import { CARDS_SHOWN_ELSEWHERE } from './format'
import { LedgerCard } from './LedgerCard'
import { changedLabels } from './useChangedRows'

interface Props {
  cards: Card[]
  /** The card the snapshot says the bot last touched. */
  focus: CardId | null
  /** `cardId|label` -> the figure the last snapshot replaced, for every row it moved. */
  retired: Map<string, string>
}

/**
 * The ledger: every account, open, in the order the backend sent them.
 *
 * Cards with a place of their own elsewhere on the board are left out here rather than
 * printed twice — the totals bar is the summary card, the panel is the plan, the chips are
 * what is still missing, the chart is the timeline.
 */
export function CardStack({ cards, focus, retired }: Props) {
  const shown = cards.filter((c) => !CARDS_SHOWN_ELSEWHERE.includes(c.id))
  if (shown.length === 0) return null
  return (
    <ul className="stack">
      {shown.map((card) => (
        <li key={card.id}>
          <LedgerCard
            card={card}
            focused={card.id === focus}
            retired={changedLabels(retired, card.id)}
          />
        </li>
      ))}
    </ul>
  )
}
