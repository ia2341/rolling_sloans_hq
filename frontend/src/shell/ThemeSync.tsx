import { useEffect } from 'react'

import { useAppContext } from '../api/ContextProvider'
import { applyThemePreference, cacheThemePreference } from '../theme/theme'

/**
 * Applies the viewer's `theme_preference` (issue #497) to the DOM on every
 * context update, and caches it so `main.tsx`'s pre-render read can apply
 * the right theme on the *next* load before this component — or any
 * `/api/` response — exists. Renders nothing; `index.css`'s
 * `[data-theme="light"|"dark"]` blocks (falling through to
 * `prefers-color-scheme` for `system`) do the actual styling.
 */
export function ThemeSync() {
  const appContext = useAppContext()
  const themePreference = appContext?.viewer.theme_preference

  useEffect(() => {
    if (themePreference === undefined) return
    applyThemePreference(themePreference)
    cacheThemePreference(themePreference)
  }, [themePreference])

  return null
}
