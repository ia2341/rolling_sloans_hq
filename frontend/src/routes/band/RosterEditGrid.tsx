import { RoleMismatchBadge } from '../../components/ui/CastLine'
import { rowBadges, type RosterEditRow } from './rosterEditModel'

interface RosterEditGridProps {
  rows: RosterEditRow[]
  rowErrors: Record<string, Record<string, string[]>>
  onDelete: (rowKey: string) => void
  onUndoDelete: (rowKey: string) => void
  onResendInvite: (personId: number) => void
  resentPersonIds: ReadonlySet<number>
}

/**
 * The Roster editor's grid (issue #374, narrowed to add/remove-only by
 * #379, and to a compact read-only card by #407): the Pending Buffer and
 * nothing else -- a struck-through row and an `Add`/`Invite` badge are
 * the edits themselves, mirroring `SetlistEditGrid`'s shape but with no
 * ordering (the Roster has no position to reorder). No name-edit
 * affordance of any kind -- an existing Person's name is set only on
 * their own Person page, and a not-yet-saved invite's name is fixed by
 * removing and re-adding the row through the Add-people popup. No
 * Role-editing control of any kind -- a Person's declared Roles are set
 * only on their Person page (#378).
 */
export function RosterEditGrid({
  rows,
  rowErrors,
  onDelete,
  onUndoDelete,
  onResendInvite,
  resentPersonIds,
}: RosterEditGridProps) {
  if (rows.length === 0) {
    return (
      <p className="text-sm text-rs-muted">
        No one is on the Roster yet. Use + Add people to start.
      </p>
    )
  }

  return (
    <ul className="flex flex-wrap gap-2">
      {rows.map((row) => {
        const errors = rowErrors[row.rowKey] ?? {}
        const badges = rowBadges(row)
        return (
          <li
            key={row.rowKey}
            className={
              row.deleted
                ? 'flex w-56 flex-col gap-2 rounded border border-rs-border p-2 opacity-60'
                : 'flex w-56 flex-col gap-2 rounded border border-rs-border p-2'
            }
          >
            <div className="flex items-baseline justify-between gap-2">
              <span
                className={
                  row.deleted
                    ? 'truncate text-sm font-medium line-through'
                    : 'truncate text-sm font-medium'
                }
              >
                {row.name}
              </span>
              <span className="shrink-0 text-xs text-rs-muted">
                {row.songCount} song{row.songCount === 1 ? '' : 's'}
              </span>
            </div>

            <div className="flex flex-wrap items-center gap-1">
              {row.isRoleMismatch && <RoleMismatchBadge />}
              {row.inviteStatus === 'not_yet_invited' && (
                <span className="rounded-full border border-dashed border-rs-border px-2 py-0.5 text-xs text-rs-muted">
                  not yet invited
                </span>
              )}
              {row.inviteStatus === 'invited' && (
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

            {errors.name && (
              <p role="alert" className="text-xs text-rs-danger">
                {errors.name.join(', ')}
              </p>
            )}

            <div className="flex flex-wrap gap-2">
              {!row.deleted &&
                row.inviteStatus !== 'accepted' &&
                row.personId !== null && (
                  <button
                    type="button"
                    onClick={() => onResendInvite(row.personId as number)}
                    disabled={resentPersonIds.has(row.personId)}
                    className="rounded border border-rs-border px-2 py-1 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {resentPersonIds.has(row.personId)
                      ? 'Invite sent'
                      : row.inviteStatus === 'not_yet_invited'
                        ? 'Invite'
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
            </div>
          </li>
        )
      })}
    </ul>
  )
}
