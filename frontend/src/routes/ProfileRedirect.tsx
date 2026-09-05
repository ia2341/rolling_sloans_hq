import { Navigate } from 'react-router-dom'

import { useAppContext } from '../api/ContextProvider'

/**
 * `/profile` resolves to the viewer's own person page (issue #328 user
 * story 7) — there is no separate `/me/profile/` route. Redirects once the
 * viewer's id arrives from `context`; renders nothing while it's still
 * `null`, since the shell never fetches context on its own.
 */
export function ProfileRedirect() {
  const appContext = useAppContext()
  if (appContext === null) return null
  return <Navigate to={`/members/${appContext.viewer.id}`} replace />
}
