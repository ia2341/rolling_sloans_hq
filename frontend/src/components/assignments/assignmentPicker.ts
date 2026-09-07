import type {
  AssignmentPickerOption,
  AssignmentPickerPayload,
} from '../../api/assignmentEditorTypes'
import type {
  AssignableRosterEntry,
  RehearsalDetail,
} from '../../api/scheduleTypes'

/** Identifies the one grid cell the "+" picker was opened on. */
interface PickerCell {
  songId: number
  songTitle: string
  roleId: number
  roleName: string
}

/**
 * Derives the "+" picker's contents for `cell` entirely from data already on
 * the page (issue #399) — no `.../assignments/picker/<song_id>/<role_id>/`
 * fetch. Mirrors `assignment_picker_for()`'s split: `declared`/`others`
 * exclude anyone already holding this exact (Song, Role) standing
 * Assignment, `backup_declared`/`backup_others` exclude anyone already a
 * Backup on this cell (both read straight off the matrix row's own
 * entries, already on the wire), and both stay empty on the Dress
 * Rehearsal (`rehearsal_song_id` null, ADR 0006).
 */
export function buildAssignmentPicker(
  detail: Pick<RehearsalDetail, 'rows' | 'roster' | 'conflicted_person_ids'>,
  cell: PickerCell,
): AssignmentPickerPayload {
  const row = detail.rows.find((candidate) => candidate.song_id === cell.songId)
  const matrixCell = row?.cells.find(
    (candidate) => candidate.role_id === cell.roleId,
  )
  const roster = detail.roster ?? []
  const conflictedIds = new Set(detail.conflicted_person_ids ?? [])

  const assignedIds = new Set(
    (matrixCell?.entries ?? [])
      .filter((entry) => entry.kind === 'assignment')
      .map((entry) => entry.person_id),
  )
  const backedUpIds = new Set(
    (matrixCell?.entries ?? [])
      .filter((entry) => entry.kind === 'backup')
      .map((entry) => entry.person_id),
  )

  const toOption = (entry: AssignableRosterEntry): AssignmentPickerOption => ({
    person_id: entry.person_id,
    person_name: entry.person_name,
    has_declared_role: entry.declared_role_ids.includes(cell.roleId),
    has_conflict: conflictedIds.has(entry.person_id),
  })

  const declared: AssignmentPickerOption[] = []
  const others: AssignmentPickerOption[] = []
  for (const entry of roster) {
    if (assignedIds.has(entry.person_id)) continue
    const option = toOption(entry)
    ;(option.has_declared_role ? declared : others).push(option)
  }

  const rehearsalSongId = row?.rehearsal_song_id ?? null
  const backupDeclared: AssignmentPickerOption[] = []
  const backupOthers: AssignmentPickerOption[] = []
  if (rehearsalSongId !== null) {
    for (const entry of roster) {
      if (backedUpIds.has(entry.person_id)) continue
      const option = toOption(entry)
      ;(option.has_declared_role ? backupDeclared : backupOthers).push(option)
    }
  }

  return {
    song_id: cell.songId,
    song_title: cell.songTitle,
    role_id: cell.roleId,
    role_name: cell.roleName,
    rehearsal_song_id: rehearsalSongId,
    declared,
    others,
    backup_declared: backupDeclared,
    backup_others: backupOthers,
  }
}
