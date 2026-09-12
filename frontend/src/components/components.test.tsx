import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import sampleJson from '../protocol/sample.json'
import { parseIncoming } from '../protocol/parse'
import type { Card, CardsMessage, TimelinePoint } from '../protocol/types'
import { CardStack } from './CardStack'
import { ErrorBanner } from './ErrorBanner'
import { FocusCard } from './FocusCard'
import { MissingChips } from './MissingChips'
import { PhaseStrip } from './PhaseStrip'
import { PlanPanel } from './PlanPanel'
import { QuestionHeadline } from './QuestionHeadline'
import { Timeline } from './Timeline'
import { VoiceBar } from './VoiceBar'

const sample = parseIncoming(sampleJson) as CardsMessage
const cardById = (id: string): Card => sample.cards.find((c) => c.id === id)!

describe('PhaseStrip', () => {
  it('fills every segment up to the current phase', () => {
    render(<PhaseStrip phase="ready" />)
    const segments = screen.getAllByRole('listitem')
    expect(segments).toHaveLength(3)
    expect(segments.filter((s) => s.dataset.filled === 'true')).toHaveLength(2)
    expect(segments[1]).toHaveAttribute('aria-current', 'step')
  })

  it('fills one segment in the first phase and all of them in the last', () => {
    const { rerender } = render(<PhaseStrip phase="gathering" />)
    expect(screen.getAllByRole('listitem').filter((s) => s.dataset.filled === 'true')).toHaveLength(
      1,
    )
    rerender(<PhaseStrip phase="plan" />)
    expect(screen.getAllByRole('listitem').filter((s) => s.dataset.filled === 'true')).toHaveLength(
      3,
    )
  })
})

describe('QuestionHeadline', () => {
  it('shows the settled question as the headline and streams new text below it', () => {
    render(<QuestionHeadline settled="What do you pay for rent?" streaming="And electr" speaking />)
    expect(screen.getByRole('heading')).toHaveTextContent('What do you pay for rent?')
    expect(screen.getByText(/And electr/)).toBeInTheDocument()
  })

  it('promotes streaming text to the headline when nothing has settled yet', () => {
    render(<QuestionHeadline settled="" streaming="Tell me about your salary" speaking />)
    expect(screen.getByRole('heading')).toHaveTextContent('Tell me about your salary')
  })

  it('falls back to an opening line before the bot has said anything', () => {
    render(<QuestionHeadline settled="" streaming="" speaking={false} />)
    expect(screen.getByRole('heading')).toHaveTextContent(/\w/)
  })
})

describe('FocusCard', () => {
  it('renders the title, a status badge and every row', () => {
    render(<FocusCard card={cardById('essentials')} />)
    expect(screen.getByRole('heading')).toHaveTextContent('Essentials')
    expect(screen.getByText(cardById('essentials').status)).toBeInTheDocument()
    expect(screen.getByText('Rent')).toBeInTheDocument()
    expect(screen.getByText('Groceries')).toBeInTheDocument()
    expect(screen.getByText('Electricity')).toBeInTheDocument()
    expect(screen.getByText('5 Oct')).toBeInTheDocument()
  })

  it('renders a trailing " ?" as a muted question mark beside the value', () => {
    render(<FocusCard card={cardById('essentials')} />)
    const value = screen.getByTestId('value-Rent')
    expect(value).toHaveTextContent('12')
    expect(within(value).getByTitle(/not confirmed/i)).toHaveTextContent('?')
  })

  it('shows the note when the card carries one', () => {
    render(<FocusCard card={cardById('essentials')} />)
    expect(screen.getByText(/Did you mean 12,000/)).toBeInTheDocument()
  })

  it('renders kv cards as a summary grid', () => {
    render(<FocusCard card={cardById('summary')} />)
    expect(screen.getByText('42,000')).toBeInTheDocument()
    expect(screen.getByText('-1,800 on 5 Oct')).toBeInTheDocument()
  })

  it.each(['ok', 'warn', 'provisional', 'final', 'blocked'] as const)(
    'carries status %s on the element, and prints the word too, so colour is never the only signal',
    (status) => {
      // Read from the card rather than hard-coding a fixture's status: which status the
      // sample happens to carry is the backend's business, not this test's.
      const { container } = render(<FocusCard card={{ ...cardById('summary'), status }} />)
      expect(container.querySelector(`[data-status="${status}"]`)).toBeInTheDocument()
      expect(screen.getByText(status)).toBeInTheDocument()
    },
  )
})

