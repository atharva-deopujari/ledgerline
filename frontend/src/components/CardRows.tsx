import { isMoreRow, isNoneRow, isNotKnownRow } from '../protocol/markers'
import { splitProvisional } from './format'

interface Props {
  rows: string[][]
  /** For rows the last snapshot moved: the figure it replaced, by row label. */
  retired?: Map<string, string>
}

/**
 * `[label, value, when]` in three columns — label left, when and amount to the right,
 * tabular figures so the column of money lines up digit for digit.
 *
 * When a figure is corrected, the one it replaced is struck through beside it for that
 * snapshot: the correction is the moment the person most needs to see, and a number that
 * simply changes while they are talking is a number they cannot check. Both figures came
 * from the backend — the retired one is the string it sent a moment ago, not a step
 * computed on the way — and the struck one can never be mistaken for the live one: it is
 * marked `data-retired`, hidden from assistive tech, and replaced there by a spoken "was
 * 45,000, now 72,000" so a screen reader hears one current figure, not two.
 */
export function CardRows({ rows, retired }: Props) {
  if (rows.length === 0) return null
  return (
    <ul className="rows">
      {rows.map((row, i) => {
        const [label, rawValue = '', when = ''] = row
        // The person said there is none of this kind. The word is the whole answer; an
        // empty amount column beside it would read as a figure still to come.
        if (isNoneRow(row)) {
          return (
            <li className="row row--none" key={`none-${i}`}>
              <span className="row__label">{label}</span>
            </li>
          )
        }
        // A trim marker stands for the rows that did not fit, so it carries no value.
        if (isMoreRow(row)) {
          return (
            <li className="row row--more" key={`more-${i}`}>
              <span className="row__label">{label}</span>
            </li>
          )
        }
        const { value, uncertain } = splitProvisional(rawValue)
        const was = retired?.get(label ?? '')
        return (
          <li
            className="row"
            /* Keyed on the value as well as the label: when a figure is corrected the row
               is a new node, so the wash actually replays instead of the browser reusing an
               element whose animation has already finished. */
            key={`${label}-${i}-${rawValue}`}
            data-changed={was === undefined ? undefined : true}
            data-known={isNotKnownRow(row) ? 'false' : undefined}
          >
            <span className="row__label">{label}</span>
            {when && <span className="row__when">{when}</span>}
            <span className="row__value" data-testid={`value-${label}`}>
              {was !== undefined && (
                <>
                  <span className="visually-hidden">{`was ${was}, now `}</span>
                  <s className="row__retired" data-retired={was} aria-hidden="true">
                    {was}
                  </s>
                </>
              )}
              <span className="row__live">
                {value}
                {uncertain && (
                  <span
                    className="row__uncertain"
                    title="Not confirmed yet"
                    aria-label="not confirmed"
                  >
                    ?
                  </span>
                )}
              </span>
            </span>
          </li>
        )
      })}
    </ul>
  )
}
