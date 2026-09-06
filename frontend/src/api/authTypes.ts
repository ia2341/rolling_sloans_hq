/** Wire types for `GET`/`POST /api/login/` (issue #362), the SPA's own sign-in endpoint. */

import type { AppContext } from './types'

/** `GET /api/login/`'s response: whether this browser already carries an authenticated session. */
export type LoginStatus =
  { authenticated: false } | { authenticated: true; context: AppContext }

/** Why a `POST /api/login/` failed — never which half (email vs. password) was wrong (#327, ADR 0013). */
export type LoginFailureReason = 'invalid_credentials' | 'throttled'

/** `POST /api/login/`'s response: the new session's context on success, or a generic failure reason. */
export type LoginResult =
  { ok: true; context: AppContext } | { ok: false; reason: LoginFailureReason }
