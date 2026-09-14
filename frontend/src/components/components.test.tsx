import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import sampleJson from '../protocol/sample.json'
import { parseIncoming } from '../protocol/parse'
import type { Card, CardsMessage, TimelinePoint } from '../protocol/types'
import { CardRows } from './CardRows'
import { CardStack } from './CardStack'
import { ErrorBanner } from './ErrorBanner'
import { LedgerCard } from './LedgerCard'
import { LowestPoint } from './LowestPoint'
import { MissingChips } from './MissingChips'
import { PhaseStrip } from './PhaseStrip'
import { PlanPanel } from './PlanPanel'
import { QuestionHeadline } from './QuestionHeadline'
import { Timeline } from './Timeline'
import { TotalsBar } from './TotalsBar'
import { VoiceBar } from './VoiceBar'
import { SPEAK_LABEL, STATUS_LABEL } from './format'

const sample = parseIncoming(sampleJson) as CardsMessage
const cardById = (id: string): Card => sample.cards.find((c) => c.id === id)!
const NOTHING_RETIRED = new Map<string, string>()

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

describe('LedgerCard', () => {
  it('renders the title, a status word and every row', () => {
    render(<LedgerCard card={cardById('essentials')} />)
    expect(screen.getByRole('heading')).toHaveTextContent('Essentials')
    expect(screen.getByText(STATUS_LABEL[cardById('essentials').status])).toBeInTheDocument()
    expect(screen.getByText('Rent')).toBeInTheDocument()
    expect(screen.getByText('Groceries')).toBeInTheDocument()
    expect(screen.getByText('Electricity')).toBeInTheDocument()
    expect(screen.getByText('5 Oct')).toBeInTheDocument()
  })

  it('renders a trailing " ?" as a muted question mark beside the value', () => {
    // Built here rather than read from the sample: no row in the current sample carries the
    // provisional suffix, and the rule is about any row that does.
    const provisional = { ...cardById('essentials'), rows: [['Rent', '12,000 ?', '5 Oct']] }
    render(<LedgerCard card={provisional} />)
    const value = screen.getByTestId('value-Rent')
    expect(value).toHaveTextContent('12,000')
    expect(within(value).getByTitle(/not confirmed/i)).toHaveTextContent('?')
  })

  it('shows the note when the card carries one', () => {
    // The summary is the card the engine writes a note on; the essentials note the old
    // sample carried was conflict machinery that has not existed since the cut.
    render(<LedgerCard card={cardById('summary')} />)
    expect(screen.getByText(/ask the lender to move it/i)).toBeInTheDocument()
  })

  it('marks the card the bot last touched, and leaves the others unmarked', () => {
    const { container, rerender } = render(<LedgerCard card={cardById('income')} focused />)
    expect(container.querySelector('[data-focused]')).toBeInTheDocument()
    rerender(<LedgerCard card={cardById('income')} />)
    expect(container.querySelector('[data-focused]')).not.toBeInTheDocument()
  })

  it.each(['ok', 'warn', 'provisional', 'final', 'blocked', 'carried'] as const)(
    'carries status %s on the element, and prints the word too, so colour is never the only signal',
    (status) => {
      // Read from the card rather than hard-coding a fixture's status: which status the
      // sample happens to carry is the backend's business, not this test's.
      const { container } = render(<LedgerCard card={{ ...cardById('income'), status }} />)
      expect(container.querySelector(`[data-status="${status}"]`)).toBeInTheDocument()
      expect(screen.getByText(STATUS_LABEL[status])).toBeInTheDocument()
    },
  )
})

