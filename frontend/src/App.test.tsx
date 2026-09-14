import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { FakeDaily, FakeMediaStream } from './call/testDouble'
import sampleJson from './protocol/sample.json'
import type { CardsMessage } from './protocol/types'

let daily: FakeDaily

const send = (data: unknown) =>
  act(() => {
    daily.last.emit('app-message', { data })
  })

const planned: CardsMessage = {
  ...(sampleJson as unknown as CardsMessage),
  v: 20,
  phase: 'plan',
  focus: 'plan',
  cards: [
    ...(sampleJson as unknown as CardsMessage).cards,
    {
      id: 'plan',
      title: 'Your plan',
      status: 'final',
      rows: [['Rent', '12,000', '5 Oct']],
      kv: { in: '48,000' },
      note: null,
    },
  ],
}

async function startCall() {
  render(<App />)
  await userEvent.click(screen.getByRole('button', { name: /start the call/i }))
  await screen.findByTestId('state-pill')
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
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({ room_url: 'https://x.daily.co/r', token: 't', session_id: 's' }),
        ),
    ),
  )
})

afterEach(() => vi.unstubAllGlobals())

describe('App', () => {
  it('shows a start screen with one button before the call', () => {
    render(<App />)
    expect(screen.getByRole('button', { name: /start the call/i })).toBeInTheDocument()
    expect(screen.queryByTestId('state-pill')).not.toBeInTheDocument()
  })

  it('renders the focused card and the question once cards arrive', async () => {
    await startCall()
    send({ label: 'rtvi-ai', type: 'bot-transcription', data: { text: 'What is your rent?' } })
    send({ label: 'rtvi-ai', type: 'bot-stopped-speaking' })
    send(sampleJson)
    expect(await screen.findByRole('heading', { name: /what is your rent/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Essentials' })).toBeInTheDocument()
  })

  it('never prints the same card twice when the bot focuses the plan', async () => {
    await startCall()
    send(planned)
    await waitFor(() => expect(screen.getAllByText('Your plan')).toHaveLength(1))
    // and the plan closes the panel, under the low point and the month it is answering,
    // rather than being dealt into the ledger as one more account
    const panel = document.querySelector('.panel')!
    expect(within(panel as HTMLElement).getByText('Your plan')).toBeInTheDocument()
    expect(document.querySelector('.stack .plan')).toBeNull()
  })

  it('shows a proposed action once, not again as a collapsed actions card', async () => {
    await startCall()
    send({
      ...planned,
      cards: planned.cards.map((c) =>
        c.id === 'plan' ? { ...c, rows: [['Defer', 'Streaming 1,200', 'to 6 Oct']] } : c,
      ),
    })
    await screen.findByText('Your plan')
    expect(screen.getAllByText('Defer')).toHaveLength(1)
    expect(screen.queryByRole('article', { name: 'Proposed' })).not.toBeInTheDocument()
  })

  it('keeps the actions card in the stack while there is no plan yet', async () => {
    await startCall()
    send(sampleJson)
    expect(await screen.findByRole('article', { name: 'Proposed' })).toBeInTheDocument()
  })

  it('keeps the missing chips out of the focus slot', async () => {
    await startCall()
    send({ ...(sampleJson as unknown as CardsMessage), focus: 'missing' })
    await screen.findByText('Electricity amount')
    expect(screen.getAllByText('Still need')).toHaveLength(1)
  })

  it('puts every account on the board at once, with no click needed to read one', async () => {
    await startCall()
    send(sampleJson)
    // The card the bot is working on is marked, not opened: a figure the person gave is a
    // figure they have to be able to see, or they cannot correct it.
    expect(await screen.findByRole('article', { name: 'Income' })).toBeInTheDocument()
    expect(screen.getByRole('article', { name: 'Essentials' })).toBeInTheDocument()
    expect(screen.getByRole('article', { name: 'Loans & cards' })).toBeInTheDocument()
    // Scoped to the card: the low-point working under the chart names the salary too.
    expect(
      within(screen.getByRole('article', { name: 'Income' })).getByText('Salary'),
    ).toBeInTheDocument()
    expect(screen.getByText('HDFC card')).toBeInTheDocument()

    const focused = document.querySelectorAll('[data-focused]')
    expect(focused).toHaveLength(1)
    expect(focused[0]).toHaveAttribute('data-card', 'essentials')
  })

  it('puts the user back on the start screen when the call never began', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('nope', { status: 500 })),
    )
    render(<App />)
    await userEvent.click(screen.getByRole('button', { name: /start the call/i }))
    await screen.findByRole('alert')
    // no voice bar for a call that does not exist
    expect(screen.queryByTestId('state-pill')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /end call/i })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /start the call/i })).toBeInTheDocument()
  })

  it('keeps the board when the call fails after cards have arrived', async () => {
    await startCall()
    send(planned)
    await screen.findByText('Your plan')
    act(() => {
      daily.last.emit('error', { errorMsg: 'Meeting has ended' })
    })
    expect(await screen.findByRole('alert')).toHaveTextContent(/meeting has ended/i)
    expect(screen.getByText('Your plan')).toBeInTheDocument()
    expect(screen.queryByTestId('state-pill')).not.toBeInTheDocument()
  })

  it('stops asking for confirmation once the bot reports the phase as done', async () => {
    await startCall()
    send({ ...planned, phase: 'plan' })
    expect(await screen.findByText(/does this work for you/i)).toBeInTheDocument()

    // the snapshot pushed after record_understanding(confirmed=True)
    send({ ...planned, v: planned.v + 1, phase: 'done' })
    await waitFor(() =>
      expect(screen.queryByText(/does this work for you/i)).not.toBeInTheDocument(),
    )
    expect(screen.getByText(/plan confirmed/i)).toBeInTheDocument()
    // the plan the user agreed to is still readable
    expect(screen.getByText('Your plan')).toBeInTheDocument()
  })

  it('does not go back to asking once the call has ended on a done snapshot', async () => {
    await startCall()
    send({ ...planned, phase: 'done' })
    await screen.findByText(/plan confirmed/i)

    act(() => {
      daily.last.emit('participant-left', { participant: { local: false } })
    })
    await screen.findByRole('button', { name: /start another call/i })
    expect(screen.queryByText(/does this work for you/i)).not.toBeInTheDocument()
    expect(screen.getByText(/plan confirmed/i)).toBeInTheDocument()
  })

  it('stops asking for confirmation when the user presses End mid-question', async () => {
    // The browser disconnects without the agent calling end_call, so the last snapshot the
    // page holds still says `confirm`.
    await startCall()
    send({ ...planned, phase: 'plan' })
    expect(await screen.findByText(/does this work for you/i)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /end call/i }))

    await waitFor(() =>
      expect(screen.queryByText(/does this work for you/i)).not.toBeInTheDocument(),
    )
    expect(screen.getByText(/call ended/i)).toBeInTheDocument()
    // and it must not pretend the user agreed
    expect(screen.queryByText(/plan confirmed/i)).not.toBeInTheDocument()
    expect(screen.getByText('Your plan')).toBeInTheDocument()
  })

  it('stops asking when the call dies on an error mid-question', async () => {
    await startCall()
    send({ ...planned, phase: 'plan' })
    await screen.findByText(/does this work for you/i)

    act(() => {
      daily.last.emit('error', { errorMsg: 'Meeting has ended' })
    })

    await waitFor(() =>
      expect(screen.queryByText(/does this work for you/i)).not.toBeInTheDocument(),
    )
    expect(screen.getByText(/call ended/i)).toBeInTheDocument()
  })

  it("does not carry the previous call's plan into the next one", async () => {
    await startCall()
    send({ ...planned, v: 4 })
    await screen.findByText('Your plan')

    act(() => {
      daily.last.emit('participant-left', { participant: { local: false } })
    })
    await userEvent.click(await screen.findByRole('button', { name: /start another call/i }))
    await screen.findByTestId('state-pill')

    // the old plan is gone the moment the new call starts
    expect(screen.queryByText('Your plan')).not.toBeInTheDocument()

    // and the new call's v=1 is accepted, not discarded as stale
    send({ ...(sampleJson as unknown as CardsMessage), v: 1 })
    expect(await screen.findByRole('heading', { name: 'Essentials' })).toBeInTheDocument()
  })

  it('surfaces a failed start and offers a retry', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('nope', { status: 500 })),
    )
    render(<App />)
    await userEvent.click(screen.getByRole('button', { name: /start the call/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/could not reach the server/i)
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument()
  })

  it('offers another call after the bot leaves, keeping the plan on screen', async () => {
    await startCall()
    send(planned)
    await screen.findByText('Your plan')
    act(() => {
      daily.last.emit('participant-left', { participant: { local: false } })
    })
    expect(await screen.findByRole('button', { name: /start another call/i })).toBeInTheDocument()
    expect(screen.getByText('Your plan')).toBeInTheDocument()
    expect(screen.queryByTestId('state-pill')).not.toBeInTheDocument()
  })
})
