import { ChevronLeft, ChevronRight, LogOut } from 'lucide-react'
import { NavLink } from 'react-router-dom'

import { useAppContext } from '../api/ContextProvider'
import { BlockNote } from '../components/ui/BlockNote'
import { useRailCollapsed } from '../hooks/useRailCollapsed'
import { cn } from '../lib/utils'
import { useEditSession } from './EditSessionContext'
import { SIDEBAR_NAV_ITEMS } from './navigation'
import { SemesterPanel } from './SemesterPanel'

/**
 * The desktop nav shell (issue #328): brand + rail toggle, the fixed nav
 * order, the stale-Semester `BlockNote` (above the semester panel, never
 * near the grid it concerns — ADR 0008), the semester panel (admin only),
 * and a quiet Log out button in its own panel at the foot. Does not scroll
 * with the page content, so nav stays reachable from anywhere.
 */
export function Sidebar() {
  const [collapsed, toggleCollapsed] = useRailCollapsed()
  const appContext = useAppContext()
  const editSession = useEditSession()
  const isAdmin = appContext?.viewer.is_admin ?? false

  return (
    <nav
      aria-label="Primary"
      className={cn(
        'sticky top-0 flex h-screen shrink-0 flex-col border-r border-rs-border bg-rs-surface',
        collapsed ? 'w-16' : 'w-64',
      )}
    >
      <div className="flex items-center justify-between border-b border-rs-border px-3 py-3">
        {!collapsed && (
          <span className="truncate font-semibold">Rolling Sloans</span>
        )}
        <button
          type="button"
          onClick={toggleCollapsed}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          className="ml-auto rounded p-1 text-rs-muted hover:bg-rs-border/40 hover:text-rs-fg"
        >
          {collapsed ? (
            <ChevronRight size={18} aria-hidden="true" />
          ) : (
            <ChevronLeft size={18} aria-hidden="true" />
          )}
        </button>
      </div>

      <ul className="flex flex-1 flex-col gap-0.5 overflow-y-auto px-2 py-3">
        {SIDEBAR_NAV_ITEMS.map((item) => (
          <li key={item.key}>
            <NavLink
              to={item.path}
              end={item.path === '/'}
              title={collapsed ? item.label : undefined}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 rounded px-2.5 py-2 text-sm font-medium',
                  isActive
                    ? 'bg-rs-accent text-rs-accent-fg'
                    : 'text-rs-fg hover:bg-rs-border/40',
                )
              }
            >
              <item.icon size={18} aria-hidden="true" className="shrink-0" />
              {!collapsed && <span className="truncate">{item.label}</span>}
            </NavLink>
          </li>
        ))}
      </ul>

      {editSession?.blockedReason != null && (
        <BlockNote message={editSession.blockedReason} collapsed={collapsed} />
      )}

      {isAdmin && <SemesterPanel collapsed={collapsed} />}

      <div className="border-t border-rs-border p-2">
        <form action="/accounts/logout/" method="post" className="contents">
          <CsrfField />
          <button
            type="submit"
            title={collapsed ? 'Log out' : undefined}
            className="flex w-full items-center gap-3 rounded px-2.5 py-2 text-sm text-rs-muted hover:bg-rs-border/40 hover:text-rs-fg"
          >
            <LogOut size={18} aria-hidden="true" className="shrink-0" />
            {!collapsed && <span>Log out</span>}
          </button>
        </form>
      </div>
    </nav>
  )
}

/** Reads the CSRF cookie `SpaIndexView` sets so the log-out form POST passes Django's CSRF check. */
function CsrfField() {
  const match = document.cookie.match(/(?:^|; )csrftoken=([^;]*)/)
  const token = match ? decodeURIComponent(match[1] ?? '') : ''
  return <input type="hidden" name="csrfmiddlewaretoken" value={token} />
}
