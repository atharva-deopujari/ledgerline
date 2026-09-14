import { to } from '../route'
import type { ReviewUser } from '../protocol/review'
import { isUsersPage } from './guards'
import { ScreenState } from './ScreenState'
import { useFetched } from './useFetched'
import { whenDate } from '../components/format'

const EMPTY = 'No one has called yet. Start a call and this fills in.'

/** Two figures the person gave, named, so a row says who they are and not only how many. */
function Headline({ facts }: { facts: ReviewUser['headline'] }) {
  if (facts.length === 0) return <span className="listing__quiet">nothing yet</span>
  return (
    <>
      {facts.map((fact) => (
        <span key={fact.name} className="listing__fact">
          <span className="listing__fact-name">{fact.name}</span> {fact.value}
        </span>
      ))}
    </>
  )
}

/** Everyone who has called, what is remembered of them, and how their last call was judged. */
export function CallersScreen() {
  const { phase, data } = useFetched('/api/review/users', isUsersPage)
  const users = data?.users ?? []

  return (
    <main className="screen">
      <header className="screen__head">
        <h1 className="screen__title">Callers</h1>
        {phase === 'ready' && (
          <p className="screen__count">
            {users.length} {users.length === 1 ? 'number' : 'numbers'}
          </p>
        )}
      </header>

      <ScreenState phase={phase} empty={users.length === 0 ? EMPTY : null} />

      {users.length > 0 && (
        <div className="scroller">
          <table className="listing" aria-label="Callers">
            <thead>
              <tr>
                <th scope="col">Number</th>
                <th scope="col" className="listing__wide">
                  Remembered
                </th>
                <th scope="col" className="listing__num">
                  Calls
                </th>
                <th scope="col" className="listing__num">
                  Facts
                </th>
                <th scope="col">Last call</th>
                <th scope="col" className="listing__num">
                  Last verdict
                </th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.phone}>
                  <td>
                    <a
                      className="listing__link"
                      href={to(`/callers/${encodeURIComponent(user.phone)}`)}
                    >
                      {user.phone}
                    </a>
                  </td>
                  <td className="listing__facts">
                    <Headline facts={user.headline} />
                  </td>
                  <td className="listing__num">{user.calls}</td>
                  <td className="listing__num">{user.facts}</td>
                  <td>{user.last_call_at ? whenDate(user.last_call_at) : '—'}</td>
                  <td className="listing__num">
                    {/* Null is "no call of theirs has been judged", which is not a zero. */}
                    {user.last_summary === null ? (
                      <span className="listing__quiet">not judged</span>
                    ) : (
                      user.last_summary.toFixed(2)
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
