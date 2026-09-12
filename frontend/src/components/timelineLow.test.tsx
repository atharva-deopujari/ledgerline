/**
 * The chart may print a figure for the month's low only when the backend has said which day
 * that is, by marking the point `e: "lowest"`. The series carries event days only, so without
 * that marker the dip in the drawn line can be a different day from `summary.lowest`, and two
 * numbers would contradict each other on screen.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { TimelinePoint } from '../protocol/types'
import { Timeline } from './Timeline'

/** The real shape: the true low falls on a day between two event days. */
const WITH_MARKER: TimelinePoint[] = [
  { d: '2026-09-11', b: 7700, e: 'start' },
  { d: '2026-09-30', b: 2000, e: 'lowest' },
  { d: '2026-10-01', b: 73000, e: 'salary' },
  { d: '2026-10-10', b: 52300, e: null },
]

const WITHOUT_MARKER: TimelinePoint[] = [
  { d: '2026-09-11', b: 7700, e: 'start' },
  { d: '2026-10-01', b: 73000, e: 'salary' },
  { d: '2026-10-10', b: 52300, e: null },
]

describe('when the backend names the lowest day', () => {
  it('labels it with its amount and date', () => {
    render(<Timeline points={WITH_MARKER} />)
    expect(screen.getByText(/2,000 on 30 Sep/)).toBeInTheDocument()
  })

  it('marks that day, not merely the dip in the drawn line', () => {
    render(<Timeline points={WITH_MARKER} />)
    expect(screen.getByTestId('timeline-low')).toHaveAttribute('data-date', '2026-09-30')
  })

  it('names it in the text alternative', () => {
    render(<Timeline points={WITH_MARKER} />)
    expect(screen.getByRole('img')).toHaveAccessibleName(/lowest 2,000 on 30 Sep/i)
  })

  it('finds the marker inside a comma-joined event label', () => {
    const points: TimelinePoint[] = [
      { d: '2026-09-11', b: 7700, e: 'start' },
      { d: '2026-09-30', b: 2000, e: 'rent, lowest' },
      { d: '2026-10-10', b: 52300, e: null },
    ]
    render(<Timeline points={points} />)
    expect(screen.getByTestId('timeline-low')).toHaveAttribute('data-date', '2026-09-30')
    expect(screen.getByText(/2,000 on 30 Sep/)).toBeInTheDocument()
  })

  it('shows a negative low in the warning colour', () => {
    const points = WITH_MARKER.map((p) => (p.e === 'lowest' ? { ...p, b: -1800 } : p))
    render(<Timeline points={points} />)
    expect(screen.getByText(/-1,800 on 30 Sep/)).toHaveAttribute('data-negative', 'true')
  })
})

describe('when it does not', () => {
  it('prints no figure of its own', () => {
    render(<Timeline points={WITHOUT_MARKER} />)
    expect(screen.queryByText(/7,700 on/)).not.toBeInTheDocument()
    expect(screen.getByText('11 Sep')).toBeInTheDocument()
    expect(screen.getByText('10 Oct')).toBeInTheDocument()
  })

  it('still marks the dip in the drawn line, and says so is only what is plotted', () => {
    render(<Timeline points={WITHOUT_MARKER} />)
    expect(screen.getByTestId('timeline-low')).toHaveAttribute('data-date', '2026-09-11')
    expect(screen.getByRole('img')).toHaveAccessibleName(/lowest plotted day/i)
  })
})
