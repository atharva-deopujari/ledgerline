import { useState } from 'react'
import { marksLowest } from '../protocol/markers'
import type { TimelinePoint } from '../protocol/types'
import { groupIndian, shortDate } from './format'

const H = 170
/** Horizontal units per day. Width follows from the number of days, so bars keep their gap. */
const DX = 10
const BAR_INSET = 1
/** A month of daily bars is the shape this draws; anything wildly longer is not plotted. */
const MAX_DAYS = 400
const DAY_MS = 86_400_000

interface Day {
  iso: string
  /** Day of the month, for the axis. */
  dom: number
  /** The balance standing on that day. */
  b: number
  /** The event label, on the days that have one. */
  e: string
  /** Index into `points`, on the days the backend actually sent. */
  point: number | null
}

const utc = (iso: string): number | null => {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso)
  return m ? Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : null
}

const isoOf = (ms: number): string => new Date(ms).toISOString().slice(0, 10)

/**
 * One entry per day from the first point to the last, carrying the balance that stands on
 * that day.
 *
 * Nothing is interpolated and nothing is added up: between two points the backend's own
 * last balance is what stands, which is what "balance after that day's events" means on a
 * day with no events. If the dates are not a range this can walk, every point becomes its
 * own column instead, so a malformed timeline still draws rather than disappearing.
 */
function byDay(points: TimelinePoint[]): Day[] {
  const first = utc(points[0].d)
  const last = utc(points[points.length - 1].d)
  const span = first !== null && last !== null ? (last - first) / DAY_MS + 1 : 0

  if (!Number.isInteger(span) || span < points.length || span > MAX_DAYS) {
    return points.map((p, i) => ({
      iso: p.d,
      dom: Number(p.d.slice(-2)) || i + 1,
      b: p.b,
      e: p.e ?? '',
      point: i,
    }))
  }

  const at = new Map<string, number>()
  points.forEach((p, i) => at.set(p.d, i))

  const days: Day[] = []
  let held = points[0].b
  for (let i = 0; i < span; i++) {
    const iso = isoOf((first as number) + i * DAY_MS)
    const hit = at.get(iso)
    if (hit !== undefined) held = points[hit].b
    days.push({
      iso,
      dom: Number(iso.slice(-2)),
      b: held,
      e: hit === undefined ? '' : (points[hit].e ?? ''),
      point: hit ?? null,
    })
  }
  return days
}

/**
 * Thirty days of running balance: a bar per day for the shape of the month, and a line
 * through the days the backend actually sent for the path between them.
 *
 * No chart library — it is a handful of arithmetic over one viewBox, and nothing to keep
 * updated. The only figures printed are ones a snapshot delivered: the hovered day's own
 * balance, and the low, which is named in words only when the backend marked that day
 * `lowest`. When it has not, the chart marks the dip it drew and says that is all it is.
 */
interface Props {
  points: TimelinePoint[]
  /**
   * Print the low in words under the chart. Off when the panel already carries the summary
   * card's own lowest above it — the same figure twice on one panel reads as two findings.
   */
  showLow?: boolean
}

export function Timeline({ points, showLow = true }: Props) {
  const [hovered, setHovered] = useState<number | null>(null)

  if (points.length < 2) return null

  const days = byDay(points)
  const W = days.length * DX

  const balances = days.map((d) => d.b)
  const floor = Math.min(0, ...balances)
  const ceiling = Math.max(0, ...balances)
  const span = ceiling - floor || 1
  const y = (b: number): number => H - ((b - floor) / span) * H
  const zeroY = y(0)

  // The low is read off the delivered points, not the days they were carried across, so a
  // balance that stands for a fortnight is still the day the backend named or reached it.
  const named = points.findIndex((p) => marksLowest(p.e))
  const sent = points.map((p) => p.b)
  const lowPoint = named >= 0 ? named : sent.indexOf(Math.min(...sent))
  const lowDay = Math.max(
    0,
    days.findIndex((d) => d.point === lowPoint),
  )
  const low = points[lowPoint]
  const lowText = `${groupIndian(low.b)} on ${shortDate(low.d)}`

  const line = points
    .map((p, i) => {
      const day = days.findIndex((d) => d.point === i)
      return `${((day < 0 ? i : day) * DX + DX / 2).toFixed(1)},${y(p.b).toFixed(1)}`
    })
    .join(' ')

  const show = hovered === null ? null : days[hovered]

  return (
    <section className="timeline" aria-label="Balance over the next 30 days">
      {/* The window, until a day is pointed at; then that day, its balance and whatever
          happened on it. Each date is its own element rather than one joined string, so the
          first and last day of the window are readable on their own. */}
      <p className="timeline__readout" data-hovered={show ? true : undefined}>
        {show ? (
          <>
            <span className="timeline__readout-date">{shortDate(show.iso)}</span>
            <span className="timeline__readout-balance">{groupIndian(show.b)}</span>
            {show.e && <span className="timeline__readout-event">{show.e}</span>}
          </>
        ) : (
          <>
            <span className="timeline__readout-date">{shortDate(days[0].iso)}</span>
            <span className="timeline__readout-dash" aria-hidden="true">
              &mdash;
            </span>
            <span className="timeline__readout-date">{shortDate(days[days.length - 1].iso)}</span>
          </>
        )}
      </p>

      <div className="timeline__plot" onMouseLeave={() => setHovered(null)}>
        <svg
          className="timeline__chart"
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="none"
          role="img"
          aria-label={
            `Balance from ${shortDate(points[0].d)} to ${shortDate(points[points.length - 1].d)}. ` +
            (named >= 0 ? `Lowest ${lowText}.` : `Lowest plotted day ${lowText}.`)
          }
        >
          {/* A full-height band on the day the low falls. With a salary spike in the month
              the balance bars before it are genuinely tiny — that is the truth of the month
              and the scale is not bent to flatter it — so the day itself is marked instead. */}
          <rect
            className="timeline__lowband"
            x={lowDay * DX}
            width={DX}
            y={0}
            height={H}
            aria-hidden="true"
          />
          {days.map((day, i) => {
            const top = Math.min(y(day.b), zeroY)
            const height = Math.max(1, Math.abs(zeroY - y(day.b)))
            return (
              <rect
                className="timeline__bar"
                key={day.iso}
                data-event={day.e ? true : undefined}
                data-low={i === lowDay ? true : undefined}
                data-hovered={i === hovered ? true : undefined}
                x={i * DX + BAR_INSET}
                width={DX - BAR_INSET * 2}
                y={top}
                height={height}
                onMouseEnter={() => setHovered(i)}
              />
            )
          })}
          {floor < 0 && ceiling > 0 && (
            <line className="timeline__zero" x1={0} x2={W} y1={zeroY} y2={zeroY} />
          )}
          <polyline className="timeline__line" points={line} />
          <circle
            data-testid="timeline-low"
            data-date={low.d}
            className="timeline__low"
            cx={lowDay * DX + DX / 2}
            cy={y(low.b)}
            r={4}
          />
        </svg>
      </div>

      <p className="timeline__axis" aria-hidden="true">
        {days.map((day, i) => (
          <span key={day.iso} data-low={i === lowDay ? true : undefined}>
            {i === 0 || day.dom % 5 === 0 ? `${day.dom}` : '·'}
          </span>
        ))}
      </p>

      {named >= 0 && showLow && (
        <p className="timeline__low-label" data-negative={low.b < 0}>
          {lowText}
        </p>
      )}
    </section>
  )
}
