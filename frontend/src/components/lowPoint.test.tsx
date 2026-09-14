/**
 * Why the lowest balance is that number. The voice explains it in one breath; this is the
 * same explanation on screen, and it adds up in front of the reader rather than asserting a
 * total they have to take on trust.
 */
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import snapshots from '../mock/snapshots.json'
import { parseIncoming } from '../protocol/parse'
import type { CardsMessage, LowPointView } from '../protocol/types'
import { LowPointWorking } from './LowPointWorking'

const plan = parseIncoming(snapshots.plan) as CardsMessage
const LOW = plan.low_point as LowPointView

describe('the working behind the lowest day', () => {
  it('shows nothing while the plan is blocked and there is no low point', () => {
    const { container } = render(<LowPointWorking low={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('opens with the balance the month starts from', () => {
    render(<LowPointWorking low={LOW} />)
    const opening = screen.getByTestId('low-opening')
    expect(opening).toHaveTextContent('8,000')
  })

  it('names every movement before the low day, with its own date', () => {
    render(<LowPointWorking low={LOW} />)
    const before = screen.getByTestId('low-before')
    expect(within(before).getByText(/groceries/i)).toBeInTheDocument()
    expect(within(before).getByText('-6,000')).toBeInTheDocument()
  })

  it('says a spread item is a running total, not a payment on one day', () => {
    render(<LowPointWorking low={LOW} />)
    const before = screen.getByTestId('low-before')
    expect(within(before).getByText(/to 30 Sep/i)).toBeInTheDocument()
  })

  it('adds the movements up to the low itself, computed here rather than restated', () => {
    render(<LowPointWorking low={LOW} />)
    const low = screen.getByTestId('low-total')
    // opening 8,000 less the 6,000 of groceries counted to that day.
    expect(low).toHaveTextContent('2,000')
    expect(low).toHaveAttribute('data-agrees', 'true')
  })

  it('names what arrives after it, and where the month closes', () => {
    render(<LowPointWorking low={LOW} />)
    const after = screen.getByTestId('low-after')
    expect(within(after).getByText(/salary/i)).toBeInTheDocument()
    expect(within(after).getByText('72,000')).toBeInTheDocument()
    expect(screen.getByTestId('low-closing')).toHaveTextContent('52,300')
  })

  it('says so rather than quietly showing its own figure when the sums disagree', () => {
    // A truncated or malformed derivation must never be presented as arithmetic that works.
    const wrong: LowPointView = { ...LOW, opening: 9999 }
    render(<LowPointWorking low={wrong} />)
    expect(screen.getByTestId('low-total')).toHaveAttribute('data-agrees', 'false')
    expect(screen.getByRole('note')).toHaveTextContent(/do not add up/i)
  })

  it('holds the two identities the contract guarantees, on the real snapshot', () => {
    const sum = (lines: typeof LOW.before) => lines.reduce((t, l) => t + l.amt, 0)
    expect(LOW.opening + sum(LOW.before)).toBe(LOW.b)
    expect(LOW.b + sum(LOW.after)).toBe(LOW.closing)
  })
})
