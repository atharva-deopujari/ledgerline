import { normalisePhone } from './phone'

/** The console's screens. Every one is reachable from `/` in two clicks or fewer. */
export type Route =
  | { name: 'call' }
  | { name: 'callers' }
  | { name: 'caller'; phone: string }
  | { name: 'calls' }
  | { name: 'recording'; id: string }
  | { name: 'evals' }
  | { name: 'report' }

const CALL: Route = { name: 'call' }

/** `/callers/<phone>`, and the `/review/users/<phone>` path the HLD published for the same page. */
const CALLER = /^\/(?:callers|review\/users)\/([^/]+)\/?$/
/** A recording's id is a file basename: no slash, no dots that could climb out of the directory. */
const RECORDING = /^\/calls\/([A-Za-z0-9_-][A-Za-z0-9._-]*)\/?$/
const PLAIN: Record<string, Route> = {
  '/callers': { name: 'callers' },
  '/calls': { name: 'calls' },
  '/evals': { name: 'evals' },
  '/report': { name: 'report' },
}

/**
 * FastAPI serves the app for any path, so the path is ours to read. An id or a phone that
 * could not name a real thing is not a page: it would only produce a fetch the server
 * answers with a 404.
 */
export function routeFor(pathname: string): Route {
  const path = pathname.replace(/\/+$/, '') || '/'
  if (path in PLAIN) return PLAIN[path]!

  const caller = CALLER.exec(pathname)
  if (caller) {
    const phone = normalisePhone(decodeURIComponent(caller[1]!))
    return phone ? { name: 'caller', phone } : CALL
  }

  const recording = RECORDING.exec(pathname)
  if (recording) {
    const id = decodeURIComponent(recording[1]!)
    return id.includes('..') ? CALL : { name: 'recording', id }
  }

  return CALL
}

/** Nothing pushes state, so the path changes only by a navigation that reloads the app. */
export const useRoute = (): Route => routeFor(window.location.pathname)

/**
 * A link that keeps `?mock=1` when it is on. The console is navigated by ordinary
 * navigations, so without this the demo would fall back to the real endpoints on the second
 * click and every screenshot would need a backend.
 */
export const to = (path: string): string =>
  new URLSearchParams(window.location.search).get('mock') === '1' ? `${path}?mock=1` : path
