/**
 * Wire types for `/api/members/` and `/api/members/<pk>/` (issue #333),
 * mirroring `scheduling/serializers.py`'s `serialize_band()`,
 * `serialize_person()` and `serialize_person_recordings()` exactly.
 *
 * Per the issue's "absent, not null" contract: a viewer-conditional key is
 * modeled with `?:`, never as `T | null` — a teammate's payload simply
 * does not carry `email` or `recordings` at all, and this file must not
 * paper over that with an optional-and-nullable union.
 */

/** One row of the Band page's Roster (issue #333). */
export interface RosterEntry {
  id: number
  name: string
  roles: string[]
  song_count: number
}

/** `data` shape of `GET /api/members/`. */
export interface BandPayload {
  semester_name: string | null
  member_count: number
  members: RosterEntry[]
}

/** One Role, as a declared-Roles chip or an entry in the editable catalog. */
export interface MemberRole {
  id: number
  name: string
}

/** One row of a Person's Songs section: the Song they're on and the Role they fill (never `is_role_mismatch` — ADR 0002). */
export interface PersonSong {
  song_id: number
  song_title: string
  artist: string
  role_name: string
}

/** One row of a Person's own Recordings list (self only). Never carries the object key (ADR 0004) — `playback_url` is a freshly issued short-lived signed GET. */
export interface PersonRecordingItem {
  id: number
  song_title: string
  rehearsal_date: string
  start_time: string | null
  end_time: string | null
  note: string
  file_size: number
  uploaded_at: string
  playback_url: string
}

/** One RehearsalSong slot as an Upload-a-take picker option. */
export interface RecordingSlotOption {
  id: number
  song_id: number
  song_title: string
  rehearsal_date: string
  start_time: string | null
  end_time: string | null
}

/** The self-only Recordings block: count, rows, and the Upload-a-take slot picker's options. */
export interface PersonRecordingsBlock {
  count: number
  items: PersonRecordingItem[]
  upload_slots: RecordingSlotOption[]
}

/**
 * `data` shape of `GET /api/members/<pk>/`, computed for exactly one of
 * the three viewer states. `email` and `recordings` are present only in
 * the self payload; `available_roles` only when `can_edit_roles`;
 * `roles`/`songs` only when `has_membership` is true (the not-yet-rostered
 * self case omits both sections entirely rather than rendering them
 * empty).
 */
export interface PersonPayload {
  id: number
  name: string
  is_self: boolean
  can_edit_roles: boolean
  has_membership: boolean
  semester_name: string | null
  email?: string
  available_roles?: MemberRole[]
  roles?: MemberRole[]
  songs?: PersonSong[]
  recordings?: PersonRecordingsBlock
}

/** Success body of `POST /api/members/recordings/presign/` (`data` of the read envelope it wears — see #307's envelope boundary rule). */
export interface RecordingPresignReservation {
  upload_url: string
  fields: Record<string, string>
  object_key: string
}

/** Failure body of `POST /api/members/recordings/presign/`: carries `context` and a plain `error` string, neither the read nor the write envelope's failure shape. */
export interface RecordingPresignErrorBody {
  error: string
}
