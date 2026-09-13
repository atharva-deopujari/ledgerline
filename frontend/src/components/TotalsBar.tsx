import type { Card } from '../protocol/types'
import { PANEL_KEYS, TOTAL_LABEL, keyAsWords, splitProvisional } from './format'

/**
 * The month in three figures, ruled off at the foot of the ledger the way a column of
 * figures is ruled off on paper.
 *
 * Every cell is a key the summary card delivered. Nothing here is added up: `in` and `out`
 * are the backend's own totals, and `unpaid` only exists on the board once the backend
 * sends it, which is the point — "unpaid if nothing changes" is a finding, not a subtotal
 * the client may reach on its own. A key this build has never heard of still prints, under
 * its own name, so a field the engine adds later appears rather than disappears.
 */
export function TotalsBar({ card }: { card: Card | undefined }) {
  if (!card) return null
  const cells = Object.entries(card.kv).filter(([key]) => !PANEL_KEYS.includes(key))
  if (cells.length === 0) return null

  return (
    <dl className="totals" data-status={card.status} aria-label={card.title}>
      {cells.map(([key, raw]) => {
        const { value, uncertain } = splitProvisional(raw)
        return (
          <div className="totals__cell" data-key={key} key={key}>
            <dt className="totals__label">{TOTAL_LABEL[key] ?? keyAsWords(key)}</dt>
            <dd className="totals__value">
              {value}
              {uncertain && (
                <span
                  className="row__uncertain"
                  title="Not confirmed yet"
                  aria-label="not confirmed"
                >
                  ?
                </span>
              )}
            </dd>
          </div>
        )
      })}
    </dl>
  )
}
