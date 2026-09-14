/**
 * F6: a call that ended before it ever joined was presented as a board — empty, captioned
 * "Listening. Start whenever." even though the call was over, with a disabled "Start another
 * call" underneath. An attempt that never produced anything belongs on the start screen.
 */
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { FakeCall, FakeDaily, FakeMediaStream } from './call/testDouble'
import sampleJson from './protocol/sample.json'

const SESSION = { room_url: 'https://x.daily.co/r', token: 't', session_id: 'sess-1' }

let daily: FakeDaily

function gateNextJoin() {
  let open: () => void = () => {}
  const gate = new Promise<void>((resolve) => {
    open = resolve
  })
  const realCreate = daily.createCallObject.bind(daily)
  daily.createCallObject = (opts: unknown) => {
    daily.createCallObject = realCreate
    const call: FakeCall = realCreate(opts)
    call.emitsLeftOnLeave = false
    call.joinImpl = async () => {
      await gate
      return { local: {} }
    }
    return call
  }
  return { open }
}

beforeEach(() => {
  // The start screen asks for a phone number; a returning caller's is already in the field,
  // which is the state every test below is about.
  localStorage.setItem('ledgerline.phone', '9876543210')
  daily = new FakeDaily()
  vi.stubGlobal('Daily', daily)
  vi.stubGlobal('MediaStream', FakeMediaStream)
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_i: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'DELETE') return new Response(null, { status: 204 })
      return new Response(JSON.stringify(SESSION), { status: 201 })
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

describe('a call that ended before it ever joined', () => {
  it('stays on the start screen instead of showing an empty board', async () => {
    const { open } = gateNextJoin()
    render(<App />)
    await userEvent.click(screen.getByRole('button', { name: /start the call/i }))
    await waitFor(() => expect(daily.calls).toHaveLength(1))

    await act(async () => {
      daily.last.emit('participant-left', { participant: { local: false } })
    })

    expect(
      screen.getByRole('heading', { name: /talk through your next thirty days/i }),
    ).toBeInTheDocument()
    expect(screen.queryByText(/listening\. start whenever/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /start another call/i })).not.toBeInTheDocument()
    expect(screen.queryByTestId('state-pill')).not.toBeInTheDocument()

    await act(async () => {
      open()
    })
  })

  it("keeps the handler's message on screen there", async () => {
    const { open } = gateNextJoin()
    render(<App />)
    await userEvent.click(screen.getByRole('button', { name: /start the call/i }))
    await waitFor(() => expect(daily.calls).toHaveLength(1))

    await act(async () => {
      daily.last.emit('camera-error', { error: { type: 'not-found' } })
    })

    expect(await screen.findByRole('alert')).toHaveTextContent(/no microphone found/i)
    expect(
      screen.getByRole('heading', { name: /talk through your next thirty days/i }),
    ).toBeInTheDocument()

    await act(async () => {
      open()
    })
  })
})

describe('a call that did go live', () => {
  it('returns to the start screen if it ended without ever sending a card', async () => {
    // Joining is not the same as producing something to read. An empty board captioned
    // "Listening. Start whenever." after the call is over is the same lie either way.
    render(<App />)
    await userEvent.click(screen.getByRole('button', { name: /start the call/i }))
    await screen.findByTestId('state-pill')

    act(() => {
      daily.last.emit('participant-left', { participant: { local: false } })
    })

    expect(
      await screen.findByRole('heading', { name: /talk through your next thirty days/i }),
    ).toBeInTheDocument()
    expect(screen.queryByText(/listening\. start whenever/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /start another call/i })).not.toBeInTheDocument()
  })

  it('keeps the board once a card has arrived', async () => {
    render(<App />)
    await userEvent.click(screen.getByRole('button', { name: /start the call/i }))
    await screen.findByTestId('state-pill')

    act(() => {
      daily.last.emit('app-message', { data: sampleJson })
      daily.last.emit('participant-left', { participant: { local: false } })
    })

    expect(await screen.findByRole('button', { name: /start another call/i })).toBeInTheDocument()
    expect(
      screen.queryByRole('heading', { name: /talk through your next thirty days/i }),
    ).not.toBeInTheDocument()
  })

  it('keeps the board when a snapshot arrived, however it ended', async () => {
    const { open } = gateNextJoin()
    render(<App />)
    await userEvent.click(screen.getByRole('button', { name: /start the call/i }))
    await waitFor(() => expect(daily.calls).toHaveLength(1))

    await act(async () => {
      daily.last.emit('app-message', { data: sampleJson })
      daily.last.emit('participant-left', { participant: { local: false } })
    })

    expect(await screen.findByRole('heading', { name: 'Essentials' })).toBeInTheDocument()
    expect(
      screen.queryByRole('heading', { name: /talk through your next thirty days/i }),
    ).not.toBeInTheDocument()

    await act(async () => {
      open()
    })
  })
})
