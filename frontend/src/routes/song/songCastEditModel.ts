import type { PreviewChange, PreviewResult } from '../../api/previewTypes'
import type {
  CastEntry,
  RoleRequirement,
  SongCastBufferWire,
  SongCastFalloutWire,
  SongCastPickerOption,
} from '../../api/setlistTypes'
import type { AppContext } from '../../api/types'

/**
 * The Cast editor's write envelope (issue #499, ADR 0019), mirroring
 * `SongRoleRequirementWriteEnvelope`'s shape. This surface's Buffer has no
 * per-row identity (every field is an id or a flat pair of ids), so
 * `errors` is always the generic envelope's flat map, never a row-keyed
 * one -- `build_song_cast_buffer_from_request()` reports through
 * `non_field_errors` alone.
 */
export interface SongCastWriteEnvelope {
  context: AppContext
  ok: boolean
  errors: Record<string, string[]>
  non_field_errors: string[]
  fallout: SongCastFalloutWire | null
  values: unknown
  data: null
}

/**
 * One not-yet-saved cast pick, held entirely in client state (issue
 * #499) -- the Song-level counterpart of the Rehearsal grid's
 * `PendingEntry`. `isRoleMismatch` predicts the flag the server would
 * compute on save (ADR 0002), so a pending name carries the same badge a
 * saved one does rather than only after a round trip.
 */
export interface PendingCastEntry {
  key: string
  roleId: number
  personId: number
  personName: string
  isRoleMismatch: boolean
}

/**
 * One Role the Cast editor offers a row for (PR #502 review). Deliberately
 * a two-field value rather than a `RoleRequirement`: the Song page derives
 * it from the *staged* Requirements rows of the open edit session (which
 * carry no `target`/`actual` yet), while the Setlist popover derives it
 * from the Song's saved `role_requirements` — and all the editor ever
 * needs from either is which Role, called what.
 */
export interface CastableRole {
  roleId: number
  roleName: string
}

/** Maps a Song payload's saved `role_requirements` onto the editor's row list -- the Setlist popover's source, where no Requirement is being edited. */
export function castableRolesFromRequirements(
  roleRequirements: RoleRequirement[],
): CastableRole[] {
  return roleRequirements.map((requirement) => ({
    roleId: requirement.role_id,
    roleName: requirement.role_name,
  }))
}

/**
 * The whole Pending Buffer the Cast editor stages, for one Song: which
 * saved `SongRoleAssignment` rows to delete, and which (role, person)
 * pairs to create. Deliberately a plain value rather than several pieces
 * of component state, so the Song page and the Setlist's inline popover
 * can share every helper below verbatim.
 */
export interface CastEditBuffer {
  removedAssignmentIds: number[]
  addedEntries: PendingCastEntry[]
}

/** The empty Buffer a fresh edit session starts from. */
export const EMPTY_CAST_BUFFER: CastEditBuffer = {
  removedAssignmentIds: [],
  addedEntries: [],
}

/** Builds the stable key a pending pick is tracked under, so re-picking the same person on the same Role overwrites rather than duplicates. */
export function castEntryKey(roleId: number, personId: number): string {
  return `${roleId}:${personId}`
}

/** Stages `option` as a pending cast pick on `roleId` -- a no-op if that exact pick is already staged. */
export function addCastEntry(
  buffer: CastEditBuffer,
  roleId: number,
  option: SongCastPickerOption,
): CastEditBuffer {
  const key = castEntryKey(roleId, option.person_id)
  if (buffer.addedEntries.some((entry) => entry.key === key)) return buffer
  return {
    ...buffer,
    addedEntries: [
      ...buffer.addedEntries,
      {
        key,
        roleId,
        personId: option.person_id,
        personName: option.person_name,
        isRoleMismatch: !option.has_declared_role,
      },
    ],
  }
}

/** Drops a pending pick by its key, leaving every saved row alone. */
export function removePendingCastEntry(
  buffer: CastEditBuffer,
  key: string,
): CastEditBuffer {
  return {
    ...buffer,
    addedEntries: buffer.addedEntries.filter((entry) => entry.key !== key),
  }
}

