import { render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import sample from '../protocol/evals.sample.json'
import { EvalsScreen } from './EvalsScreen'

const serve = (body: unknown, status = 200) =>
  vi.fn(async () => new Response(JSON.stringify(body), { status }))

beforeEach(() => vi.stubGlobal('fetch', serve(sample)))
afterEach(() => vi.unstubAllGlobals())

describe('the Evals screen', () => {
  it('puts each scenario against each check, as a rate', async () => {
    render(<EvalsScreen />)
    const matrix = await screen.findByRole('table', { name: /check matrix/i })
    const row = within(matrix).getByRole('row', { name: /owner_call_1/ })
    // money_traceable and speakable both whole, state_matches_call short of it.
    expect(within(row).getAllByText('100%')).toHaveLength(2)
    expect(within(row).getByText('93%')).toBeInTheDocument()
  })

  it('marks a rate short of every run, which is the thing to look at', async () => {
    render(<EvalsScreen />)
    const matrix = await screen.findByRole('table', { name: /check matrix/i })
    expect(within(matrix).getByText('93%')).toHaveAttribute('data-short', 'true')
    expect(within(matrix).getAllByText('100%')[0]).not.toHaveAttribute('data-short')
  })

  it('says what each person in a scenario does', async () => {
    render(<EvalsScreen />)
    expect(await screen.findByText(/hedges, fragments mid-sentence/i)).toBeInTheDocument()
  })

  it('names the judge criteria as advisory and points at the report', async () => {
    render(<EvalsScreen />)
    expect(await screen.findByText(/advisory/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /the report/i })).toHaveAttribute('href', '/report')
    expect(screen.getByText(/low point explained/i)).toBeInTheDocument()
  })

  it('says how much was replayed and when', async () => {
    render(<EvalsScreen />)
    expect(await screen.findByText(/449 runs/)).toBeInTheDocument()
  })

  it('answers an empty runs directory in a sentence', async () => {
    vi.stubGlobal('fetch', serve({ ...sample, scenarios: [], matrix: {}, runs_total: 0 }))
    render(<EvalsScreen />)
    expect(await screen.findByText(/no simulation runs on disk yet/i)).toBeInTheDocument()
  })
})