describe('a corrected figure', () => {
  const ROWS = [['Salary', '72,000', '1 Oct']]

  it('strikes the figure it replaced beside the live one', () => {
    render(<CardRows rows={ROWS} retired={new Map([['Salary', '45,000']])} />)
    const value = screen.getByTestId('value-Salary')
    expect(value).toHaveTextContent('72,000')
    expect(within(value).getByText('45,000')).toHaveAttribute('data-retired', '45,000')
  })

  it('keeps the retired figure out of reach of assistive tech, as one spoken correction', () => {
    render(<CardRows rows={ROWS} retired={new Map([['Salary', '45,000']])} />)
    const struck = screen.getByText('45,000')
    // Hidden, so a screen reader never reads two figures and has to guess which is current.
    expect(struck).toHaveAttribute('aria-hidden', 'true')
    expect(struck.tagName).toBe('S')
    // What it reads instead: one sentence, the old figure named as old, so the correction
    // is heard as "was 45,000, now 72,000" and not as two competing amounts.
    const value = screen.getByTestId('value-Salary')
    expect(within(value).getByText('was 45,000, now')).toHaveClass('visually-hidden')
    expect(within(value).getByText('72,000')).toHaveClass('row__live')
  })

  it('strikes nothing when the backend sent the same figure again', () => {
    render(<CardRows rows={ROWS} retired={NOTHING_RETIRED} />)
    expect(screen.queryByText('45,000')).not.toBeInTheDocument()
    expect(document.querySelector('[data-changed]')).toBeNull()
  })
})

describe('CardStack', () => {
  it('shows every account open, including the one in focus', () => {
    render(<CardStack cards={sample.cards} focus="essentials" retired={NOTHING_RETIRED} />)
    // Nothing is collapsed and nothing is behind a click: a figure the person gave has to
    // be on the board, or they cannot correct it.
    expect(screen.getByRole('article', { name: 'Essentials' })).toBeInTheDocument()
    expect(screen.getByRole('article', { name: 'Income' })).toBeInTheDocument()
    expect(screen.getByRole('article', { name: 'Loans & cards' })).toBeInTheDocument()
    expect(screen.getByText('Salary')).toBeInTheDocument()
    expect(screen.getByText('Bike EMI')).toBeInTheDocument()
  })

  it('leaves out the cards another part of the board owns', () => {
    render(<CardStack cards={sample.cards} focus="essentials" retired={NOTHING_RETIRED} />)
    // `missing` is the chip row, `summary` is the totals bar; printing them here would be
    // the same figures twice.
    expect(screen.queryByRole('article', { name: 'Still need' })).not.toBeInTheDocument()
    expect(screen.queryByRole('article', { name: 'This month' })).not.toBeInTheDocument()
  })

  it('marks the focused card only', () => {
    const { container } = render(
      <CardStack cards={sample.cards} focus="essentials" retired={NOTHING_RETIRED} />,
    )
    const focused = container.querySelectorAll('[data-focused]')
    expect(focused).toHaveLength(1)
    expect(focused[0]).toHaveAttribute('data-card', 'essentials')
  })

  it('renders nothing when every card is spoken for', () => {
    const { container } = render(
      <CardStack cards={[cardById('missing')]} focus={null} retired={NOTHING_RETIRED} />,
    )
    expect(container).toBeEmptyDOMElement()
  })
})

