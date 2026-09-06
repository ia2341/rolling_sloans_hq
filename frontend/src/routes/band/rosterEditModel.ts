import type { PreviewChange, PreviewResult } from '../../api/previewTypes'
import type {
  MemberRole,
  RosterEditBufferWire,
  RosterEditFalloutWire,
  RosterEditMember,
  RosterImportCandidate,
  UnrosteredPerson,
} from '../../api/memberTypes'
import type { AppContext } from '../../api/types'

/**
 * `/api/members/roster/{preview,save}/`'s write envelope, specialized over
 * this surface's own `errors` shape (`{row_key: {field: [messages]}}`)
 * exactly like `SetlistWriteEnvelope` (`setlistEditModel.ts`) — every
 * error here is a per-row, per-field Validation Error
 * (`RosterBufferValidationError.row_errors`), never a bare field name.
 */
export interface RosterWriteEnvelope {
  context: AppContext
  ok: boolean
  errors: Record<string, Record<string, string[]>>
  non_field_errors: string[]
  fallout: RosterEditFalloutWire | null
  values: unknown
  data: null
}

/**
 * One row of the Roster editor's Pending Buffer, held entirely in client
 * state (issue #374, mirroring `setlistEditModel.ts`'s `EditRow`). The
 * grid *is* this Buffer and nothing else -- a struck-through row and a
 * `Rename`/`Roles`/`Add`/`Invite` badge are all derived from the fields
 * here, never from a second, server-computed shape (ADR 0008: only the
 * server's Preview computes Fallout; this is display-only bookkeeping).
 */
export interface RosterEditRow {
  rowKey: string
  /** `null` only for a not-yet-created invite -- there is no Person row yet. */
  personId: number | null
  name: string
  /** Invite rows only; `null` for every existing/imported/added row (ADR 0005 keeps email off every other Roster surface). */
  email: string | null
  roleIds: Set<number>
  /** Struck through and kept in place with Undo, rather than removed from the array -- but only for a row that has something to undo to (`original !== null`); see `deleteRosterRow()`. */
  deleted: boolean
  origin: 'existing' | 'imported' | 'added' | 'invited'
  /** From the server, for an existing row that never set a password -- backs the "invited · not active yet" badge and "Invite again" control. */
  isPendingInvite: boolean
  isRoleMismatch: boolean
  songCount: number
  /** The saved values at load time, for an existing row -- `null` for a brand-new one (imported, added or invited this session), which has nothing to diff against. */
  original: { name: string; roleIds: Set<number> } | null
}

let rowKeySequence = 0

/** Returns a fresh, render-stable row key (issue #374) -- never reused within one editing session. */
export function nextRowKey(prefix: string): string {
  rowKeySequence += 1
  return `${prefix}-${rowKeySequence}`
}

/** Builds the editor's initial Buffer rows from a freshly-loaded `/api/members/roster/` payload. */
export function rowsFromPayload(members: RosterEditMember[]): RosterEditRow[] {
  return members.map((member) => {
    const roleIds = new Set(member.roles.map((role) => role.id))
    return {
      rowKey: `member-${member.id}`,
      personId: member.id,
      name: member.name,
      email: null,
      roleIds,
      deleted: false,
      origin: 'existing',
      isPendingInvite: member.is_pending_invite,
      isRoleMismatch: member.is_role_mismatch,
      songCount: member.song_count,
      original: { name: member.name, roleIds: new Set(roleIds) },
    }
  })
}

/** Builds one Buffer row for an import-candidate ticked in the Add-people sheet's "Import" section. */
export function newImportedRow(
  candidate: RosterImportCandidate,
): RosterEditRow {
  return {
    rowKey: nextRowKey('imported'),
    personId: candidate.id,
    name: candidate.name,
    email: null,
    roleIds: new Set(candidate.roles.map((role) => role.id)),
    deleted: false,
    origin: 'imported',
    isPendingInvite: false,
    isRoleMismatch: false,
    songCount: 0,
    original: null,
  }
}

/** Builds one Buffer row for an unrostered active Person ticked in the Add-people sheet's "Add existing member" section. */
export function newAddedRow(person: UnrosteredPerson): RosterEditRow {
  return {
    rowKey: nextRowKey('added'),
    personId: person.id,
    name: person.name,
    email: null,
    roleIds: new Set<number>(),
    deleted: false,
    origin: 'added',
    isPendingInvite: false,
    isRoleMismatch: false,
    songCount: 0,
    original: null,
  }
}

/** Builds one Buffer row for a not-yet-existing Person submitted through the Add-people sheet's "Invite new member" section. */
export function newInviteRow(name: string, email: string): RosterEditRow {
  return {
    rowKey: nextRowKey('invited'),
    personId: null,
    name,
    email,
    roleIds: new Set<number>(),
    deleted: false,
    origin: 'invited',
    isPendingInvite: false,
    isRoleMismatch: false,
    songCount: 0,
    original: null,
  }
}

/** True if two Role-id sets hold exactly the same ids, regardless of insertion order. */
function roleSetsEqual(a: Set<number>, b: Set<number>): boolean {
  if (a.size !== b.size) return false
  for (const id of a) if (!b.has(id)) return false
  return true
}

/** True if `row` differs from its saved snapshot; always `false` for a brand-new row (nothing to diff against). */
export function isEdited(row: RosterEditRow): boolean {
  if (row.original === null) return false
  return (
    row.name !== row.original.name ||
    !roleSetsEqual(row.roleIds, row.original.roleIds)
  )
}

