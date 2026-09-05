import type { RouteObject } from 'react-router-dom'

import { Band } from './routes/Band'
import { NotFound } from './routes/NotFound'
import { Person } from './routes/Person'
import { PlaceholderPage } from './routes/PlaceholderPage'
import { ProfileRedirect } from './routes/ProfileRedirect'
import { Setlist } from './routes/Setlist'
import { Song } from './routes/Song'
import { AppShell } from './shell/AppShell'

/**
 * The app's route table (issue #328), shared between the browser router
 * (`router.tsx`) and tests (which mount it in a `MemoryRouter` instead).
 * `AppShell` wraps every route via a layout route, so nav chrome is never a
 * per-page concern. Home and Schedule/Conflicts are still placeholders
 * (#332, #331); Setlist, Song detail (#330) and Band/Person (#333) are
 * built end to end.
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
      { path: '/members', element: <Band /> },
      { path: '/members/:personId', element: <Person /> },
      { path: '/profile', element: <ProfileRedirect /> },
      { path: '*', element: <NotFound /> },
    ],
  },
]
