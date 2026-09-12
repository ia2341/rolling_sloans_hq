import type { CastEntry, RoleRequirement } from '../../api/setlistTypes'
import type { CastEditBuffer } from './songCastEditModel'

interface CastEditorProps {
  cast: CastEntry[]
  /** Only Roles carrying a SongRoleRequirement are castable at all (ADR 0015) — the editor shows exactly those rows. */
  roleRequirements: RoleRequirement[]
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
 * Rows come from `roleRequirements`, not from `cast`: a Role is castable
 * only once a Requirement exists for it (ADR 0015), so a Requirement with
 * nobody on it must still offer its "+" and a Role with no Requirement
 * must not appear at all. Names render as plain text here rather than
 * through `CastCell`, because every name in edit mode needs its own
 * remove control — `CastCell`'s read-mode rendering (person links, the
 * "(you)" marker) is what the non-editing view keeps using.
 */
export function CastEditor({
  cast,
  roleRequirements,
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
      {roleRequirements.length === 0 ? (
        <p className="text-sm text-rs-muted">
          No Role Requirements yet — add one below before casting anyone.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {roleRequirements.map((requirement) => {
            const entry = cast.find(
              (candidate) => candidate.role_id === requirement.role_id,
            )
            const pending = buffer.addedEntries.filter(
              (candidate) => candidate.roleId === requirement.role_id,
            )
            return (
              <li
                key={requirement.role_id}
                className="flex flex-col gap-1 rounded border border-rs-border p-2"
              >
                <span className="text-xs font-semibold uppercase text-rs-muted">
                  {requirement.role_name}
                </span>
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
                              aria-label={`Remove ${performer.name} from ${requirement.role_name}`}
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
                      {entryToAdd.isRoleMismatch && <span>◦</span>}
                      <button
                        type="button"
                        aria-label={`Remove ${entryToAdd.personName} from ${requirement.role_name}`}
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
                        id: requirement.role_id,
                        name: requirement.role_name,
                      })
                    }
                    className="rounded border border-rs-border px-2 py-0.5 text-xs font-medium hover:bg-rs-border/40"
                  >
                    + Cast {requirement.role_name}
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