describe('CardStack', () => {
  it('excludes the focused card and the cards other panels own', () => {
    render(<CardStack cards={sample.cards} focus="essentials" onFocus={() => {}} />)
    const titles = screen.getAllByRole('button').map((b) => b.textContent ?? '')
    expect(titles.some((t) => t.includes('Essentials'))).toBe(false)
    expect(titles.some((t) => t.includes('Still need'))).toBe(false)
    expect(titles.some((t) => t.includes('Income'))).toBe(true)
    expect(titles.some((t) => t.includes('Loans & cards'))).toBe(true)
  })

  it('collapses each card to its title and a one-line summary', () => {
    render(<CardStack cards={sample.cards} focus="essentials" onFocus={() => {}} />)
    const income = screen.getByRole('button', { name: /Income/ })
    expect(income).toHaveTextContent('Salary')
  })

  it('reports a click so the card can be focused locally', async () => {
    const onFocus = vi.fn()
    render(<CardStack cards={sample.cards} focus="essentials" onFocus={onFocus} />)
    await userEvent.click(screen.getByRole('button', { name: /Income/ }))
    expect(onFocus).toHaveBeenCalledWith('income')
  })

  it('renders nothing when every card is spoken for', () => {
    const { container } = render(
      <CardStack cards={[cardById('missing')]} focus={null} onFocus={() => {}} />,
    )
    expect(container).toBeEmptyDOMElement()
  })
})

