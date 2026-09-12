/** Wire types for `/api/setlist/` and `/api/songs/<pk>/` (issue #330), mirroring `scheduling/serializers.py`. */

export interface CastPerformer {
  id: number
  name: string
  is_role_mismatch: boolean
  /** The underlying `SongRoleAssignment` row id -- what the Cast editor's ✕ stages into `removed_assignment_ids` (issue #499, ADR 0019). Absent on a Schedule `MatrixEntry` adaptation, which carries its own `id`. */
  assignment_id?: number
  /** Absent on the Setlist's own cast (it has no notion of Backup) — present when adapted from a Schedule `MatrixEntry` (issue: UI overhaul round 2, shared cast grid). */
  kind?: 'assignment' | 'backup'
  has_conflict?: boolean
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
  /** This Role's RoleGroup id -- lets the Add Songs role-count step build a `role_group_counts` wire entry without a second request (issue #462). */
  group_id: number
  /** The instrument-family bucket this Role's group merges into on the cast tables (issue #457). */
  group_name: string
  /** Fixes this Role's group's column order, independent of `group_name`'s alphabetical order. */
  group_order: number
  /** True for the one catch-all group — a Role in it gets its own column rather than merging with groupmates. */
  group_is_catch_all: boolean
}

export interface SetlistSong {
  id: number
  title: string
  artist: string
  length: string
  position: number
  notes: string
  /** The Song's own optimistic-concurrency stamp -- what the inline cast popover pins its `SongCastEditBuffer` to (ADR 0019). */
  updated_at: string
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

/** One Role Group -> target count entry staged on a brand-new setlist row (issue #461). */
export interface SetlistRoleGroupCountWire {
  role_group_id: number
  count: number
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
  /** Only meaningful when `song_id` is null -- an existing Song's Requirements are edited elsewhere (issue #461). */
  role_group_counts: SetlistRoleGroupCountWire[]
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

/** One `SetlistRoleRequirementAddition`, as `serialize_setlist_edit_fallout()` emits it (issue #461). */
export interface SetlistRoleRequirementAdditionWire {
  song_title: string
  role_name: string
  count: number
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
  pending_role_requirements: SetlistRoleRequirementAdditionWire[]
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

/** One `RoleFillStatus` (issue #207, #339): a Role Requirement's target vs. actual headcount. */
export interface RoleRequirement {
  role_id: number
  role_name: string
  target: number
  actual: number
  is_understaffed: boolean
  is_retired_role: boolean
}

/** One Role the Requirements editor's `+ Add role requirement` control may offer (issue #339). */
export interface AddableRole {
  id: number
  name: string
}

/** `data` shape of `GET /api/songs/<pk>/`. `available_roles` is absent entirely for a non-admin viewer. */
export interface SongPayload {
  id: number
  title: string
  artist: string
  length: string
  position: number
  notes: string
  /** The Song's own optimistic-concurrency stamp, the Cast editor's staleness anchor (ADR 0019). */
  updated_at: string
  cast: CastEntry[]
  role_requirements: RoleRequirement[]
  recording_groups: RecordingGroup[]
  rehearsed_at: RehearsedAtRow[]
  available_roles?: AddableRole[]
}

/** One `/api/songs/<pk>/requirements/{preview,save}/` request body entry (issue #339, mirroring `scheduling/api_builders.py`'s wire shape). */
export interface SongRoleRequirementEntryWire {
  role_id: number
  count: number
}

/** `/api/songs/<pk>/requirements/{preview,save}/` request body (issue #339, mirroring `scheduling/services.py`'s `SongRoleRequirementBuffer`). */
export interface SongRoleRequirementBufferWire {
  semester_id: number
  semester_updated_at: string
  entries: SongRoleRequirementEntryWire[]
}

/** One `SongRoleRequirementAddition`, as `serialize_song_role_requirement_fallout()` emits it. */
export interface SongRoleRequirementAdditionWire {
  role_name: string
  count: number
}

/** One `SongRoleRequirementCountChange`, as `serialize_song_role_requirement_fallout()` emits it. */
export interface SongRoleRequirementCountChangeWire {
  role_name: string
  before: number
  after: number
}

/** One `SongRoleRequirementRemoval`, as `serialize_song_role_requirement_fallout()` emits it. */
export interface SongRoleRequirementRemovalWire {
  role_name: string
  is_retired_role: boolean
}

/** `SongRoleRequirementFallout`, as `serialize_song_role_requirement_fallout()` emits it -- the Requirements Preview response's `fallout` value. */
export interface SongRoleRequirementFalloutWire {
  is_blocked: boolean
  block_message: string
  is_stale: boolean
  pending_adds: SongRoleRequirementAdditionWire[]
  pending_edits: SongRoleRequirementCountChangeWire[]
  pending_removals: SongRoleRequirementRemovalWire[]
  loud: string[]
  quiet: string[]
}

/** One future Rehearsal a cast candidate can't make, as `serialize_song_cast_picker()` emits it (issue #499, ADR 0019). Admin-only: `reason` is ADR 0005 free text, served only by an `AdminApiView`. */
export interface SongCastConflictEntryWire {
  rehearsal_id: number
  date: string
  is_full_conflict: boolean
  reason: string
}

/** One Song-level cast candidate, as `serialize_song_cast_picker()` emits it (issue #499). */
export interface SongCastPickerOption {
  person_id: number
  person_name: string
  has_declared_role: boolean
  conflicts: SongCastConflictEntryWire[]
}

/** `data` shape of `GET /api/songs/<pk>/cast/picker/<role_id>/` -- its own shape, not the write envelope. */
export interface SongCastPickerPayload {
  song_id: number
  song_title: string
  role_id: number
  role_name: string
  declared: SongCastPickerOption[]
  others: SongCastPickerOption[]
}

/** One `(role_id, person_id)` cast add, as `build_song_cast_buffer_from_request()` reads it. */
export interface SongCastAddedEntryWire {
  role_id: number
  person_id: number
}

/** `/api/songs/<pk>/cast/{preview,save}/` request body (issue #499, mirroring `scheduling/services.py`'s `SongCastEditBuffer`).
 *
 * Carries no `semester_id`, unlike every other Buffer on the wire: this
 * surface's Semester check is "does the URL's Song belong to the viewing
 * Semester", answered server-side with a 404.
 */
export interface SongCastBufferWire {
  song_updated_at: string
  removed_assignment_ids: number[]
  added_entries: SongCastAddedEntryWire[]
}

/** One pending add or removal line, as `serialize_song_cast_fallout()` emits it. */
export interface SongCastChangeWire {
  role_name: string
  person_name: string
}

/** `SongCastFallout`, as `serialize_song_cast_fallout()` emits it -- the Cast Preview response's `fallout` value. */
export interface SongCastFalloutWire {
  is_blocked: boolean
  block_message: string
  is_stale: boolean
  pending_adds: SongCastChangeWire[]
  pending_removals: SongCastChangeWire[]
  loud: string[]
  quiet: string[]
}

/**
 * The Song page's combined edit body: the flat union of the Requirements
 * and cast Buffer wires, posted to `songs/<pk>/edit/{preview,save}/` so
 * both Buffers commit in one transaction (PR #502 review). The two key
 * sets don't overlap, which is what lets each server-side builder read
 * exactly the keys it already documents.
 */
export type SongEditBufferWire = SongRoleRequirementBufferWire &
  SongCastBufferWire

/** `SongEditFallout`, as `serialize_song_edit_fallout()` emits it -- `cast` is null when the session staged no cast change. */
export interface SongEditFalloutWire {
  requirements: SongRoleRequirementFalloutWire
  cast: SongCastFalloutWire | null
}
