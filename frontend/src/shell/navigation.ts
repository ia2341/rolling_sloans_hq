import {
  CalendarDays,
  Home,
  Music,
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
 * The sidebar's fixed nav order (issue #328, Conflicts removed by the
 * pills/tables UI overhaul): Home, Schedule, Songs/Setlist, Band, Profile.
 * There is no Semesters item and no Recordings item.
 *
 * There is no standalone Conflicts nav item — it used to deep-link into
 * `/schedule`'s All-rehearsals sub-view, which duplicated the Schedule
 * item itself (both pointed at the same page). Schedule's own
 * "All rehearsals" sub-view is reached from within `/schedule`. The
 * separate admin-only `/conflicts` adjudication surface is unaffected —
 * it's reached via the "Adjudicate conflicts" button on Schedule, not
 * from the sidebar.
 */
export const SIDEBAR_NAV_ITEMS: NavItem[] = [
  { key: 'home', label: 'Home', path: '/', icon: Home },
  { key: 'schedule', label: 'Schedule', path: '/schedule', icon: CalendarDays },
  { key: 'songs', label: 'Songs/Setlist', path: '/setlist', icon: Music },
  { key: 'band', label: 'Band', path: '/members', icon: Users },
  { key: 'profile', label: 'Profile', path: '/profile', icon: User },
]

/**
 * The phone tab bar's items (issue #328, Conflicts removed — see
 * `SIDEBAR_NAV_ITEMS`): Home, Schedule, Songs, plus More (rendered
 * separately by `TabBar.tsx`, not from this list — it opens a sheet
 * rather than navigating).
 */
export const TAB_BAR_NAV_ITEMS: NavItem[] = [
  { key: 'home', label: 'Home', path: '/', icon: Home },
  { key: 'schedule', label: 'Schedule', path: '/schedule', icon: CalendarDays },
  { key: 'songs', label: 'Songs', path: '/setlist', icon: Music },
]

/**
 * Whether a nav item should render as active for the current location.
 *
 * Compares only `location.pathname` against the item's path — now that
 * no two nav items share a pathname (Conflicts, which used to share
 * `/schedule` with a `view` query param, is gone), a simple prefix match
 * is enough.
 */
export function isNavItemActive(
  item: NavItem,
  location: { pathname: string; search: string },
): boolean {
  const itemPath = item.path.split('?')[0]
  return itemPath === '/'
    ? location.pathname === '/'
    : location.pathname === itemPath ||
        location.pathname.startsWith(`${itemPath}/`)
}