/** Stages a saved `SongRoleAssignment` for deletion -- idempotent, so a double-click stages one removal. */
export function removeSavedCastEntry(
  buffer: CastEditBuffer,
  assignmentId: number,
): CastEditBuffer {
  if (buffer.removedAssignmentIds.includes(assignmentId)) return buffer
  return {
    ...buffer,
    removedAssignmentIds: [...buffer.removedAssignmentIds, assignmentId],
  }
}

/** Un-stages a saved row's removal (the ✕'s Undo). */
export function undoRemoveSavedCastEntry(
  buffer: CastEditBuffer,
  assignmentId: number,
): CastEditBuffer {
  return {
    ...buffer,
    removedAssignmentIds: buffer.removedAssignmentIds.filter(
      (id) => id !== assignmentId,
    ),
  }
}

/** How many unsaved changes the shell's edit toolbar should report: every removal plus every pick. */
export function computeCastChangeCount(buffer: CastEditBuffer): number {
  return buffer.removedAssignmentIds.length + buffer.addedEntries.length
}

/** Person ids already cast on `roleId` (saved, minus staged removals, plus staged picks) -- what the picker must not re-offer. */
export function castPersonIdsFor(
  cast: CastEntry[],
  buffer: CastEditBuffer,
  roleId: number,
): Set<number> {
  const ids = new Set<number>()
  const entry = cast.find((candidate) => candidate.role_id === roleId)
  for (const performer of entry?.performers ?? []) {
    if (
      performer.assignment_id !== undefined &&
      buffer.removedAssignmentIds.includes(performer.assignment_id)
    ) {
      continue
    }
    ids.add(performer.id)
  }
  for (const pending of buffer.addedEntries) {
    if (pending.roleId === roleId) ids.add(pending.personId)
  }
  return ids
}

/** Builds the Cast Preview/Save request body from the current Buffer, pinned to the Song's own `updated_at` (ADR 0019). */
export function buildCastBufferWire(
  songUpdatedAt: string,
  buffer: CastEditBuffer,
): SongCastBufferWire {
  return {
    song_updated_at: songUpdatedAt,
    removed_assignment_ids: [...buffer.removedAssignmentIds],
    added_entries: buffer.addedEntries.map((entry) => ({
      role_id: entry.roleId,
      person_id: entry.personId,
    })),
  }
}

const STALE_MESSAGE =
  'This Song changed while you were editing — reload and reapply.'

/**
 * Maps the Cast Preview write envelope onto `SaveChangesDialog`'s
 * surface-agnostic `PreviewResult` (issue #499). This surface never
 * carries a `doomed` block: removing a cast member destroys no Recording
 * and no upload, only a row an admin can re-add from the same picker.
 */
export function mapSongCastPreviewToResult(
  envelope: SongCastWriteEnvelope,
): PreviewResult {
  if (!envelope.ok || envelope.fallout === null) {
    return {
      ok: false,
      changes: [],
      fallout: { loud: [], quiet: [] },
      nonFieldErrors: envelope.non_field_errors,
    }
  }

  const fallout = envelope.fallout
  if (fallout.is_blocked) {
    return {
      ok: false,
      changes: [],
      fallout: { loud: [], quiet: [] },
      nonFieldErrors: [fallout.block_message],
    }
  }
  if (fallout.is_stale) {
    return {
      ok: false,
      changes: [],
      fallout: { loud: [], quiet: [] },
      nonFieldErrors: [STALE_MESSAGE],
    }
  }

  const changes: PreviewChange[] = [
    ...fallout.pending_adds.map((change): PreviewChange => ({
      op: 'Add',
      object: `${change.person_name} — ${change.role_name}`,
    })),
    ...fallout.pending_removals.map((change): PreviewChange => ({
      op: 'Remove',
      object: `${change.person_name} — ${change.role_name}`,
    })),
  ]

  return {
    ok: true,
    changes,
    fallout: { loud: fallout.loud, quiet: fallout.quiet },
  }
}
