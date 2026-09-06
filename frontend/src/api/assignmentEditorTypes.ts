/** Wire types for the assignment editor's picker/preview/save endpoints (issue #338), mirroring `scheduling/serializers.py`. */

export interface AssignmentPickerOption {
  person_id: number
  person_name: string
  has_declared_role: boolean
  /** A bare marker only, never a reason, a declaration type or a time (ADR 0005). */
  has_conflict: boolean
}

/** `data` shape of `GET /api/schedule/<id>/assignments/picker/<song_id>/<role_id>/` — its own shape, not the write envelope. */
export interface AssignmentPickerPayload {
  song_id: number
  song_title: string
  role_id: number
  role_name: string
  /** Null on the Dress Rehearsal (ADR 0006): no RehearsalSong to anchor a Backup on, rendered as structural copy. */
  rehearsal_song_id: number | null
  declared: AssignmentPickerOption[]
  others: AssignmentPickerOption[]
  backup_declared: AssignmentPickerOption[]
  backup_others: AssignmentPickerOption[]
}

/** `fallout` shape of the assignment editor's preview/save envelope. */
export interface AssignmentEditFalloutPayload {
  is_blocked: boolean
  block_message: string
  is_stale: boolean
  loud: string[]
  quiet: string[]
}

export interface AssignmentAddedEntryInput {
  song_id: number
  role_id: number
  person_id: number
}

export interface AssignmentAddedBackupEntryInput {
  rehearsal_song_id: number
  role_id: number
  person_id: number
  covering_for_id: number | null
}

export interface AssignmentBackupCoveringForUpdateInput {
  backup_id: number
  covering_for_id: number | null
}

/** Wire body for `POST /api/schedule/<id>/assignments/{preview,save}/`. */
export interface AssignmentEditBufferInput {
  semester_id: number
  semester_updated_at: string
  removed_assignment_ids: number[]
  added_entries: AssignmentAddedEntryInput[]
  removed_backup_ids: number[]
  added_backup_entries: AssignmentAddedBackupEntryInput[]
  backup_covering_for_updates: AssignmentBackupCoveringForUpdateInput[]
}

/** Wire body for `POST /api/schedule/<id>/running-order/{preview,save}/` — the "Edit Rehearsal" drag-and-drop's pure reorder Buffer.
 *
 * Every other `RehearsalEditRow` field (date/time/overrides) and each
 * row's own `slot_count` are read fresh off the database server-side
 * (`build_rehearsal_reorder_buffer_from_request()`), so this wire shape
 * only ever names the new order of the Rehearsal's existing
 * `RehearsalSong` ids — it can never silently change a slot_count or a
 * Semester default the way a hand-crafted full row could.
 */
export interface RunningOrderReorderInput {
  semester_id: number
  semester_updated_at: string
  ordered_rehearsal_song_ids: number[]
}
