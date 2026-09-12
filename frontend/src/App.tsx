import { useCallback, useReducer, useState } from 'react'
import { useDailyCall } from './call/useDailyCall'
import { CardStack } from './components/CardStack'
import { ErrorBanner } from './components/ErrorBanner'
import { FocusCard } from './components/FocusCard'
import { MissingChips } from './components/MissingChips'
import { PhaseStrip } from './components/PhaseStrip'
import { PlanPanel } from './components/PlanPanel'
import { QuestionHeadline } from './components/QuestionHeadline'
import { Timeline } from './components/Timeline'
import { VoiceBar } from './components/VoiceBar'
import { CARDS_SHOWN_ELSEWHERE } from './components/format'
import type { CardId } from './protocol/types'
import { initialSession, sessionReducer } from './state/sessionReducer'

const OPENING_LINE =
  'A short call about your next thirty days. Say what comes in, what goes out, and when.'

export default function App() {
  const [session, dispatch] = useReducer(sessionReducer, initialSession)
  const { start, starting, stop, toggleMic, micOn, audioRef } = useDailyCall(dispatch)
  // A card the user tapped open. Cleared whenever the bot moves the focus itself.
  const [pinned, setPinned] = useState<CardId | null>(null)

  const snapshot = session.cards
  const focusId = pinned ?? snapshot?.focus ?? null
  // The bot can focus a card that has a panel of its own (the plan, the chips, the
  // timeline). Showing it in the focus slot too would print it twice.
  const focusCard =
    focusId && !CARDS_SHOWN_ELSEWHERE.includes(focusId)
      ? (snapshot?.cards.find((c) => c.id === focusId) ?? null)
      : null
  const missingCard = snapshot?.cards.find((c) => c.id === 'missing')
  const hasPlan = Boolean(snapshot?.cards.some((c) => c.id === 'plan'))
  // Once the plan exists it carries the action rows itself, so the `actions` card would be
  // the same deferral a second time, collapsed.
  const stackCards = hasPlan
    ? (snapshot?.cards.filter((c) => c.id !== 'actions') ?? [])
    : (snapshot?.cards ?? [])
  const connecting = session.call === 'connecting'
  const inCall = connecting || session.call === 'live'
  // `starting` outlives `connecting`: after a terminal event the reducer says the call is
  // over while the attempt is still unwinding, and start() would refuse in that window.
  const busy = inCall || starting
  // Nobody is listening once the call stops, however it stopped.
  const callOver = session.call === 'ended' || session.call === 'error'
  // Stay on the start screen while connecting, with the button disabled, rather than
  // swapping in an empty board: the user can see the press was taken.
  // A failure before anything arrived keeps them there too; one that happens mid-call
  // keeps the board, because what is on it is still worth reading.
  // The board is kept for a finished call only when it has something on it. Joining is not
  // enough: a call that ended before any card arrived leaves an empty board captioned
  // "Listening. Start whenever." after the call is over, which is the same lie as showing it
  // for an attempt that never joined at all.
  const started = session.call === 'live' || (!!snapshot && session.call !== 'idle')

  const onFocus = useCallback((id: CardId) => setPinned(id), [])
  const onStart = useCallback(() => {
    setPinned(null)
    void start()
  }, [start])

  return (
    <div className="app" data-call={session.call}>
      <audio ref={audioRef} playsInline />

      <header className="app__top">
        <p className="app__brand">Ledgerline</p>
        {snapshot && <PhaseStrip phase={snapshot.phase} />}
      </header>

      <ErrorBanner message={session.error} onRetry={onStart} disabled={busy} />

      {!started ? (
        <main className="start">
          <h1 className="start__title">Talk through your month.</h1>
          <p className="start__line">{OPENING_LINE}</p>
          <button
            type="button"
            className="start__button"
            onClick={onStart}
            disabled={busy}
            aria-busy={busy}
          >
            {connecting ? 'Starting…' : starting ? 'Finishing the last attempt…' : 'Start the call'}
          </button>
        </main>
      ) : (
        <main className="board">
          <div className="board__lead">
            <QuestionHeadline
              settled={session.lastQuestion}
              streaming={session.question}
              speaking={session.speak === 'speaking'}
            />
            {hasPlan && snapshot ? (
              <PlanPanel snapshot={snapshot} ended={callOver} />
            ) : focusCard ? (
              <FocusCard card={focusCard} />
            ) : (
              <p className="board__waiting">
                {session.call === 'connecting' ? 'Connecting…' : 'Listening. Start whenever.'}
              </p>
            )}
            {missingCard && <MissingChips card={missingCard} />}
          </div>

          <div className="board__rest">
            {snapshot && snapshot.timeline.length > 0 && <Timeline points={snapshot.timeline} />}
            {snapshot && <CardStack cards={stackCards} focus={focusId} onFocus={onFocus} />}
          </div>
        </main>
      )}

      {session.call === 'live' && (
        <footer className="app__bottom">
          <VoiceBar
            speak={session.speak}
            micOn={micOn}
            onToggleMic={toggleMic}
            onEnd={() => void stop()}
          />
        </footer>
      )}

      {/* Only under the board. Without the board the start screen's own button is the way
          back, and showing both would be two controls for one action. */}
      {started && session.call === 'ended' && (
        <footer className="app__bottom">
          <button
            type="button"
            className="start__button"
            onClick={onStart}
            disabled={busy}
            aria-busy={busy}
          >
            {starting ? 'Finishing the last attempt…' : 'Start another call'}
          </button>
        </footer>
      )}
    </div>
  )
}
