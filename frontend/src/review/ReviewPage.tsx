import { to } from '../route'
import { type ReactNode, useId } from 'react'
import { groupIndian, whenDate } from '../components/format'
import { ForgetButton } from '../components/ForgetButton'
import { rememberPhone } from '../phone'
import type { ReviewCall, ReviewFact, ReviewNote } from '../protocol/review'
import { useUserReview } from './useUserReview'

const UNREADABLE = 'The memory could not be read, so what is below may be incomplete.'
const FAILED = 'Could not load this page. The call itself is unaffected.'

/** Money arrives as a string and is grouped for reading; anything else is printed as sent. */
function factValue(fact: ReviewFact): string {
  if (fact.ended || fact.value === null) return 'ended'
  const asNumber = Number(fact.value)
  return fact.field === 'amount' && Number.isFinite(asNumber) ? groupIndian(asNumber) : fact.value
}

function FactRow({ fact }: { fact: ReviewFact }) {
  const value = factValue(fact)
  return (
    <li className="fact" data-ended={fact.ended || undefined}>
      <span className="fact__name">
        {fact.name} {fact.field}
      </span>
      <span className="fact__when">{whenDate(fact.last_confirmed_at)}</span>
      <span className="fact__value">
        {fact.superseded ? (
          <>
            <span className="visually-hidden">{`was ${value}, replaced `}</span>
            <s className="row__retired" data-retired={value} aria-hidden="true">
              {value}
            </s>
          </>
        ) : (
          value
        )}
      </span>
    </li>
  )
}

function NoteRow({ note }: { note: ReviewNote }) {
  return (
    <li className="note" data-superseded={note.superseded || undefined}>
      <span className="note__category">{note.category}</span>
      <span className="note__text">{note.text}</span>
      {note.evidence_turn !== null && <span className="note__turn">turn {note.evidence_turn}</span>}
    </li>
  )
}

function CallRow({ call }: { call: ReviewCall }) {
  return (
    <li className="call">
      <span className="call__when">{whenDate(call.started_at)}</span>
      <span className="call__id">{call.session_id}</span>
      {/* Null without LANGFUSE_PROJECT_ID: a link that goes nowhere is worse than none. */}
      {call.trace_url && (
        <a className="call__trace" href={call.trace_url} target="_blank" rel="noreferrer noopener">
          Langfuse trace
        </a>
      )}
    </li>
  )
}

interface BlockProps {
  title: string
  testId: string
  children: ReactNode
}

/** One ruled section of the page: a heading, and the list under it. */
function Block({ title, testId, children }: BlockProps) {
  const id = useId()
  return (
    <section aria-labelledby={id}>
      <h2 className="review__head" id={id}>
        {title}
      </h2>
      <ul className="review__list" data-testid={testId}>
        {children}
      </ul>
    </section>
  )
}

/**
 * `/review/users/{phone}`: what the system remembers about one person, the history behind
 * it, their calls, and the button that deletes the lot. No authentication — a demo
 * instrument on a private deployment, said plainly in the README.
 */
export function ReviewPage({ phone }: { phone: string }) {
  const { phase, review } = useUserReview(phone)

  return (
    <div className="app app--review">
      <header className="masthead">
        <p className="masthead__brand">Ledgerline</p>
        <p className="masthead__clear">{phone}</p>
      </header>

      {phase === 'loading' && <p className="review__waiting">Reading…</p>}
      {phase === 'failed' && (
        <p className="review__waiting" role="alert">
          {FAILED}
        </p>
      )}

      {review && (
        <main className="review">
          {/* Not the same as a first-time caller, and never shown as one. */}
          {!review.memory_read && <p className="review__warning">{UNREADABLE}</p>}

          <Block title="What is remembered" testId="review-active">
            {review.active.map((fact) => (
              <FactRow key={`${fact.kind}:${fact.name}.${fact.field}`} fact={fact} />
            ))}
          </Block>

          <Block title="What it replaced" testId="review-history">
            {review.history.map((fact) => (
              <FactRow
                key={`${fact.kind}:${fact.name}.${fact.field}@${fact.recorded_at}`}
                fact={fact}
              />
            ))}
          </Block>

          {review.notes.length > 0 && (
            <Block title="In their own words" testId="review-notes">
              {review.notes.map((note) => (
                <NoteRow key={`${note.recorded_at}-${note.text}`} note={note} />
              ))}
            </Block>
          )}

          <Block title="Calls" testId="review-calls">
            {review.calls.map((call) => (
              <CallRow key={call.session_id} call={call} />
            ))}
          </Block>

          <div className="caller__actions">
            {/* The start form reads the remembered number, so calling as this person is
                writing it there and going to the form. */}
            <button
              type="button"
              className="opening__button"
              onClick={() => {
                rememberPhone(phone)
                window.location.assign(to('/'))
              }}
            >
              Call as this number
            </button>
            <ForgetButton phone={phone} />
          </div>
        </main>
      )}
    </div>
  )
}
