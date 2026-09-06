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
 * Builds the Viewing dropdown/sheet's items from `context.semester_options`
 * (issue #329): one `ResponsiveMenuItem` per Semester, newest-created
 * first (the order `semester_options_for()` already returns them in),
 * each carrying its status chip, its three counts, and a tick on
 * `is_viewing`. Selecting posts to `/api/semesters/select/`; `pending`
 * tracks the in-flight request so a caller can disable the trigger while
 * it resolves.
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
    selectSemester(semesterId).finally(() => setPending(false))
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
