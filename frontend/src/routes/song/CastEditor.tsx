import type { CastEntry } from '../../api/setlistTypes'
import { RoleMismatchBadge } from '../../components/ui/CastLine'
import type { CastableRole, CastEditBuffer } from './songCastEditModel'

interface CastEditorProps {
  cast: CastEntry[]
  /**
   * Only Roles carrying a SongRoleRequirement are castable at all (ADR
   * 0015) — the editor shows exactly those rows. The Song page passes the
   * *staged* Requirements of the open edit session, not the last-saved
   * ones, so a Requirement added in this session is castable immediately
   * and one removed in it stops being offered (PR #502 review); the
   * Setlist popover, which edits no Requirements, passes the saved set.
   */
  castableRoles: CastableRole[]
  buffer: CastEditBuffer
  onOpenPicker: (role: { id: number; name: string }) => void
  onRemoveSaved: (assignmentId: number) => void
  onUndoRemoveSaved: (assignmentId: number) => void
  onRemovePending: (key: string) => void
}

/**
 * The Song page's Cast edit mode (issue #499, ADR 0019): one row per
 * castable Role, each listing who plays it with a ✕ per person and a "+
 * Cast someone" control that opens `CastPickerSheet`. A removed saved row
 * stays visible, struck through, with Undo — the same treatment
 * `RequirementsEditor` gives a removed Requirement, so the two edit modes
 * on this page read alike.
 *
 * Rows come from `castableRoles`, not from `cast`: a Role is castable
 * only once a Requirement exists for it (ADR 0015), so a Requirement with
 * nobody on it must still offer its "+" and a Role with no Requirement
 * must not appear at all. Names render as plain text here rather than
 * through `CastCell`, because every name in edit mode needs its own
 * remove control — `CastCell`'s read-mode rendering (person links, the
 * "(you)" marker) is what the non-editing view keeps using. A mismatched
 * Role Assignment (ADR 0002) wears the shared `RoleMismatchBadge` on both
 * a saved and a staged name, the same marker the read-only cast tables
 * use, rather than an unexplained glyph of this surface's own.
 */
export function CastEditor({
  cast,
  castableRoles,
  buffer,
  onOpenPicker,
  onRemoveSaved,
  onUndoRemoveSaved,
  onRemovePending,
}: CastEditorProps) {
  return (
    <div className="pt-2">
      <p className="pb-2 text-xs text-rs-muted">
        A cast change applies to every rehearsal and the concert.
      </p>
      {castableRoles.length === 0 ? (
        <p className="text-sm text-rs-muted">
          No Role Requirements yet — add one below before casting anyone.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {castableRoles.map((requirement) => {
            const entry = cast.find(
              (candidate) => candidate.role_id === requirement.roleId,
            )
            const pending = buffer.addedEntries.filter(
              (candidate) => candidate.roleId === requirement.roleId,
            )
            const activeCount =
              (entry?.performers ?? []).filter(
                (performer) =>
                  performer.assignment_id === undefined ||
                  !buffer.removedAssignmentIds.includes(
                    performer.assignment_id,
                  ),
              ).length + pending.length
            const target = requirement.target
            return (
              <li
                key={requirement.roleId}
                className="flex flex-col gap-1 rounded border border-rs-border p-2"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-semibold uppercase text-rs-muted">
                    {requirement.roleName}
                  </span>
                  {target !== undefined && (
                    <span
                      className={`text-xs ${
                        activeCount < target
                          ? 'text-rs-warning-fg'
                          : activeCount > target
                            ? 'text-rs-warning-fg'
                            : 'text-rs-muted'
                      }`}
                    >
                      {activeCount} of {target} cast
                      {activeCount < target && ' (understaffed)'}
                      {activeCount > target && ' (overstaffed)'}
                    </span>
                  )}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {(entry?.performers ?? []).map((performer) => {
                    const assignmentId = performer.assignment_id
                    const removed =
                      assignmentId !== undefined &&
                      buffer.removedAssignmentIds.includes(assignmentId)
                    return (
                      <span
                        key={performer.id}
                        className={`inline-flex items-center gap-1 rounded-full border border-rs-border px-2 py-0.5 text-xs ${
                          removed ? 'opacity-50 line-through' : ''
                        }`}
                      >
                        {performer.name}
                        {performer.is_role_mismatch && <RoleMismatchBadge />}
                        {assignmentId !== undefined &&
                          (removed ? (
                            <button
                              type="button"
                              onClick={() => onUndoRemoveSaved(assignmentId)}
                              className="no-underline"
                            >
                              Undo
                            </button>
                          ) : (
                            <button
                              type="button"
                              aria-label={`Remove ${performer.name} from ${requirement.roleName}`}
                              onClick={() => onRemoveSaved(assignmentId)}
                            >
                              ✕
                            </button>
                          ))}
                      </span>
                    )
                  })}
                  {pending.map((entryToAdd) => (
                    <span
                      key={entryToAdd.key}
                      className="inline-flex items-center gap-1 rounded-full border border-rs-border px-2 py-0.5 text-xs ring-2 ring-rs-accent"
                    >
                      {entryToAdd.personName}
                      {entryToAdd.isRoleMismatch && <RoleMismatchBadge />}
                      <button
                        type="button"
                        aria-label={`Remove ${entryToAdd.personName} from ${requirement.roleName}`}
                        onClick={() => onRemovePending(entryToAdd.key)}
                      >
                        ✕
                      </button>
                    </span>
                  ))}
                  <button
                    type="button"
                    onClick={() =>
                      onOpenPicker({
                        id: requirement.roleId,
                        name: requirement.roleName,
                      })
                    }
                    className="rounded border border-rs-border px-2 py-0.5 text-xs font-medium hover:bg-rs-border/40"
                  >
                    + Cast {requirement.roleName}
                  </button>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
