import type { ReactNode } from 'react'
import { type Route, to } from '../route'

/** Every capability the product has, two clicks from the front page at most. */
const TABS = [
  { name: 'call', href: '/', label: 'New call' },
  { name: 'callers', href: '/callers', label: 'Callers' },
  { name: 'calls', href: '/calls', label: 'Calls' },
  { name: 'evals', href: '/evals', label: 'Evals' },
  { name: 'report', href: '/report', label: 'Report' },
] as const

/** A screen reached from a tab keeps that tab lit. */
const OWNER: Partial<Record<Route['name'], (typeof TABS)[number]['name']>> = {
  caller: 'callers',
  recording: 'calls',
}

/**
 * The console: the wordmark, the tabs, and one screen under them. Links are plain anchors —
 * nothing pushes state, the server serves the app for any path, and a full navigation is
 * both the simplest thing that works and the one the back button already understands.
 */
export function ConsoleShell({ route, children }: { route: Route; children: ReactNode }) {
  return (
    <div className="app">
      <ConsoleTabs route={route} />
      {children}
    </div>
  )
}

/**
 * The tabs on their own, for the front page: the call board mounts one audio element and
 * keeps it, so the screen swaps under a wrapper that never unmounts rather than being
 * wrapped by two different shells.
 */
export function ConsoleTabs({ route, children }: { route: Route; children?: ReactNode }) {
  const current = OWNER[route.name] ?? route.name
  return (
    <header className="masthead masthead--console">
      <p className="masthead__brand">Ledgerline</p>
      {children}
      <nav className="tabs" aria-label="Console">
        {TABS.map((tab) => (
          <a
            key={tab.name}
            className="tabs__tab"
            href={to(tab.href)}
            data-current={tab.name === current || undefined}
            aria-current={tab.name === current ? 'page' : undefined}
          >
            {tab.label}
          </a>
        ))}
      </nav>
    </header>
  )
}
