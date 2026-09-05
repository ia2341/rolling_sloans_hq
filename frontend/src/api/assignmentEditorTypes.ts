/** Wire types for the assignment editor's picker/preview/save endpoints (issue #338), mirroring `scheduling/serializers.py`. */

export interface AssignmentPickerOption {
  person_id: number
  person_name: string
  has_declared_role: boolean
  /** A marker only, never a reason (ADR 0005): e.g. "away all evening" or "away 19:40–20:15". */
  conflict_note: string | null
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
