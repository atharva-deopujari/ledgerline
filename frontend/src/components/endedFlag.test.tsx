/**
 * F3: `readiness()` used to set phase `done` for a call that merely ended, so a user who
 * said goodbye without agreeing saw "Plan confirmed." The wire now separates the two:
 * `phase: "done"` means the person confirmed, `ended: true` means the call stopped.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import sampleJson from '../protocol/sample.json'
import { parseIncoming } from '../protocol/parse'
import type { CardsMessage, Phase } from '../protocol/types'
import { PlanPanel } from './PlanPanel'

const base = parseIncoming(sampleJson) as CardsMessage

const snap = (phase: Phase, ended?: boolean): CardsMessage => ({
  ...base,
  phase,
  ...(ended === undefined ? {} : { ended }),
  cards: [
    ...base.cards,
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

const confirmed = () => screen.queryByText(/plan confirmed/i)
const ended = () => screen.queryByText(/call ended/i)
const asking = () => screen.queryByText(/does this work for you/i)

describe('the agent ends the call without agreement', () => {
  it('says the call ended, not that the plan was confirmed', () => {
    // end_call fired after a goodbye: ended is true, phase never reached done, and the
    // browser is still connected so the call lifecycle says live.
    render(<PlanPanel snapshot={snap('plan', true)} ended={false} />)
    expect(ended()).toBeInTheDocument()
    expect(confirmed()).not.toBeInTheDocument()
    expect(asking()).not.toBeInTheDocument()
  })

  it.each(['gathering', 'ready', 'plan'] as const)('does the same from phase %s', (phase) => {
    render(<PlanPanel snapshot={snap(phase, true)} ended={false} />)
    expect(ended()).toBeInTheDocument()
    expect(confirmed()).not.toBeInTheDocument()
  })
})

describe('the person actually confirmed', () => {
  it('says the plan was confirmed', () => {
    render(<PlanPanel snapshot={snap('done')} ended={false} />)
    expect(confirmed()).toBeInTheDocument()
    expect(ended()).not.toBeInTheDocument()
  })

  it('still says confirmed once the call has also ended', () => {
    render(<PlanPanel snapshot={snap('done', true)} ended />)
    expect(confirmed()).toBeInTheDocument()
    expect(ended()).not.toBeInTheDocument()
  })
})

describe('the call is still going', () => {
  it('asks when neither the snapshot nor the lifecycle says it is over', () => {
    render(<PlanPanel snapshot={snap('plan')} ended={false} />)
    expect(asking()).toBeInTheDocument()
  })

  it('treats an absent ended field as not ended', () => {
    render(<PlanPanel snapshot={snap('plan')} />)
    expect(asking()).toBeInTheDocument()
    expect(ended()).not.toBeInTheDocument()
  })

  it('still honours the browser End button when the snapshot says nothing', () => {
    render(<PlanPanel snapshot={snap('plan')} ended />)
    expect(ended()).toBeInTheDocument()
    expect(confirmed()).not.toBeInTheDocument()
  })
})

describe('the parser carries the flag', () => {
  it('keeps ended when the backend sends it', () => {
    const got = parseIncoming({ ...sampleJson, ended: true }) as CardsMessage
    expect(got.ended).toBe(true)
  })

  it('accepts a snapshot without it', () => {
    const got = parseIncoming(sampleJson) as CardsMessage
    expect(got).not.toBeNull()
    expect(got.ended).toBeFalsy()
  })

  it('rejects a non-boolean ended', () => {
    expect(parseIncoming({ ...sampleJson, ended: 'yes' })).toBeNull()
    expect(parseIncoming({ ...sampleJson, ended: 1 })).toBeNull()
  })
})
