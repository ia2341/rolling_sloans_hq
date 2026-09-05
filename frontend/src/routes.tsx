import type { RouteObject } from 'react-router-dom'

import { NotFound } from './routes/NotFound'
import { PlaceholderPage } from './routes/PlaceholderPage'
import { ProfileRedirect } from './routes/ProfileRedirect'
import { AppShell } from './shell/AppShell'

/**
 * The app's route table (issue #328), shared between the browser router
 * (`router.tsx`) and tests (which mount it in a `MemoryRouter` instead).
 * `AppShell` wraps every route via a layout route, so nav chrome is never a
 * per-page concern. Every page here but `NotFound` and `ProfileRedirect`
 * is a placeholder: the real Home, Schedule, Setlist/Song, Band/Person and
 * Conflicts surfaces are #330-#333's — this ticket owns the shell and the
 * six nav destinations being reachable.
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
      {
        path: '/setlist',
        element: <PlaceholderPage title="Setlist" owningIssue="#330" />,
      },
      {
        path: '/songs/:songId',
        element: <PlaceholderPage title="Song" owningIssue="#330" />,
      },
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
