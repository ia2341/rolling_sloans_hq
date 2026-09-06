import type { LoginResult, LoginStatus } from './authTypes'
import { csrfHeader } from './client'

const LOGIN_API_URL = '/api/login/'

/**
 * Calls `GET /api/login/` to ask whether this browser already has an
 * authenticated session (issue #362).
 *
 * Deliberately not routed through `apiFetch()`: that wrapper's whole
 * contract assumes a session already exists (a 401 bounces to `/login`),
 * which is exactly the question this call is answering, so it would be
 * circular here. This endpoint always answers 200, win or lose.
 */
export async function fetchLoginStatus(): Promise<LoginStatus> {
  const response = await fetch(LOGIN_API_URL)
  return (await response.json()) as LoginStatus
}

/**
 * Calls `POST /api/login/` with `email`/`password` to authenticate and
 * start a session (issue #362, ADR 0013).
 *
 * Also not routed through `apiFetch()`, for the same reason as
 * `fetchLoginStatus()` — plus a failed login is a well-formed 200
 * (`{ok: false, reason: ...}`), not the kind of non-2xx `apiFetch()`
 * throws `ApiError` for.
 */
export async function submitLogin(
  email: string,
  password: string,
): Promise<LoginResult> {
  const response = await fetch(LOGIN_API_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...csrfHeader(),
    },
    body: JSON.stringify({ email, password }),
  })
  return (await response.json()) as LoginResult
}
