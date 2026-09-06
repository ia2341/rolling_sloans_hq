import type { FormEvent } from 'react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { fetchLoginStatus, submitLogin } from '../api/auth'
import type { LoginFailureReason } from '../api/authTypes'
import { setContext } from '../api/contextStore'

/** Copy for each `LoginFailureReason` (#327/ADR 0013: never say which of email/password was wrong). */
const FAILURE_MESSAGES: Record<LoginFailureReason, string> = {
  invalid_credentials: 'Incorrect email or password.',
  throttled: 'Too many attempts. Please wait a while and try again.',
}

/**
 * `/login` (issue #362): the SPA's own sign-in page, deliberately outside
 * `AppShell` — see `routes.tsx` — since there is no session, no `context`,
 * and so nothing for the sidebar/nav chrome to render yet.
 *
 * Two fetches, not one: `fetchLoginStatus()` on mount bounces an
 * already-authenticated visitor straight to `/`, and `submitLogin()` on
 * submit is the actual sign-in POST. Both go through `api/auth.ts` rather
 * than the shared `apiFetch()` wrapper, since that wrapper's 401-bounces-
 * to-`/login` contract assumes a session already exists — exactly the
 * thing neither of these calls can assume. Deliberately just Email,
 * Password and one Sign In button: no forgot-password link, no sign-up
 * link (there is no self-registration — `identity/services.py`'s
 * `invite_person()` is the only path to an account).
 */
export function Login() {
  const navigate = useNavigate()
  const [checkingStatus, setCheckingStatus] = useState(true)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    void fetchLoginStatus().then((status) => {
      if (cancelled) return
      if (status.authenticated) {
        setContext(status.context)
        navigate('/', { replace: true })
        return
      }
      setCheckingStatus(false)
    })
    return () => {
      cancelled = true
    }
  }, [navigate])

  /** Submits the form: posts credentials, and on success seeds the context store before navigating to Home. */
  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitting(true)
    setErrorMessage(null)
    void submitLogin(email, password).then((result) => {
      if (result.ok) {
        setContext(result.context)
        navigate('/', { replace: true })
        return
      }
      setSubmitting(false)
      setErrorMessage(FAILURE_MESSAGES[result.reason])
    })
  }

  if (checkingStatus) return null

  return (
    <div className="flex min-h-screen items-center justify-center bg-rs-bg px-4">
      <div className="w-full max-w-sm rounded-lg border border-rs-border bg-rs-surface p-6 shadow-sm">
        <h1 className="text-xl font-semibold text-rs-fg">Rolling Sloans</h1>
        <p className="pt-1 text-sm text-rs-muted">Sign in to continue.</p>

        <form className="pt-5" onSubmit={handleSubmit}>
          <label className="block pb-3 text-sm">
            <span className="block pb-1 font-medium text-rs-fg">Email</span>
            <input
              type="email"
              name="email"
              autoComplete="username"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="w-full rounded border border-rs-border bg-rs-surface px-3 py-2 text-sm text-rs-fg focus:outline focus:outline-2 focus:outline-offset-2 focus:outline-rs-accent"
            />
          </label>

          <label className="block pb-4 text-sm">
            <span className="block pb-1 font-medium text-rs-fg">Password</span>
            <input
              type="password"
              name="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="w-full rounded border border-rs-border bg-rs-surface px-3 py-2 text-sm text-rs-fg focus:outline focus:outline-2 focus:outline-offset-2 focus:outline-rs-accent"
            />
          </label>

          {errorMessage !== null && (
            <p className="pb-4 text-sm text-rs-danger" role="alert">
              {errorMessage}
            </p>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded bg-rs-accent px-3 py-2 text-sm font-medium text-rs-accent-fg disabled:opacity-60"
          >
            {submitting ? 'Signing in…' : 'Sign In'}
          </button>
        </form>
      </div>
    </div>
  )
}
