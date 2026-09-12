/**
 * Validates anything that arrives on Daily's `app-message` before it reaches the reducer.
 * Card text is LLM-generated, so nothing is trusted: every field is checked by hand
 * (no zod — the shape is small and the contract lives next door in types.ts).
 */
import type {
  Card,
  CardId,
  CardStatus,
  CardsMessage,
  Incoming,
  Phase,
  RtviMessage,
  TimelinePoint,
} from './types'

const PHASES = ['gathering', 'ready', 'plan', 'done'] as const
const CARD_IDS = [
  'income',
  'debts',
  'essentials',
  'optionals',
  'missing',
  'summary',
  'timeline',
  'actions',
  'plan',
] as const
const STATUSES = ['ok', 'warn', 'provisional', 'final', 'blocked'] as const
/** The only RTVI types we consume; everything else on the rtvi-ai label is dropped. */
const RTVI_TYPES = [
  'bot-transcription',
  'bot-started-speaking',
  'bot-stopped-speaking',
  'user-started-speaking',
] as const

type Obj = Record<string, unknown>

const isObj = (x: unknown): x is Obj => typeof x === 'object' && x !== null && !Array.isArray(x)
const isStr = (x: unknown): x is string => typeof x === 'string'
const isNum = (x: unknown): x is number => typeof x === 'number' && Number.isFinite(x)
const isNullish = (x: unknown): boolean => x === null || x === undefined
const oneOf = <T extends string>(list: readonly T[], x: unknown): x is T =>
  isStr(x) && (list as readonly string[]).includes(x)

/** rows are [label, value, when] triples, but we only require "array of strings". */
function parseRows(raw: unknown): string[][] | null {
  if (!Array.isArray(raw)) return null
  const rows: string[][] = []
  for (const row of raw) {
    if (!Array.isArray(row) || !row.every(isStr)) return null
    rows.push(row as string[])
  }
  return rows
}

function parseKv(raw: unknown): Record<string, string> | null {
  if (!isObj(raw)) return null
  for (const value of Object.values(raw)) if (!isStr(value)) return null
  return raw as Record<string, string>
}

function parseCard(raw: unknown): Card | null {
  if (!isObj(raw)) return null
  if (!oneOf(CARD_IDS, raw.id)) return null
  if (!isStr(raw.title)) return null
  if (!oneOf(STATUSES, raw.status)) return null
  const rows = parseRows(raw.rows)
  if (rows === null) return null
  const kv = parseKv(raw.kv)
  if (kv === null) return null
  if (!isNullish(raw.note) && !isStr(raw.note)) return null
  return {
    id: raw.id as CardId,
    title: raw.title,
    status: raw.status as CardStatus,
    rows,
    kv,
    note: isStr(raw.note) ? raw.note : null,
  }
}

function parsePoint(raw: unknown): TimelinePoint | null {
  if (!isObj(raw)) return null
  if (!isStr(raw.d) || !isNum(raw.b)) return null
  if (!isNullish(raw.e) && !isStr(raw.e)) return null
  return { d: raw.d, b: raw.b, e: isStr(raw.e) ? raw.e : null }
}

function parseCards(raw: Obj): CardsMessage | null {
  if (!isNum(raw.v)) return null
  if (!oneOf(PHASES, raw.phase)) return null
  if (!(raw.focus === null || oneOf(CARD_IDS, raw.focus))) return null
  if (!Array.isArray(raw.cards) || !Array.isArray(raw.timeline)) return null
  if (raw.ended !== undefined && typeof raw.ended !== 'boolean') return null

  const cards: Card[] = []
  for (const c of raw.cards) {
    const card = parseCard(c)
    if (card === null) return null
    cards.push(card)
  }
  const timeline: TimelinePoint[] = []
  for (const p of raw.timeline) {
    const point = parsePoint(p)
    if (point === null) return null
    timeline.push(point)
  }
  return {
    type: 'cards',
    v: raw.v,
    phase: raw.phase as Phase,
    focus: raw.focus as CardId | null,
    cards,
    timeline,
    // Separate from `phase`: `done` means the person confirmed, `ended` means the call
    // stopped, whoever stopped it.
    ended: raw.ended === true,
  }
}

function parseRtvi(raw: Obj): RtviMessage | null {
  if (!oneOf(RTVI_TYPES, raw.type)) return null
  if (raw.type === 'bot-transcription') {
    if (!isObj(raw.data) || !isStr(raw.data.text)) return null
    return { label: 'rtvi-ai', type: 'bot-transcription', data: { text: raw.data.text } }
  }
  return { label: 'rtvi-ai', type: raw.type, data: raw.data }
}

/** The single entry point: returns a message we understand, or null. Never throws. */
export function parseIncoming(raw: unknown): Incoming | null {
  if (!isObj(raw)) return null
  if (raw.label === 'rtvi-ai') return parseRtvi(raw)
  if (raw.type === 'cards') return parseCards(raw)
  return null
}
