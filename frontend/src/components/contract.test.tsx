/**
 * Facts about real snapshots that types.ts does not state (docs/process/requests.md, A-1):
 * cards are omitted rather than emptied, and a trimmed card ends with a "+N more" marker.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import sampleJson from '../protocol/sample.json'
import { parseIncoming } from '../protocol/parse'
import type { Card, CardsMessage } from '../protocol/types'
import { CardStack } from './CardStack'
import { LedgerCard } from './LedgerCard'
import { MissingChips } from './MissingChips'
import { PlanPanel } from './PlanPanel'
import { TotalsBar } from './TotalsBar'

const sample = parseIncoming(sampleJson) as CardsMessage
const without = (id: string): Card[] => sample.cards.filter((c) => c.id !== id)
const NOTHING_RETIRED = new Map<string, string>()

describe('omitted cards', () => {
  it('drops a card from the stack as soon as the snapshot stops sending it', () => {
    const { rerender } = render(
      <CardStack cards={sample.cards} focus="essentials" retired={NOTHING_RETIRED} />,
    )
    expect(screen.getByRole('article', { name: 'Optional' })).toBeInTheDocument()
    rerender(
      <CardStack cards={without('optionals')} focus="essentials" retired={NOTHING_RETIRED} />,
    )
    expect(screen.queryByRole('article', { name: 'Optional' })).not.toBeInTheDocument()
    expect(screen.getByRole('article', { name: 'Income' })).toBeInTheDocument()
  })

  it('renders an empty stack rather than placeholders when the snapshot has nothing for it', () => {
    const { container } = render(
      <CardStack
        cards={sample.cards.filter((c) => c.id === 'summary')}
        focus={null}
        retired={NOTHING_RETIRED}
      />,
    )
    expect(container).toBeEmptyDOMElement()
  })
})

describe('the "+N more" trim marker', () => {
  const trimmed: Card = {
    id: 'debts',
    title: 'Loans & cards',
    status: 'ok',
    rows: [
      ['Bike EMI', '4,200', '5 Oct'],
      ['+3 more', '', ''],
    ],
    kv: {},
    note: null,
  }

  it('renders as a muted line with no value column', () => {
    render(<LedgerCard card={trimmed} />)
    const marker = screen.getByText('+3 more')
    expect(marker.closest('li')).toHaveClass('row--more')
    expect(screen.queryByTestId('value-+3 more')).not.toBeInTheDocument()
  })

  it('leaves an ordinary row that merely starts with a plus alone', () => {
    render(<LedgerCard card={{ ...trimmed, rows: [['+900 buffer', '900', '5 Oct']] }} />)
    expect(screen.getByTestId('value-+900 buffer')).toHaveTextContent('900')
  })
})

describe('unpaid plan rows (the shape build_cards emits, requests.md D-1)', () => {
  const withPlan = (rows: string[][], note: string | null = null): CardsMessage => ({
    ...sample,
    cards: [
      ...sample.cards,
      { id: 'plan', title: 'Your plan', status: 'final', rows, kv: {}, note },
    ],
  })

  it('groups a row whose "when" column says unpaid, keeping its amount', () => {
    render(
      <PlanPanel
        snapshot={withPlan([
          ['Rent', '12,000', '5 Oct'],
          ['Streaming', '1,200', 'unpaid, due 5 Oct'],
        ])}
      />,
    )
    const unpaid = screen.getByTestId('plan-unpaid')
    expect(unpaid).toHaveTextContent('Streaming')
    expect(unpaid).toHaveTextContent('1,200')
    expect(unpaid).not.toHaveTextContent('Rent')
  })

  it('matches the word whatever its case', () => {
    render(<PlanPanel snapshot={withPlan([['Streaming', '1,200', 'Unpaid, due 5 Oct']])} />)
    expect(screen.getByTestId('plan-unpaid')).toHaveTextContent('Streaming')
  })

  it('renders the plan note, which carries the consequences', () => {
    render(
      <PlanPanel
        snapshot={withPlan(
          [['Rent', '12,000', '5 Oct']],
          'Streaming lapses for a week; nothing else is late.',
        )}
      />,
    )
    expect(screen.getByText(/Streaming lapses for a week/)).toBeInTheDocument()
    expect(screen.queryByTestId('plan-unpaid')).not.toBeInTheDocument()
  })
})

describe('a value the user does not know (requests.md A-2)', () => {
  const missing = (rows: string[][], note: string | null = null): Card => ({
    id: 'missing',
    title: 'Still need',
    status: 'warn',
    rows,
    kv: {},
    note,
  })

  it('renders a "not known" row muted, not as something still being asked for', () => {
    render(
      <MissingChips
        card={missing([
          ['Opening balance', '', ''],
          ['Electricity', 'amount', 'not known'],
        ])}
      />,
    )
    const asked = screen.getByText('Opening balance').closest('li')!
    const parked = screen.getByText('Electricity').closest('li')!
    expect(asked.dataset.known).not.toBe('false')
    expect(parked.dataset.known).toBe('false')
  })

  it('matches "not known" whatever its case and surrounding words', () => {
    render(<MissingChips card={missing([['Electricity', '', 'Not known — user declined']])} />)
    expect(screen.getByText('Electricity').closest('li')!.dataset.known).toBe('false')
  })

  it('shows the note the backend sends with it', () => {
    render(
      <MissingChips
        card={missing(
          [['Electricity', 'amount', 'not known']],
          'You said you do not know the electricity bill; I am planning without it.',
        )}
      />,
    )
    expect(screen.getByText(/planning without it/)).toBeInTheDocument()
  })
})

describe('conflict notes are shown, never interpreted', () => {
  /**
   * Conflicts now cover dates, card minimums, debt kind and opening balance. The wording is
   * the backend's job; the frontend prints the note it is given and nothing else.
   */
  const conflicted = (note: string): Card => ({
    id: 'income',
    title: 'Income',
    status: 'warn',
    rows: [['Salary', '42,000', '10th']],
    kv: {},
    note,
  })

  it.each([
    'You said the salary lands on the 10th, then the 15th. Which is right?',
    'You called the HDFC a loan earlier and a card just now. Which is it?',
    'The card minimum was 3,200, then 4,000. Which is right?',
    'Opening balance was 3,000, then 800. Which is right?',
  ])('prints %s verbatim', (note) => {
    render(<LedgerCard card={conflicted(note)} />)
    expect(screen.getByText(note)).toBeInTheDocument()
  })

  it('leaves a non-money value alone rather than trying to read it', () => {
    render(<LedgerCard card={conflicted('any note')} />)
    // "10th" is a date in the "when" column; it is printed as sent, not parsed.
    expect(screen.getByText('10th')).toBeInTheDocument()
    expect(screen.getByTestId('value-Salary')).toHaveTextContent('42,000')
  })
})

