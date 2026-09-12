/** Wire types for the assignment editor's picker/preview/save endpoints (issue #338), mirroring `scheduling/serializers.py`. */

export interface AssignmentPickerOption {
  person_id: number
  person_name: string
  has_declared_role: boolean
  /** A bare marker only, never a reason, a declaration type or a time (ADR 0005). */
  has_conflict: boolean
}

/** `data` shape of `GET /api/schedule/<id>/assignments/picker/<song_id>/<role_id>/` — its own shape, not the write envelope.
 *
 * Backup-only since ADR 0019: this surface writes no standing assignment,
 * so the `declared`/`others` candidate split it used to carry now lives on
 * `SongCastPickerPayload` instead. `rehearsal_song_id` is never null —
 * the Dress Rehearsal 404s before this payload is built (ADR 0003).
 */
export interface AssignmentPickerPayload {
  song_id: number
  song_title: string
  role_id: number
  role_name: string
  rehearsal_song_id: number | null
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

/** Wire body for `POST /api/schedule/<id>/assignments/{preview,save}/` — Backup-only since ADR 0019. */
export interface AssignmentEditBufferInput {
  semester_id: number
  semester_updated_at: string
  removed_backup_ids: number[]
  added_backup_entries: AssignmentAddedBackupEntryInput[]
  backup_covering_for_updates: AssignmentBackupCoveringForUpdateInput[]
}

/** One song-swap override: replaces an existing Running Order slot's Song without changing its position (issue #406). */
export interface RunningOrderSongOverrideInput {
  rehearsal_song_id: number
  song_id: number
}

/** Wire body for `POST /api/schedule/<id>/running-order/{preview,save}/` — the "Edit Rehearsal" drag-and-drop's pure reorder Buffer, plus the Assignments table's song-swap dropdown (issue #406).
 *
 * Every other `RehearsalEditRow` field (date/time/overrides) and each
 * row's own `slot_count` are read fresh off the database server-side
 * (`build_rehearsal_reorder_buffer_from_request()`), so this wire shape
 * only ever names the new order of the Rehearsal's existing
 * `RehearsalSong` ids — it can never silently change a slot_count or a
 * Semester default the way a hand-crafted full row could. `song_overrides`
 * is the one exception: each entry substitutes a different Song into one
 * of those existing rows, leaving its position and slot_count untouched.
 */
export interface RunningOrderReorderInput {
  semester_id: number
  semester_updated_at: string
  ordered_rehearsal_song_ids: number[]
  song_overrides: RunningOrderSongOverrideInput[]
}
