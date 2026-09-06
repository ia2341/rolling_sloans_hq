import { Menu } from 'lucide-react'
import { useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'

import { cn } from '../lib/utils'
import { MoreSheet } from './MoreSheet'
import { isNavItemActive, TAB_BAR_NAV_ITEMS } from './navigation'

/**
 * The phone bottom tab bar (issue #328): exactly five items — Home,
 * Schedule, Songs, Conflicts, and More — with `aria-current` on whichever
 * is active. Fixed to the viewport bottom so it stays thumb-reachable
 * regardless of scroll position.
 */
export function TabBar() {
  const [moreOpen, setMoreOpen] = useState(false)
  const location = useLocation()

  return (
    <>
      <nav
        aria-label="Primary"
        className="fixed inset-x-0 bottom-0 z-20 flex border-t border-rs-border bg-rs-surface"
      >
        {TAB_BAR_NAV_ITEMS.map((item) => {
          const isActive = isNavItemActive(item, location)
          return (
            <NavLink
              key={item.key}
              to={item.path}
              className={cn(
                'flex flex-1 flex-col items-center gap-0.5 py-2 text-xs font-medium',
                isActive ? 'text-rs-accent' : 'text-rs-muted',
              )}
            >
              <item.icon size={20} aria-hidden="true" />
              {item.label}
            </NavLink>
          )
        })}
        <button
          type="button"
          onClick={() => setMoreOpen(true)}
          aria-haspopup="dialog"
          className="flex flex-1 flex-col items-center gap-0.5 py-2 text-xs font-medium text-rs-muted"
        >
          <Menu size={20} aria-hidden="true" />
          More
        </button>
      </nav>
      <MoreSheet open={moreOpen} onOpenChange={setMoreOpen} />
    </>
  )
}
