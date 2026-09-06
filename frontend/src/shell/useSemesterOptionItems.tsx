import { useCallback, useState } from 'react'

import { apiFetch } from '../api/client'
import { useAppContext } from '../api/ContextProvider'
import type { WriteEnvelope } from '../api/types'
import type { ResponsiveMenuItem } from '../components/ui/ResponsiveMenu'
import { SemesterStatusChip } from '../components/ui/SemesterStatusChip'

/**
 * Posts `semesterId` (or `null` to clear the selection) to
 * `/api/semesters/select/` (issue #329). The response's `context` updates
 * the shell automatically through `apiFetch`'s envelope handling — no
 * caller reads the response itself.
 */
async function selectSemester(semesterId: number | null): Promise<void> {
  await apiFetch<WriteEnvelope>('/api/semesters/select/', {
    method: 'POST',
    body: JSON.stringify({ semester_id: semesterId }),
  })
}

/**
 * Reloads the whole page (issue #363) after a successful Semester switch.
 * Nearly every page's data hangs off "the viewing Semester" and none of it
 * re-fetches on its own when `context` changes underneath it, so a plain
 * context update leaves a page showing stale data for the Semester it was
 * loaded under. A hard reload is the simplest fix given no router-level
 * revalidation mechanism (e.g. `useRevalidator`) exists anywhere else in
 * this codebase yet.
 */
function reloadPage(): void {
  window.location.reload()
}

/**
 * Builds the Viewing dropdown/sheet's items from `context.semester_options`
 * (issue #329): one `ResponsiveMenuItem` per Semester, newest-created
 * first (the order `semester_options_for()` already returns them in),
 * each carrying its status chip, its three counts, and a tick on
 * `is_viewing`. Selecting posts to `/api/semesters/select/` and, on
 * success, hard-reloads the page (issue #363) so every page's data — all
 * of it scoped to "the viewing Semester" — reflects the new selection
 * rather than sitting stale under updated shell chrome; `pending` tracks
 * the in-flight request so a caller can disable the trigger while it
 * resolves (and stays true through a successful select, since the reload
 * tears the component down anyway).
 */
export function useSemesterOptionItems(): {
  items: ResponsiveMenuItem[]
  pending: boolean
} {
  const appContext = useAppContext()
  const [pending, setPending] = useState(false)
  const options = appContext?.semester_options ?? []

  const onSelect = useCallback((semesterId: number) => {
    setPending(true)
    selectSemester(semesterId)
      .then(() => reloadPage())
      .catch(() => setPending(false))
  }, [])

  const items: ResponsiveMenuItem[] = options.map((option) => ({
    key: String(option.id),
    label: (
      <span className="flex items-center gap-2">
        {option.name}
        <SemesterStatusChip status={option.status} />
      </span>
    ),
    secondaryText: `${option.member_count} members · ${option.song_count} songs · ${option.rehearsal_count} rehearsals`,
    selected: option.is_viewing,
    onSelect: () => onSelect(option.id),
  }))

  return { items, pending }
}
