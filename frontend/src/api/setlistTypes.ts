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

/** One `/api/setlist/{preview,save}/` request body row (issue #335, mirroring `scheduling/api_builders.py`'s wire shape). */
export interface SetlistEditRowWire {
  row_key: string
  song_id: number | null
  title: string
  artist: string
  /** `M:SS`/`H:MM:SS`, exactly what was typed -- never seconds, never a client-side parse. */
  length: string
  notes: string
}

/** `/api/setlist/{preview,save}/` request body (issue #335, mirroring `scheduling/services.py`'s `SetlistEditBuffer`). */
export interface SetlistEditBufferWire {
  semester_id: number
  semester_updated_at: string
  rows: SetlistEditRowWire[]
  deleted_song_ids: number[]
}

/** One `SetlistSongDeletion`, as `serialize_setlist_edit_fallout()` emits it. */
export interface SetlistSongDeletionWire {
  title: string
  recording_count: number
  uploader_count: number
  running_order_count: number
}

/** `SetlistEditFallout`, as `serialize_setlist_edit_fallout()` emits it -- the `/api/setlist/preview/` response's `fallout` value. */
export interface SetlistEditFalloutWire {
  is_blocked: boolean
  block_message: string
  is_stale: boolean
  pending_adds: string[]
  pending_edits: string[]
  reordered: boolean
  pending_deletions: SetlistSongDeletionWire[]
  loud: string[]
  quiet: string[]
}

/** One Spotify playlist candidate, as `serialize_spotify_import()` emits it (issue #335). */
export interface SpotifyImportCandidate {
  title: string
  artist: string
  length: string
  already_in_setlist: boolean
}

/** `data` shape of `POST /api/setlist/spotify/` (issue #335) -- answers its own question, not the write envelope. */
export interface SpotifyImportPayload {
  songs: SpotifyImportCandidate[]
  skipped_count: number
  skipped_reasons: Record<string, number>
  /** `''` on a successful fetch; a readable explanation (bad link, unconfigured credential, Spotify failure) otherwise. */
  message: string
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
