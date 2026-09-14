import { isReportPage } from './guards'
import { Markdown } from './markdown'
import { ScreenState } from './ScreenState'
import { useFetched } from './useFetched'

const EMPTY = 'The report is empty. It lives at evals/REPORT.md.'

/** `evals/REPORT.md`, as the repository holds it. */
export function ReportScreen() {
  const { phase, data } = useFetched('/api/review/report', isReportPage)
  const markdown = data?.markdown ?? ''

  return (
    <main className="screen">
      <ScreenState phase={phase} empty={phase === 'ready' && !markdown.trim() ? EMPTY : null} />
      {markdown.trim() && <Markdown text={markdown} />}
    </main>
  )
}
