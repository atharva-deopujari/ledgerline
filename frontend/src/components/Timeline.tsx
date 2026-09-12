import { marksLowest } from '../protocol/markers'
import type { TimelinePoint } from '../protocol/types'
import { groupIndian, shortDate } from './format'

const W = 320
const H = 96
const PAD_Y = 14

interface Placed {
  point: TimelinePoint
  x: number
  y: number
}

/**
 * Thirty days of running balance as one line. No chart library: it is a polyline over a
 * fixed viewBox, scaled by CSS, which is a handful of arithmetic and nothing to keep updated.
 */
export function Timeline({ points }: { points: TimelinePoint[] }) {
  if (points.length < 2) return null

  const balances = points.map((p) => p.b)
  const min = Math.min(...balances)
  const max = Math.max(...balances)
  const span = max - min || 1
  const placed: Placed[] = points.map((point, i) => ({
    point,
    x: (i / (points.length - 1)) * W,
    y: PAD_Y + (1 - (point.b - min) / span) * (H - PAD_Y * 2),
  }))

  // The named day when there is one; otherwise the earliest day at the lowest drawn balance.
  const namedIndex = points.findIndex((point) => marksLowest(point.e))
  const lowIndex = namedIndex >= 0 ? namedIndex : balances.indexOf(min)
  const low = placed[lowIndex]
  const named = namedIndex >= 0
  const lowText = `${groupIndian(low.point.b)} on ${shortDate(low.point.d)}`

  const zeroY = PAD_Y + (1 - (0 - min) / span) * (H - PAD_Y * 2)
  const showZero = min < 0 && max > 0

  return (
    <section className="timeline" aria-label="Balance over the next 30 days">
      <svg
        className="timeline__chart"
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={
          `Balance from ${shortDate(points[0].d)} to ${shortDate(points[points.length - 1].d)}. ` +
          (named ? `Lowest ${lowText}.` : `Lowest plotted day ${lowText}.`)
        }
      >
        {showZero && <line className="timeline__zero" x1={0} x2={W} y1={zeroY} y2={zeroY} />}
        <polyline
          className="timeline__line"
          points={placed.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')}
        />
        {placed.map((p) => (
          <circle
            key={p.point.d}
            className="timeline__dot"
            cx={p.x}
            cy={p.y}
            r={p.point.e ? 2.5 : 1.5}
          />
        ))}
        <circle
          data-testid="timeline-low"
          data-date={low.point.d}
          className="timeline__low"
          cx={low.x}
          cy={low.y}
          r={4.5}
        />
      </svg>
      <p className="timeline__axis">
        <span>{shortDate(points[0].d)}</span>
        {named && (
          <span className="timeline__low-label" data-negative={low.point.b < 0}>
            {lowText}
          </span>
        )}
        <span>{shortDate(points[points.length - 1].d)}</span>
      </p>
    </section>
  )
}
