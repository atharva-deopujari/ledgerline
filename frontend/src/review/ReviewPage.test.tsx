/**
 * Langfuse is the review screen for calls; this is the one thing it cannot show — what the
 * system remembers about a person, and their own control to delete it.
 */
import { render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { UserReview } from '../protocol/review'
import sample from '../protocol/review.sample.json'
import { ReviewPage } from './ReviewPage'

const REVIEW = sample as UserReview

const serve = (review: UserReview) =>
  vi.fn(async (url: unknown) =>
    String(url).includes('/api/review/')
      ? new Response(JSON.stringify(review), { status: 200 })
      : new Response(null, { status: 204 }),
  )

beforeEach(() => vi.stubGlobal('fetch', serve(REVIEW)))
afterEach(() => vi.unstubAllGlobals())

const show = async (review: UserReview = REVIEW) => {
  vi.stubGlobal('fetch', serve(review))
  render(<ReviewPage phone={review.phone} />)
  return await screen.findByTestId('review-active')
}

describe('the memory page', () => {
  it('names whose memory it is', async () => {
    await show()
    expect(screen.getByText('9876543210')).toBeInTheDocument()
  })

  it('lists the active facts as a ledger, with the figures grouped', async () => {
    const active = await show()
    expect(within(active).getByText(/salary/i)).toBeInTheDocument()
    expect(within(active).getByText('45,000')).toBeInTheDocument()
    expect(within(active).getByText('14,000')).toBeInTheDocument()
    // The superseded figure is history, not an active fact.
    expect(within(active).queryByText('12,000')).not.toBeInTheDocument()
  })

  it('strikes the superseded figure and dates it', async () => {
    await show()
    const history = screen.getByTestId('review-history')
    const struck = within(history).getByText('12,000')
    expect(struck.tagName).toBe('S')
    expect(struck).toHaveAttribute('data-retired', '12,000')
    expect(struck).toHaveAttribute('aria-hidden', 'true')
    expect(within(history).getByText(/14 Aug 2026/)).toBeInTheDocument()
  })

  it('reads a tombstone as ended rather than as a figure that went missing', async () => {
    await show()
    const history = screen.getByTestId('review-history')
    const gym = within(history).getByText(/gym/i).closest('li')
    expect(within(gym as HTMLElement).getByText(/ended/i)).toBeInTheDocument()
  })

  it('shows what the person said in words, with the turn it came from', async () => {
    await show()
    const notes = screen.getByTestId('review-notes')
    expect(within(notes).getByText(/does not want to ask the landlord/i)).toBeInTheDocument()
    expect(within(notes).getByText(/turn 9/i)).toBeInTheDocument()
  })

  it('lists the calls, linking only the ones with a trace', async () => {
    await show()
    const calls = screen.getByTestId('review-calls')
    expect(within(calls).getAllByRole('listitem')).toHaveLength(2)
    expect(within(calls).getAllByRole('link')).toHaveLength(1)
  })

  it('says the memory could not be read, which is not the same as no history', async () => {
    await show({ ...REVIEW, memory_read: false, active: [], history: [], notes: [] })
    expect(screen.getByText(/could not be read/i)).toBeInTheDocument()
    expect(screen.queryByText(/no history/i)).not.toBeInTheDocument()
  })

  it('renders an empty call list without complaint', async () => {
    await show({ ...REVIEW, calls: [] })
    expect(screen.getByTestId('review-calls')).toBeEmptyDOMElement()
  })

  it('offers the person their own delete control', async () => {
    await show()
    expect(screen.getByRole('button', { name: /forget/i })).toBeInTheDocument()
  })

  it('says so when the page itself could not be loaded', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(null, { status: 500 })),
    )
    render(<ReviewPage phone="9876543210" />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/could not/i)
  })
})

describe('calling as a caller', () => {
  it('writes the number where the start form reads it, then goes to the form', async () => {
    localStorage.clear()
    const assign = vi.fn()
    vi.spyOn(window, 'location', 'get').mockReturnValue({
      ...window.location,
      assign,
    } as unknown as Location)

    await show()
    screen.getByRole('button', { name: /call as this number/i }).click()

    expect(localStorage.getItem('ledgerline.phone')).toBe(REVIEW.phone)
    expect(assign).toHaveBeenCalledWith('/')
  })
})
