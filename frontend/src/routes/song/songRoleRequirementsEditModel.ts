import type { PreviewChange, PreviewResult } from '../../api/previewTypes'
import type {
  RoleRequirement,
  SongRoleRequirementBufferWire,
  SongRoleRequirementFalloutWire,
} from '../../api/setlistTypes'
import type { AppContext } from '../../api/types'

/**
 * The Requirements editor's write envelope (issue #339), mirroring
 * `SetlistWriteEnvelope`'s shape: `errors` is this surface's own
 * `{row_key: {field: [messages]}}` (`build_song_role_requirement_buffer_from_request()`'s
 * `role-<role_id>`/`entry-<index>` keying), never the generic envelope's
 * flat `Record<string, string[]>`.
 */
export interface SongRoleRequirementWriteEnvelope {
  context: AppContext
  ok: boolean
  errors: Record<string, Record<string, string[]>>
  non_field_errors: string[]
  fallout: SongRoleRequirementFalloutWire | null
  values: unknown
  data: null
}

/**
 * One row of the Requirements editor's Pending Buffer, held entirely in
 * client state (issue #339) -- the same "the grid *is* this Buffer"
 * convention `EditRow` (setlist) uses. A removed row stays in the array,
 * struck through with Undo, rather than disappearing (user story 8).
 */
export interface RequirementEditRow {
  roleId: number
  roleName: string
  count: number
  /** `null` for a brand-new row (nothing to diff against); the saved target count otherwise. */
  originalCount: number | null
  isRetiredRole: boolean
  removed: boolean
}

/** Builds the editor's initial Buffer rows from a freshly-loaded `/api/songs/<pk>/` payload's `role_requirements`. */
export function rowsFromPayload(
  roleRequirements: RoleRequirement[],
): RequirementEditRow[] {
  return roleRequirements.map((status) => ({
    roleId: status.role_id,
    roleName: status.role_name,
    count: status.target,
    originalCount: status.target,
    isRetiredRole: status.is_retired_role,
    removed: false,
  }))
}

/** Appends a brand-new row for `role`, defaulting its target count to 1 -- a no-op if `role` already has a row. */
export function addRequirementRow(
  rows: RequirementEditRow[],
  role: { id: number; name: string },
): RequirementEditRow[] {
  if (rows.some((row) => row.roleId === role.id)) return rows
  return [
    ...rows,
    {
      roleId: role.id,
      roleName: role.name,
      count: 1,
      originalCount: null,
      isRetiredRole: false,
      removed: false,
    },
  ]
}

/** Updates `roleId`'s row count in place. */
export function updateRequirementCount(
  rows: RequirementEditRow[],
  roleId: number,
  count: number,
): RequirementEditRow[] {
  return rows.map((row) => (row.roleId === roleId ? { ...row, count } : row))
}

/** Marks `roleId`'s row removed (struck through, kept for Undo) -- a never-saved row is dropped outright instead. */
export function removeRequirementRow(
  rows: RequirementEditRow[],
  roleId: number,
): RequirementEditRow[] {
  const row = rows.find((candidate) => candidate.roleId === roleId)
  if (!row) return rows
  if (row.originalCount === null)
    return rows.filter((candidate) => candidate.roleId !== roleId)
  return rows.map((candidate) =>
    candidate.roleId === roleId ? { ...candidate, removed: true } : candidate,
  )
}

/** Un-marks `roleId`'s row for removal. */
export function undoRemoveRequirementRow(
  rows: RequirementEditRow[],
  roleId: number,
): RequirementEditRow[] {
  return rows.map((row) =>
    row.roleId === roleId ? { ...row, removed: false } : row,
  )
}

/** True if `row`'s count differs from its saved target; always `false` for a brand-new or removed row. */
export function isEditedCount(row: RequirementEditRow): boolean {
  if (row.removed || row.originalCount === null) return false
  return row.count !== row.originalCount
}

/** How many unsaved changes the toolbar should report: every add, every count edit, every removal (issue #339 user story 4). */
export function computeChangeCount(rows: RequirementEditRow[]): number {
  let count = 0
  for (const row of rows) {
    if (row.removed) {
      count += 1
    } else if (row.originalCount === null) {
      count += 1
    } else if (isEditedCount(row)) {
      count += 1
    }
  }
  return count
}

/** Builds the Requirements Preview/Save request body from the current Buffer -- removed rows are simply not named (issue #339). */
export function buildRequirementBufferWire(
  semesterId: number,
  semesterUpdatedAt: string,
  rows: RequirementEditRow[],
): SongRoleRequirementBufferWire {
  return {
    semester_id: semesterId,
    semester_updated_at: semesterUpdatedAt,
    entries: rows
      .filter((row) => !row.removed)
      .map((row) => ({ role_id: row.roleId, count: row.count })),
  }
}

const STALE_MESSAGE =
  'The Requirements changed while you were editing — reload and reapply.'

/**
 * Maps the Requirements Preview write envelope onto `SaveChangesDialog`'s
 * surface-agnostic `PreviewResult` (issue #339). This surface's honest
 * `loud` tier is usually empty (nothing here destroys a Recording or an
 * Assignment) and it never carries a `doomed` block, per its Fallout's
 * documented shape.
 */
export function mapSongRoleRequirementPreviewToResult(
  envelope: SongRoleRequirementWriteEnvelope,
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

  const changes: PreviewChange[] = [
    ...fallout.pending_adds.map((addition): PreviewChange => ({
      op: 'Add',
      object: `${addition.role_name}, ${addition.count}`,
    })),
    ...fallout.pending_edits.map((change): PreviewChange => ({
      op: 'Roles',
      object: `${change.role_name}, ${change.before} → ${change.after}`,
    })),
    ...fallout.pending_removals.map((removal): PreviewChange => ({
      op: 'Delete',
      object: removal.role_name,
    })),
  ]

  return {
    ok: true,
    changes,
    fallout: { loud: fallout.loud, quiet: fallout.quiet },
  }
}
