import {
  CalendarDays,
  Home,
  Music,
  TriangleAlert,
  User,
  Users,
  type LucideIcon,
} from 'lucide-react'

export interface NavItem {
  key: string
  label: string
  path: string
  icon: LucideIcon
}

/**
 * The sidebar's fixed nav order (issue #328): Home, Conflicts, Schedule,
 * Songs/Setlist, Band, Profile. Conflicts is deliberately top-level,
 * directly under Home, and carries no count (ADR 0005 — see
 * `Sidebar.tsx`). There is no Semesters item and no Recordings item.
 *
 * Conflicts' `path` deep-links into `/schedule`'s All-rehearsals sub-view
 * (issue #331) rather than a route of its own — `/schedule/` absorbed
 * `/me/conflicts/` outright (issue #190), with no separate route and no
 * redirect.
 */
export const SIDEBAR_NAV_ITEMS: NavItem[] = [
  { key: 'home', label: 'Home', path: '/', icon: Home },
  {
    key: 'conflicts',
    label: 'Conflicts',
    path: '/schedule?view=all',
    icon: TriangleAlert,
  },
  { key: 'schedule', label: 'Schedule', path: '/schedule', icon: CalendarDays },
  { key: 'songs', label: 'Songs/Setlist', path: '/setlist', icon: Music },
  { key: 'band', label: 'Band', path: '/members', icon: Users },
  { key: 'profile', label: 'Profile', path: '/profile', icon: User },
]

/**
 * The phone tab bar's five items (issue #328): Home, Schedule, Songs and
 * Conflicts, plus More (rendered separately by `TabBar.tsx`, not from this
 * list — it opens a sheet rather than navigating).
 */
export const TAB_BAR_NAV_ITEMS: NavItem[] = [
  { key: 'home', label: 'Home', path: '/', icon: Home },
  { key: 'schedule', label: 'Schedule', path: '/schedule', icon: CalendarDays },
  { key: 'songs', label: 'Songs', path: '/setlist', icon: Music },
  {
    key: 'conflicts',
    label: 'Conflicts',
    path: '/schedule?view=all',
    icon: TriangleAlert,
  },
]
