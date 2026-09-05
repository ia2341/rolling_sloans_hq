import { Navigate, useLocation } from 'react-router-dom'

import { useAppContext } from '../api/ContextProvider'

/**
 * `/profile` resolves to the viewer's own person page (issue #328 user
 * story 7) — there is no separate `/me/profile/` route. Redirects once the
 * viewer's id arrives from `context`; renders nothing while it's still
 * `null`, since the shell never fetches context on its own. Forwards the
 * incoming `?song=<id>` (or any other query string) onto the target route
 * (issue #333): Setlist's `+` and the Song page's "+ Add a recording" both
 * link here as `/profile?song=<id>` to preselect that Song's slots in the
 * Person page's upload picker, and dropping the search string here would
 * silently break that deep link.
 */
export function ProfileRedirect() {
  const appContext = useAppContext()
  const location = useLocation()
  if (appContext === null) return null
  return (
    <Navigate
      to={`/members/${appContext.viewer.id}${location.search}`}
      replace
    />
  )
}
