/** Wire types for `/api/setlist/` and `/api/songs/<pk>/` (issue #330), mirroring `scheduling/serializers.py`. */

export interface CastPerformer {
  id: number
  name: string
  is_role_mismatch: boolean
}

export interface CastEntry {
  role_id: number
  role_name: string
  code: string
  performers: CastPerformer[]
}

export interface RoleLegendEntry {
  id: number
  name: string
  code: string
}

export interface SetlistSong {
  id: number
  title: string
  artist: string
  length: string
  position: number
  notes: string
  cast: CastEntry[]
  recording_count: number
}

/** `data` shape of `GET /api/setlist/`. */
export interface SetlistPayload {
  semester_name: string | null
  song_count: number
  total_running_time: string
  roles: RoleLegendEntry[]
  songs: SetlistSong[]
}

export interface Recording {
  id: number
  uploaded_by_name: string
  note: string
  playback_url: string
}

export interface RecordingGroup {
  rehearsal_id: number
  date: string
  start_time: string | null
  end_time: string | null
  take_count: number
  recordings: Recording[]
}

export interface RehearsedAtRow {
  rehearsal_id: number
  date: string
  is_dress_rehearsal: boolean
  start_time: string | null
  end_time: string | null
}

export interface NextRehearsal {
  id: number
  date: string
}

/** `data` shape of `GET /api/songs/<pk>/`. `next_rehearsal` is absent entirely for a non-admin viewer. */
export interface SongPayload {
  id: number
  title: string
  artist: string
  length: string
  position: number
  notes: string
  cast: CastEntry[]
  recording_groups: RecordingGroup[]
  rehearsed_at: RehearsedAtRow[]
  next_rehearsal?: NextRehearsal | null
}