/**
 * Deletes `rowKey` from the Buffer (issue #374, mirroring
 * `setlistEditModel.ts`'s `EditRow` delete rule): a row with nothing to
 * undo to (added/imported/invited this same session, `original === null`)
 * is simply removed from the array outright; an existing row is struck
 * through and kept in place, since removing it needs Undo and the Save
 * popup's `pending_removals` line.
 */
export function deleteRosterRow(
  rows: RosterEditRow[],
  rowKey: string,
): RosterEditRow[] {
  const row = rows.find((candidate) => candidate.rowKey === rowKey)
  if (!row) return rows
  if (row.original === null) {
    return rows.filter((candidate) => candidate.rowKey !== rowKey)
  }
  return rows.map((candidate) =>
    candidate.rowKey === rowKey ? { ...candidate, deleted: true } : candidate,
  )
}

/** Returns the badges a grid row should render (issue #374), reusing `PreviewChange['op']`'s existing tokens rather than inventing new display vocabulary. */
export function rowBadges(row: RosterEditRow): PreviewChange['op'][] {
  if (row.deleted) return ['Remove']
  if (row.original === null)
    return [row.origin === 'invited' ? 'Invite' : 'Add']
  const badges: PreviewChange['op'][] = []
  if (row.name !== row.original.name) badges.push('Rename')
  if (!roleSetsEqual(row.roleIds, row.original.roleIds)) badges.push('Roles')
  return badges
}

/**
 * How many unsaved changes the toolbar should report (issue #374,
 * mirroring `setlistEditModel.ts`'s `computeChangeCount`): every new row,
 * every edit to an existing row, plus every removal.
 */
export function computeChangeCount(rows: RosterEditRow[]): number {
  let count = 0
  rows.forEach((row) => {
    if (row.deleted) {
      count += 1
      return
    }
    if (row.original === null) {
      count += 1
      return
    }
    if (isEdited(row)) count += 1
  })
  return count
}

/** Builds the `/api/members/roster/{preview,save}/` request body from the current Buffer (issue #374). */
export function buildBufferWire(
  semesterId: number,
  semesterUpdatedAt: string,
  rows: RosterEditRow[],
): RosterEditBufferWire {
  return {
    semester_id: semesterId,
    semester_updated_at: semesterUpdatedAt,
    entries: rows
      .filter((row) => row.personId !== null && !row.deleted)
      .map((row) => ({
        row_key: row.rowKey,
        person_id: row.personId as number,
        name: row.name,
        role_ids: [...row.roleIds].sort((a, b) => a - b),
      })),
    removed_person_ids: rows
      .filter((row) => row.original !== null && row.deleted)
      .map((row) => row.personId as number),
    invites: rows
      .filter((row) => row.personId === null && !row.deleted)
      .map((row) => ({
        row_key: row.rowKey,
        name: row.name,
        email: row.email ?? '',
      })),
  }
}

/** Adds `role` to `available_roles` if it isn't already present, for the picker's own list after a "declare a new Role" round trip. */
export function withDeclaredRole(
  availableRoles: MemberRole[],
  role: MemberRole,
): MemberRole[] {
  if (availableRoles.some((candidate) => candidate.id === role.id))
    return availableRoles
  return [...availableRoles, role]
}

const STALE_MESSAGE =
  'The roster changed while you were editing — reload and reapply.'

/**
 * Maps `/api/members/roster/preview/`'s write envelope onto
 * `SaveChangesDialog`'s surface-agnostic `PreviewResult` (issue #374),
 * mirroring `mapSetlistPreviewToResult()` exactly. A stale Semester
 * (`fallout.is_stale`) is folded into `ok: false` with a
 * `nonFieldErrors` message; a blocked Buffer (`fallout.is_blocked`,
 * e.g. `SelfRemovalError`) is folded in the same way, using the
 * server's own `block_message`.
 */
export function mapRosterPreviewToResult(
  envelope: RosterWriteEnvelope,
): PreviewResult {
  if (!envelope.ok || envelope.fallout === null) {
    return {
      ok: false,
      changes: [],
      fallout: { loud: [], quiet: [] },
      errors: envelope.errors,
      nonFieldErrors: envelope.non_field_errors,
    }
  }

  const fallout = envelope.fallout
  if (fallout.is_stale) {
    return {
      ok: false,
      changes: [],
      fallout: { loud: [], quiet: [] },
      nonFieldErrors: [STALE_MESSAGE],
    }
  }
  if (fallout.is_blocked) {
    return {
      ok: false,
      changes: [],
      fallout: { loud: [], quiet: [] },
      nonFieldErrors: [fallout.block_message],
    }
  }

  const changes: PreviewChange[] = [
    ...fallout.pending_adds.map((name): PreviewChange => ({
      op: 'Add',
      object: name,
    })),
    ...fallout.pending_invites.map((name): PreviewChange => ({
      op: 'Invite',
      object: name,
    })),
    ...fallout.pending_role_changes.map((description): PreviewChange => ({
      op: 'Roles',
      object: description,
    })),
    ...fallout.pending_name_edits.map((description): PreviewChange => ({
      op: 'Rename',
      object: description,
    })),
    ...fallout.pending_removals.map((removal): PreviewChange => ({
      op: 'Remove',
      object: removal.name,
    })),
  ]

  return {
    ok: true,
    changes,
    fallout: { loud: fallout.loud, quiet: fallout.quiet },
  }
}
