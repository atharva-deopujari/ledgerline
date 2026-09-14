import type { Verdict } from '../protocol/verdict'
import type { VerdictState } from '../verdict/useVerdict'
import { keyAsWords } from './format'

const REVIEWING = 'Reviewing this call…'
const GAVE_UP = 'The review did not come back. The call itself is saved.'
const FAILED_LINE = 'This call could not be reviewed.'

/**
 * The judge's view of the call that just ended. Demo-facing: the person on a real call would
 * never see it, so it is written for whoever is reading the run afterwards.
 */
export function VerdictPanel({ state }: { state: VerdictState }) {
  if (state.phase === 'idle') return null
  if (state.phase !== 'done') {
    return <p className="verdict__waiting">{state.phase === 'reviewing' ? REVIEWING : GAVE_UP}</p>
  }
  return <Panel verdict={state.verdict} />
}

function Panel({ verdict }: { verdict: Verdict }) {
  if (verdict.status === 'failed') {
    // A verdict that failed still says something. An empty panel would read as a pass.
    return (
      <section className="verdict" aria-label="Call review">
        <p className="verdict__waiting">{FAILED_LINE}</p>
      </section>
    )
  }
  return (
    <section className="verdict" aria-label="Call review">
      <header className="verdict__head">
        <h3 className="verdict__title">Call review</h3>
        {verdict.summary !== null && (
          <p className="verdict__score" data-testid="verdict-summary">
            {verdict.summary.toFixed(2)}
          </p>
        )}
      </header>

      {verdict.deterministic.length > 0 && (
        <ul className="verdict__list" data-testid="verdict-rules">
          {verdict.deterministic.map((rule) => (
            <li key={rule.rule} className="verdict__row" data-passed={rule.passed}>
              <span className="verdict__name">{keyAsWords(rule.rule)}</span>
              <span className="verdict__outcome">{rule.passed ? 'pass' : 'fail'}</span>
              {rule.detail && <span className="verdict__detail">{rule.detail}</span>}
            </li>
          ))}
        </ul>
      )}

      {verdict.intent.length > 0 && (
        <ul className="verdict__list" data-testid="verdict-intent">
          {verdict.intent.map((criterion) => (
            <li key={criterion.criterion} className="verdict__row" data-outcome={criterion.outcome}>
              <span className="verdict__name">{keyAsWords(criterion.criterion)}</span>
              <span className="verdict__outcome">{keyAsWords(criterion.outcome)}</span>
              <span className="verdict__detail">
                {criterion.reason}
                {criterion.turn !== null && (
                  <span className="verdict__turn"> · turn {criterion.turn}</span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}

      <p className="verdict__foot">
        {verdict.judge_model && <span className="verdict__judge">{verdict.judge_model}</span>}
        {verdict.trace_url && (
          <a
            className="verdict__trace"
            href={verdict.trace_url}
            target="_blank"
            rel="noreferrer noopener"
          >
            Langfuse trace
          </a>
        )}
      </p>
    </section>
  )
}
