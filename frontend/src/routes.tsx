import type { RouteObject } from 'react-router-dom'

import { NotFound } from './routes/NotFound'
import { Root } from './routes/Root'

/**
 * The app's route table, shared between the browser router (`router.tsx`)
 * and tests (which mount it in a `MemoryRouter` instead). Ships here with a
 * single placeholder route and a not-found route, enough to prove the
 * Django catch-all end to end; the real route table is issue #328's.
 */
export const routes: RouteObject[] = [
  {
    path: '/',
    element: <Root />,
  },
  {
    path: '*',
    element: <NotFound />,
  },
]
