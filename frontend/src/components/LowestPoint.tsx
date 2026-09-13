import type { Card } from '../protocol/types'
import { splitLowest, splitProvisional } from './format'

/**
 * The one figure the whole call is about: how little is left on the worst day of the next
 * thirty, set at the top of the panel where it can be read from across the room.
 *
 * It is `summary.lowest` exactly as delivered, split on its own " on " for layout. The
 * label says when it cannot be trusted yet — a low computed while a figure is still missing
 * can still move, and a number that big must not look settled when it is not.
 */
export function LowestPoint({ card }: { card: Card | undefined }) {
  const raw = card?.kv.lowest
  if (!card || !raw) return null

  const { value, uncertain } = splitProvisional(raw)
  const { figure, when } = splitLowest(value)
  const provisional = uncertain || card.status === 'provisional'
  // The plan has left something unpaid, so the low is not merely small, it is short.
  const alarm = Boolean(card.kv.unpaid)

  return (
    <section className="lowest" data-alarm={alarm || undefined} aria-label="Lowest point">
      <p className="lowest__label">
        Lowest point in the next thirty days
        {provisional && <span className="lowest__caveat">still provisional</span>}
      </p>
      <p className="lowest__figure">{figure}</p>
      {when && <p className="lowest__when">{when}</p>}
    </section>
  )
}
