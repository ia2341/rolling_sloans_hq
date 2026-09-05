import type { RouteObject } from 'react-router-dom'

import { NotFound } from './routes/NotFound'
import { PlaceholderPage } from './routes/PlaceholderPage'
import { ProfileRedirect } from './routes/ProfileRedirect'
import { Schedule } from './routes/Schedule'
import { Setlist } from './routes/Setlist'
import { Song } from './routes/Song'
import { AppShell } from './shell/AppShell'

/**
 * The app's route table (issue #328), shared between the browser router
 * (`router.tsx`) and tests (which mount it in a `MemoryRouter` instead).
 * `AppShell` wraps every route via a layout route, so nav chrome is never a
 * per-page concern. Home and Band/Person are still placeholders (#332,
 * #333); Setlist, Song detail and Schedule are built end to end. `/schedule`
 * absorbed `/me/conflicts/` outright (issue #190) — there is no
 * `/conflicts` route at all, and no redirect from one.
 */
export const routes: RouteObject[] = [
  {
    element: <AppShell />,
    children: [
      {
        path: '/',
        element: <PlaceholderPage title="Home" owningIssue="#332" />,
      },
      { path: '/schedule', element: <Schedule /> },
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
