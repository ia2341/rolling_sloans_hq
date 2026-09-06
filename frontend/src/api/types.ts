/** Wire types for the `/api/` envelope (issue #326), mirrored on the client. */

export type SemesterStatus = 'live' | 'draft' | 'previously_published'

export interface Viewer {
  id: number
  name: string
  email: string
  is_admin: boolean
}

export interface ViewingSemester {
  id: number
  name: string
  status: SemesterStatus
  published_at: string | null
  updated_at: string
}

export interface LiveSemester {
  id: number
  name: string
}

export interface SemesterOption {
  id: number
  name: string
  status: SemesterStatus
  is_viewing: boolean
  member_count: number
  song_count: number
  rehearsal_count: number
}

/** The six-key `context` block every `/api/` response carries (issue #326). */
export interface AppContext {
  viewer: Viewer
  viewing_semester: ViewingSemester | null
  live_semester: LiveSemester | null
  semester_warning: boolean
  semester_options: SemesterOption[]
  pending_conflict_count: number | null
}

/** Envelope for an endpoint answering a question (`ApiView.read_response()`). */
export interface ReadEnvelope<TData> {
  context: AppContext
  data: TData
}

/** Envelope for an endpoint that takes a Pending Buffer (`ApiView.write_response()`). */
export interface WriteEnvelope<
  TData = unknown,
  TValues = unknown,
  TFallout = unknown,
> {
  context: AppContext
  ok: boolean
  errors: Record<string, string[]>
  non_field_errors: string[]
  fallout: TFallout | null
  values: TValues | null
  data: TData | null
}
