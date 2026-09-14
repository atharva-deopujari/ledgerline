import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ConsoleShell } from './ConsoleShell'

const shell = (route: Parameters<typeof ConsoleShell>[0]['route']) =>
  render(
    <ConsoleShell route={route}>
      <main>a screen</main>
    </ConsoleShell>,
  )

describe('the console shell', () => {
  it('offers every capability as a tab', () => {
    shell({ name: 'call' })
    const nav = screen.getByRole('navigation', { name: /console/i })
    expect(
      within(nav)
        .getAllByRole('link')
        .map((a) => a.getAttribute('href')),
    ).toEqual(['/', '/callers', '/calls', '/evals', '/report'])
  })

  it('lights the tab you are on', () => {
    shell({ name: 'calls' })
    expect(screen.getByRole('link', { current: 'page' })).toHaveTextContent('Calls')
  })

  it('keeps the parent tab lit on a screen reached from it', () => {
    // A caller belongs to Callers, a recording to Calls: the tab says where you are.
    shell({ name: 'caller', phone: '9876543210' })
    expect(screen.getByRole('link', { current: 'page' })).toHaveTextContent('Callers')
    shell({ name: 'recording', id: 'voice-1' })
    expect(screen.getAllByRole('link', { current: 'page' })[1]).toHaveTextContent('Calls')
  })

  it('puts the screen under the tabs', () => {
    shell({ name: 'report' })
    expect(screen.getByRole('main')).toHaveTextContent('a screen')
  })
})
