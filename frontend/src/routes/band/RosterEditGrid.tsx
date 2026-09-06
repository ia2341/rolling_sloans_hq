import type { MemberRole } from '../../api/memberTypes'
import { RoleMismatchBadge } from '../../components/ui/CastLine'
import { isEdited, rowBadges, type RosterEditRow } from './rosterEditModel'
import { RolePicker } from './RolePicker'

interface RosterEditGridProps {
  rows: RosterEditRow[]
  rowErrors: Record<string, Record<string, string[]>>
  availableRoles: MemberRole[]
  onUpdateName: (rowKey: string, name: string) => void
  onUpdateRoles: (rowKey: string, roleIds: Set<number>) => void
  onDelete: (rowKey: string) => void
  onUndoDelete: (rowKey: string) => void
  onResendInvite: (personId: number) => void
  resentPersonIds: ReadonlySet<number>
  onRoleDeclared: (role: MemberRole) => void
}

/**
 * The Roster editor's grid (issue #374): the Pending Buffer and nothing
 * else -- a struck-through row and a `Remove`/`Add`/`Invite`/`Rename`/
 * `Roles` badge are the edits themselves, mirroring `SetlistEditGrid`'s
 * shape but with no ordering (the Roster has no position to reorder).
 */
export function RosterEditGrid({
  rows,
  rowErrors,
  availableRoles,
  onUpdateName,
  onUpdateRoles,
  onDelete,
  onUndoDelete,
  onResendInvite,
  resentPersonIds,
  onRoleDeclared,
}: RosterEditGridProps) {
  if (rows.length === 0) {
    return (
      <p className="text-sm text-rs-muted">
        No one is on the Roster yet. Use + Add people to start.
      </p>
    )
  }

  return (
    <ul className="flex flex-col gap-2">
      {rows.map((row) => {
        const errors = rowErrors[row.rowKey] ?? {}
        const badges = rowBadges(row)
        return (
          <li
            key={row.rowKey}
            className={
              row.deleted
                ? 'rounded border border-rs-border p-3 opacity-60'
                : 'rounded border border-rs-border p-3'
            }
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="flex min-w-0 flex-1 flex-col gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    type="text"
                    value={row.name}
                    disabled={row.deleted}
                    onChange={(event) =>
                      onUpdateName(row.rowKey, event.target.value)
                    }
                    className={
                      row.deleted
                        ? 'rounded border border-rs-border px-2 py-1 text-sm line-through'
                        : 'rounded border border-rs-border px-2 py-1 text-sm'
                    }
                  />
                  {row.isRoleMismatch && <RoleMismatchBadge />}
                  {row.isPendingInvite && (
                    <span className="rounded-full border border-dashed border-rs-border px-2 py-0.5 text-xs text-rs-muted">
                      invited · not active yet
                    </span>
                  )}
                  {badges.map((badge) => (
                    <span
                      key={badge}
                      className="rounded bg-rs-border/60 px-1.5 py-0.5 text-xs font-semibold uppercase"
                    >
                      {badge}
                    </span>
                  ))}
                </div>

                {!row.deleted && (
                  <RolePicker
                    roleIds={row.roleIds}
                    availableRoles={availableRoles}
                    onChange={(next) => onUpdateRoles(row.rowKey, next)}
                    onRoleDeclared={onRoleDeclared}
                  />
                )}

                {errors.name && (
                  <p role="alert" className="text-xs text-rs-danger">
                    {errors.name.join(', ')}
                  </p>
                )}
                {errors.role_ids && (
                  <p role="alert" className="text-xs text-rs-danger">
                    {errors.role_ids.join(', ')}
                  </p>
                )}
              </div>

              <div className="flex shrink-0 flex-col items-end gap-2 text-sm">
                <p className="text-rs-muted">
                  {row.songCount} song{row.songCount === 1 ? '' : 's'}
                </p>
                {row.isPendingInvite && row.personId !== null && (
                  <button
                    type="button"
                    onClick={() => onResendInvite(row.personId as number)}
                    disabled={resentPersonIds.has(row.personId)}
                    className="rounded border border-rs-border px-2 py-1 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {resentPersonIds.has(row.personId)
                      ? 'Invite sent'
                      : 'Invite again'}
                  </button>
                )}
                {row.deleted ? (
                  <button
                    type="button"
                    onClick={() => onUndoDelete(row.rowKey)}
                    className="rounded border border-rs-border px-2 py-1 text-xs font-medium"
                  >
                    Undo
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => onDelete(row.rowKey)}
                    className="rounded border border-rs-border px-2 py-1 text-xs font-medium text-rs-danger"
                  >
                    Remove
                  </button>
                )}
                {!row.deleted && isEdited(row) && (
                  <span className="sr-only">Edited</span>
                )}
              </div>
            </div>
          </li>
        )
      })}
    </ul>
  )
}
