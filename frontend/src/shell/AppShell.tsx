import type { ReactNode } from 'react'
import { Outlet } from 'react-router-dom'

import { ContextProvider } from '../api/ContextProvider'
import { EditToolbar } from '../components/ui/EditToolbar'
import { useIsPhone } from '../hooks/useIsPhone'
import { EditSessionProvider, useEditSession } from './EditSessionContext'
import { PageTitleProvider } from './PageTitleContext'
import { Sidebar } from './Sidebar'
import { TabBar } from './TabBar'
import { TopBar } from './TopBar'

/**
 * Wraps every SPA route (issue #328): `Sidebar` above the phone breakpoint,
 * `TabBar` + `TopBar` below it. Not a per-route concern — a route renders
 * a page, never chrome.
 *
 * Issue #484's soft `MustChangePasswordBanner` used to mount here; issue
 * #487 (ADR 0018) replaced that discretionary choice with a request-level
 * gate (`config.views.BaseView`) that redirects a must-change-password
 * Person to `/change-password` before any route under this shell can even
 * finish its first `/api/` fetch, so the banner would have flashed for at
 * most one render and never actually been seen — removed as dead weight
 * rather than kept as an unreachable second mechanism.
 */
export function AppShell() {
  return (
    <ContextProvider>
      <EditSessionProvider>
        <PageTitleProvider>
          <ShellLayout>
            <Outlet />
          </ShellLayout>
        </PageTitleProvider>
      </EditSessionProvider>
    </ContextProvider>
  )
}

/** Picks the phone (`TopBar`/`TabBar`) or desktop (`Sidebar`) chrome around `children` based on `useIsPhone()`. */
function ShellLayout({ children }: { children: ReactNode }) {
  const isPhone = useIsPhone()

  if (isPhone) {
    return (
      <div className="flex min-h-screen flex-col pb-16">
        <TopBar />
        <main className="flex-1 px-3 py-3">{children}</main>
        <TabBar />
      </div>
    )
  }

  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <div className="flex flex-1 flex-col">
        <ActiveEditToolbar />
        <main className="flex-1 px-6 py-6">{children}</main>
      </div>
    </div>
  )
}

/** Renders the sticky `EditToolbar` only while a surface has registered an `EditSession` (desktop only — see the chrome-budget note in `TopBar.tsx`). */
function ActiveEditToolbar() {
  const editSession = useEditSession()
  if (editSession === null) return null

  return (
    <EditToolbar
      what={editSession.what}
      changeCount={editSession.changeCount}
      blockedReason={editSession.blockedReason}
      onDiscard={editSession.discard}
      onRequestSave={editSession.requestSave}
    />
  )
}
