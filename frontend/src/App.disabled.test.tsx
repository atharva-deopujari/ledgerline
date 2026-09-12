/**
 * The Start control must never accept a second gesture while a call is coming up or live —
 * the belt to the hook's braces, after a live call posted /api/sessions sixteen times.
 */
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { FakeDaily, FakeMediaStream } from './call/testDouble'

let daily: FakeDaily

const SESSION = { room_url: 'https://x.daily.co/r', token: 't', session_id: 's' }

beforeEach(() => {
  daily = new FakeDaily()
  vi.stubGlobal('Daily', daily)
  vi.stubGlobal('MediaStream', FakeMediaStream)
})
afterEach(() => vi.unstubAllGlobals())

describe('the Start control while a call is coming up', () => {
  it('is disabled from the moment it is pressed until the call is up', async () => {
    let release: (r: Response) => void = () => {}
    const pending = new Promise<Response>((resolve) => {
      release = resolve
    })
    const fetchImpl = vi.fn(() => pending)
    vi.stubGlobal('fetch', fetchImpl)

    render(<App />)
    const button = screen.getByRole('button', { name: /start the call/i })
    await userEvent.click(button)

    // still on screen, but refusing further presses while the POST is in flight
    expect(button).toBeDisabled()
    await userEvent.click(button)
    await userEvent.click(button)
    expect(fetchImpl).toHaveBeenCalledTimes(1)

    await act(async () => {
      release(new Response(JSON.stringify(SESSION), { status: 201 }))
      await pending
    })
    await waitFor(() => expect(screen.getByTestId('state-pill')).toBeInTheDocument())
    expect(fetchImpl).toHaveBeenCalledTimes(1)
  })

  it('shows the 409 sentence and re-enables the button so the user can end and retry', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('busy', { status: 409 })),
    )
    render(<App />)
    await userEvent.click(screen.getByRole('button', { name: /start the call/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/a call is already running/i)
    expect(screen.getByRole('button', { name: /start the call/i })).toBeEnabled()
  })

  it('offers a working second call after the bot leaves', async () => {
    const starts: RequestInit[] = []
    const fetchImpl = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST') starts.push(init)
      return new Response(JSON.stringify(SESSION), { status: 201 })
    })
    vi.stubGlobal('fetch', fetchImpl)

    render(<App />)
    await userEvent.click(screen.getByRole('button', { name: /start the call/i }))
    await screen.findByTestId('state-pill')

    act(() => {
      daily.last.emit('participant-left', { participant: { local: false } })
    })
    // With no card ever received the board is not kept, so the way back is the start
    // screen's own button rather than the board footer's.
    const again = await screen.findByRole('button', { name: /^start the call$/i })
    await waitFor(() => expect(daily.calls[0].destroyed).toBe(1))

    await userEvent.click(again)
    // Retiring the first call also DELETEs its session, so count starts, not requests.
    await waitFor(() => expect(starts).toHaveLength(2))
  })
})
