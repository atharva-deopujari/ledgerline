/**
 * F6: the script said "twenty-seven seven out" for 27,700 — a number no one says aloud, and
 * one the card beside it did not show.
 *
 * This walks the journey the way a listener hears it: for each spoken line, every money
 * amount in it must appear somewhere in the snapshot that is on screen at the time. The
 * words are parsed rather than compared against a second list of numbers, so a cue cannot
 * drift from the fixture without this failing.
 */
import { describe, expect, it } from 'vitest'
import snapshots from './snapshots.json'
import { MOCK_SCRIPT } from './script'

const UNITS: Record<string, number> = {
  zero: 0,
  one: 1,
  two: 2,
  three: 3,
  four: 4,
  five: 5,
  six: 6,
  seven: 7,
  eight: 8,
  nine: 9,
  ten: 10,
  eleven: 11,
  twelve: 12,
  thirteen: 13,
  fourteen: 14,
  fifteen: 15,
  sixteen: 16,
  seventeen: 17,
  eighteen: 18,
  nineteen: 19,
  twenty: 20,
  thirty: 30,
  forty: 40,
  fifty: 50,
  sixty: 60,
  seventy: 70,
  eighty: 80,
  ninety: 90,
}
const SCALES: Record<string, number> = { hundred: 100, thousand: 1_000, lakh: 100_000 }

/** Spoken amounts here are thousands; anything smaller is a day count or an ordinal. */
const AMOUNT_FLOOR = 1_000

const isNumberWord = (w: string) => w in UNITS || w in SCALES

/** "twenty-seven thousand seven hundred" -> 27700 */
function runToNumber(words: string[]): number {
  let total = 0
  let chunk = 0
  for (const word of words) {
    if (word in UNITS) {
      chunk += UNITS[word]
    } else if (word === 'hundred') {
      chunk = (chunk || 1) * 100
    } else {
      total += (chunk || 1) * SCALES[word]
      chunk = 0
    }
  }
  return total + chunk
}

/** Every maximal run of number words in a sentence, as numbers. */
function spokenNumbers(text: string): number[] {
  const words = text
    .toLowerCase()
    .replace(/[^a-z\s-]/g, ' ')
    .split(/[\s-]+/)
    .filter(Boolean)
  const found: number[] = []
  let run: string[] = []
  for (const word of [...words, '.']) {
    if (isNumberWord(word)) {
      run.push(word)
    } else if (run.length > 0) {
      found.push(runToNumber(run))
      run = []
    }
  }
  return found
}

/** Every number written anywhere in a snapshot: row values, kv, notes. */
function numbersIn(snapshot: unknown): Set<number> {
  const out = new Set<number>()
  for (const match of JSON.stringify(snapshot).matchAll(/\d[\d,]*/g)) {
    const value = Number(match[0].replace(/,/g, ''))
    if (Number.isFinite(value)) out.add(value)
  }
  return out
}

type Cue = { label: string; type: string; data?: { text?: string } }
const isCards = (d: unknown): d is { type: string } =>
  typeof d === 'object' && d !== null && (d as { type?: string }).type === 'cards'
const isSpoken = (d: unknown): d is Cue =>
  typeof d === 'object' &&
  d !== null &&
  (d as Cue).label === 'rtvi-ai' &&
  (d as Cue).type === 'bot-transcription'

describe('the spoken journey', () => {
  it('speaks only amounts the snapshot on screen actually shows', () => {
    let onScreen: Set<number> = new Set()
    const checked: number[] = []

    for (const event of MOCK_SCRIPT) {
      if (isCards(event.data)) {
        onScreen = numbersIn(event.data)
        continue
      }
      if (!isSpoken(event.data)) continue
      for (const amount of spokenNumbers(event.data.data?.text ?? '')) {
        if (amount < AMOUNT_FLOOR) continue
        expect(
          onScreen.has(amount),
          `spoken ${amount} is not on the snapshot showing at that moment`,
        ).toBe(true)
        checked.push(amount)
      }
    }

    // Guard against the check silently passing because it found nothing to check.
    expect(checked.length).toBeGreaterThanOrEqual(4)
  })

  it('parses the amounts this journey actually speaks', () => {
    expect(spokenNumbers('twenty-seven thousand seven hundred out')).toEqual([27700])
    expect(spokenNumbers('Seventy-two thousand in')).toEqual([72000])
    expect(spokenNumbers('forty-two thousand for salary, then forty-five thousand')).toEqual([
      42000, 45000,
    ])
    expect(spokenNumbers('did you mean twelve thousand?')).toEqual([12000])
    // day counts and ordinals stay below the floor, or are not cardinal words at all
    expect(spokenNumbers('the next thirty days')).toEqual([30])
    expect(spokenNumbers('due on the twentieth')).toEqual([])
  })

  it('would have caught the reported defect', () => {
    // "twenty-seven seven" parses as 27 + 7, not 27,700 — and neither is on the card.
    const ready = numbersIn(snapshots.ready)
    expect(ready.has(27700)).toBe(true)
    for (const wrong of spokenNumbers('twenty-seven seven out')) {
      expect(wrong).not.toBe(27700)
    }
  })
})
