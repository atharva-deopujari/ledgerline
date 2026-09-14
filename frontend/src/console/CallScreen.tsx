import { VerdictPanel } from '../components/VerdictPanel'
import { whenExact } from '../components/format'
import { isCallDetail } from './guards'
import { ScreenState } from './ScreenState'
import { useFetched } from './useFetched'

const MISSING = 'No recording with that name. It may have been cleared from evals/runs.'

interface Turn {
  role?: unknown
  text?: unknown
  tool_calls?: unknown
}

interface ToolCall {
  name?: unknown
  arguments?: unknown
  result?: unknown
}

const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null)

/**
 * The recording's shape belongs to the recorder, not to a contract, so everything below is
 * read defensively: a turn without a role or a tool call without a result renders as much of
 * itself as it has rather than taking the screen down.
 */
const turnsOf = (call: Record<string, unknown>): Turn[] =>
  Array.isArray(call.turns) ? (call.turns as Turn[]) : []

const toolCallsOf = (turn: Turn): ToolCall[] =>
  Array.isArray(turn.tool_calls) ? (turn.tool_calls as ToolCall[]) : []

function ToolCalls({ calls }: { calls: ToolCall[] }) {
  if (calls.length === 0) return null
  return (
    <details className="tools">
      <summary className="tools__summary">
        {calls.length === 1 ? '1 tool call' : `${calls.length} tool calls`}
      </summary>
      {calls.map((call, i) => (
        <div className="tools__call" key={`${str(call.name) ?? 'call'}-${i}`}>
          <p className="tools__name">{str(call.name) ?? 'unnamed'}</p>
          <pre className="tools__args">{JSON.stringify(call.arguments ?? {}, null, 2)}</pre>
          {str(call.result) && <p className="tools__result">{str(call.result)}</p>}
        </div>
      ))}
    </details>
  )
}

/** One recording: what was said, what the coach did about it, and how it was judged. */
export function CallScreen({ id }: { id: string }) {
  const { phase, data } = useFetched(`/api/review/calls/${encodeURIComponent(id)}`, isCallDetail)
  const call = data?.call
  const turns = call ? turnsOf(call) : []

  return (
    <main className="screen">
      <header className="screen__head">
        <h1 className="screen__title">{str(call?.session_id) ?? id}</h1>
        {call && (
          <p className="screen__count">
            {[
              str(call.source),
              str(call.prompt_version),
              call.plan_final === true ? 'plan reached' : null,
              str(call.ended_by) && `ended by ${str(call.ended_by)}`,
            ]
              .filter(Boolean)
              .join(' · ')}
          </p>
        )}
      </header>

      <ScreenState phase={phase} failed={MISSING} />

      {call && (
        <>
          <section className="transcript" aria-label="Transcript">
            {turns.length === 0 && <p className="screen__empty">This recording has no turns.</p>}
            {turns.map((turn, i) => (
              <article
                className="turn"
                data-role={str(turn.role) ?? 'unknown'}
                key={`${i}-${str(turn.text)?.slice(0, 12) ?? ''}`}
              >
                <p className="turn__who">{str(turn.role) === 'user' ? 'Person' : 'Coach'}</p>
                <p className="turn__text">{str(turn.text) ?? ''}</p>
                <ToolCalls calls={toolCallsOf(turn)} />
              </article>
            ))}
          </section>

          {data?.verdict && <VerdictPanel state={{ phase: 'done', verdict: data.verdict }} />}

          <section aria-labelledby="state-head">
            <h2 className="review__head" id="state-head">
              Final state
            </h2>
            {/* Printed as it was saved. The recorder owns this shape, so inventing a layout
                for it would be a second contract nobody agreed to. */}
            <pre className="state">{JSON.stringify(call.state ?? {}, null, 2)}</pre>
          </section>

          <p className="screen__count">
            Recorded {str(call.today) ? `for ${whenExact(String(call.today))}` : 'without a date'}
            {Array.isArray(call.cards_versions)
              ? ` · ${call.cards_versions.length} card updates`
              : ''}
          </p>
        </>
      )}
    </main>
  )
}