describe('TotalsBar', () => {
  it('prints the summary card’s own figures under readable labels', () => {
    render(<TotalsBar card={cardById('summary')} />)
    expect(screen.getByText('In')).toBeInTheDocument()
    expect(screen.getByText('42,000')).toBeInTheDocument()
    expect(screen.getByText('Out')).toBeInTheDocument()
    expect(screen.getByText('9,412')).toBeInTheDocument()
  })

  it('leaves the lowest to the panel rather than printing it twice', () => {
    render(<TotalsBar card={cardById('summary')} />)
    expect(screen.queryByText(/on 25 Sep/)).not.toBeInTheDocument()
  })

  it('carries the summary status, so a provisional month says so', () => {
    const { container } = render(
      <TotalsBar card={{ ...cardById('summary'), status: 'provisional' }} />,
    )
    expect(container.querySelector('[data-status="provisional"]')).toBeInTheDocument()
  })

  it('never drops a key it has no label for', () => {
    const card = { ...cardById('summary'), kv: { in: '42,000', unpaid_total: '3,200' } }
    render(<TotalsBar card={card} />)
    // A field the engine adds later must appear under its own name, not vanish.
    expect(screen.getByText('unpaid total')).toBeInTheDocument()
    expect(screen.getByText('3,200')).toBeInTheDocument()
  })

  it('renders nothing without a summary card', () => {
    const { container } = render(<TotalsBar card={undefined} />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('LowestPoint', () => {
  it('splits the delivered sentence into a figure and a day', () => {
    render(<LowestPoint card={cardById('summary')} />)
    expect(screen.getByText('0')).toBeInTheDocument()
    expect(screen.getByText('on 25 Sep')).toBeInTheDocument()
  })

  it('says so while the month is still provisional', () => {
    render(<LowestPoint card={{ ...cardById('summary'), status: 'provisional' }} />)
    expect(screen.getByText(/still provisional/i)).toBeInTheDocument()
  })

  it('renders nothing when the summary carries no lowest', () => {
    const { container } = render(<LowestPoint card={{ ...cardById('summary'), kv: {} }} />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('MissingChips', () => {
  it('renders one chip per row of the missing card', () => {
    render(<MissingChips card={cardById('missing')} />)
    expect(screen.getByText('Electricity amount')).toBeInTheDocument()
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
    expect(low).toHaveAttribute('data-date', '2026-09-25')
  })

  it('draws one bar per day of the window, not one per point', () => {
    const { container } = render(<Timeline points={sample.timeline} />)
    // 11 Sep to 10 Oct inclusive. The backend sends six points; the month has thirty days,
    // and the balance on a day with no events is the last one it sent.
    expect(container.querySelectorAll('.timeline__bar')).toHaveLength(30)
  })

  it('labels the first and last dates, and claims no figure of its own', () => {
    // `showLow={false}` is how the board renders it whenever the summary carries a lowest:
    // the panel prints that figure, and two on one screen read as two findings.
    render(<Timeline points={sample.timeline} showLow={false} />)
    expect(screen.getByText('11 Sep')).toBeInTheDocument()
    expect(screen.getByText('10 Oct')).toBeInTheDocument()
    // The summary card owns the month's lowest; the chart must not print a rival number,
    // because it plots event days only and can miss the real low.
    expect(screen.queryByText(/on 25 Sep/)).not.toBeInTheDocument()
  })

  it('reads out a day only when that day is pointed at', async () => {
    const { container } = render(<Timeline points={sample.timeline} />)
    expect(screen.queryByText('2,800')).not.toBeInTheDocument()
    await userEvent.hover(container.querySelectorAll('.timeline__bar')[0])
    // The figure shown is the balance the backend sent for that day, not a derived one.
    expect(screen.getByText('2,800')).toBeInTheDocument()
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

  it('numbers the proposed changes as steps still to take', () => {
    const { container } = render(<PlanPanel snapshot={planCard(ACTIONS_AND_UNPAID)} />)
    // An ordered list, so they read as a sequence to work through — and nothing in it is
    // ever ticked, because none of it has happened yet.
    expect(container.querySelector('ol.plan__actions')).toBeInTheDocument()
    expect(container.querySelectorAll('.plan__action')).toHaveLength(2)
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
  it('follows the speak state in words, not only in the wave', () => {
    const { rerender } = render(
      <VoiceBar speak="idle" micOn onToggleMic={() => {}} onEnd={() => {}} />,
    )
    const pill = () => screen.getByTestId('state-pill')
    expect(pill()).toHaveTextContent(SPEAK_LABEL.idle)
    rerender(<VoiceBar speak="listening" micOn onToggleMic={() => {}} onEnd={() => {}} />)
    expect(pill()).toHaveTextContent(SPEAK_LABEL.listening)
    rerender(<VoiceBar speak="speaking" micOn onToggleMic={() => {}} onEnd={() => {}} />)
    expect(pill()).toHaveTextContent(SPEAK_LABEL.speaking)
    rerender(<VoiceBar speak="thinking" micOn onToggleMic={() => {}} onEnd={() => {}} />)
    expect(pill()).toHaveTextContent(SPEAK_LABEL.thinking)
  })

  it('hides the wave from assistive tech, since the words already carry the state', () => {
    const { container } = render(
      <VoiceBar speak="speaking" micOn onToggleMic={() => {}} onEnd={() => {}} />,
    )
    expect(container.querySelector('.voicebar__wave')).toHaveAttribute('aria-hidden', 'true')
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
