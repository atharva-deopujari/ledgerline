import { describe, expect, it, beforeEach, vi } from 'vitest'
import { forgetRememberedPhone, normalisePhone, readRememberedPhone, rememberPhone } from './phone'

describe('normalisePhone', () => {
  it('accepts ten digits and returns them bare', () => {
    expect(normalisePhone('9876543210')).toBe('9876543210')
  })

  it('accepts the separators people actually type', () => {
    expect(normalisePhone(' 98765 43210 ')).toBe('9876543210')
    expect(normalisePhone('(987) 654-3210')).toBe('9876543210')
  })

  it('accepts E.164 and keeps the plus', () => {
    expect(normalisePhone('+919876543210')).toBe('+919876543210')
    expect(normalisePhone('+91 98765 43210')).toBe('+919876543210')
  })

  it('refuses anything else', () => {
    // The server validates too and answers 422; this is only so the person is told first.
    expect(normalisePhone('')).toBeNull()
    expect(normalisePhone('98765')).toBeNull()
    expect(normalisePhone('98765432101')).toBeNull()
    expect(normalisePhone('+0123456789')).toBeNull()
    expect(normalisePhone('+1234567')).toBeNull()
    expect(normalisePhone('+1234567890123456')).toBeNull()
    expect(normalisePhone('98765abcde')).toBeNull()
  })
})

describe('remembering it for the next visit', () => {
  beforeEach(() => localStorage.clear())

  it('round-trips the normalised number', () => {
    rememberPhone('+91 98765 43210')
    expect(readRememberedPhone()).toBe('+919876543210')
  })

  it('never stores a number the server would refuse', () => {
    rememberPhone('98765')
    expect(readRememberedPhone()).toBe('')
  })

  it('reads nothing when the browser refuses storage', () => {
    // Private windows throw on access rather than returning null.
    const get = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied')
    })
    const set = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('denied')
    })
    expect(readRememberedPhone()).toBe('')
    expect(() => rememberPhone('9876543210')).not.toThrow()
    get.mockRestore()
    set.mockRestore()
  })

  it('forgets the number when the person asks to be forgotten', () => {
    rememberPhone('9876543210')
    forgetRememberedPhone()
    expect(readRememberedPhone()).toBe('')
  })

  it('ignores a stored value that is no longer valid', () => {
    localStorage.setItem('ledgerline.phone', 'not a number')
    expect(readRememberedPhone()).toBe('')
  })
})
