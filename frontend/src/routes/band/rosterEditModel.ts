import type { PreviewChange, PreviewResult } from '../../api/previewTypes'
import type {
  InviteStatus,
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
 * `values` stays `unknown` (shared by resend-invite's `null`, Preview's
 * echoed-Buffer shape, and Save's `RosterSaveValues`) -- a caller narrows
 * it to the shape it actually expects for the endpoint it called.
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
 * grid *is* this Buffer and nothing else -- a struck-through row and an
 * `Add`/`Invite` badge are all derived from the fields here, never from a
 * second, server-computed shape (ADR 0008: only the server's Preview
 * computes Fallout; this is display-only bookkeeping). Carries no Role
 * data (issue #379): the Roster editor is add/remove-only, and a Person's
 * declared Roles are set only on their Person page (#378). Every card is
 * read-only (issue #407): there is no name-edit affordance, so no
 * `Rename` badge either -- fixing a typo in a not-yet-saved invite is
 * remove-and-re-add through the Add-people popup.
 */
export interface RosterEditRow {
  rowKey: string
  /** `null` only for a not-yet-created row -- there is no Person row yet. */
  personId: number | null
  name: string
  /** New-Person rows only; `null` for every existing/imported/added row (ADR 0005 keeps email off every other Roster surface). */
  email: string | null
  /** Struck through and kept in place with Undo, rather than removed from the array -- but only for a row that has something to undo to (`original`); see `deleteRosterRow()`. */
  deleted: boolean
  origin: 'existing' | 'imported' | 'added' | 'invited'
  /** From the server for an existing row, or set locally for a row staged this session -- backs the "must change password" badge. */
  inviteStatus: InviteStatus
  isRoleMismatch: boolean
  songCount: number
  /** `true` for a row present when the page loaded (`origin: 'existing'`); `false` for a brand-new one (imported, added or newly created this session) -- backs the strike-through-and-Undo delete rule, since only a loaded row has a server state to undo to. */
  original: boolean
}

let rowKeySequence = 0

/** Returns a fresh, render-stable row key (issue #374) -- never reused within one editing session. */
export function nextRowKey(prefix: string): string {
  rowKeySequence += 1
  return `${prefix}-${rowKeySequence}`
}

/** Builds the editor's initial Buffer rows from a freshly-loaded `/api/members/roster/` payload. */
export function rowsFromPayload(members: RosterEditMember[]): RosterEditRow[] {
  return members.map((member) => ({
    rowKey: `member-${member.id}`,
    personId: member.id,
    name: member.name,
    email: null,
    deleted: false,
    origin: 'existing',
    inviteStatus: member.invite_status,
    isRoleMismatch: member.is_role_mismatch,
    songCount: member.song_count,
    original: true,
  }))
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
    deleted: false,
    origin: 'imported',
    inviteStatus: 'active',
    isRoleMismatch: false,
    songCount: 0,
    original: false,
  }
}

/** Builds one Buffer row for an unrostered active Person ticked in the Add-people sheet's "Add existing member" section. */
export function newAddedRow(person: UnrosteredPerson): RosterEditRow {
  return {
    rowKey: nextRowKey('added'),
    personId: person.id,
    name: person.name,
    email: null,
    deleted: false,
    origin: 'added',
    inviteStatus: 'active',
    isRoleMismatch: false,
    songCount: 0,
    original: false,
  }
}

/**
 * Builds one Buffer row for a not-yet-existing Person submitted through the
 * Add-people sheet's "New member" section (issue #482, ADR 0018 --
 * replacing the old "Invite new member" section's Invite-now/Add-without-
 * inviting choice with the single admin-relayed-temp-password path).
 */
export function newInviteRow(name: string, email: string): RosterEditRow {
  return {
    rowKey: nextRowKey('invited'),
    personId: null,
    name,
    email,
    deleted: false,
    origin: 'invited',
    inviteStatus: 'must_change_password',
    isRoleMismatch: false,
    songCount: 0,
    original: false,
  }
}

/**
 * Deletes `rowKey` from the Buffer (issue #374, mirroring
 * `setlistEditModel.ts`'s `EditRow` delete rule): a row with nothing to
 * undo to (added/imported/invited this same session, `original: false`)
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
  if (!row.original) {
    return rows.filter((candidate) => candidate.rowKey !== rowKey)
  }
  return rows.map((candidate) =>
    candidate.rowKey === rowKey ? { ...candidate, deleted: true } : candidate,
  )
}

/**
 * Returns the badges a grid row should render (issue #374, narrowed by
 * #407: no `Rename` badge -- the grid no longer offers a name-edit
 * affordance, so an existing row never has anything to badge; narrowed
 * again by #482: no `Invite` badge -- every new row is created the same
 * way now, so all of them badge `Add`), reusing `PreviewChange['op']`'s
 * existing tokens rather than inventing new display vocabulary.
 */
export function rowBadges(row: RosterEditRow): PreviewChange['op'][] {
  if (row.deleted) return ['Remove']
  if (!row.original) return ['Add']
  return []
}

/**
 * How many unsaved changes the toolbar should report (issue #374,
 * narrowed by #407): every new row, plus every removal. There is no
 * per-field edit to an existing row to count anymore -- the Roster
 * editor is add/remove-only once a row is loaded.
 */
export function computeChangeCount(rows: RosterEditRow[]): number {
  let count = 0
  rows.forEach((row) => {
    if (row.deleted) {
      count += 1
      return
    }
    if (!row.original) count += 1
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
      })),
    removed_person_ids: rows
      .filter((row) => row.original && row.deleted)
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
    ...fallout.pending_created.map((name): PreviewChange => ({
      op: 'Add',
      object: name,
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