describe('summary keys are backend field names', () => {
  const summary = (kv: Record<string, string>): Card => ({
    id: 'summary',
    title: 'This month',
    status: 'ok',
    rows: [],
    kv,
    note: null,
  })

  it('renders an underscored key as words, and keeps its value untouched', () => {
    render(<TotalsBar card={summary({ in: '72,000', out: '32,200', unpaid_total: '4,500' })} />)
    expect(screen.getByText('unpaid total')).toBeInTheDocument()
    expect(screen.queryByText('unpaid_total')).not.toBeInTheDocument()
    expect(screen.getByText('4,500')).toBeInTheDocument()
  })
})

describe('the totals bar never drops a field silently', () => {
  const summary = (kv: Record<string, string>): Card => ({
    id: 'summary',
    title: 'This month',
    status: 'ok',
    rows: [],
    kv,
    note: null,
  })

  it('prints every key the snapshot carries, labelled or not', () => {
    const kv = { in: '72,000', out: '27,700', unpaid: '4,500', buffer_left: '900' }
    const { container } = render(<TotalsBar card={summary(kv)} />)
    // One cell per key. A figure the engine starts sending cannot slip off the board
    // merely because this build has no nice label for it.
    expect(container.querySelectorAll('.totals__cell')).toHaveLength(4)
    for (const value of Object.values(kv)) {
      expect(screen.getByText(value)).toBeInTheDocument()
    }
  })

  it('hands `lowest` to the panel instead, so the figure is printed once', () => {
    const { container } = render(
      <TotalsBar card={summary({ in: '72,000', lowest: '2,000 on 30 Sep' })} />,
    )
    expect(container.querySelectorAll('.totals__cell')).toHaveLength(1)
    expect(screen.queryByText('2,000 on 30 Sep')).not.toBeInTheDocument()
  })
})
