/**
 * The report is 1,900 lines of headings, tables, fenced code and prose. This renders it into
 * React elements, never into HTML: the file is read off disk by the server, and a renderer
 * that went through innerHTML would make its contents executable.
 */
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { Markdown } from './markdown'

const show = (text: string) => render(<Markdown text={text} />)

describe('the markdown the report needs', () => {
  it('sets headings by level, under the page title', () => {
    show('# One\n\n## Two\n\n### Three')
    expect(screen.getByRole('heading', { level: 2, name: 'One' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 3, name: 'Two' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 4, name: 'Three' })).toBeInTheDocument()
  })

  it('joins the lines of a paragraph and keeps paragraphs apart', () => {
    const { container } = show('one line\nand its wrap\n\na second paragraph')
    const paragraphs = container.querySelectorAll('.md__p')
    expect(paragraphs).toHaveLength(2)
    expect(paragraphs[0]).toHaveTextContent('one line and its wrap')
  })

  it('renders a table as a ledger, with figures read right', () => {
    show('| check | rate |\n|---|---|\n| money_traceable | 96% |')
    const table = screen.getByRole('table')
    expect(within(table).getByRole('columnheader', { name: 'check' })).toBeInTheDocument()
    const figure = within(table).getByText('96%')
    expect(figure).toHaveClass('listing__num')
    expect(within(table).getByText('money_traceable')).not.toHaveClass('listing__num')
  })

  it('keeps a fenced block as it was written, indentation and all', () => {
    const { container } = show('```\nuv run pytest\n  indented\n```')
    const block = container.querySelector('.md__code')
    expect(block).toHaveTextContent('uv run pytest')
    expect(block?.textContent).toBe('uv run pytest\n  indented')
  })

  it('renders both kinds of list', () => {
    const { container } = show('- one\n- two\n\n1. first\n2. second')
    expect(container.querySelectorAll('ul li')).toHaveLength(2)
    expect(container.querySelectorAll('ol li')).toHaveLength(2)
  })

  it('reads inline code, bold and links inside a line', () => {
    show('see `checks.py`, which is **the judge**, in [the repo](https://example.com/x)')
    expect(screen.getByText('checks.py').tagName).toBe('CODE')
    expect(screen.getByText('the judge').tagName).toBe('STRONG')
    const link = screen.getByRole('link', { name: 'the repo' })
    expect(link).toHaveAttribute('href', 'https://example.com/x')
    expect(link).toHaveAttribute('rel', expect.stringContaining('noreferrer'))
  })

  it('draws a horizontal rule', () => {
    const { container } = show('above\n\n---\n\nbelow')
    expect(container.querySelector('hr')).toBeInTheDocument()
  })

  it('never turns markup in the file into markup on the page', () => {
    // The report is data. A <script> in it is four words, not a script.
    show('a line with <script>alert(1)</script> in it')
    expect(document.querySelector('script')).toBeNull()
    expect(screen.getByText(/<script>alert\(1\)<\/script>/)).toBeInTheDocument()
  })
})

describe('the report as it actually is', () => {
  it('renders the whole of evals/REPORT.md without falling over', () => {
    // The sample is a stub; the real file is nineteen hundred lines of headings, tables,
    // fenced code and prose, and it is the only document this renderer exists for.
    // Read rather than imported: the file is outside the Vite root, which `?raw` refuses.
    const report = readFileSync(resolve(process.cwd(), '../evals/REPORT.md'), 'utf8')
    const { container } = render(<Markdown text={report} />)

    expect(container.querySelectorAll('h2, h3, h4').length).toBeGreaterThan(20)
    expect(container.querySelectorAll('table').length).toBeGreaterThan(5)
    expect(container.querySelectorAll('.md__code').length).toBeGreaterThan(5)
    // Nothing was dropped on the floor: every non-blank line reached the page.
    const rendered = container.textContent ?? ''
    expect(rendered).toContain('Ledgerline evaluation report')
    expect(rendered.length).toBeGreaterThan(40_000)
  })
})
