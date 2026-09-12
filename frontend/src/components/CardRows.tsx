import { isMoreRow } from '../protocol/markers'
import { splitProvisional } from './format'

/** [label, value, when] rows, shared by the focus card and the plan panel. */
export function CardRows({ rows }: { rows: string[][] }) {
  if (rows.length === 0) return null
  return (
    <ul className="rows">
      {rows.map((row, i) => {
        const [label, rawValue = '', when = ''] = row
        // A trim marker stands for the rows that did not fit, so it carries no value.
        if (isMoreRow(row)) {
          return (
            <li className="row row--more" key={`more-${i}`}>
              <span className="row__label">{label}</span>
            </li>
          )
        }
        const { value, uncertain } = splitProvisional(rawValue)
        return (
          <li className="row" key={`${label}-${i}`}>
            <span className="row__label">{label}</span>
            <span className="row__value" data-testid={`value-${label}`}>
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
            {when && <span className="row__when">{when}</span>}
          </li>
        )
      })}
    </ul>
  )
}
