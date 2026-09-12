import { Monitor, Moon, Sun } from 'lucide-react'
import { useState } from 'react'

import { apiFetch } from '../api/client'
import { useAppContext } from '../api/ContextProvider'
import type { ThemePreference, WriteEnvelope } from '../api/types'

const THEME_PREFERENCE_OPTIONS: {
  value: ThemePreference
  label: string
  Icon: typeof Sun
}[] = [
  { value: 'light', label: 'Light theme', Icon: Sun },
  { value: 'dark', label: 'Dark theme', Icon: Moon },
  { value: 'system', label: 'Match system theme', Icon: Monitor },
]

/**
 * The global Light/Dark/System icon toggle (issue #500), reachable from
 * every page's top-right chrome rather than buried on the viewer's own
 * `/members/:id` (where it originally shipped as `ThemePreferenceRow` in
 * issue #497). Reads the current value off `context.viewer` (a durable,
 * per-Person setting, not browser-local) and posts a change to
 * `/api/theme/`; the envelope's `context` block updates the shared store
 * on success, which `ThemeSync` picks up to actually repaint the page.
 */
export function ThemeToggle() {
  const appContext = useAppContext()
  const [isSaving, setIsSaving] = useState(false)
  const themePreference = appContext?.viewer.theme_preference ?? 'system'

  async function selectPreference(preference: ThemePreference) {
    if (preference === themePreference || isSaving) return
    setIsSaving(true)
    try {
      await apiFetch<WriteEnvelope>('/api/theme/', {
        method: 'POST',
        body: JSON.stringify({ theme_preference: preference }),
      })
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <div className="inline-flex shrink-0 rounded border border-rs-border">
      {THEME_PREFERENCE_OPTIONS.map(({ value, label, Icon }) => (
        <button
          key={value}
          type="button"
          disabled={isSaving}
          onClick={() => void selectPreference(value)}
          aria-label={label}
          aria-pressed={themePreference === value}
          className={
            themePreference === value
              ? 'bg-rs-accent p-1.5 text-rs-accent-fg'
              : 'p-1.5 text-rs-muted hover:text-rs-fg'
          }
        >
          <Icon size={16} aria-hidden="true" />
        </button>
      ))}
    </div>
  )
}
