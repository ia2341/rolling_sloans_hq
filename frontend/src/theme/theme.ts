import type { ThemePreference } from '../api/types'

/**
 * Local cache key for the viewer's last-known `theme_preference` (issue
 * #500). The setting itself lives on `Person` and travels with the
 * `context.viewer` envelope, so this cache exists only to apply the right
 * theme before that first `/api/` response lands — never as the source of
 * truth, which stays the server.
 */
const STORAGE_KEY = 'rs-theme-preference'

const VALID_PREFERENCES: readonly ThemePreference[] = [
  'light',
  'dark',
  'system',
]

/** Sets (or clears, for `system`) the `data-theme` attribute `index.css`'s override blocks key off. */
export function applyThemePreference(preference: ThemePreference): void {
  const root = document.documentElement
  if (preference === 'system') {
    delete root.dataset.theme
  } else {
    root.dataset.theme = preference
  }
}

/** Best-effort `localStorage` write, so the next page load can apply this preference before context arrives. */
export function cacheThemePreference(preference: ThemePreference): void {
  try {
    localStorage.setItem(STORAGE_KEY, preference)
  } catch {
    // Private-browsing/storage-blocked: the server-sourced preference still applies once context loads.
  }
}

/** Returns the last-cached preference, or `'system'` if none is cached or storage is unavailable. */
export function readCachedThemePreference(): ThemePreference {
  try {
    const cached = localStorage.getItem(STORAGE_KEY)
    if ((VALID_PREFERENCES as string[]).includes(cached ?? '')) {
      return cached as ThemePreference
    }
  } catch {
    // Fall through to the system default below.
  }
  return 'system'
}
