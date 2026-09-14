/**
 * The owner hung up on a live call and found the board with no way off it. When a call is
 * over the console is still there, and the screen says where to go next — each of which ends
 * the call properly on the way out rather than dropping the connection and walking off.
 */
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { FakeDaily, FakeMediaStream } from './call/testDouble'
import sampleJson from './protocol/sample.json'

const SESSION = {
  room_url: 'https://x.daily.co/r',
  token: 't',
  session_id: '9876543210-20260914T100211Z',
}

let daily: FakeDaily
let fetchMock: ReturnType<typeof vi.fn>
let assign: ReturnType<typeof vi.fn>

beforeEach(() => {
  localStorage.setItem('ledgerline.phone', '9876543210')
  daily = new FakeDaily()
  fetchMock = vi.fn(async (url: unknown, init?: RequestInit) => {
    if (init?.method === 'DELETE') return new Response(null, { status: 204 })
    if (String(url).endsWith('/verdict')) return new Response('', { status: 202 })
    return new Response(JSON.stringify(SESSION), { status: 200 })
  })
  assign = vi.fn()
  vi.spyOn(window, 'location', 'get').mockReturnValue({
    ...window.location,
    search: '',
    assign,
  } as unknown as Location)
  vi.stubGlobal('Daily', daily)
  vi.stubGlobal('MediaStream', FakeMediaStream)
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => vi.unstubAllGlobals())

async function endedCall() {
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

describe('when a call is over', () => {
  it('keeps the console tabs on screen, during the call and after it', async () => {
    render(<App />)
    await userEvent.click(screen.getByRole('button', { name: /start the call/i }))
    await screen.findByTestId('state-pill')
    // Mid-call: the tabs are there, not hidden behind the board.
    expect(screen.getByRole('navigation', { name: /console/i })).toBeInTheDocument()

    await act(async () => {
      daily.last.emit('left-meeting', {})
    })
    expect(screen.getByRole('navigation', { name: /console/i })).toBeInTheDocument()
  })

  it('offers the three ways on from the ended screen', async () => {
    await endedCall()
    const after = screen.getByRole('navigation', { name: /after the call/i })
    expect(within(after).getByRole('button', { name: /back to start/i })).toBeInTheDocument()
    expect(within(after).getByRole('button', { name: /see this call/i })).toBeInTheDocument()
    expect(within(after).getByRole('button', { name: /your memory/i })).toBeInTheDocument()
  })

  it('tears the call down before going back to the start', async () => {
    await endedCall()
    const call = daily.last
    await userEvent.click(screen.getByRole('button', { name: /back to start/i }))

    // The call object is destroyed before the page goes anywhere, so no Daily connection is
    // left behind for the navigation to drop. (The server ends a live session itself; the
    // client only DELETEs one that never reached the room, which is why there is no DELETE
    // to assert on a call that ended normally.)
    await waitFor(() => expect(call.destroyed).toBeGreaterThan(0))
    expect(assign).toHaveBeenCalledWith('/')
  })

  it('sends "see this call" at the recording that was just made', async () => {
    await endedCall()
    await userEvent.click(screen.getByRole('button', { name: /see this call/i }))
    // The recorder's basename carries the voice- prefix; the session id may not.
    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith('/calls/voice-9876543210-20260914T100211Z'),
    )
  })

  it('sends "your memory" at the page for that number', async () => {
    await endedCall()
    await userEvent.click(screen.getByRole('button', { name: /your memory/i }))
    await waitFor(() => expect(assign).toHaveBeenCalledWith('/callers/9876543210'))
  })
})
