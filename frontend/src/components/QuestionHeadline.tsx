interface Props {
  /** The last question the bot finished asking. */
  settled: string
  /** What it is saying right now. */
  streaming: string
  speaking: boolean
}

const OPENING = 'Start the call and tell me about your money.'

/**
 * The headline is the settled question, set large in the serif — the one thing on the board
 * you are meant to be answering. While the bot talks, the new sentence streams underneath
 * it; until the first question settles, the stream *is* the headline.
 *
 * Keyed on the text so a new question fades up in place of the old one instead of swapping
 * mid-read. The block holds its height either way, so the ledger below it never jumps.
 */
export function QuestionHeadline({ settled, streaming, speaking }: Props) {
  const headline = settled || streaming || OPENING
  const showStream = Boolean(settled) && Boolean(streaming)
  return (
    <div className="headline" aria-live="polite">
      <h1 className="headline__question" key={headline}>
        {headline}
      </h1>
      {showStream && (
        <p className="headline__stream" data-speaking={speaking}>
          {streaming}
        </p>
      )}
    </div>
  )
}
