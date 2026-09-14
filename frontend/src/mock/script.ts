/**
 * The review script for `?mock=1`: the whole journey as wire messages, on a timer.
 *
 * The four card snapshots this replays come from `snapshots.json`, which
 * `scripts/dump_mock_snapshots.py`
 * generates from real domain fixtures — that file is the source of truth and is never edited
 * by hand. Everything written here is the conversation around them: the RTVI text cues that
 * make the headline stream and the state pill move.
 *
 * Because the snapshots are real `build_cards` output, this journey cannot show a number the
 * engine could not produce, and it breaks the same way the real bot would if the contract
 * drifts.
 */
import snapshots from './snapshots.json'

export interface MockEvent {
  /** Milliseconds after the previous event. */
  after: number
  data: unknown
}

const say = (text: string) => ({ label: 'rtvi-ai', type: 'bot-transcription', data: { text } })
const botStarts = { label: 'rtvi-ai', type: 'bot-started-speaking' }
const botStops = { label: 'rtvi-ai', type: 'bot-stopped-speaking' }
const userStarts = { label: 'rtvi-ai', type: 'user-started-speaking' }

// `returning` is the fifth frame in the file and is deliberately not replayed here: a
// returning caller's opening is a different call, not a step in this one. It is the fixture
// the carried rendering is built and screenshotted against.
const { gathering, ready, plan, done } = snapshots

export const MOCK_SCRIPT: MockEvent[] = [
  // Opening question.
  { after: 400, data: botStarts },
  { after: 200, data: say('Tell me what comes in each month') },
  { after: 900, data: say('and when it lands.') },
  { after: 500, data: botStops },
  { after: 700, data: userStarts },

  // Gathering: salary and the fixed outgoings are down; the electricity amount is the one
  // thing still outstanding, so the summary is provisional.
  { after: 2400, data: gathering },
  { after: 300, data: botStarts },
  { after: 200, data: say('Forty-five thousand in, rent twelve thousand,') },
  { after: 1000, data: say('groceries nine thousand spread across the month.') },
  { after: 1100, data: say('What does electricity usually come to?') },
  { after: 800, data: botStops },
  { after: 900, data: userStarts },

  // Ready: nothing missing, and the thirty-day line appears.
  { after: 2600, data: ready },
  { after: 300, data: botStarts },
  { after: 200, data: say('Seventy-two thousand in, twenty-seven thousand seven hundred out.') },
  { after: 1200, data: say('The next thirty days are covered.') },
  { after: 800, data: botStops },
  { after: 1000, data: userStarts },

  // Plan: the bike EMI falls due before the salary lands, so the plan asks the lender to
  // move it and leaves the instalment outstanding until they agree.
  { after: 2600, data: plan },
  { after: 300, data: botStarts },
  { after: 200, data: say('The bike EMI is due on the twentieth,') },
  { after: 900, data: say('and the money does not arrive until the first.') },
  { after: 1100, data: say('Ask the lender to move it, and hold the streaming payment.') },
  { after: 1000, data: say('Does that work for you, or is there anything you would change?') },
  { after: 900, data: botStops },
  { after: 1400, data: userStarts },

  // Done: the user agreed. Same plan, nothing left to ask.
  { after: 2200, data: done },
  { after: 300, data: botStarts },
  { after: 200, data: say('Good. That is your plan for the next thirty days.') },
  { after: 1100, data: botStops },
]
