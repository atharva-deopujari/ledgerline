import type { CardStatus } from '../protocol/types'

/** The status word itself is the label, so colour is never the only signal. */
export function StatusBadge({ status }: { status: CardStatus }) {
  return (
    <span className="badge" data-status={status}>
      {status}
    </span>
  )
}
