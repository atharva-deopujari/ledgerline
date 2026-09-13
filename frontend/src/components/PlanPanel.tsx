import { isUnpaidRow } from '../protocol/markers'
import type { CardsMessage } from '../protocol/types'
import { CardKv } from './CardKv'
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
 * The end of the journey: what the plan asks the person to change, and what it still cannot
 * cover, on the panel where the low point and the month's shape already are.
 *
 * `build_cards` sets the plan card's rows to exactly `action_rows + unpaid`. Every one of
 * them is outstanding — nothing here has been done — so the proposed changes are numbered
 * as things still to do and never ticked, and the separate `actions` card is deliberately
 * not read: its rows are these same rows, and rendering both showed every deferral twice.
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
  const confirmed = snapshot.phase === 'done'
  const over = ended || snapshot.ended

  return (
    <section className="plan" data-status={plan.status} aria-label={plan.title}>
      <header className="plan__head">
        <h2 className="plan__title">{plan.title}</h2>
        <StatusBadge status={plan.status} />
      </header>

      <CardKv kv={plan.kv} />

      {proposed.length > 0 && (
        <div className="plan__group" data-testid="plan-proposed">
          <h3 className="plan__group-title">Proposed changes</h3>
          <ol className="plan__actions">
            {proposed.map(([what, detail = '', when = ''], i) => (
              <li className="plan__action" key={`${what}-${i}`}>
                <span className="plan__what">
                  {what}
                  {detail && <span className="plan__detail"> {detail}</span>}
                </span>
                {when && <span className="plan__when">{when}</span>}
              </li>
            ))}
          </ol>
        </div>
      )}

      {unpaid.length > 0 && (
        <div className="plan__group plan__group--unpaid" data-testid="plan-unpaid">
          <h3 className="plan__group-title">Left unpaid this month</h3>
          <ul className="plan__unpaid">
            {unpaid.map(([label, value = '', when = ''], i) => (
              <li className="plan__owed" key={`${label}-${i}`}>
                <span className="plan__owed-label">{label}</span>
                <span className="plan__owed-value">{value}</span>
                {when && <span className="plan__when">{when}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* What it costs if the plan does not come off. Never an action without its price. */}
      {plan.note && <p className="plan__consequence">{plan.note}</p>}

      <p
        className="plan__confirm"
        data-confirmed={confirmed || undefined}
        data-ended={!confirmed && over ? true : undefined}
      >
        {confirmed ? CONFIRMED : over ? ENDED : CONFIRM}
      </p>
    </section>
  )
}
