import { normalisePhone } from './phone'

/** The board, or one person's memory page. */
type Route = { name: 'call' } | { name: 'review'; phone: string }

const CALL: Route = { name: 'call' }
const REVIEW = /^\/review\/users\/([^/]+)\/?$/

/**
 * FastAPI serves the app for any path, so the path is ours to read. A phone that is not a
 * phone is not a page: it would only produce a fetch the server answers with a 404.
 */
export function routeFor(pathname: string): Route {
  const match = REVIEW.exec(pathname)
  if (!match) return CALL
  const phone = normalisePhone(decodeURIComponent(match[1]))
  return phone ? { name: 'review', phone } : CALL
}

/** Nothing pushes state, so the path changes only by a navigation that reloads the app. */
export const useRoute = (): Route => routeFor(window.location.pathname)
