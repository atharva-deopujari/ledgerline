/**
 * The start screen asks for a phone number and nothing else. The number is the person's id
 * for the whole system — the Postgres row, the recording filename and the Langfuse trace all
 * read as one call of one person — so it is checked here before a call is attempted, and
 * remembered so a returning caller does not retype it.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { FakeDaily, FakeMediaStream } from './call/testDouble'

let daily: FakeDaily
let fetchMock: ReturnType<typeof vi.fn>

const postedBodies = () =>
  fetchMock.mock.calls
    .filter(([, init]) => (init as RequestInit | undefined)?.method === 'POST')
    .map(([, init]) => JSON.parse(String((init as RequestInit).body)) as { phone: string })

const field = () => screen.getByLabelText(/phone/i)
const startButton = () => screen.getByRole('button', { name: /start the call/i })

beforeEach(() => {
  localStorage.clear()
  daily = new FakeDaily()
  fetchMock = vi.fn(
    async () =>
      new Response(
        JSON.stringify({ room_url: 'https://x.daily.co/r', token: 't', session_id: 's' }),
      ),
  )
  vi.stubGlobal('Daily', daily)
  vi.stubGlobal('MediaStream', FakeMediaStream)
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => vi.unstubAllGlobals())

describe('the phone number on the start screen', () => {
  it('is the only field, and starts empty for a first-time caller', () => {
    render(<App />)
    expect(field()).toHaveValue('')
    expect(screen.getAllByRole('textbox')).toHaveLength(1)
  })

  it('rides in the POST body, normalised, when the call starts', async () => {
    render(<App />)
    await userEvent.type(field(), '98765 43210')
    await userEvent.click(startButton())

    await waitFor(() => expect(postedBodies()).toEqual([{ phone: '9876543210' }]))
  })

  it('takes E.164 as well as ten digits', async () => {
    render(<App />)
    await userEvent.type(field(), '+91 98765 43210')
    await userEvent.click(startButton())

    await waitFor(() => expect(postedBodies()).toEqual([{ phone: '+919876543210' }]))
  })

  it('never posts a number the server would refuse, and says what it wants instead', async () => {
    render(<App />)
    await userEvent.type(field(), '98765')
    await userEvent.click(startButton())

    expect(await screen.findByRole('alert')).toHaveTextContent(/ten digits/i)
    expect(postedBodies()).toEqual([])
    expect(daily.calls).toHaveLength(0)
  })

  it('remembers the number for the next visit', async () => {
    const first = render(<App />)
    await userEvent.type(field(), '9876543210')
    await userEvent.click(startButton())
    await waitFor(() => expect(postedBodies()).toHaveLength(1))
    first.unmount()

    render(<App />)
    expect(field()).toHaveValue('9876543210')
  })

  it('remembers nothing until a call is actually started', async () => {
    const first = render(<App />)
    await userEvent.type(field(), '9876543210')
    first.unmount()

    render(<App />)
    expect(field()).toHaveValue('')
  })
})
