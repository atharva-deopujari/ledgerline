/**
 * Everyone who has called, and what the system remembers of them. The screen is a ledger:
 * figures right, hairlines between, no zebra, and an empty store answered in a sentence.
 */
import { render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import sample from '../protocol/users.sample.json'
import { CallersScreen } from './CallersScreen'

const serve = (body: unknown, status = 200) =>
  vi.fn(async () => new Response(JSON.stringify(body), { status }))

beforeEach(() => vi.stubGlobal('fetch', serve(sample)))
afterEach(() => vi.unstubAllGlobals())

const show = async (body: unknown = sample, status = 200) => {
  vi.stubGlobal('fetch', serve(body, status))
  render(<CallersScreen />)
  return await screen.findByRole('table', { name: /callers/i })
}

describe('the Callers screen', () => {
  it('lists one row per caller, newest call first as the server sent them', async () => {
    const table = await show()
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveTextContent('9869101897')
  })

  it('gives every row a link to that caller', async () => {
    const table = await show()
    const link = within(table).getByRole('link', { name: /9869101897/ })
    expect(link).toHaveAttribute('href', '/callers/9869101897')
  })

  it('shows what is remembered: calls, facts and the headline figures', async () => {
    const table = await show()
    const row = within(table).getAllByRole('row')[1]!
    expect(within(row).getByText('3')).toBeInTheDocument()
    expect(within(row).getByText('7')).toBeInTheDocument()
    // The name is set apart from the figure, so the row's text is the assertion.
    expect(row).toHaveTextContent('rent 13,000 on the 7th')
    expect(row).toHaveTextContent('salary 30,000 on the 30th')
  })

  it('says a caller has not been judged rather than scoring them zero', async () => {
    const table = await show()
    const unjudged = within(table).getAllByRole('row')[2]!
    // last_summary is null: no call of theirs carries a verdict yet.
    expect(within(unjudged).getByText(/not judged/i)).toBeInTheDocument()
    expect(within(unjudged).queryByText('0.00')).not.toBeInTheDocument()
  })

  it('prints the score of a caller who has been judged', async () => {
    const table = await show()
    expect(within(table).getByText('0.86')).toBeInTheDocument()
  })

  it('answers an empty store in a sentence', async () => {
    vi.stubGlobal('fetch', serve({ users: [] }))
    render(<CallersScreen />)
    expect(await screen.findByText(/no one has called yet/i)).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('says so when the list could not be read', async () => {
    vi.stubGlobal('fetch', serve(null, 500))
    render(<CallersScreen />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/could not/i)
  })
})
