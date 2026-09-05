import type { RouteObject } from 'react-router-dom'

import { Band } from './routes/Band'
import { NotFound } from './routes/NotFound'
import { Person } from './routes/Person'
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
 * per-page concern. Home is still a placeholder (#332); Setlist, Song detail
 * (#330), Schedule (#331) and Band/Person (#333) are built end to end.
 * `/schedule` absorbed `/me/conflicts/` outright (issue #190) — there is no
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
      { path: '/members', element: <Band /> },
      { path: '/members/:personId', element: <Person /> },
      { path: '/profile', element: <ProfileRedirect /> },
      { path: '*', element: <NotFound /> },
    ],
  },
]
