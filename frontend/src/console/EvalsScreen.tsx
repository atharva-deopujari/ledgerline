import { to } from '../route'
import { keyAsWords, whenExact } from '../components/format'
import { isEvalsPage } from './guards'
import { ScreenState } from './ScreenState'
import { useFetched } from './useFetched'

const EMPTY = 'No simulation runs on disk yet. Run the harness and the matrix fills in.'

/** A rate is the one figure on this screen; anything under a whole pass is worth looking at. */
const rate = (value: number | undefined) =>
  value === undefined ? null : `${Math.round(value * 100)}%`

/** The scenarios, and how today's checks fare when replayed over every saved run of each. */
export function EvalsScreen() {
  const { phase, data } = useFetched('/api/review/evals', isEvalsPage)
  const scenarios = data?.scenarios ?? []
  const checks = data?.checks ?? []

  return (
    <main className="screen">
      <header className="screen__head">
        <h1 className="screen__title">Evals</h1>
        {data && (
          <p className="screen__count">
            {data.runs_total} runs · replayed {whenExact(data.computed_at)}
          </p>
        )}
      </header>

      <ScreenState phase={phase} empty={scenarios.length === 0 ? EMPTY : null} />

      {scenarios.length > 0 && (
        <>
          <section aria-labelledby="matrix-head">
            <h2 className="review__head" id="matrix-head">
              Deterministic checks, replayed over every saved run
            </h2>
            <div className="scroller">
              <table className="listing" aria-label="Check matrix">
                <thead>
                  <tr>
                    <th scope="col" className="listing__wide">
                      Scenario
                    </th>
                    {checks.map((check) => (
                      <th scope="col" key={check} className="listing__num">
                        {keyAsWords(check)}
                      </th>
                    ))}
                    <th scope="col" className="listing__num">
                      Runs
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {scenarios.map((scenario) => (
                    <tr key={scenario.name}>
                      <th scope="row" className="listing__scenario">
                        {scenario.name}
                      </th>
                      {checks.map((check) => {
                        const value = data?.matrix[scenario.name]?.[check]
                        return (
                          <td
                            key={check}
                            className="listing__num"
                            data-short={value !== undefined && value < 1 ? true : undefined}
                          >
                            {rate(value) ?? <span className="listing__quiet">—</span>}
                          </td>
                        )
                      })}
                      <td className="listing__num">{scenario.runs}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section aria-labelledby="scenarios-head">
            <h2 className="review__head" id="scenarios-head">
              What each person does
            </h2>
            <ul className="personas">
              {scenarios.map((scenario) => (
                <li className="personas__one" key={scenario.name}>
                  <p className="personas__name">{scenario.name}</p>
                  <p className="personas__line">{scenario.persona}</p>
                </li>
              ))}
            </ul>
          </section>

          <section aria-labelledby="criteria-head">
            <h2 className="review__head" id="criteria-head">
              Judge criteria
            </h2>
            <p className="screen__empty">
              {/* Advisory until the calibration in the report says otherwise: the judge is an
                  instrument, and an instrument that has not been read against human
                  dispositions gates nothing. */}
              Advisory. These are answered by the judge model on live calls, not replayed here;
              their agreement with the human dispositions is in{' '}
              <a href={to('/report')}>the report</a>.
            </p>
            <ul className="personas">
              {(data?.criteria ?? []).map((criterion) => (
                <li className="personas__one" key={criterion}>
                  <p className="personas__name">{keyAsWords(criterion)}</p>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </main>
  )
}
