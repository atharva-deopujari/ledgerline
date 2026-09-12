/**
 * F4: the panel kept asking "Does this work for you?" after the user had already agreed,
 * and on the plan left on screen after the call ended. The backend now reports a `done`
 * phase once understanding is confirmed or the call is over.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import sampleJson from '../protocol/sample.json'
import { parseIncoming } from '../protocol/parse'
import type { CardsMessage, Phase } from '../protocol/types'
import { PhaseStrip } from './PhaseStrip'
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
      kv: { in: '48,000' },
      note: null,
    },
  ],
})

describe('the confirmation question', () => {
  it('asks while the plan is still open', () => {
    for (const phase of ['ready', 'plan'] as const) {
      const { unmount } = render(<PlanPanel snapshot={withPlan(phase)} />)
      expect(screen.getByText(/does this work for you/i)).toBeInTheDocument()
      expect(screen.queryByText(/plan confirmed/i)).not.toBeInTheDocument()
      unmount()
    }
  })

  it('stops asking once the phase is done, and says so instead', () => {
    render(<PlanPanel snapshot={withPlan('done')} />)
    expect(screen.queryByText(/does this work for you/i)).not.toBeInTheDocument()
    expect(screen.getByText(/plan confirmed/i)).toBeInTheDocument()
  })

  it('still shows the plan itself when done', () => {
    render(<PlanPanel snapshot={withPlan('done')} />)
    expect(screen.getByRole('heading', { name: /Your plan/ })).toBeInTheDocument()
    expect(screen.getByText('Defer')).toBeInTheDocument()
  })

  it('survives the snapshot transition from an open plan to done', () => {
    const { rerender } = render(<PlanPanel snapshot={withPlan('plan')} />)
    expect(screen.getByText(/does this work for you/i)).toBeInTheDocument()

    rerender(<PlanPanel snapshot={withPlan('done')} />)
    expect(screen.queryByText(/does this work for you/i)).not.toBeInTheDocument()
    expect(screen.getByText(/plan confirmed/i)).toBeInTheDocument()
  })
})

describe('the phase strip at done', () => {
  it('fills completely and marks nothing as still in progress', () => {
    render(<PhaseStrip phase="done" />)
    const segments = screen.getAllByRole('listitem')
    expect(segments).toHaveLength(3)
    expect(segments.filter((s) => s.dataset.filled === 'true')).toHaveLength(3)
    expect(segments.filter((s) => s.getAttribute('aria-current') === 'step')).toHaveLength(0)
  })

  it('still marks the current step before done', () => {
    render(<PhaseStrip phase="plan" />)
    const segments = screen.getAllByRole('listitem')
    expect(segments.filter((s) => s.getAttribute('aria-current') === 'step')).toHaveLength(1)
  })
})

describe('the parser accepts the new phase', () => {
  it('parses a done snapshot', () => {
    const got = parseIncoming({ ...sampleJson, phase: 'done' }) as CardsMessage | null
    expect(got).not.toBeNull()
    expect(got!.phase).toBe('done')
  })

  it('still rejects a phase that is not in the contract', () => {
    expect(parseIncoming({ ...sampleJson, phase: 'finished' })).toBeNull()
  })
})
