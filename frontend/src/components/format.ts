/** Shared row/value shaping. The bot sends display strings; we only split off its hedges. */
import { PROVISIONAL_SUFFIX, isMoreRow } from '../protocol/markers'
import type { CardId, Phase } from '../protocol/types'

/**
 * The strip's three segments. `done` is deliberately not one of them: it is not a fourth
 * step, it is every step finished, so it fills the whole strip instead of adding to it.
 */
export const PHASE_ORDER: Phase[] = ['gathering', 'ready', 'plan']

export const PHASE_LABEL: Record<Phase, string> = {
  gathering: 'Gathering',
  ready: 'Ready',
  plan: 'Plan',
  done: 'Done',
}

/** Cards that have a panel of their own and must not appear twice. */
export const CARDS_SHOWN_ELSEWHERE: CardId[] = ['missing', 'plan', 'timeline']

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

/** One line that stands in for a collapsed card. */
export function oneLineSummary(rows: string[][], kv: Record<string, string>): string {
  const items = rows.filter((r) => !isMoreRow(r))
  if (items.length > 0) {
    const parts = items.slice(0, 2).map(([label, value]) => {
      const shown = splitProvisional(value ?? '').value
      return shown ? `${label} ${shown}` : label
    })
    return parts.join(' · ') + (items.length > 2 ? ` · +${items.length - 2}` : '')
  }
  const entries = Object.entries(kv)
  if (entries.length > 0) {
    // Same rule as rows: show a few and say how many were left, so a field the backend
    // adds later (an unpaid total, say) can never vanish from this line unannounced.
    const shown = entries
      .slice(0, 3)
      .map(([k, v]) => `${k.replace(/_/g, ' ')} ${v}`)
      .join(' · ')
    return shown + (entries.length > 3 ? ` · +${entries.length - 3}` : '')
  }
  return 'Nothing yet'
}
