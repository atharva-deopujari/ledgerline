import { useCallback, useReducer, useState } from 'react'
import { useDailyCall } from './call/useDailyCall'
import { CardStack } from './components/CardStack'
import { ErrorBanner } from './components/ErrorBanner'
import { ForgetButton } from './components/ForgetButton'
import { LowestPoint } from './components/LowestPoint'
import { LowPointWorking } from './components/LowPointWorking'
import { MissingChips } from './components/MissingChips'
import { PhaseStrip } from './components/PhaseStrip'
import { PlanPanel } from './components/PlanPanel'
import { QuestionHeadline } from './components/QuestionHeadline'
import { Timeline } from './components/Timeline'
import { TotalsBar } from './components/TotalsBar'
import { VoiceBar } from './components/VoiceBar'
import { useChangedRows } from './components/useChangedRows'
import { CallersScreen } from './console/CallersScreen'
import { CallScreen } from './console/CallScreen'
import { CallsScreen } from './console/CallsScreen'
import { ConsoleShell, ConsoleTabs } from './console/ConsoleShell'
import { EvalsScreen } from './console/EvalsScreen'
import { ReportScreen } from './console/ReportScreen'
import { ReviewPage } from './review/ReviewPage'
import { to, useRoute } from './route'
import { VerdictPanel } from './components/VerdictPanel'
import { forgetRememberedPhone, normalisePhone, readRememberedPhone, rememberPhone } from './phone'
import { initialSession, sessionReducer } from './state/sessionReducer'
import { useVerdict } from './verdict/useVerdict'

const OPENING_TITLE = 'Talk through your next thirty days.'
const OPENING_LINE =
  'Say what comes in, what goes out, and when. Nothing to type once the call starts — the page keeps up with you.'
const PHONE_HINT = 'Ten digits, or a plus and the country code.'
const CONNECTING_LINE =
  'Allow the microphone when your browser asks. Start speaking as soon as you hear the first question.'

