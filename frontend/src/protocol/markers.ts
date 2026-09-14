/**
 * Words the backend embeds inside row text, and the predicates that read them.
 *
 * Unlike `CardId` or `Phase`, these are not typed union members — they are plain strings
 * matched inside a cell, so a typo here fails silently and the row just renders as an
 * ordinary one. Keeping them in a single module means the contract vocabulary has one
 * definition per marker and one place to change when `build_cards` changes.
 */

/** A plan row the plan deliberately leaves for later, flagged in its "when" column. */
export const UNPAID = 'unpaid'

/** A value the user said they do not know, or declined to give, kept in the missing card. */
export const NOT_KNOWN = 'not known'

/** The kind-level answer "there are none of these", written as a label with an empty value. */
export const NONE = 'none'

/** The timeline point the backend has identified as the month's true lowest day. */
export const LOWEST = 'lowest'

const cell = (row: string[], index: number): string => (row[index] ?? '').toLowerCase()

/** `when` column contains the marker. */
const whenContains = (row: string[], marker: string): boolean => cell(row, 2).includes(marker)

export const isUnpaidRow = (row: string[]): boolean => whenContains(row, UNPAID)

export const isNotKnownRow = (row: string[]): boolean => whenContains(row, NOT_KNOWN)

/** A "None" label with an empty value cell is the kind-level answer "there are none of these";
 *  an item a person calls "none" with a figure beside it is not swallowed. */
export const isNoneRow = (row: string[]): boolean =>
  (row[0] ?? '').trim().toLowerCase() === NONE && !(row[1] ?? '').trim()

/**
 * `e` can name several events comma-joined, so the marker is matched as one of the parts
 * rather than anywhere in the string.
 */
export const marksLowest = (event: string | null | undefined): boolean =>
  (event ?? '')
    .split(',')
    .map((part) => part.trim().toLowerCase())
    .includes(LOWEST)

/**
 * When a snapshot is trimmed to fit the 4 KB app-message limit, the backend replaces the
 * rows it dropped with a single ["+N more", "", ""]. It is a count, not an item.
 */
export const isMoreRow = (row: string[]): boolean => /^\+\d+ more$/.test(row[0] ?? '')

/** A value the bot is not sure about arrives as "12 ?". */
export const PROVISIONAL_SUFFIX = ' ?'
