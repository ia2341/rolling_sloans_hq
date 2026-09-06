/** Wire types for `GET /api/` (issue #332), mirroring `scheduling/serializers.py`'s `serialize_home()`. */

import type { Timeline } from './scheduleTypes'

export interface NextRehearsalCard {
  rehearsal_id: number
  date: string
  is_dress: boolean
  arrival_time: string
  departure_time: string
  timeline: Timeline
}

export interface AttendanceWindow {
  arrival_time: string
  departure_time: string
}

export interface UpcomingRehearsalRow {
  id: number
  date: string
  start_time: string
  end_time: string
  is_dress: boolean
  is_past: boolean
  your_window: AttendanceWindow | null
}

export interface SongProgressRow {
  id: number
  title: string
  artist: string
  length: string
  position: number
  completed: number
  total: number
  has_assignment: boolean
}

export interface SetupChecklistItem {
  key: string
  label: string
  is_done: boolean
  status: string
  destination: string
  waiting_on: string | null
}

export interface SetupChecklist {
  semester_name: string
  items: SetupChecklistItem[]
}

/** `data` shape of `GET /api/`. */
export interface HomePayload {
  semester_name: string | null
  next_rehearsal: NextRehearsalCard | null
  upcoming_rehearsals: UpcomingRehearsalRow[]
  song_progress: SongProgressRow[]
  /** Present only for an admin viewing a draft Semester with something still empty (issue #332). */
  setup_checklist: SetupChecklist | null
  /** True exactly once, on the first Home read after an admin creates this Semester (issue #332). */
  just_created: boolean
}
