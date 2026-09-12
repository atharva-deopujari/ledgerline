/**
 * F3: after a terminal event during a pending join the reducer shows ended/error, so the
 * Start and Try again controls were enabled again — while `start()` still refused silently
 * until the original join settled or hit its 20 s timeout. Pressing an enabled button and
 * getting nothing is the worst of both. The control is disabled and says why instead.
 */
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { FakeCall, FakeDaily, FakeMediaStream } from './call/testDouble'

const SESSION = { room_url: 'https://x.daily.co/r', token: 't', session_id: 'sess-1' }

let daily: FakeDaily
let starts: number

function stubFetch() {
  starts = 0
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'DELETE') return new Response(null, { status: 204 })
      starts += 1
      return new Response(JSON.stringify(SESSION), { status: 201 })
    }),
  )
}

/** The next call object hangs in join() until `open()` is called. */
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
  daily = new FakeDaily()
  vi.stubGlobal('Daily', daily)
  vi.stubGlobal('MediaStream', FakeMediaStream)
  stubFetch()
})
afterEach(() => vi.unstubAllGlobals())

const startControl = () =>
  screen.getByRole('button', { name: /start the call|starting|finishing the last attempt/i })

describe('the interval between a terminal event and the join settling', () => {
  it('disables the Start control and says what it is waiting for', async () => {
    const { open } = gateNextJoin()
    render(<App />)
    await userEvent.click(screen.getByRole('button', { name: /start the call/i }))
    await waitFor(() => expect(daily.calls).toHaveLength(1))

    await act(async () => {
      daily.last.emit('error', { errorMsg: 'Meeting has ended' })
    })

    // The banner explains what went wrong...
    expect(await screen.findByRole('alert')).toHaveTextContent(/meeting has ended/i)
    // ...and every way back in is visibly unavailable, not silently inert.
    expect(startControl()).toBeDisabled()
    expect(startControl()).toHaveTextContent(/finishing the last attempt/i)
    expect(screen.getByRole('button', { name: /try again/i })).toBeDisabled()

    await act(async () => {
      open()
    })
  })

  it('re-enables once the attempt settles, and one press starts exactly one call', async () => {
    const { open } = gateNextJoin()
    render(<App />)
    await userEvent.click(screen.getByRole('button', { name: /start the call/i }))
    await waitFor(() => expect(daily.calls).toHaveLength(1))
    await act(async () => {
      daily.last.emit('error', { errorMsg: 'Meeting has ended' })
    })
    expect(startControl()).toBeDisabled()

    await act(async () => {
      open()
    })

    await waitFor(() => expect(startControl()).toBeEnabled())
    expect(startControl()).toHaveTextContent(/start the call/i)
    expect(starts).toBe(1)

    await userEvent.click(startControl())
    await waitFor(() => expect(starts).toBe(2))
    expect(daily.calls).toHaveLength(2)
  })

  it('a press while disabled does nothing at all, including no POST', async () => {
    const { open } = gateNextJoin()
    render(<App />)
    await userEvent.click(screen.getByRole('button', { name: /start the call/i }))
    await waitFor(() => expect(daily.calls).toHaveLength(1))
    await act(async () => {
      daily.last.emit('participant-left', { participant: { local: false } })
    })

    await userEvent.click(startControl())
    expect(starts).toBe(1)
    expect(daily.calls).toHaveLength(1)

    await act(async () => {
      open()
    })
  })
})

describe('the ordinary path is unchanged', () => {
  it('shows Starting while connecting, then the live call', async () => {
    const { open } = gateNextJoin()
    render(<App />)
    await userEvent.click(screen.getByRole('button', { name: /start the call/i }))

    await waitFor(() => expect(startControl()).toHaveTextContent(/starting/i))
    expect(startControl()).toBeDisabled()

    await act(async () => {
      open()
    })
    await screen.findByTestId('state-pill')
  })
})
