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
import { FocusCard } from './FocusCard'
import { MissingChips } from './MissingChips'
import { PlanPanel } from './PlanPanel'
import { oneLineSummary } from './format'

const sample = parseIncoming(sampleJson) as CardsMessage
const without = (id: string): Card[] => sample.cards.filter((c) => c.id !== id)

describe('omitted cards', () => {
  it('drops a card from the stack as soon as the snapshot stops sending it', () => {
    const { rerender } = render(
      <CardStack cards={sample.cards} focus="essentials" onFocus={() => {}} />,
    )
    expect(screen.getByRole('button', { name: /Optional/ })).toBeInTheDocument()
    rerender(<CardStack cards={without('optionals')} focus="essentials" onFocus={() => {}} />)
    expect(screen.queryByRole('button', { name: /Optional/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Income/ })).toBeInTheDocument()
  })

  it('renders an empty stack rather than placeholders when only the focus card is left', () => {
    const { container } = render(
      <CardStack
        cards={sample.cards.filter((c) => c.id === 'essentials')}
        focus="essentials"
        onFocus={() => {}}
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
    render(<FocusCard card={trimmed} />)
    const marker = screen.getByText('+3 more')
    expect(marker.closest('li')).toHaveClass('row--more')
    expect(screen.queryByTestId('value-+3 more')).not.toBeInTheDocument()
  })

  it('is not counted as an item in a collapsed summary', () => {
    expect(oneLineSummary(trimmed.rows, {})).toBe('Bike EMI 4,200')
  })

  it('leaves an ordinary row that merely starts with a plus alone', () => {
    render(<FocusCard card={{ ...trimmed, rows: [['+900 buffer', '900', '5 Oct']] }} />)
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
    render(<FocusCard card={conflicted(note)} />)
    expect(screen.getByText(note)).toBeInTheDocument()
  })

  it('leaves a non-money value alone rather than trying to read it', () => {
    render(<FocusCard card={conflicted('any note')} />)
    // "10th" is a date in the "when" column; it is printed as sent, not parsed.
    expect(screen.getByText('10th')).toBeInTheDocument()
    expect(screen.getByTestId('value-Salary')).toHaveTextContent('42,000')
  })
})

describe('summary keys are backend field names', () => {
  it('renders an underscored key as words, and keeps its value untouched', () => {
    render(
      <FocusCard
        card={{
          id: 'summary',
          title: 'This month',
          status: 'ok',
          rows: [],
          kv: { in: '72,000', out: '32,200', unpaid_total: '4,500' },
          note: null,
        }}
      />,
    )
    expect(screen.getByText('unpaid total')).toBeInTheDocument()
    expect(screen.queryByText('unpaid_total')).not.toBeInTheDocument()
    expect(screen.getByText('4,500')).toBeInTheDocument()
  })
})

describe('a collapsed card never drops a field silently', () => {
  it('counts the kv entries it could not fit', () => {
    const kv = { in: '72,000', out: '27,700', lowest: '2,000 on 30 Sep', unpaid: '4,500' }
    expect(oneLineSummary([], kv)).toBe('in 72,000 · out 27,700 · lowest 2,000 on 30 Sep · +1')
  })

  it('says nothing extra when everything fits', () => {
    expect(oneLineSummary([], { in: '72,000', out: '27,700' })).toBe('in 72,000 · out 27,700')
  })

  it('reads an underscored key as words here too', () => {
    expect(oneLineSummary([], { unpaid_total: '4,500' })).toBe('unpaid total 4,500')
  })
})
