import type { CardStatus } from '../protocol/types'
import { STATUS_LABEL } from './format'

/** The status is written out beside the title, so colour is never the only signal. */
export function StatusBadge({ status }: { status: CardStatus }) {
  return (
    <span className="status" data-status={status}>
      {STATUS_LABEL[status]}
    </span>
  )
}
