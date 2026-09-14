/**
 * Wire protocol between the bot and the browser. CONTRACT.
 * Mirrors ledgerline/domain/cards.py field for field. If you change one, change the other and
 * regenerate frontend/src/protocol/sample.json from the Python side.
 *
 * Two message families arrive on Daily's `app-message` event:
 *  1. Our cards snapshot (CardsMessage). Full snapshot every time, monotonic `v`.
 *  2. Pipecat's default RTVI messages, `label: "rtvi-ai"`. We consume four, drop the rest.
 */

export type Phase = "gathering" | "ready" | "plan" | "done";

export type CardId =
  | "income"
  | "debts"
  | "essentials"
  | "optionals"
  | "missing"
  | "summary"
  | "timeline"
  | "actions"
  | "plan";

export type CardStatus = "ok" | "warn" | "provisional" | "final" | "blocked" | "carried";

export interface Card {
  id: CardId;
  title: string;
  status: CardStatus;
  /** [label, value, when] */
  rows: string[][];
  kv: Record<string, string>;
  note?: string | null;
}

export interface TimelinePoint {
  /** ISO date */
  d: string;
  /** balance in whole rupees after that day's events */
  b: number;
  /** short event label, only on event days */
  e?: string | null;
}

export interface LowPointLine {
  /** ISO date; for a spread item, the last day counted in this total */
  d: string
  label: string
  /** whole rupees, signed the way the balance moves: negative out, positive in */
  amt: number
  /** a running total up to `d`, not one payment on it */
  spread: boolean
}

/**
 * Why the lowest balance is that number, so the screen and the voice explain it the same way.
 * Two identities hold, the same ones the domain guarantees:
 *   opening + sum(before.amt) === b
 *   b + sum(after.amt) === closing
 * Every amount is whole rupees, signed the way the balance moves (out negative, in positive).
 */
export interface LowPointView {
  /** ISO date of the lowest day */
  d: string
  /** balance in whole rupees on that day */
  b: number
  opening: number
  closing: number
  before: LowPointLine[]
  after: LowPointLine[]
}

export interface CardsMessage {
  type: "cards";
  v: number;
  phase: Phase;
  focus: CardId | null;
  cards: Card[];
  timeline: TimelinePoint[];
  /** The arithmetic behind the lowest day; null while the plan is blocked. */
  low_point: LowPointView | null;
  /** True once the call has ended, whoever ended it. Independent of `phase`: `done` means the
   *  person confirmed the plan; `ended` alone means the call stopped before they did. */
  ended?: boolean;
}

/** The four RTVI messages we consume. Shapes per Pipecat 1.9 RTVI 2.1 protocol. */
export type RtviMessage =
  | { label: "rtvi-ai"; type: "bot-transcription"; data: { text: string } }
  | { label: "rtvi-ai"; type: "bot-started-speaking"; data?: unknown }
  | { label: "rtvi-ai"; type: "bot-stopped-speaking"; data?: unknown }
  | { label: "rtvi-ai"; type: "user-started-speaking"; data?: unknown };

export type Incoming = CardsMessage | RtviMessage;

export type SpeakState = "idle" | "listening" | "speaking" | "thinking";

export interface SessionStartResponse {
  room_url: string;
  token: string;
  session_id: string;
}
