/**
 * The only destructive control in the product. It deletes every fact remembered about a
 * phone number and cannot be undone, so it asks once, in the page, before it fires.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ForgetButton } from './ForgetButton'

let fetchMock: ReturnType<typeof vi.fn>

const deletes = () =>
  (fetchMock.mock.calls as unknown[][])
    .filter(([, init]) => (init as RequestInit | undefined)?.method === 'DELETE')
    .map(([url]) => String(url))

beforeEach(() => {
  fetchMock = vi.fn(async () => new Response(null, { status: 204 }))
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => vi.unstubAllGlobals())

const ask = async () => {
  await userEvent.click(screen.getByRole('button', { name: /forget/i }))
}

describe('ForgetButton', () => {
  it('asks before it deletes anything', async () => {
    render(<ForgetButton phone="9876543210" />)
    await ask()

    expect(screen.getByText(/cannot be undone/i)).toBeInTheDocument()
    expect(deletes()).toEqual([])
  })

  it('lets the person back out, with nothing sent', async () => {
    render(<ForgetButton phone="9876543210" />)
    await ask()
    await userEvent.click(screen.getByRole('button', { name: /cancel/i }))

    expect(screen.queryByText(/cannot be undone/i)).not.toBeInTheDocument()
    expect(deletes()).toEqual([])
  })

  it('deletes the number once it is confirmed, and says it is done', async () => {
    render(<ForgetButton phone="9876543210" />)
    await ask()
    await userEvent.click(screen.getByRole('button', { name: /yes, forget/i }))

    await waitFor(() => expect(deletes()).toEqual(['/api/users/9876543210']))
    expect(await screen.findByText(/nothing is kept/i)).toBeInTheDocument()
    // Nothing left to press: the number is gone.
    expect(screen.queryByRole('button', { name: /forget/i })).not.toBeInTheDocument()
  })

  it('escapes the number, so an E.164 plus survives the URL', async () => {
    render(<ForgetButton phone="+919876543210" />)
    await ask()
    await userEvent.click(screen.getByRole('button', { name: /yes, forget/i }))

    await waitFor(() => expect(deletes()).toEqual(['/api/users/%2B919876543210']))
  })

  it('says when it could not, and leaves the control there to try again', async () => {
    fetchMock.mockImplementation(async () => new Response(null, { status: 500 }))
    render(<ForgetButton phone="9876543210" />)
    await ask()
    await userEvent.click(screen.getByRole('button', { name: /yes, forget/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not/i)
    expect(screen.getByRole('button', { name: /forget/i })).toBeEnabled()
  })

  it('offers nothing when there is no number to forget', () => {
    const { container } = render(<ForgetButton phone="" />)
    expect(container).toBeEmptyDOMElement()
  })
})
