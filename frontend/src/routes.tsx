import type { RouteObject } from 'react-router-dom'

import { NotFound } from './routes/NotFound'
import { PlaceholderPage } from './routes/PlaceholderPage'
import { ProfileRedirect } from './routes/ProfileRedirect'
import { Setlist } from './routes/Setlist'
import { Song } from './routes/Song'
import { AppShell } from './shell/AppShell'

/**
 * The app's route table (issue #328), shared between the browser router
 * (`router.tsx`) and tests (which mount it in a `MemoryRouter` instead).
 * `AppShell` wraps every route via a layout route, so nav chrome is never a
 * per-page concern. Home, Schedule/Conflicts and Band/Person are still
 * placeholders (#332, #331, #333); Setlist and Song detail are #330's —
 * the SPA's first two read surfaces built end to end.
 */
export const routes: RouteObject[] = [
  {
    element: <AppShell />,
    children: [
      {
        path: '/',
        element: <PlaceholderPage title="Home" owningIssue="#332" />,
      },
      {
        path: '/conflicts',
        element: <PlaceholderPage title="Conflicts" owningIssue="#331" />,
      },
      {
        path: '/schedule',
        element: <PlaceholderPage title="Schedule" owningIssue="#331" />,
      },
      { path: '/setlist', element: <Setlist /> },
      { path: '/songs/:songId', element: <Song /> },
      {
        path: '/members',
        element: <PlaceholderPage title="Band" owningIssue="#333" />,
      },
      {
        path: '/members/:personId',
        element: <PlaceholderPage title="Member" owningIssue="#333" />,
      },
      { path: '/profile', element: <ProfileRedirect /> },
      { path: '*', element: <NotFound /> },
    ],
  },
]