function CallApp() {
  const [session, dispatch] = useReducer(sessionReducer, initialSession)
  const { start, starting, stop, toggleMic, micOn, sessionId, audioRef } = useDailyCall(dispatch)

  const snapshot = session.cards
  // What each corrected row used to say, so the board can show the correction happening.
  const retired = useChangedRows(snapshot)

  const summary = snapshot?.cards.find((c) => c.id === 'summary')
  const missingCard = snapshot?.cards.find((c) => c.id === 'missing')
  const hasPlan = Boolean(snapshot?.cards.some((c) => c.id === 'plan'))
  // Once the plan exists it carries the action rows itself, so the `actions` card would be
  // the same deferral a second time, collapsed.
  const stackCards = hasPlan
    ? (snapshot?.cards.filter((c) => c.id !== 'actions') ?? [])
    : (snapshot?.cards ?? [])
  const nothingMissing = Boolean(snapshot) && !missingCard?.rows.length

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

  // The number is the person's id everywhere downstream, so it is checked before a call is
  // attempted. The server checks it too and answers 422; this is only so they are told first.
  const [phone, setPhone] = useState(readRememberedPhone)
  const [refused, setRefused] = useState(false)

  // The judge's verdict on the call that just ended; nothing is asked for until it has.
  const review = useVerdict(sessionId, callOver)

  /** The recording's basename. C's session id may or may not carry the recorder's prefix. */
  const recordingId =
    sessionId && (sessionId.startsWith('voice-') ? sessionId : `voice-${sessionId}`)
  const calledNumber = normalisePhone(phone)

  /**
   * End the call, then go. `stop()` is what the End control does — it leaves the room and
   * DELETEs the session — and it is awaited so the server hears about it before the page
   * unloads, rather than being left to time the room out on its own.
   */
  const leaveTo = useCallback(
    async (href: string) => {
      await stop()
      window.location.assign(href)
    },
    [stop],
  )

  const onStart = useCallback(() => {
    const valid = normalisePhone(phone)
    if (!valid) {
      setRefused(true)
      return
    }
    setRefused(false)
    rememberPhone(valid)
    void start(valid)
  }, [phone, start])

  return (
    <div className="app" data-call={session.call}>
      <audio ref={audioRef} playsInline />

      {/* The tabs stay through the call and after it: a person who has just hung up must
          never be left on a board with no way off it. */}
      <ConsoleTabs route={{ name: 'call' }}>
        {snapshot && <PhaseStrip phase={snapshot.phase} />}
        {nothingMissing && <p className="masthead__clear">nothing still needed</p>}
      </ConsoleTabs>

      <ErrorBanner message={session.error} onRetry={onStart} disabled={busy} />

      {!started ? (
        <main className="opening">
          <div className="opening__copy">
            <p className="opening__kicker">{connecting ? 'connecting' : 'about four minutes'}</p>
            <h1 className="opening__title">{OPENING_TITLE}</h1>
            <p className="opening__line">{connecting ? CONNECTING_LINE : OPENING_LINE}</p>
          </div>
          <div className="opening__panel">
            <form
              className="opening__form"
              onSubmit={(e) => {
                e.preventDefault()
                onStart()
              }}
            >
              <label className="opening__label" htmlFor="phone">
                Your phone number
              </label>
              <input
                id="phone"
                className="opening__field"
                type="tel"
                inputMode="tel"
                autoComplete="tel"
                value={phone}
                onChange={(e) => {
                  setPhone(e.target.value)
                  setRefused(false)
                }}
                aria-invalid={refused}
                aria-describedby={refused ? 'phone-hint' : undefined}
                disabled={busy}
              />
              <button className="opening__button" disabled={busy} aria-busy={busy}>
                {connecting
                  ? 'Starting…'
                  : starting
                    ? 'Finishing the last attempt…'
                    : 'Start the call'}
              </button>
            </form>
            {refused && (
              <p className="opening__hint" id="phone-hint" role="alert">
                {PHONE_HINT}
              </p>
            )}
            {/* The person's own delete control, beside the number it deletes. */}
            <ForgetButton phone={normalisePhone(phone) ?? ''} onForgotten={forgetRememberedPhone} />
          </div>
        </main>
      ) : (
        <main className="board">
          <section className="ledger" aria-label="Your month">
            <QuestionHeadline
              settled={session.lastQuestion}
              streaming={session.question}
              speaking={session.speak === 'speaking'}
            />

            {snapshot && stackCards.length > 0 ? (
              <>
                <p className="ledger__colheads" aria-hidden="true">
                  <span>when</span>
                  <span>amount</span>
                </p>
                <CardStack cards={stackCards} focus={snapshot.focus} retired={retired} />
              </>
            ) : (
              <p className="ledger__waiting">
                {connecting ? 'Connecting…' : 'Listening. Start whenever.'}
              </p>
            )}

            <MissingChips card={missingCard} />

            {/* Ruled paper under the last card, so the ledger reads as a page with room
                left on it rather than as a list that happens to stop. */}
            <div className="ledger__rule" aria-hidden="true" />

            <TotalsBar card={summary} />
          </section>

          <aside className="panel" aria-label="The month ahead">
            <LowestPoint card={summary} />
            {snapshot && snapshot.timeline.length > 0 && (
              <Timeline points={snapshot.timeline} showLow={!summary?.kv.lowest} />
            )}
            {/* Under the figure and its chart: why the month gets that low, in the same
                order the bot says it. */}
            <LowPointWorking low={snapshot?.low_point ?? null} />
            {hasPlan && snapshot ? (
              <PlanPanel snapshot={snapshot} ended={callOver} />
            ) : (
              summary?.note && <p className="panel__note">{summary.note}</p>
            )}
            {/* The judge runs after the call, so this is the last thing on the panel. */}
            <VerdictPanel state={review} />
          </aside>
        </main>
      )}

      {session.call === 'live' && (
        <footer className="app__foot">
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
        <footer className="app__foot app__foot--again">
          <button
            type="button"
            className="opening__button"
            onClick={onStart}
            disabled={busy}
            aria-busy={busy}
          >
            {starting ? 'Finishing the last attempt…' : 'Start another call'}
          </button>
          <nav className="ended" aria-label="After the call">
            {/* Every one of these leaves the page, so the call is ended first: a navigation
                would drop the Daily connection without telling the server, and the next
                call would meet its own session still registered. */}
            <button type="button" className="ended__link" onClick={() => void leaveTo(to('/'))}>
              Back to start
            </button>
            {recordingId && (
              <button
                type="button"
                className="ended__link"
                onClick={() => void leaveTo(to(`/calls/${encodeURIComponent(recordingId)}`))}
              >
                See this call
              </button>
            )}
            {calledNumber && (
              <button
                type="button"
                className="ended__link"
                onClick={() => void leaveTo(to(`/callers/${encodeURIComponent(calledNumber)}`))}
              >
                Your memory
              </button>
            )}
          </nav>
        </footer>
      )}
    </div>
  )
}

/**
 * Two pages: the call board, and one person's memory page. The path is read once — nothing
 * pushes state — and the board's hooks only run when the board is the page.
 */
export default function App() {
  const route = useRoute()
  if (route.name === 'call') return <CallApp />
  return (
    <ConsoleShell route={route}>
      {route.name === 'caller' ? (
        <ReviewPage phone={route.phone} />
      ) : route.name === 'calls' ? (
        <CallsScreen />
      ) : route.name === 'recording' ? (
        <CallScreen id={route.id} />
      ) : route.name === 'evals' ? (
        <EvalsScreen />
      ) : route.name === 'report' ? (
        <ReportScreen />
      ) : (
        <CallersScreen />
      )}
    </ConsoleShell>
  )
}
