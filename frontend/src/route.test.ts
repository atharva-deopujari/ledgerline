/**
 * Two pages, no router: the call board, and one memory page per phone. `?mock=1` already
 * reads the URL for a decision like this, so the pathname is read the same way.
 */
import { describe, expect, it } from 'vitest'
import { routeFor } from './route'

describe('routeFor', () => {
  it('sends the root at the call board', () => {
    expect(routeFor('/')).toEqual({ name: 'call' })
    expect(routeFor('')).toEqual({ name: 'call' })
  })

  it('reads the phone out of a review path', () => {
    expect(routeFor('/review/users/9876543210')).toEqual({
      name: 'review',
      phone: '9876543210',
    })
  })

  it('decodes an E.164 number, whose plus is escaped in a URL', () => {
    expect(routeFor('/review/users/%2B919876543210')).toEqual({
      name: 'review',
      phone: '+919876543210',
    })
  })

  it('tolerates a trailing slash', () => {
    expect(routeFor('/review/users/9876543210/')).toEqual({
      name: 'review',
      phone: '9876543210',
    })
  })

  it('refuses a number the rest of the app would refuse, rather than asking about it', () => {
    // The page would otherwise fetch /api/review/users/nonsense and show its 404 as a bug.
    expect(routeFor('/review/users/nonsense')).toEqual({ name: 'call' })
    expect(routeFor('/review/users/98765')).toEqual({ name: 'call' })
    expect(routeFor('/review/users/')).toEqual({ name: 'call' })
  })

  it('sends anything else at the board, since the server serves the app for any path', () => {
    expect(routeFor('/somewhere/else')).toEqual({ name: 'call' })
  })
})
