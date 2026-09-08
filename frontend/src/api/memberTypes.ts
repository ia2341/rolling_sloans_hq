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

/**
 * One row of the Band page's Roster (issue #333). `invite_status` (issue
 * #455) is present only for an admin viewer -- every Membership is on
 * this list regardless of invite state, so an admin needs a way to tell
 * a not-yet-invited row apart from an active one; a non-admin viewer has
 * no business seeing a teammate's invite lifecycle.
 */
export interface RosterEntry {
  id: number
  name: string
  roles: string[]
  song_count: number
  invite_status?: InviteStatus
}

/**
 * Admin-only gap flag on `/api/members/`: people with a SongRoleAssignment
 * this Semester but no Membership row, so their casting is invisible on
 * the Roster (mirrors `services.unassigned_role_holders_for`). Absent
 * entirely for a non-admin viewer or when nothing is published, per the
 * "absent, not null" wire contract.
 */
export interface UnassignedRoleHolders {
  count: number
  names: string[]
}

/** `data` shape of `GET /api/members/`. */
export interface BandPayload {
  semester_name: string | null
  member_count: number
  members: RosterEntry[]
  unassigned_role_holders?: UnassignedRoleHolders
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

/** A Person's invite lifecycle status (issue #397), mirroring `identity.services.invite_status_for()` exactly. */
export type InviteStatus = 'not_yet_invited' | 'invited' | 'accepted'

/**
 * `data` shape of `GET /api/members/<pk>/`, computed for exactly one of
 * the three viewer states. `email` and `recordings` are present only in
 * the self payload; `available_roles` only when `can_edit_roles`; `songs`
 * only when `has_membership` is true (the not-yet-rostered self case omits
 * that section rather than rendering it empty). `roles` (issue #378,
 * ADR-0014) is unconditional — a standing `PersonRole` declaration needs no
 * Membership to exist, so it's never gated by `has_membership` the way
 * `songs` is. `invite_status` (issue #397) is present only for an admin
 * viewing a teammate — never for `is_self` (a session implies
 * `'accepted'`) and never for a plain teammate viewer.
 */
export interface PersonPayload {
  id: number
  name: string
  is_self: boolean
  can_edit_roles: boolean
  has_membership: boolean
  semester_name: string | null
  roles: MemberRole[]
  email?: string
  available_roles?: MemberRole[]
  invite_status?: InviteStatus
  songs?: PersonSong[]
  recordings?: PersonRecordingsBlock
}

/**
 * Wire types for the Roster editor (issue #336's backend, #374's
 * frontend), mirroring `scheduling/serializers.py`'s
 * `serialize_roster_edit()`/`serialize_roster_edit_fallout()`/
 * `serialize_roster_candidates()`/`serialize_role_declaration()` exactly.
 */

/**
 * One row of `GET /api/members/roster/`'s `members` list — every Membership
 * in the viewing Semester, invited-but-inactive included. No Role data
 * (issue #379): the Roster editor is add/remove-only now, and a Person's
 * declared Roles are set only on their Person page (#378). `invite_status`
 * (issue #397) replaces the old binary `is_pending_invite`.
 */
export interface RosterEditMember {
  id: number
  name: string
  song_count: number
  is_role_mismatch: boolean
  invite_status: InviteStatus
}

/** `data` shape of `GET /api/members/roster/`. No `available_roles` (issue #379): the editor offers no Role-editing control. */
export interface RosterEditPayload {
  semester_id: number | null
  semester_updated_at: string | null
  active_count: number
  invited_count: number
  members: RosterEditMember[]
}

/** One row of `GET /api/members/roster/candidates/`'s `import_candidates` list — a prior Semester's Roster, proposed fresh (ADR 0001). */
export interface RosterImportCandidate {
  id: number
  name: string
  roles: MemberRole[]
}

/** One row of `GET /api/members/roster/candidates/`'s `unrostered_people` list — an active Person with no Membership this Semester. */
export interface UnrosteredPerson {
  id: number
  name: string
}

/** `data` shape of `GET /api/members/roster/candidates/`. */
export interface RosterCandidatesPayload {
  import_source_semester_name: string | null
  import_candidates: RosterImportCandidate[]
  unrostered_people: UnrosteredPerson[]
}

/** One `/api/members/roster/{preview,save}/` request body `entries` row (mirrors `scheduling/services.py`'s `RosterEditEntry`). No `role_ids` (issue #379) -- this Buffer carries no Role data. */
export interface RosterEditEntryWire {
  row_key: string
  person_id: number
  name: string
}

/**
 * One `/api/members/roster/{preview,save}/` request body `invites` row
 * (mirrors `scheduling/services.py`'s `RosterInvite`). `send_invite`
 * (issue #397) is the "Invite now" vs "Add without inviting" choice; it's
 * always sent explicitly here even though the backend defaults it to
 * `true` when absent.
 */
export interface RosterInviteWire {
  row_key: string
  name: string
  email: string
  send_invite: boolean
}

/** `/api/members/roster/{preview,save}/` request body (mirrors `scheduling/services.py`'s `RosterEditBuffer`). */
export interface RosterEditBufferWire {
  semester_id: number
  semester_updated_at: string
  entries: RosterEditEntryWire[]
  removed_person_ids: number[]
  invites: RosterInviteWire[]
}

/** One `RosterRemoval`, as `serialize_roster_edit_fallout()` emits it — the one place a Roster surface shows an email (ADR 0005, issue #228). */
export interface RosterRemovalWire {
  person_id: number
  name: string
  email: string
}

/**
 * `RosterEditFallout`, as `serialize_roster_edit_fallout()` emits it -- the
 * `/api/members/roster/preview/` response's `fallout` value. No
 * `pending_role_changes` (issue #379) -- this Buffer never touches Role
 * data. `pending_added_without_invite` (issue #397) lists a send_invite:
 * false row's outcome separately from `pending_invites`. No
 * `pending_name_edits` (issue #407) -- the Roster editor no longer offers
 * a name-edit affordance.
 */
export interface RosterEditFalloutWire {
  is_blocked: boolean
  block_message: string
  is_stale: boolean
  pending_adds: string[]
  pending_invites: string[]
  pending_added_without_invite: string[]
  pending_removals: RosterRemovalWire[]
  loud: string[]
  quiet: string[]
}

/** `data` shape of `POST /api/members/roster/roles/` — the Role that resulted, plus whether it was created, matched or reactivated. */
export interface RoleDeclaration {
  role: MemberRole
  created: boolean
  reactivated: boolean
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
