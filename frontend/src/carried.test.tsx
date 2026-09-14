/**
 * A returning caller's first screen. Their rent and salary came from the last call and have
 * not been confirmed this one, so the cards say where the figures came from — they are not
 * wrong, only unconfirmed, and the plan is blocked until the person says.
 */
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { CardStack } from './components/CardStack'
import snapshots from './mock/snapshots.json'
import { parseIncoming } from './protocol/parse'
import type { CardsMessage } from './protocol/types'

const returning = parseIncoming(snapshots.returning) as CardsMessage

describe('a carried card', () => {
  it('survives the parser rather than being dropped as an unknown status', () => {
    expect(returning).not.toBeNull()
    expect(returning.cards.filter((c) => c.status === 'carried')).toHaveLength(2)
  })

  it('says where the figure came from, in words, not only in colour', () => {
    render(<CardStack cards={returning.cards} focus={returning.focus} retired={new Map()} />)
    const income = screen.getByText('Income').closest('article, section, li, div')
    expect(income).not.toBeNull()
    expect(within(income as HTMLElement).getByText(/from last call/i)).toBeInTheDocument()
  })

  it('keeps the note the backend wrote about confirming each one', () => {
    render(<CardStack cards={returning.cards} focus={returning.focus} retired={new Map()} />)
    expect(screen.getAllByText(/confirm or change each/i).length).toBeGreaterThan(0)
  })
})
