/** Wire types for `/api/schedule/` and its two Conflict writes (issue #331), mirroring `scheduling/serializers.py`. */

export type DeclarationType =
  'full_absence' | 'late_arrival' | 'early_departure'

export interface TimelineSlot {
  song_id: number
  song_title: string
  start_time: string
  end_time: string
  is_viewer: boolean
}

export interface Timeline {
  slots: TimelineSlot[]
  window_start: string
  window_end: string
  viewer_song_count: number
  total_song_count: number
  viewer_start_time: string | null
  viewer_end_time: string | null
  is_dress_rehearsal: boolean
}

/** The "Your availability" block. `status` is null when nothing is declared. */
export interface Availability {
  declaration_type: DeclarationType | null
  type_label: string | null
  declared_time: string | null
  reason: string | null
  status: 'pending' | 'approved' | 'rejected' | null
  admin_note: string | null
  is_dress: boolean
  is_editable: boolean
}

export interface MatrixEntry {
  id: number
  kind: 'assignment' | 'backup'
  person_id: number
  person_name: string
  is_role_mismatch: boolean
  has_conflict: boolean
  /** Admin-only (ADR 0007): absent entirely for a member, even when null. */
  covering_for_name?: string | null
}

export interface MatrixCell {
  role_id: number
  entries: MatrixEntry[]
}

export interface MatrixRow {
  song_id: number
  song_title: string
  /** Null on the Dress Rehearsal, which has no per-song slot times (ADR 0003). */
  start_time: string | null
  cells: MatrixCell[]
}

export interface RoleLegendEntry {
  id: number
  name: string
  code: string
}

export interface RehearsalDetail {
  id: number
  date: string
  start_time: string
  end_time: string
  is_dress: boolean
  is_past: boolean
  can_edit_assignments: boolean
  timeline: Timeline
  availability: Availability
  roles: RoleLegendEntry[]
  rows: MatrixRow[]
}

export type YourState =
  | { kind: 'mandatory' }
  | { kind: 'conflict'; type_label: string; declared_time: string | null }
  | { kind: 'window'; arrival_time: string; departure_time: string }
  | { kind: 'not_needed' }

export interface ScheduleListRow {
  id: number
  date: string
  start_time: string
  end_time: string
  is_dress: boolean
  is_past: boolean
  song_count: number
  your_state: YourState
  /** Admin-only: absent for a member, and absent for a past/Dress Rehearsal even for an admin. */
  pending_count?: number
}

/** `data` shape of `GET /api/schedule/`. */
export interface SchedulePayload {
  semester_name: string | null
  schedule: {
    past: ScheduleListRow[]
    future: ScheduleListRow[]
  }
  selected: RehearsalDetail | null
}

/** `data` shape of a successful declare/edit — the same `Availability` shape the read view carries. */
export type DeclareConflictData = Availability
