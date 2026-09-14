/**
 * "No loans" and "nobody asked about loans" used to look identical: the card was simply
 * absent. The backend now sends the card with one `["None", "", ""]` row, and the board has
 * to render that as an answer rather than as a card with a blank in it.
 */
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import snapshots from '../mock/snapshots.json'
import { parseIncoming } from '../protocol/parse'
import type { CardsMessage } from '../protocol/types'
import { CardRows } from './CardRows'
import { LedgerCard } from './LedgerCard'

const gathering = parseIncoming(snapshots.gathering) as CardsMessage
const debts = gathering.cards.find((c) => c.id === 'debts')

describe('a kind the person says they have none of', () => {
  it('arrives as a card with one None row, not as an absent card', () => {
    expect(debts).toBeDefined()
    expect(debts?.rows).toEqual([['None', '', '']])
  })

  it('renders the answer, and no empty value beside it', () => {
    render(<CardRows rows={[['None', '', '']]} />)
    const row = screen.getByRole('listitem')
    expect(within(row).getByText('None')).toBeInTheDocument()
    // One cell only: a blank amount column would read as a figure nobody has given yet.
    expect(row.querySelectorAll('span')).toHaveLength(1)
  })

  it('marks the row, so it can be set apart from a row carrying a figure', () => {
    const { container } = render(<CardRows rows={[['None', '', '']]} />)
    expect(container.querySelector('.row--none')).toBeInTheDocument()
  })

  it('leaves a real item called "none" with a figure alone', () => {
    render(<CardRows rows={[['None', '4,500', '20 Sep']]} />)
    expect(screen.getByText('4,500')).toBeInTheDocument()
    expect(document.querySelector('.row--none')).toBeNull()
  })

  it('keeps the card readable as a whole: a title, its status, and the answer', () => {
    render(<LedgerCard card={debts!} />)
    expect(screen.getByText(/loans/i)).toBeInTheDocument()
    expect(screen.getByText('None')).toBeInTheDocument()
  })
})
