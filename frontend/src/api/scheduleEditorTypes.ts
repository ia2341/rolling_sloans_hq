/** Wire types for `/api/schedule/editor/` and its write endpoints (issue #337), mirroring `scheduling/serializers.py`. */

export type PinnedReason = 'recording' | 'manual_slot_count'

export interface RunningOrderRowPayload {
  rehearsal_song_id: number
  song_id: number
  song_title: string
  slot_count: number
  start_time: string
  end_time: string
  is_pinned: boolean
  pinned_reasons: PinnedReason[]
}

export interface EditableRehearsal {
  id: number
  date: string
  start_time: string
  end_time: string | null
  is_full_setlist: boolean
  setup_grace_minutes: number | null
  teardown_grace_minutes: number | null
  arrival_buffer_minutes: number | null
  departure_buffer_minutes: number | null
  running_order: RunningOrderRowPayload[]
}

export interface PastRehearsal {
  id: number
  date: string
  start_time: string
  end_time: string | null
  is_full_setlist: boolean
  song_count: number
}

export interface EditorSetlistSong {
  id: number
  title: string
  artist: string
  position: number
}

export interface SemesterDefaults {
  default_rehearsal_duration_minutes: number
  default_setup_grace_minutes: number
  default_teardown_grace_minutes: number
  default_song_slot_count: number
  default_arrival_buffer_minutes: number
  default_departure_buffer_minutes: number
  default_dress_rehearsal_count: number
}

export interface RehearsalTimeRow {
  day_of_week: number
  start_time: string
  end_time: string
}

export interface SkipDateRow {
  start_date: string
  end_date: string | null
}

export interface RehearsalPatternPayload {
  start_date: string
  end_date: string
  rehearsal_times: RehearsalTimeRow[]
  skip_dates: SkipDateRow[]
}

/** `data` shape of `GET /api/schedule/editor/`. */
export interface ScheduleEditorPayload {
  semester_name: string | null
  rehearsals: EditableRehearsal[]
  past_rehearsals: PastRehearsal[]
  setlist_songs: EditorSetlistSong[]
  semester_defaults: SemesterDefaults | null
  pattern: RehearsalPatternPayload | null
}

/** One Running Order sub-grid row in the Pending Buffer's wire shape. */
export interface RunningOrderRowInput {
  rehearsal_song_id: number | null
  song_id: number
  slot_count: number
}

/** One Rehearsal edit grid row in the Pending Buffer's wire shape. */
export interface RehearsalEditRowInput {
  row_key: string
  rehearsal_id: number | null
  date: string
  start_time: string
  end_time: string | null
  is_full_setlist: boolean
  setup_grace_minutes: number | null
  teardown_grace_minutes: number | null
  arrival_buffer_minutes: number | null
  departure_buffer_minutes: number | null
  running_order: RunningOrderRowInput[]
}

/** The whole `/api/schedule/editor/{preview,save}/` request body. */
export interface RehearsalEditBufferInput {
  semester_id: number
  semester_updated_at: string
  rows: RehearsalEditRowInput[]
  deleted_rehearsal_ids: number[]
}

export interface DoomedRecordingGroup {
  label: string
  recording_count: number
  uploader_count: number
}

/** The rehearsal editor's `fallout` shape, echoed as `PreviewResult['fallout']`'s server-side source. */
export interface RehearsalEditFalloutPayload {
  is_blocked: boolean
  block_message: string
  is_stale: boolean
  loud: string[]
  quiet: string[]
  doomed_recording_groups: DoomedRecordingGroup[]
}

export interface GenerationCreateItem {
  date: string
  start_time: string
  end_time: string
  is_dress_rehearsal: boolean
}

export interface GenerationKeepItem {
  rehearsal_id: number
  date: string
  start_time: string
  end_time: string
}

export interface GenerationRetimeItem {
  rehearsal_id: number
  date: string
  old_start_time: string
  old_end_time: string
  new_start_time: string
  new_end_time: string
  song_count: number
  conflict_count: number
}

export interface GenerationOrphanItem {
  rehearsal_id: number
  date: string
  start_time: string
  end_time: string
  song_count: number
  conflict_count: number
  recording_count: number
  delete_disabled: boolean
}

/** `data` shape of `POST /api/schedule/editor/generate/diff/`. */
export interface RehearsalGenerationDiff {
  creates: GenerationCreateItem[]
  keeps: GenerationKeepItem[]
  retimes: GenerationRetimeItem[]
  orphans: GenerationOrphanItem[]
}

export interface DealtRow {
  rehearsal_song_id: number | null
  song_id: number
  slot_count: number
}

export interface DealtRehearsal {
  rehearsal_id: number
  rows: DealtRow[]
}

/** `data` shape of `POST /api/schedule/editor/deal/`. */
export interface RehearsalDealPayload {
  rehearsals: DealtRehearsal[]
}

/** `data` shape of `POST /api/schedule/editor/rehearsal/<id>/shuffle/`. */
export interface ShuffleRowsPayload {
  rows: DealtRow[]
}
