/** Wire types for `/api/semesters/...` (issue #329), mirroring `scheduling/serializers.py`. */

import type { SemesterStatus } from './types'

/** One row of `GET /api/semesters/management-rows/`'s `data`, matching `serialize_semester_management_rows`. */
export interface SemesterManagementRow {
  id: number
  name: string
  status: SemesterStatus
  is_viewing: boolean
  member_count: number
  song_count: number
  rehearsal_count: number
  recording_count: number
  /** ISO timestamp: the staleness token for this row's own Reapply-defaults request (not just the viewing Semester's). */
  updated_at: string
}

/** `GET /api/semesters/<pk>/publish-impact/`'s `data`, matching `serialize_semester_publish_impact`. */
export interface SemesterPublishImpact {
  target_semester_id: number
  target_semester_name: string
  is_already_live: boolean
  incumbent: { id: number; name: string } | null
  incumbent_rehearsal_count: number
  incumbent_song_count: number
  has_no_setlist: boolean
  has_no_rehearsals: boolean
}

/** `GET /api/semesters/<pk>/deletion-summary/`'s `data`, matching `serialize_semester_deletion_summary`. */
export interface SemesterDeletionSummary {
  member_count: number
  song_count: number
  rehearsal_count: number
  recording_count: number
}

/** The `fallout` value of the Reapply-defaults preview/save envelopes, matching `serialize_semester_defaults_fallout`. */
export interface SemesterDefaultsFallout {
  is_blocked: boolean
  block_message: string
  is_stale: boolean
  changed_rehearsal_count: number
  loud: string[]
  quiet: string[]
}

/** The six timing-default fields `POST /api/semesters/create/` and the Reapply-defaults surface both take, matching `SemesterCreateApiView.TIMING_DEFAULT_FIELDS`. */
export interface SemesterTimingDefaults {
  default_rehearsal_duration_minutes: number
  default_setup_grace_minutes: number
  default_teardown_grace_minutes: number
  default_song_slot_count: number
  default_arrival_buffer_minutes: number
  default_departure_buffer_minutes: number
}

/** `POST /api/semesters/create/`'s request body. */
export interface CreateSemesterBody extends SemesterTimingDefaults {
  name: string
}

/** `POST /api/semesters/reapply-defaults/{preview,save}/`'s shared request body, matching `SemesterDefaultsReapplyBuffer`'s wire shape. */
export interface SemesterDefaultsReapplyBody {
  semester_id: number
  semester_updated_at: string
}
