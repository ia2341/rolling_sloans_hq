import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { useIsPhone } from '../../hooks/useIsPhone'

interface PageHeadProps {
  title: string
  subline?: string
  /** The surface's single admin action, e.g. `Edit setlist`, `+ Add songs` (issue #328). */
  action?: ReactNode
  /**
   * A route this page was reached *from* and has no other way back to —
   * an admin destination the sidebar doesn't link (`/conflicts`), or one
   * only reachable via a button on another page (`/schedule/edit`) rather
   * than a link a phone's `TopBar` or browser-back reliably returns to
   * (issue: UI overhaul round 2, item 6). Renders a small `← Back` link
   * above the title, on every breakpoint.
   */
  backTo?: string
  backLabel?: string
}

/**
 * `<h1>`, a sub-line, and a right-aligned slot for one admin action (issue
 * #328). Every read and edit surface uses this, which is what keeps the
 * Edit button in the same place on every page.
 *
 * On a phone, the `<h1>` is dropped: `TopBar` already names the surface
 * from the same title via `usePageTitle()`, and rendering it twice would
 * spend the phone's chrome budget on a duplicate heading. The subline and
 * action still render there, since neither exists in the top bar. `backTo`
 * renders regardless of breakpoint, since neither the phone `TopBar` nor
 * the desktop sidebar reliably gets a viewer back from every admin surface.
 */
export function PageHead({
  title,
  subline,
  action,
  backTo,
  backLabel = 'Back',
}: PageHeadProps) {
  const isPhone = useIsPhone()

  return (
    <div className="pb-4">
      {backTo !== undefined && (
        <Link to={backTo} className="mb-1 inline-block text-sm text-rs-accent">
          ← {backLabel}
        </Link>
      )}
      <div className="flex items-start justify-between gap-3">
        <div>
          {!isPhone && <h1 className="text-xl font-semibold">{title}</h1>}
          {subline !== undefined && (
            <p className="text-sm text-rs-muted">{subline}</p>
          )}
        </div>
        {action !== undefined && <div className="shrink-0">{action}</div>}
      </div>
    </div>
  )
}
