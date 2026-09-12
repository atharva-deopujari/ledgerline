import { isUnpaidRow } from '../protocol/markers'
import type { CardsMessage } from '../protocol/types'
import { CardKv } from './CardKv'
import { CardRows } from './CardRows'
import { StatusBadge } from './StatusBadge'

/**
 * The same question the agent asks aloud. It never asks anyone to repeat the plan back — a
 * plain yes confirms — so the panel must not instruct a step the voice side does not want.
 */
const CONFIRM = 'Does this work for you? Say so, or tell me what to change.'

/**
 * The person confirmed the plan. This comes from `phase === "done"` and nothing else: a call
 * that merely stopped is not an agreement, and saying so would put words in their mouth.
 */
const CONFIRMED = 'Plan confirmed.'

/** The call stopped before that happened. Saying it was confirmed would be a lie. */
const ENDED = 'Call ended. This is where the plan was left.'

/**
 * The end of the journey: what the plan asks the user to change, and what it still cannot
 * cover.
 *
 * `build_cards` sets the plan card's rows to exactly `action_rows + unpaid`. Every one of
 * them is outstanding — nothing here has been done — so no group may read as "covered", and
 * the separate `actions` card is deliberately not read: its rows are these same rows, and
 * rendering both showed every deferral twice.
 */
interface Props {
  snapshot: CardsMessage
  /**
   * The call is over as far as the browser is concerned. Pressing End disconnects without
   * the agent calling `end_call`, so the last snapshot may not know yet. The snapshot's own
   * `ended` covers the other direction: the agent hung up while the browser is still
   * connected. Either one means nobody is left to answer the question.
   */
  ended?: boolean
}

export function PlanPanel({ snapshot, ended = false }: Props) {
  const plan = snapshot.cards.find((c) => c.id === 'plan')
  if (!plan) return null
  const proposed = plan.rows.filter((r) => !isUnpaidRow(r))
  const unpaid = plan.rows.filter(isUnpaidRow)

  return (
    <section className="plan" data-status={plan.status} aria-label={plan.title}>
      <header className="card__head">
        <h2 className="card__title">{plan.title}</h2>
        <StatusBadge status={plan.status} />
      </header>

      <CardKv kv={plan.kv} />
      {plan.note && <p className="card__note">{plan.note}</p>}

      {proposed.length > 0 && (
        <div className="plan__group" data-testid="plan-proposed">
          <h3 className="plan__group-title">Proposed changes</h3>
          <CardRows rows={proposed} />
        </div>
      )}

      {unpaid.length > 0 && (
        <div className="plan__group plan__group--unpaid" data-testid="plan-unpaid">
          <h3 className="plan__group-title">Left unpaid this month</h3>
          <CardRows rows={unpaid} />
        </div>
      )}

      {snapshot.phase === 'done' ? (
        <p className="plan__confirm" data-confirmed="true">
          {CONFIRMED}
        </p>
      ) : ended || snapshot.ended ? (
        <p className="plan__confirm" data-ended="true">
          {ENDED}
        </p>
      ) : (
        <p className="plan__confirm">{CONFIRM}</p>
      )}
    </section>
  )
}
