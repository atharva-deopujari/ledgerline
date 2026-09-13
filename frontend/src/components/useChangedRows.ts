import { useState } from 'react'
import type { CardsMessage } from '../protocol/types'

/** `cardId|label` — a row's identity across snapshots. */
const key = (cardId: string, label: string): string => `${cardId}|${label}`

const EMPTY: Map<string, string> = new Map()

const readValues = (snapshot: CardsMessage): Map<string, string> => {
  const values = new Map<string, string>()
  for (const card of snapshot.cards) {
    for (const [label, value = ''] of card.rows) values.set(key(card.id, label ?? ''), value)
  }
  return values
}

/** Rows present in both snapshots whose delivered string differs, and what it used to be. */
function diff(before: CardsMessage | null, after: CardsMessage | null): Map<string, string> {
  if (!before || !after) return EMPTY
  const was = readValues(before)
  const retired = new Map<string, string>()
  for (const [id, value] of readValues(after)) {
    const old = was.get(id)
    if (old !== undefined && old !== value) retired.set(id, old)
  }
  return retired
}

/**
 * What each row's figure was, for the rows this snapshot changed.
 *
 * The board takes a full snapshot every time and reconciles by card id, so "what changed"
 * is not in the message — it is the difference between two of them. That difference lives
 * here, beside the view, rather than in the reducer: the session state is the snapshot the
 * backend sent, and this is only how the board shows the move to it.
 *
 * It compares the delivered strings and nothing else, so no arithmetic is done and no
 * figure is invented — the retired value is one the backend itself sent a moment ago. A row
 * that is new, or one whose card has only just appeared, has nothing to retire.
 *
 * The previous snapshot is kept in state and adjusted during render, which is React's own
 * way of remembering what the last props were: the comparison happens once per snapshot,
 * and a re-render for any other reason (a hover on the chart, the call ending) keeps
 * reporting the same rows instead of comparing a snapshot against itself and finding none.
 */
export function useChangedRows(snapshot: CardsMessage | null): Map<string, string> {
  const [seen, setSeen] = useState<CardsMessage | null>(null)
  const [retired, setRetired] = useState<Map<string, string>>(EMPTY)

  if (snapshot !== seen) {
    const next = diff(seen, snapshot)
    setSeen(snapshot)
    setRetired(next)
    return next
  }
  return retired
}

export const rowKey = key

/** The retired figures for `cardId`'s rows, by label, which is what a card hands down. */
export function changedLabels(retired: Map<string, string>, cardId: string): Map<string, string> {
  const prefix = `${cardId}|`
  const mine = new Map<string, string>()
  for (const [id, was] of retired) {
    if (id.startsWith(prefix)) mine.set(id.slice(prefix.length), was)
  }
  return mine
}
