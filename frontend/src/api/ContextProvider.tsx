import {
  createContext,
  useContext,
  useSyncExternalStore,
  type ReactNode,
} from 'react'

import { getContextSnapshot, subscribeToContext } from './contextStore'
import type { AppContext } from './types'

const AppContextReactContext = createContext<AppContext | null>(null)

/**
 * Makes the shared `/api/` context store (issue #326, #328) available
 * through React context. Wraps `AppShell`; the value is `null` until the
 * first successful `/api/` response arrives, since the shell never issues
 * a context request of its own — see `apiFetch()`.
 */
export function ContextProvider({ children }: { children: ReactNode }) {
  const value = useSyncExternalStore(
    subscribeToContext,
    getContextSnapshot,
    () => null,
  )
  return (
    <AppContextReactContext.Provider value={value}>
      {children}
    </AppContextReactContext.Provider>
  )
}

/** Returns the current `AppContext`, or `null` before any `/api/` response has arrived. */
export function useAppContext(): AppContext | null {
  return useContext(AppContextReactContext)
}
