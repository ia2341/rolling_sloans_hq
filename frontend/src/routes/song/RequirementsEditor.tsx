import type { RequirementEditRow } from './songRoleRequirementsEditModel'

interface RequirementsEditorProps {
  rows: RequirementEditRow[]
  rowErrors: Record<string, Record<string, string[]>>
  onUpdateCount: (roleId: number, count: number) => void
  onRemove: (roleId: number) => void
  onUndoRemove: (roleId: number) => void
  onOpenAddSheet: () => void
}

/**
 * The Requirements editor's row list (issue #339): one full-width,
 * tappable row per Requirement on every viewport (no horizontal-scroll
 * fallback, user story 29) -- a single-column card layout works
 * identically on desktop and phone here, unlike the Setlist grid's
 * table/cards split. A row marked for removal stays visible, struck
 * through, with Undo (user story 8); a retired Role's row is shown and
 * clearable, never hidden (issue #207).
 */
export function RequirementsEditor({
  rows,
  rowErrors,
  onUpdateCount,
  onRemove,
  onUndoRemove,
  onOpenAddSheet,
}: RequirementsEditorProps) {
  return (
    <div className="pt-2">
      {rows.length === 0 ? (
        <p className="pb-2 text-sm text-rs-muted">No Role Requirements yet.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {rows.map((row) => {
            const fieldErrors = rowErrors[`role-${row.roleId}`]
            return (
              <li
                key={row.roleId}
                className={`flex items-center gap-2 rounded border border-rs-border p-2 ${row.removed ? 'opacity-50' : ''}`}
              >
                <span className={`flex-1 text-sm ${row.removed ? 'line-through' : ''}`}>
                  {row.roleName}
                  {row.isRetiredRole && (
                    <span className="ml-1 text-xs text-rs-muted">(retired Role)</span>
                  )}
                  {row.originalCount === null && !row.removed && (
                    <span className="ml-1 text-xs text-rs-muted">(new)</span>
                  )}
                </span>
                {!row.removed && (
                  <input
                    type="number"
                    min={1}
                    value={row.count}
                    onChange={(event) => onUpdateCount(row.roleId, Number(event.target.value))}
                    aria-label={`${row.roleName} target count`}
                    className="w-16 rounded border border-rs-border px-2 py-1 text-sm"
                  />
                )}
                {row.removed ? (
                  <button
                    type="button"
                    onClick={() => onUndoRemove(row.roleId)}
                    className="rounded border border-rs-border px-2 py-1 text-xs font-medium hover:bg-rs-border/40"
                  >
                    Undo
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => onRemove(row.roleId)}
                    aria-label={`Remove ${row.roleName} requirement`}
                    className="rounded border border-rs-border px-2 py-1 text-xs font-medium hover:bg-rs-border/40"
                  >
                    Remove
                  </button>
                )}
                {fieldErrors && (
                  <ul className="basis-full text-xs text-rs-danger">
                    {Object.entries(fieldErrors).map(([field, messages]) => (
                      <li key={field}>
                        {field}: {messages.join(', ')}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            )
          })}
        </ul>
      )}
      <button
        type="button"
        onClick={onOpenAddSheet}
        className="mt-2 rounded border border-rs-border px-3 py-1.5 text-sm font-medium hover:bg-rs-border/40"
      >
        + Add role requirement
      </button>
    </div>
  )
}
