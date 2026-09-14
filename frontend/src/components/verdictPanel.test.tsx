/**
 * The verdict is a demo instrument: the person on a real call never sees it. It still has to
 * be honest — a failed review says so in a line rather than showing an empty panel, and a
 * criterion that did not apply is not a pass.
 */
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Verdict } from '../protocol/verdict'
import sample from '../protocol/verdict.sample.json'
import { VerdictPanel } from './VerdictPanel'

/** The sample the orchestrator generates from `ledgerline/judge/models.py`. */
const READY = sample as Verdict
const FAILED: Verdict = {
  ...READY,
  status: 'failed',
  summary: null,
  deterministic: [],
  intent: [],
  trace_url: null,
}

describe('VerdictPanel', () => {
  it('says it is reviewing, quietly, while the judge works', () => {
    render(<VerdictPanel state={{ phase: 'reviewing', verdict: null }} />)
    expect(screen.getByText(/reviewing this call/i)).toBeInTheDocument()
    expect(screen.queryByRole('list')).not.toBeInTheDocument()
  })

  it('shows nothing at all before the call has ended', () => {
    const { container } = render(<VerdictPanel state={{ phase: 'idle', verdict: null }} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('prints every deterministic rule with its result', () => {
    render(<VerdictPanel state={{ phase: 'done', verdict: READY }} />)
    const rules = screen.getByTestId('verdict-rules')
    expect(within(rules).getByText(/money traceable/i)).toBeInTheDocument()
    // A failed rule carries the sentence that broke it, or the reader cannot act on it.
    // The detail now opens with the sub-rule that failed, and is rendered as any detail is.
    expect(
      within(rules).getByText(
        /state_matches_facts: rent 12,000 stated on turn 6 was not recorded/i,
      ),
    ).toBeInTheDocument()
    expect(within(rules).getAllByRole('listitem')).toHaveLength(3)
  })

  it('keeps the three intent states apart, and never reads a not-applicable as a pass', () => {
    render(<VerdictPanel state={{ phase: 'done', verdict: READY }} />)
    const intent = screen.getByTestId('verdict-intent')
    expect(within(intent).getByText(/led like a coach/i)).toBeInTheDocument()
    expect(within(intent).getByText(/^fail$/i)).toBeInTheDocument()
    expect(within(intent).getByText(/not applicable/i)).toBeInTheDocument()
    expect(within(intent).getByText(/^pass$/i)).toBeInTheDocument()
    // The turn it rests on, quoted, so a reader can go and look at it.
    expect(within(intent).getByText(/turn 14/i)).toBeInTheDocument()
  })

  it('shows the summary score and the judge that gave it', () => {
    render(<VerdictPanel state={{ phase: 'done', verdict: READY }} />)
    expect(screen.getByTestId('verdict-summary')).toHaveTextContent('0.60')
    expect(screen.getByText(/gpt-5.6-luna/i)).toBeInTheDocument()
  })

  it('links the Langfuse trace when there is one', () => {
    render(<VerdictPanel state={{ phase: 'done', verdict: READY }} />)
    const link = screen.getByRole('link', { name: /trace/i })
    expect(link).toHaveAttribute('href', READY.trace_url)
    expect(link).toHaveAttribute('rel', expect.stringContaining('noreferrer'))
  })

  it('leaves the link out rather than dead when the trace is not there', () => {
    const noTrace = { ...READY, trace_url: null }
    render(<VerdictPanel state={{ phase: 'done', verdict: noTrace }} />)
    expect(screen.queryByRole('link', { name: /trace/i })).not.toBeInTheDocument()
  })

  it('says a failed review failed instead of showing an empty panel', () => {
    render(<VerdictPanel state={{ phase: 'done', verdict: FAILED }} />)
    expect(screen.getByText(/could not be reviewed/i)).toBeInTheDocument()
    expect(screen.queryByTestId('verdict-rules')).not.toBeInTheDocument()
    expect(screen.queryByTestId('verdict-intent')).not.toBeInTheDocument()
  })

  it('says so when the review never came back', () => {
    render(<VerdictPanel state={{ phase: 'gave-up', verdict: null }} />)
    expect(screen.getByText(/did not come back/i)).toBeInTheDocument()
  })
})
