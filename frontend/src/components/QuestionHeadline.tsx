interface Props {
  /** The last question the bot finished asking. */
  settled: string
  /** What it is saying right now. */
  streaming: string
  speaking: boolean
}

const OPENING = 'Start the call and tell me about your money.'

/**
 * The headline is the settled question. While the bot talks, the new sentence streams
 * underneath it — until the first question settles, the stream is the headline.
 */
export function QuestionHeadline({ settled, streaming, speaking }: Props) {
  const headline = settled || streaming || OPENING
  const showStream = Boolean(settled) && Boolean(streaming)
  return (
    <div className="headline" aria-live="polite">
      <h1 className="headline__question">{headline}</h1>
      {showStream && (
        <p className="headline__stream" data-speaking={speaking}>
          {streaming}
        </p>
      )}
    </div>
  )
}
