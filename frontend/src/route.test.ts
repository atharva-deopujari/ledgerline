/**
 * Two clicks from `/` to anything, and no router: the path is read, and a path that could not
 * name a real caller or recording falls back to the console's front page rather than asking
 * the server about nonsense.
 */
import { describe, expect, it, vi } from 'vitest'
import { routeFor, to } from './route'

describe('routeFor', () => {
  it('sends the root at the new-call screen', () => {
    expect(routeFor('/')).toEqual({ name: 'call' })
    expect(routeFor('')).toEqual({ name: 'call' })
  })

  it('reads the flat tabs', () => {
    expect(routeFor('/callers')).toEqual({ name: 'callers' })
    expect(routeFor('/calls')).toEqual({ name: 'calls' })
    expect(routeFor('/evals')).toEqual({ name: 'evals' })
    expect(routeFor('/report')).toEqual({ name: 'report' })
    expect(routeFor('/report/')).toEqual({ name: 'report' })
  })

  it('reads the phone out of a caller path', () => {
    expect(routeFor('/callers/9876543210')).toEqual({ name: 'caller', phone: '9876543210' })
    expect(routeFor('/callers/%2B919876543210')).toEqual({
      name: 'caller',
      phone: '+919876543210',
    })
  })

  it('still answers the review path the HLD published for that page', () => {
    expect(routeFor('/review/users/9876543210')).toEqual({ name: 'caller', phone: '9876543210' })
  })

  it('refuses a caller whose number is not a number', () => {
    expect(routeFor('/callers/nonsense')).toEqual({ name: 'call' })
    expect(routeFor('/callers/98765')).toEqual({ name: 'call' })
    // A trailing slash on the tab is the tab, not a caller with an empty number.
    expect(routeFor('/callers/')).toEqual({ name: 'callers' })
  })

  it('reads a recording id, which is a file basename', () => {
    expect(routeFor('/calls/voice-9869101897-20260913T194053Z')).toEqual({
      name: 'recording',
      id: 'voice-9869101897-20260913T194053Z',
    })
  })

  it('refuses an id that could climb out of the recordings directory', () => {
    // The server guards this too; the page simply never asks.
    expect(routeFor('/calls/..%2F..%2Fetc%2Fpasswd')).toEqual({ name: 'call' })
    expect(routeFor('/calls/../secrets')).toEqual({ name: 'call' })
    expect(routeFor('/calls/.hidden')).toEqual({ name: 'call' })
  })

  it('sends anything else at the front page, since the server serves the app for any path', () => {
    expect(routeFor('/somewhere/else')).toEqual({ name: 'call' })
  })
})

describe('to', () => {
  it('leaves a path alone in the ordinary case', () => {
    expect(to('/callers')).toBe('/callers')
  })

  it('carries ?mock=1 across a navigation, so the demo stays the demo', () => {
    const search = vi.spyOn(window, 'location', 'get')
    search.mockReturnValue({ ...window.location, search: '?mock=1' } as unknown as Location)
    expect(to('/calls/voice-1')).toBe('/calls/voice-1?mock=1')
    search.mockRestore()
  })
})
