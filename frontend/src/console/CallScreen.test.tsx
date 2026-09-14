/**
 * One recording, read the way a person would: what was said, what the coach did under each
 * of its turns, how it was judged, and the state it ended in.
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import sample from '../protocol/call.sample.json'
import { CallScreen } from './CallScreen'

const serve = (body: unknown, status = 200) =>
  vi.fn(async () => new Response(JSON.stringify(body), { status }))

beforeEach(() => vi.stubGlobal('fetch', serve(sample)))
afterEach(() => vi.unstubAllGlobals())

const show = async (body: unknown = sample) => {
  vi.stubGlobal('fetch', serve(body))
  render(<CallScreen id="voice-9869101897-20260914T100211Z" />)
  return await screen.findByRole('region', { name: /transcript/i })
}

describe('the Call screen', () => {
  it('asks for that recording by id', async () => {
    const fetchMock = serve(sample)
    vi.stubGlobal('fetch', fetchMock)
    render(<CallScreen id="voice-1" />)
    await screen.findByRole('region', { name: /transcript/i })
    expect(fetchMock).toHaveBeenCalledWith('/api/review/calls/voice-1')
  })

  it('tells the two speakers apart', async () => {
    const transcript = await show()
    const turns = within(transcript).getAllByRole('article')
    expect(turns).toHaveLength(3)
    expect(turns[0]).toHaveTextContent('Coach')
    expect(turns[1]).toHaveTextContent('Person')
    expect(turns[1]).toHaveTextContent('Around 60,000 in the bank')
  })

  it('keeps the tool calls of a turn under it, collapsed until asked for', async () => {
    const transcript = await show()
    expect(within(transcript).getByText(/1 tool call/i)).toBeInTheDocument()
    // Collapsed: the result is in the DOM but not shown until the disclosure is opened.
    expect(screen.getByText(/bank balance 60,000, noted/i)).not.toBeVisible()

    await userEvent.click(within(transcript).getByText(/1 tool call/i))
    expect(screen.getByText(/bank balance 60,000, noted/i)).toBeVisible()
    expect(screen.getByText(/"amount": 60000/)).toBeInTheDocument()
  })

  it('shows the verdict for the call', async () => {
    await show()
    expect(screen.getByLabelText(/call review/i)).toBeInTheDocument()
  })

  it('prints the final state as it was saved', async () => {
    await show()
    expect(screen.getByText(/"opening_balance": "60000.00"/)).toBeInTheDocument()
  })

  it('survives a recording with turns that are missing pieces', async () => {
    // The recorder owns this shape; a screen that falls over on it is the screen's fault.
    const ragged = {
      call: { session_id: 'x', turns: [{ role: 'user' }, { text: 'no role' }, {}] },
      verdict: sample.verdict,
    }
    const transcript = await show(ragged)
    expect(within(transcript).getAllByRole('article')).toHaveLength(3)
  })

  it('says so when there is no such recording', async () => {
    vi.stubGlobal('fetch', serve(null, 404))
    render(<CallScreen id="nope" />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/no recording with that name/i)
  })
})
