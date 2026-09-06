import type { RouteObject } from 'react-router-dom'

import { Band } from './routes/Band'
import { ConflictAdjudicationDetail } from './routes/ConflictAdjudicationDetail'
import { ConflictAdjudicationIndex } from './routes/ConflictAdjudicationIndex'
import { Home } from './routes/Home'
import { NotFound } from './routes/NotFound'
import { Person } from './routes/Person'
import { ProfileRedirect } from './routes/ProfileRedirect'
import { Schedule } from './routes/Schedule'
import { ScheduleEdit } from './routes/ScheduleEdit'
import { Setlist } from './routes/Setlist'
import { Song } from './routes/Song'
import { AppShell } from './shell/AppShell'

/**
 * The app's route table (issue #328), shared between the browser router
 * (`router.tsx`) and tests (which mount it in a `MemoryRouter` instead).
 * `AppShell` wraps every route via a layout route, so nav chrome is never a
 * per-page concern. Home (#332), Setlist, Song detail (#330), Schedule
 * (#331), Band/Person (#333), the rehearsal schedule editor (#337) and
 * Conflict adjudication (#340) are built end to end.
 * `/schedule` absorbed `/me/conflicts/` outright (issue #190) — there is no
 * member-facing `/conflicts` route, and no redirect from one. `/conflicts`
 * below is a different, admin-only surface (#340): the adjudication index
 * and detail, unrelated to that member-facing absorption.
 */
export const routes: RouteObject[] = [
  {
    element: <AppShell />,
    children: [
      { path: '/', element: <Home /> },
      { path: '/schedule', element: <Schedule /> },
      { path: '/schedule/edit', element: <ScheduleEdit /> },
      { path: '/setlist', element: <Setlist /> },
      { path: '/songs/:songId', element: <Song /> },
      { path: '/members', element: <Band /> },
      { path: '/members/:personId', element: <Person /> },
      { path: '/profile', element: <ProfileRedirect /> },
      { path: '/conflicts', element: <ConflictAdjudicationIndex /> },
      {
        path: '/conflicts/:rehearsalId',
        element: <ConflictAdjudicationDetail />,
      },
      { path: '*', element: <NotFound /> },
    ],
  },
]
