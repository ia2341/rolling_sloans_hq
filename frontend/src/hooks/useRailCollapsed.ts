import { useCallback, useState } from 'react'

const STORAGE_KEY = 'rs-sidebar-rail-collapsed'

function readStored(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === 'true'
  } catch {
    return false
  }
}

function writeStored(collapsed: boolean): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, String(collapsed))
  } catch {
    // A browser that refuses storage (private mode, disabled site data)
    // still gets a working, expanded sidebar (issue #328) — it just
    // re-collapses on the next visit instead of remembering.
  }
}

/**
 * Persists the sidebar's rail-collapsed state as a per-viewer browser
 * convenience (issue #328 user story 11), not server state. Every read is
 * wrapped so a browser that refuses storage still renders an expanded
 * sidebar rather than throwing.
 */
export function useRailCollapsed(): [boolean, () => void] {
  const [collapsed, setCollapsed] = useState(readStored)

  const toggle = useCallback(() => {
    setCollapsed((previous) => {
      const next = !previous
      writeStored(next)
      return next
    })
  }, [])

  return [collapsed, toggle]
}
