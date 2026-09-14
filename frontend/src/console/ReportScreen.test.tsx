import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import sample from '../protocol/report.sample.json'
import { ReportScreen } from './ReportScreen'

const serve = (body: unknown, status = 200) =>
  vi.fn(async () => new Response(JSON.stringify(body), { status }))

beforeEach(() => vi.stubGlobal('fetch', serve(sample)))
afterEach(() => vi.unstubAllGlobals())

describe('the Report screen', () => {
  it('renders the report the repository holds', async () => {
    render(<ReportScreen />)
    expect(await screen.findByRole('heading', { name: /evaluation report/i })).toBeInTheDocument()
    expect(screen.getByRole('table')).toBeInTheDocument()
  })

  it('says so when the file is empty rather than showing a blank page', async () => {
    vi.stubGlobal('fetch', serve({ markdown: '   ' }))
    render(<ReportScreen />)
    expect(await screen.findByText(/the report is empty/i)).toBeInTheDocument()
  })

  it('says so when it could not be read', async () => {
    vi.stubGlobal('fetch', serve(null, 500))
    render(<ReportScreen />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/could not/i)
  })
})
