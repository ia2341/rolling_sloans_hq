import type { ReactNode } from 'react'

import { useIsPhone } from '../../hooks/useIsPhone'

interface PageHeadProps {
  title: string
  subline?: string
  /** The surface's single admin action, e.g. `Edit setlist`, `+ Add songs` (issue #328). */
  action?: ReactNode
}

/**
 * `<h1>`, a sub-line, and a right-aligned slot for one admin action (issue
 * #328). Every read and edit surface uses this, which is what keeps the
 * Edit button in the same place on every page.
 *
 * On a phone, the `<h1>` is dropped: `TopBar` already names the surface
 * from the same title via `usePageTitle()`, and rendering it twice would
 * spend the phone's chrome budget on a duplicate heading. The subline and
 * action still render there, since neither exists in the top bar.
 */
export function PageHead({ title, subline, action }: PageHeadProps) {
  const isPhone = useIsPhone()

  return (
    <div className="flex items-start justify-between gap-3 pb-4">
      <div>
        {!isPhone && <h1 className="text-xl font-semibold">{title}</h1>}
        {subline !== undefined && (
          <p className="text-sm text-rs-muted">{subline}</p>
        )}
      </div>
      {action !== undefined && <div className="shrink-0">{action}</div>}
    </div>
  )
}
