interface EditToolbarProps {
  what: string
  changeCount: number
  blockedReason: string | null
  onDiscard: () => void
  onRequestSave: () => void
}

/**
 * The sticky dark edit-in-place toolbar (issue #328 user stories 18-22):
 * Discard and Save changes, plus an unsaved-change count once there is one.
 * Rendered from one component so every admin surface's toolbar is the same
 * toolbar. There is deliberately no Preview button — the Save popup (#334)
 * is the only way to see consequences.
 */
export function EditToolbar({
  what,
  changeCount,
  blockedReason,
  onDiscard,
  onRequestSave,
}: EditToolbarProps) {
  return (
    <div
      aria-label={`Editing ${what}`}
      className="sticky top-0 z-30 flex items-center justify-between gap-3 bg-rs-toolbar-bg px-4 py-2 text-rs-toolbar-fg"
    >
      <span className="text-sm">
        {changeCount > 0
          ? `${changeCount} unsaved change${changeCount === 1 ? '' : 's'}`
          : ''}
      </span>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={onDiscard}
          className="rounded border border-rs-toolbar-fg/30 px-3 py-1.5 text-sm font-medium hover:bg-white/10"
        >
          Discard
        </button>
        <button
          type="button"
          onClick={onRequestSave}
          disabled={changeCount === 0 || blockedReason !== null}
          className="rounded bg-rs-accent px-3 py-1.5 text-sm font-medium text-rs-accent-fg disabled:cursor-not-allowed disabled:opacity-50"
        >
          Save changes
        </button>
      </div>
    </div>
  )
}
