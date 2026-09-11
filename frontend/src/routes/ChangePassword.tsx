import type { FormEvent } from 'react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { apiFetch } from '../api/client'
import type { WriteEnvelope } from '../api/types'

/**
 * `/change-password` (issue #487, ADR 0018): the one route a signed-in
 * Person with `must_change_password=True` can still reach, along with
 * `PasswordChangeApiView` itself — everything else answers the
 * request-level gate's 403, which `apiFetch()` turns into a full-page
 * navigation here, the same way a 401 lands on `/login`.
 *
 * Deliberately outside `AppShell` (see `routes.tsx`), matching `Login`:
 * there is nothing this page needs from the shared `context` fetch, and a
 * gated route mounted underneath `AppShell` would just bounce back here
 * anyway. Posts to the same `/api/password/` endpoint the voluntary
 * change-password affordance on `/members/<pk>/` uses
 * (`PasswordChangeApiView`) — a real, validated change is what clears the
 * flag server-side, whether it happened here (forced) or there
 * (voluntary).
 */
export function ChangePassword() {
  const navigate = useNavigate()
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword1, setNewPassword1] = useState('')
  const [newPassword2, setNewPassword2] = useState('')
  const [errors, setErrors] = useState<Record<string, string[]>>({})
  const [submitting, setSubmitting] = useState(false)

  /** Submits the three password fields; on success, the forced-change condition is cleared, so it's safe to enter the app. */
  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitting(true)
    setErrors({})
    void apiFetch<WriteEnvelope>('/api/password/', {
      method: 'POST',
      body: JSON.stringify({
        old_password: oldPassword,
        new_password1: newPassword1,
        new_password2: newPassword2,
      }),
    }).then((envelope) => {
      if (envelope.ok) {
        navigate('/', { replace: true })
        return
      }
      setSubmitting(false)
      setErrors(envelope.errors)
    })
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-rs-bg px-4">
      <div className="w-full max-w-sm rounded-lg border border-rs-border bg-rs-surface p-6 shadow-sm">
        <h1 className="text-xl font-semibold text-rs-fg">Set a new password</h1>
        <p className="pt-1 text-sm text-rs-muted">
          An admin gave you a temp password to sign in. Choose your own before
          continuing.
        </p>

        <form className="pt-5 flex flex-col gap-3" onSubmit={handleSubmit}>
          <label className="flex flex-col gap-1 text-sm">
            Temp password
            <input
              type="password"
              autoComplete="current-password"
              required
              value={oldPassword}
              onChange={(event) => setOldPassword(event.target.value)}
              className="rounded border border-rs-border px-2 py-1"
            />
            {errors.old_password?.map((message) => (
              <span key={message} className="text-rs-danger">
                {message}
              </span>
            ))}
          </label>
          <label className="flex flex-col gap-1 text-sm">
            New password
            <input
              type="password"
              autoComplete="new-password"
              required
              value={newPassword1}
              onChange={(event) => setNewPassword1(event.target.value)}
              className="rounded border border-rs-border px-2 py-1"
            />
            {errors.new_password1?.map((message) => (
              <span key={message} className="text-rs-danger">
                {message}
              </span>
            ))}
          </label>
          <label className="flex flex-col gap-1 text-sm">
            Confirm new password
            <input
              type="password"
              autoComplete="new-password"
              required
              value={newPassword2}
              onChange={(event) => setNewPassword2(event.target.value)}
              className="rounded border border-rs-border px-2 py-1"
            />
            {errors.new_password2?.map((message) => (
              <span key={message} className="text-rs-danger">
                {message}
              </span>
            ))}
          </label>

          <button
            type="submit"
            disabled={submitting}
            className="mt-2 w-full rounded bg-rs-accent px-3 py-2 text-sm font-medium text-rs-accent-fg disabled:opacity-60"
          >
            {submitting ? 'Saving…' : 'Save password'}
          </button>
        </form>
      </div>
    </div>
  )
}
