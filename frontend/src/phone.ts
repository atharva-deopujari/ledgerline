/**
 * The one field on the start screen. The server validates the number too and answers 422,
 * so this exists to tell the person before the call is attempted, not to be the only guard.
 */

const STORAGE_KEY = 'ledgerline.phone'

/** Ten digits as dialled locally, or E.164: a plus, a country digit, 8 to 15 digits total. */
const TEN_DIGITS = /^\d{10}$/
const E164 = /^\+[1-9]\d{7,14}$/

/**
 * The number as the server should see it, or `null` if it is not one. Spaces, dashes and
 * brackets are how people write a phone number and carry no meaning, so they are dropped.
 */
export function normalisePhone(input: string): string | null {
  const trimmed = input.replace(/[\s\-().]/g, '')
  if (TEN_DIGITS.test(trimmed) || E164.test(trimmed)) return trimmed
  return null
}

/** The number from the last visit, or `''`. Never a value the server would refuse. */
export function readRememberedPhone(): string {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    return (stored && normalisePhone(stored)) || ''
  } catch {
    // A private window can throw rather than return null; the field just starts empty.
    return ''
  }
}

export function rememberPhone(phone: string): void {
  const valid = normalisePhone(phone)
  if (!valid) return
  try {
    localStorage.setItem(STORAGE_KEY, valid)
  } catch {
    // Storage being unavailable costs the person one retype next time, nothing more.
  }
}

/** After a person asks to be forgotten, the browser forgets them too. */
export function forgetRememberedPhone(): void {
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    // Nothing was stored in the first place.
  }
}
