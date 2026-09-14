/**
 * End to end inside the app: a call ends, the board says it is being reviewed, the poll asks
 * the endpoint for that call's id, and the verdict lands in the plan column.
 */
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { FakeDaily, FakeMediaStream } from './call/testDouble'
import sampleJson from './protocol/sample.json'
import type { Verdict } from './protocol/verdict'
import sample from './protocol/verdict.sample.json'

const READY = sample as Verdict

let daily: FakeDaily
let fetchMock: ReturnType<typeof vi.fn>

const SESSION = { room_url: 'https://x.daily.co/r', token: 't', session_id: 'sess-7' }

const verdictCalls = () =>
  (fetchMock.mock.calls as unknown[][])
    .map(([url]) => String(url))
    .filter((url) => url.endsWith('/verdict'))

beforeEach(() => {
  localStorage.setItem('ledgerline.phone', '9876543210')
  daily = new FakeDaily()
  fetchMock = vi.fn(async (url: unknown) =>
    String(url).endsWith('/verdict')
      ? new Response(JSON.stringify(READY), { status: 200 })
      : new Response(JSON.stringify(SESSION), { status: 200 }),
  )
  vi.stubGlobal('Daily', daily)
  vi.stubGlobal('MediaStream', FakeMediaStream)
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => vi.unstubAllGlobals())

async function callThatEnds() {
  render(<App />)
  await userEvent.click(screen.getByRole('button', { name: /start the call/i }))
  await screen.findByTestId('state-pill')
  act(() => {
    daily.last.emit('app-message', { data: sampleJson })
  })
  await act(async () => {
    daily.last.emit('left-meeting', {})
  })
}

describe('the verdict on the board', () => {
  it('asks about nothing while the call is still running', async () => {
    render(<App />)
    await userEvent.click(screen.getByRole('button', { name: /start the call/i }))
    await screen.findByTestId('state-pill')
    act(() => {
      daily.last.emit('app-message', { data: sampleJson })
    })

    expect(verdictCalls()).toEqual([])
    expect(screen.queryByText(/reviewing this call/i)).not.toBeInTheDocument()
  })

  it('polls the endpoint for the call that just ended, and shows what comes back', async () => {
    await callThatEnds()

    expect(verdictCalls()).toEqual(['/api/sessions/sess-7/verdict'])
    expect(await screen.findByLabelText(/call review/i)).toBeInTheDocument()
    expect(screen.getByTestId('verdict-summary')).toHaveTextContent('0.60')
    expect(screen.getByRole('link', { name: /trace/i })).toHaveAttribute('href', READY.trace_url)
  })
})
