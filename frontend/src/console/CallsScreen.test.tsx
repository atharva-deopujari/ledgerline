/**
 * Every recording on disk. Live calls and simulation runs sit in one ledger, told apart by a
 * word rather than by which table they are in.
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import sample from '../protocol/calls.sample.json'
import { CallsScreen } from './CallsScreen'

const serve = (body: unknown, status = 200) =>
  vi.fn(async () => new Response(JSON.stringify(body), { status }))

beforeEach(() => vi.stubGlobal('fetch', serve(sample)))
afterEach(() => vi.unstubAllGlobals())

const show = async () => {
  render(<CallsScreen />)
  return await screen.findByRole('table', { name: /calls/i })
}

describe('the Calls screen', () => {
  it('lists live and simulated recordings together, each linking to itself', async () => {
    const table = await show()
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(2)
    expect(within(rows[0]!).getByRole('link')).toHaveAttribute(
      'href',
      '/calls/voice-9869101897-20260914T100211Z',
    )
    expect(rows[0]).toHaveTextContent('live')
    expect(rows[1]).toHaveTextContent('simulated')
  })

  it('shows what the run was: turns, whether a plan was reached, how it ended, the prompt', async () => {
    const table = await show()
    const row = within(table).getAllByRole('row')[1]!
    expect(row).toHaveTextContent('48')
    expect(row).toHaveTextContent('reached')
    expect(row).toHaveTextContent('done')
    expect(row).toHaveTextContent('v2@7')
  })

  it('gives each check a dot that says in words what it says in colour', async () => {
    const table = await show()
    const failed = within(table).getAllByRole('row')[2]!
    expect(within(failed).getByText(/state matches call failed/i)).toBeInTheDocument()
    expect(within(failed).getByText(/money traceable passed/i)).toBeInTheDocument()
  })

  it('says a simulated run was not judged rather than scoring it', async () => {
    const table = await show()
    const simulated = within(table).getAllByRole('row')[2]!
    expect(within(simulated).getByText(/not judged/i)).toBeInTheDocument()
    expect(simulated).not.toHaveTextContent('0.00')
  })

  it('filters by source without going back to the server', async () => {
    const fetchMock = serve(sample)
    vi.stubGlobal('fetch', fetchMock)
    await show()

    await userEvent.selectOptions(screen.getByLabelText(/source/i), 'live')
    expect(screen.getAllByRole('row')).toHaveLength(2)
    expect(screen.queryByText('simulated')).not.toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('filters by scenario or number, with the options taken from the whole list', async () => {
    await show()
    await userEvent.selectOptions(screen.getByLabelText(/scenario or number/i), 'owner_call_1')
    expect(screen.getAllByRole('row')).toHaveLength(2)
    expect(screen.getByText('simulated')).toBeInTheDocument()
  })

  it('says so when a filter matches nothing, without losing the filter', async () => {
    await show()
    await userEvent.selectOptions(screen.getByLabelText(/source/i), 'live')
    await userEvent.selectOptions(screen.getByLabelText(/scenario or number/i), 'owner_call_1')
    expect(screen.getByText(/no call matches/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/source/i)).toHaveValue('live')
  })

  it('answers an empty recordings directory in a sentence', async () => {
    vi.stubGlobal('fetch', serve({ calls: [] }))
    render(<CallsScreen />)
    expect(await screen.findByText(/no calls have been recorded/i)).toBeInTheDocument()
  })
})