describe('MissingChips', () => {
  it('renders one chip per row of the missing card', () => {
    render(<MissingChips card={cardById('missing')} />)
    expect(screen.getByText('Opening balance')).toBeInTheDocument()
    expect(screen.getByText('Electricity')).toBeInTheDocument()
  })

  it('renders nothing without a missing card or with no rows', () => {
    const { container, rerender } = render(<MissingChips card={undefined} />)
    expect(container).toBeEmptyDOMElement()
    rerender(<MissingChips card={{ ...cardById('missing'), rows: [] }} />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('Timeline', () => {
  it('draws a polyline and marks the lowest point', () => {
    const { container } = render(<Timeline points={sample.timeline} />)
    expect(container.querySelector('polyline')).toBeInTheDocument()
    const low = container.querySelector('[data-testid="timeline-low"]')
    expect(low).toBeInTheDocument()
    expect(low).toHaveAttribute('data-date', '2026-10-05')
  })

  it('labels the first and last dates, and claims no figure of its own', () => {
    render(<Timeline points={sample.timeline} />)
    expect(screen.getByText('11 Sep')).toBeInTheDocument()
    expect(screen.getByText('10 Oct')).toBeInTheDocument()
    // The summary card owns the month's lowest; the chart must not print a rival number,
    // because it plots event days only and can miss the real low.
    expect(screen.queryByText(/-1,800/)).not.toBeInTheDocument()
  })

  it('marks the earliest day when the lowest balance repeats', () => {
    const points: TimelinePoint[] = [
      { d: '2026-09-11', b: 100, e: null },
      { d: '2026-09-12', b: -50, e: 'rent' },
      { d: '2026-09-13', b: -50, e: null },
    ]
    render(<Timeline points={points} />)
    expect(screen.getByTestId('timeline-low')).toHaveAttribute('data-date', '2026-09-12')
  })

  it('renders nothing with fewer than two points', () => {
    const { container } = render(<Timeline points={[{ d: '2026-09-11', b: 1, e: null }]} />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('PlanPanel', () => {
  /**
   * build_cards sets the plan card's rows to exactly `action_rows + unpaid`. They are all
   * things the user still has to do, so none of them may be labelled as already covered,
   * and the separate `actions` card must not be read while a plan card exists — its rows
   * are the same rows.
   */
  const planCard = (rows: string[][], note: string | null = null): CardsMessage => ({
    ...sample,
    phase: 'plan',
    cards: [
      ...sample.cards,
      { id: 'plan', title: 'Your plan', status: 'final', rows, kv: { in: '42,000' }, note },
    ],
  })

  const ACTIONS_AND_UNPAID = [
    ['Defer', 'Streaming 1,200', 'to 6 Oct'],
    ['Split', 'Groceries 6,000', '3,000 now, 3,000 on 6 Oct'],
    ['HDFC card min', '3,200', 'unpaid, due 12 Oct'],
  ]

  it('is absent until a plan card exists', () => {
    const { container } = render(<PlanPanel snapshot={sample} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows the summary, the note and the confirmation question', () => {
    render(<PlanPanel snapshot={planCard(ACTIONS_AND_UNPAID, 'Timing, not structural.')} />)
    expect(screen.getByRole('heading', { name: /Your plan/ })).toBeInTheDocument()
    expect(screen.getByText('42,000')).toBeInTheDocument()
    expect(screen.getByText('Timing, not structural.')).toBeInTheDocument()
    expect(screen.getByText(/does this work for you/i)).toBeInTheDocument()
    // the agent never asks for the plan to be repeated back, so neither does the panel
    expect(screen.queryByText(/back to me|repeat/i)).not.toBeInTheDocument()
  })

  it('calls the non-unpaid rows proposed changes, never covered', () => {
    render(<PlanPanel snapshot={planCard(ACTIONS_AND_UNPAID)} />)
    expect(screen.getByText(/proposed changes/i)).toBeInTheDocument()
    expect(screen.queryByText(/covered/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/^done$|already paid/i)).not.toBeInTheDocument()
  })

  it('splits proposed changes from what is left unpaid', () => {
    render(<PlanPanel snapshot={planCard(ACTIONS_AND_UNPAID)} />)
    const proposed = screen.getByTestId('plan-proposed')
    expect(within(proposed).getByText('Defer')).toBeInTheDocument()
    expect(within(proposed).getByText('Split')).toBeInTheDocument()
    expect(within(proposed).queryByText('HDFC card min')).not.toBeInTheDocument()

    const unpaid = screen.getByTestId('plan-unpaid')
    expect(within(unpaid).getByText('HDFC card min')).toBeInTheDocument()
    expect(screen.getByText(/left unpaid/i)).toBeInTheDocument()
  })

  it('never prints an action twice, even though the actions card carries the same rows', () => {
    // sample.cards already contains an `actions` card whose row is ["Defer", ...].
    const snapshot = planCard([['Defer', 'Streaming 1,200', 'to 6 Oct']])
    expect(snapshot.cards.some((c) => c.id === 'actions')).toBe(true)

    render(<PlanPanel snapshot={snapshot} />)
    expect(screen.getAllByText('Defer')).toHaveLength(1)
    expect(screen.getAllByText('Streaming 1,200')).toHaveLength(1)
  })

  it('renders no proposed group when the plan asks for nothing', () => {
    render(<PlanPanel snapshot={planCard([['HDFC card min', '3,200', 'unpaid, due 12 Oct']])} />)
    expect(screen.queryByTestId('plan-proposed')).not.toBeInTheDocument()
    expect(screen.getByTestId('plan-unpaid')).toBeInTheDocument()
  })

  it('renders no unpaid group when nothing is left unpaid', () => {
    render(<PlanPanel snapshot={planCard([['Defer', 'Streaming 1,200', 'to 6 Oct']])} />)
    expect(screen.queryByTestId('plan-unpaid')).not.toBeInTheDocument()
    expect(screen.getByTestId('plan-proposed')).toBeInTheDocument()
  })
})

describe('VoiceBar', () => {
  it('follows the speak state in the pill text', () => {
    const { rerender } = render(
      <VoiceBar speak="idle" micOn onToggleMic={() => {}} onEnd={() => {}} />,
    )
    const pill = () => screen.getByTestId('state-pill')
    expect(pill()).toHaveTextContent(/idle/i)
    rerender(<VoiceBar speak="listening" micOn onToggleMic={() => {}} onEnd={() => {}} />)
    expect(pill()).toHaveTextContent(/listening/i)
    rerender(<VoiceBar speak="speaking" micOn onToggleMic={() => {}} onEnd={() => {}} />)
    expect(pill()).toHaveTextContent(/speaking/i)
    rerender(<VoiceBar speak="thinking" micOn onToggleMic={() => {}} onEnd={() => {}} />)
    expect(pill()).toHaveTextContent(/thinking/i)
  })

  it('toggles the mic and ends the call', async () => {
    const onToggleMic = vi.fn()
    const onEnd = vi.fn()
    render(<VoiceBar speak="listening" micOn onToggleMic={onToggleMic} onEnd={onEnd} />)
    await userEvent.click(screen.getByRole('button', { name: /mute/i }))
    expect(onToggleMic).toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: /end/i }))
    expect(onEnd).toHaveBeenCalled()
  })

  it('names the mic button for what the click will do', () => {
    const { rerender } = render(
      <VoiceBar speak="listening" micOn onToggleMic={() => {}} onEnd={() => {}} />,
    )
    expect(screen.getByRole('button', { name: /^mute/i })).toBeInTheDocument()
    rerender(<VoiceBar speak="listening" micOn={false} onToggleMic={() => {}} onEnd={() => {}} />)
    expect(screen.getByRole('button', { name: /unmute/i })).toBeInTheDocument()
  })
})

describe('ErrorBanner', () => {
  it('shows nothing without a message', () => {
    const { container } = render(<ErrorBanner message={null} onRetry={() => {}} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('announces the message and offers a retry', async () => {
    const onRetry = vi.fn()
    render(<ErrorBanner message="No microphone found." onRetry={onRetry} />)
    expect(screen.getByRole('alert')).toHaveTextContent('No microphone found.')
    await userEvent.click(screen.getByRole('button', { name: /try again/i }))
    expect(onRetry).toHaveBeenCalled()
  })
})
