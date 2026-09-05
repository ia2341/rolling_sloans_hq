import { setContext } from './contextStore'
import type { AppContext } from './types'

const LOGIN_URL = '/accounts/login/'
const CSRF_COOKIE_NAME = 'csrftoken'
const CSRF_HEADER_NAME = 'X-CSRFToken'
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])

/** Raised for a non-2xx `/api/` response other than the 401 the wrapper handles itself. */
export class ApiError extends Error {
  readonly status: number
  readonly body: unknown

  constructor(status: number, body: unknown) {
    super(`/api/ request failed with status ${status}`)
    this.status = status
    this.body = body
  }
}

function readCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`))
  return match ? decodeURIComponent(match[1] ?? '') : null
}

/**
 * The one fetch wrapper every `/api/` call in the SPA goes through (issue
 * #326, consumed by #328's `ContextProvider`).
 *
 * - Attaches the CSRF header (`ensure_csrf_cookie` on `SpaIndexView` sets
 *   the cookie this reads) on every unsafe method.
 * - A 401 means the session expired: rather than resolve with a body the
 *   caller has to notice, this navigates the whole page to the login
 *   screen and returns a promise that never resolves, so no caller has to
 *   guard every call site against a session that died mid-request.
 * - Every other non-2xx status rejects with `ApiError`, carrying the
 *   parsed body so a caller can read `errors`/`non_field_errors` off a
 *   write envelope's failure shape.
 * - On success, updates the shared context store from the response's
 *   `context` block — the shell never fetches context on its own.
 */
export async function apiFetch<TEnvelope extends { context: AppContext }>(
  path: string,
  init: RequestInit = {},
): Promise<TEnvelope> {
  const method = (init.method ?? 'GET').toUpperCase()
  const headers = new Headers(init.headers)
  if (init.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  if (!SAFE_METHODS.has(method)) {
    const csrfToken = readCookie(CSRF_COOKIE_NAME)
    if (csrfToken !== null) headers.set(CSRF_HEADER_NAME, csrfToken)
  }

  const response = await fetch(path, { ...init, method, headers })

  if (response.status === 401) {
    window.location.assign(LOGIN_URL)
    return new Promise<TEnvelope>(() => {})
  }

  const body = (await response.json()) as unknown

  if (!response.ok) {
    throw new ApiError(response.status, body)
  }

  const envelope = body as TEnvelope
  setContext(envelope.context)
  return envelope
}
