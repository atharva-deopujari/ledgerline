/** Shared row/value shaping. The bot sends display strings; we only split off its hedges. */
import { PROVISIONAL_SUFFIX } from '../protocol/markers'
import type { CardId, CardStatus, Phase, SpeakState } from '../protocol/types'

/**
 * The three words across the masthead. `done` is deliberately not a fourth: it is not
 * another step, it is every step finished, so it marks all three and leaves none current.
 */
export const PHASE_ORDER: Phase[] = ['gathering', 'ready', 'plan']

export const PHASE_LABEL: Record<Phase, string> = {
  gathering: 'gathering',
  ready: 'ready',
  plan: 'plan',
  done: 'done',
}

/**
 * Cards with a place of their own on the board, so the ledger stack must not print them a
 * second time: `summary` is the totals bar, `plan` and `actions` the panel, `missing` the
 * chips, `timeline` the chart.
 */
export const CARDS_SHOWN_ELSEWHERE: CardId[] = ['missing', 'plan', 'timeline', 'summary']

/**
 * The status word a card shows beside its title. The enum is the contract; these are the
 * same five states said in the board's own voice, and each is still a word rather than a
 * colour, so the colour only ever seconds what is already written.
 *
 * Nothing here reads the figures: `warn` says attention is needed, not *why* — the card's
 * own note is where the backend explains itself.
 */
export const STATUS_LABEL: Record<CardStatus, string> = {
  ok: 'confirmed',
  warn: 'needs attention',
  provisional: 'not confirmed',
  final: 'settled',
  blocked: 'blocked',
  // Not an error: nothing on the card is wrong, it is last call's figure waiting to be
  // confirmed. The word says where it came from rather than what is wrong with it.
  carried: 'from last call',
}

/** What the voice bar says the bot is doing. */
export const SPEAK_LABEL: Record<SpeakState, string> = {
  idle: 'not speaking',
  listening: 'listening',
  speaking: 'speaking',
  thinking: 'working it out',
}

/**
 * The summary card's keys, in the order the totals bar prints them. `lowest` is not here:
 * it is the big figure on the panel, and printing it twice would read as two findings.
 * Anything the backend adds later is unknown to this map and falls through to its own key,
 * so a new field appears on the board rather than disappearing from it.
 */
export const TOTAL_LABEL: Record<string, string> = {
  in: 'In',
  out: 'Out',
  unpaid: 'Unpaid if nothing changes',
}

/** Shown on the panel, not in the totals bar. */
export const PANEL_KEYS = ['lowest']

/** Backend field names read as words: `unpaid_total` is two of them. */
export const keyAsWords = (key: string): string => key.replace(/_/g, ' ')

/**
 * A value the bot is not sure about arrives as "12 ?". Split the mark off so it can be
 * rendered quietly instead of reading as part of the number.
 */
export function splitProvisional(value: string): { value: string; uncertain: boolean } {
  if (value.endsWith(PROVISIONAL_SUFFIX)) {
    return { value: value.slice(0, -PROVISIONAL_SUFFIX.length), uncertain: true }
  }
  return { value, uncertain: false }
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "2026-10-05" -> "5 Oct". Parsed by hand: Date() would drag the local timezone in. */
export function shortDate(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso)
  if (!m) return iso
  return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1] ?? ''}`.trim()
}

/** -1800 -> "-1,800". Indian grouping, matching the strings the backend already sends. */
export function groupIndian(amount: number): string {
  const sign = amount < 0 ? '-' : ''
  const digits = String(Math.abs(Math.round(amount)))
  if (digits.length <= 3) return sign + digits
  const head = digits.slice(0, -3)
  const tail = digits.slice(-3)
  return sign + head.replace(/\B(?=(\d{2})+(?!\d))/g, ',') + ',' + tail
}

/**
 * `summary.lowest` arrives as one delivered sentence, "2,000 on 30 Sep". The panel sets the
 * figure large and the day under it, so the string is split for layout — never re-derived.
 * A string that is not in that shape stays whole and becomes the figure, unlabelled.
 */
export function splitLowest(lowest: string): { figure: string; when: string } {
  const at = lowest.indexOf(' on ')
  if (at === -1) return { figure: lowest, when: '' }
  return { figure: lowest.slice(0, at), when: lowest.slice(at + 1) }
}

/**
 * "2026-09-14T10:02:11Z" -> "14 Sep 2026". Parsed by hand rather than through Date, which
 * would drag the reader's timezone into a stamp the server wrote in UTC.
 */
export function whenDate(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  if (!m) return iso
  return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1] ?? ''} ${m[1]}`
}

/** The same stamp with its time, for a screen about one call rather than many. */
export function whenExact(iso: string): string {
  const time = /T(\d{2}):(\d{2})/.exec(iso)
  return time ? `${whenDate(iso)}, ${time[1]}:${time[2]}` : whenDate(iso)
}
