import { to } from '../route'
import { useState } from 'react'
import type { CallSummary } from '../protocol/review'
import { keyAsWords, whenExact } from '../components/format'
import { isCallsPage } from './guards'
import { ScreenState } from './ScreenState'
import { useFetched } from './useFetched'

const EMPTY = 'No calls have been recorded yet. Live calls and simulation runs both land here.'
const NONE_MATCH = 'No call matches that filter.'

const CHECKS = ['money_traceable', 'state_matches_call', 'speakable'] as const

/** One dot per deterministic check, in a fixed order, titled so the dot is never the only signal. */
function Checks({ checks }: { checks: CallSummary['checks'] }) {
  return (
    <span className="checks">
      {CHECKS.map((name) => (
        <span
          key={name}
          className="checks__dot"
          data-passed={checks[name]}
          title={`${keyAsWords(name)}: ${checks[name] ? 'pass' : 'fail'}`}
        >
          <span className="visually-hidden">{`${keyAsWords(name)} ${checks[name] ? 'passed' : 'failed'}`}</span>
        </span>
      ))}
    </span>
  )
}

/** Every recording on disk, live and simulated, and how each one was judged. */
export function CallsScreen() {
  const { phase, data } = useFetched('/api/review/calls', isCallsPage)
  const [source, setSource] = useState('all')
  const [label, setLabel] = useState('all')

  const calls = data?.calls ?? []
  // Filtered here rather than by refetching: the list is already in hand, and the options
  // have to come from the whole list anyway or a filter could hide its own way back.
  const labels = [...new Set(calls.map((call) => call.label))].sort()
  const shown = calls.filter(
    (call) =>
      (source === 'all' || call.source === source) && (label === 'all' || call.label === label),
  )

  return (
    <main className="screen">
      <header className="screen__head">
        <h1 className="screen__title">Calls</h1>
        {phase === 'ready' && (
          <p className="screen__count">
            {shown.length === calls.length
              ? `${calls.length} recorded`
              : `${shown.length} of ${calls.length}`}
          </p>
        )}
      </header>

      {calls.length > 0 && (
        <div className="filters">
          <label className="filters__field">
            <span className="filters__label">Source</span>
            <select value={source} onChange={(e) => setSource(e.target.value)}>
              <option value="all">All</option>
              <option value="live">Live</option>
              <option value="simulated">Simulated</option>
            </select>
          </label>
          <label className="filters__field">
            <span className="filters__label">Scenario or number</span>
            <select value={label} onChange={(e) => setLabel(e.target.value)}>
              <option value="all">All</option>
              {labels.map((one) => (
                <option key={one} value={one}>
                  {one}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}

      <ScreenState
        phase={phase}
        empty={calls.length === 0 ? EMPTY : shown.length === 0 ? NONE_MATCH : null}
      />

      {shown.length > 0 && (
        <div className="scroller">
          <table className="listing" aria-label="Calls">
            <thead>
              <tr>
                <th scope="col" className="listing__wide">
                  Call
                </th>
                <th scope="col">Started</th>
                <th scope="col" className="listing__num">
                  Turns
                </th>
                <th scope="col">Plan</th>
                <th scope="col">Ended by</th>
                <th scope="col">Prompt</th>
                <th scope="col">Checks</th>
                <th scope="col" className="listing__num">
                  Verdict
                </th>
              </tr>
            </thead>
            <tbody>
              {shown.map((call) => (
                <tr key={call.id}>
                  <td>
                    <a className="listing__link" href={to(`/calls/${encodeURIComponent(call.id)}`)}>
                      {call.label}
                    </a>
                    <span className="listing__source">{call.source}</span>
                  </td>
                  <td>{whenExact(call.started_at)}</td>
                  <td className="listing__num">{call.turns}</td>
                  <td>
                    {call.plan_final ? 'reached' : <span className="listing__quiet">no</span>}
                  </td>
                  <td>{call.ended_by ?? <span className="listing__quiet">—</span>}</td>
                  <td>{call.prompt_version ?? <span className="listing__quiet">—</span>}</td>
                  <td>
                    <Checks checks={call.checks} />
                  </td>
                  <td className="listing__num">
                    {/* Null on every simulated run: no judge scored it, and a number made
                        from three booleans would be arithmetic nobody asked for. */}
                    {call.summary === null ? (
                      <span className="listing__quiet">not judged</span>
                    ) : (
                      call.summary.toFixed(2)
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  )
}
