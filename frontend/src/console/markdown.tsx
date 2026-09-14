import type { ReactNode } from 'react'

/**
 * Enough Markdown for `evals/REPORT.md`: headings, paragraphs, lists, tables, fenced code,
 * rules, and inline code, bold and links.
 *
 * It builds React elements rather than HTML, so nothing is ever injected into the page: the
 * report is a file the server reads off disk, and a renderer that went through
 * `dangerouslySetInnerHTML` would make that file's contents executable. That is also why
 * there is no Markdown dependency here — every one of them renders to an HTML string, which
 * would then have to be sanitised to be safe.
 */

const INLINE = /(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))/g

/** `code`, **bold** and [links](url), left as text when they are none of those. */
function inline(text: string): ReactNode[] {
  return text.split(INLINE).map((part, i) => {
    if (part.startsWith('`') && part.endsWith('`') && part.length > 1) {
      return <code key={i}>{part.slice(1, -1)}</code>
    }
    if (part.startsWith('**') && part.endsWith('**') && part.length > 3) {
      return <strong key={i}>{part.slice(2, -2)}</strong>
    }
    const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(part)
    if (link) {
      return (
        <a key={i} href={link[2]} target="_blank" rel="noreferrer noopener">
          {link[1]}
        </a>
      )
    }
    return part
  })
}

const isTableRow = (line: string) => line.startsWith('|')
const isDivider = (line: string) => /^\|[\s|:-]+\|$/.test(line)
const cells = (line: string) =>
  line
    .replace(/^\||\|$/g, '')
    .split('|')
    .map((cell) => cell.trim())

/** A figure column is read right; a word column is read left. */
const numeric = (value: string) => /^[-+]?[\d,.]+%?$/.test(value.trim())

function Table({ rows }: { rows: string[] }) {
  const [head, ...body] = rows.filter((row) => !isDivider(row)).map(cells)
  return (
    <div className="scroller">
      <table className="listing">
        <thead>
          <tr>
            {(head ?? []).map((cell, i) => (
              <th key={i} scope="col">
                {inline(cell)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td key={j} className={numeric(cell) ? 'listing__num' : undefined}>
                  {inline(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** The report as the repository holds it. */
export function Markdown({ text }: { text: string }) {
  const out: ReactNode[] = []
  const lines = text.split('\n')

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i]!

    if (line.startsWith('```')) {
      const code: string[] = []
      i += 1
      while (i < lines.length && !lines[i]!.startsWith('```')) {
        code.push(lines[i]!)
        i += 1
      }
      out.push(
        <pre className="md__code" key={out.length}>
          {code.join('\n')}
        </pre>,
      )
      continue
    }

    if (isTableRow(line)) {
      const rows: string[] = []
      while (i < lines.length && isTableRow(lines[i]!)) {
        rows.push(lines[i]!)
        i += 1
      }
      i -= 1
      out.push(<Table key={out.length} rows={rows} />)
      continue
    }

    const heading = /^(#{1,4})\s+(.*)$/.exec(line)
    if (heading) {
      const level = heading[1]!.length
      const Tag = `h${Math.min(level + 1, 6)}` as 'h2'
      out.push(
        <Tag className={`md__h${level}`} key={out.length}>
          {inline(heading[2]!)}
        </Tag>,
      )
      continue
    }

    if (/^(---|\*\*\*)\s*$/.test(line)) {
      out.push(<hr className="md__rule" key={out.length} />)
      continue
    }

    if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
      const items: string[] = []
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i]!)) {
        items.push(lines[i]!.replace(/^\s*([-*]|\d+\.)\s+/, ''))
        i += 1
      }
      i -= 1
      const ordered = /^\s*\d+\./.test(line)
      const List = ordered ? 'ol' : 'ul'
      out.push(
        <List className="md__list" key={out.length}>
          {items.map((item, n) => (
            <li key={n}>{inline(item)}</li>
          ))}
        </List>,
      )
      continue
    }

    if (line.trim() === '') continue

    // A paragraph runs until a blank line or the start of any other block.
    const para: string[] = []
    while (
      i < lines.length &&
      lines[i]!.trim() !== '' &&
      !isTableRow(lines[i]!) &&
      !lines[i]!.startsWith('```') &&
      !/^#{1,4}\s/.test(lines[i]!) &&
      !/^\s*([-*]|\d+\.)\s+/.test(lines[i]!)
    ) {
      para.push(lines[i]!)
      i += 1
    }
    i -= 1
    out.push(
      <p className="md__p" key={out.length}>
        {inline(para.join(' '))}
      </p>,
    )
  }

  return <div className="md">{out}</div>
}
