/**
 * F5: pressing End disconnects the browser without the agent calling `end_call`, so the last
 * snapshot the page holds can still say `plan` or `confirm`. The panel must not keep asking a
 * question no one is listening to — the call lifecycle decides, not the stale phase.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import sampleJson from '../protocol/sample.json'
import { parseIncoming } from '../protocol/parse'
import type { CardsMessage, Phase } from '../protocol/types'
import { PlanPanel } from './PlanPanel'

const sample = parseIncoming(sampleJson) as CardsMessage

const withPlan = (phase: Phase): CardsMessage => ({
  ...sample,
  phase,
  cards: [
    ...sample.cards,
    {
      id: 'plan',
      title: 'Your plan',
      status: 'final',
      rows: [['Defer', 'Streaming 1,200', 'to 6 Oct']],
      kv: {},
      note: null,
    },
  ],
})

describe('a call that ended before the user agreed', () => {
  it.each(['plan', 'ready'] as const)(
    'stops asking when the call is over, even on a %s snapshot',
    (phase) => {
      render(<PlanPanel snapshot={withPlan(phase)} ended />)
      expect(screen.queryByText(/does this work for you/i)).not.toBeInTheDocument()
    },
  )

  it('still asks while the call is live on the same snapshot', () => {
    render(<PlanPanel snapshot={withPlan('plan')} ended={false} />)
    expect(screen.getByText(/does this work for you/i)).toBeInTheDocument()
  })

  it('keeps the plan itself readable after the call', () => {
    render(<PlanPanel snapshot={withPlan('plan')} ended />)
    expect(screen.getByRole('heading', { name: /Your plan/ })).toBeInTheDocument()
    expect(screen.getByText('Defer')).toBeInTheDocument()
  })

  it('does not claim the plan was confirmed when it was not', () => {
    // The user hung up mid-question. Saying "Plan confirmed." would be a lie.
    render(<PlanPanel snapshot={withPlan('plan')} ended />)
    expect(screen.queryByText(/plan confirmed/i)).not.toBeInTheDocument()
    expect(screen.getByText(/call ended/i)).toBeInTheDocument()
  })

  it('does say confirmed when the bot reported done before the call ended', () => {
    render(<PlanPanel snapshot={withPlan('done')} ended />)
    expect(screen.getByText(/plan confirmed/i)).toBeInTheDocument()
    expect(screen.queryByText(/does this work for you/i)).not.toBeInTheDocument()
  })

  it('defaults to live when the prop is omitted', () => {
    render(<PlanPanel snapshot={withPlan('plan')} />)
    expect(screen.getByText(/does this work for you/i)).toBeInTheDocument()
  })
})
