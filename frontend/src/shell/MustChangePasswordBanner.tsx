import { Link } from 'react-router-dom'

import { useAppContext } from '../api/ContextProvider'

/**
 * A persistent nag banner (issue #484) for a viewer whose `must_change_password`
 * flag is still set — i.e. they last logged in with an admin-relayed temp
 * password (ADR 0018) and haven't replaced it. Deliberately a soft,
 * dismiss-nothing banner rather than a hard gate: a 25-person band's trust
 * level doesn't call for blocking the rest of the app, per the issue's own
 * guidance. Links to the viewer's own `/members/:id` page, where
 * `ChangePasswordRow` (issue #333) lives; the banner disappears with no
 * reload the moment that change succeeds, because `PasswordChangeApiView`'s
 * envelope clears the flag and `ContextProvider`'s shared store re-renders
 * every subscriber (including this one) off that same response.
 */
export function MustChangePasswordBanner() {
  const appContext = useAppContext()
  const viewer = appContext?.viewer

  if (viewer === undefined || !viewer.must_change_password) return null

  return (
    <div className="flex items-center justify-between gap-2 border-b border-rs-warning-border bg-rs-warning-bg px-3 py-1.5 text-xs text-rs-warning-fg">
      <span>
        You&apos;re still using the temporary password an admin gave you —
        change it to keep your account secure.
      </span>
      <Link
        to={`/members/${viewer.id}`}
        className="shrink-0 rounded border border-rs-warning-border px-2 py-0.5 font-medium hover:bg-rs-warning-border/30"
      >
        Change password
      </Link>
    </div>
  )
}
