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
 * fetch. Backup-only since ADR 0019: `backup_declared`/`backup_others`
 * exclude anyone already a Backup on this cell (read straight off the
 * matrix row's own entries, already on the wire), and stay empty on the
 * Dress Rehearsal (`rehearsal_song_id` null, ADR 0003/0006), which this
 * surface no longer offers an edit mode for at all. The
 * `declared`/`others` standing-assignment split this used to derive moved
 * to the Song-level cast picker, which fetches it from the server so it
 * can carry each candidate's conflict summary.
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
    backup_declared: backupDeclared,
    backup_others: backupOthers,
  }
}
