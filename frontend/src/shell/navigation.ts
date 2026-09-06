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
 * is enough for every item except Band vs. Profile (issue #363): the
 * Profile item's real destination, `/members/:personId` for the viewer's
 * own id (reached via `ProfileRedirect` from `/profile`), also matches
 * the Band item's `/members` prefix, so without this special case Band
 * would always win the highlight on your own Person page. `viewerId` is
 * the logged-in viewer's own id (`context.viewer.id`); omit it (e.g. a
 * logged-out render) to fall back to the plain prefix match, which always
 * favors Band on `/members/:personId`.
 */
export function isNavItemActive(
  item: NavItem,
  location: { pathname: string; search: string },
  viewerId?: number,
): boolean {
  // Special-cased ahead of the plain prefix match below: `/members/:id`
  // is Band's own path prefix, but it's also where `ProfileRedirect`
  // lands the Profile item's click — so on the viewer's own id, Profile
  // must win the highlight instead of Band, even though Profile's `path`
  // (`/profile`) itself never matches this pathname by prefix.
  const memberDetailMatch = /^\/members\/(\d+)(?:\/|$)/.exec(location.pathname)
  if (
    memberDetailMatch !== null &&
    (item.key === 'band' || item.key === 'profile')
  ) {
    const viewedPersonId = Number(memberDetailMatch[1])
    const isOwnProfile = viewerId !== undefined && viewedPersonId === viewerId
    return item.key === 'profile' ? isOwnProfile : !isOwnProfile
  }

  const itemPath = item.path.split('?')[0]
  return itemPath === '/'
    ? location.pathname === '/'
    : location.pathname === itemPath ||
        location.pathname.startsWith(`${itemPath}/`)
}
