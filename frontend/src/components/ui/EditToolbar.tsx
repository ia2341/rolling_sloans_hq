interface EditToolbarProps {
  what: string
  changeCount: number
  blockedReason: string | null
  onDiscard: () => void
  onRequestSave: () => void
}

/**
 * The sticky dark edit-in-place toolbar (issue #328 user stories 18-22):
 * `Editing <what> — N unsaved change(s)` (or `no changes yet`), Discard,
 * and Save changes. Rendered from one component so every admin surface's
 * toolbar is the same toolbar. There is deliberately no Preview button —
 * the Save popup (#334) is the only way to see consequences.
 */
export function EditToolbar({
  what,
  changeCount,
  blockedReason,
  onDiscard,
  onRequestSave,
}: EditToolbarProps) {
  const changeSummary =
    changeCount === 0
      ? 'no changes yet'
      : `${changeCount} unsaved change${changeCount === 1 ? '' : 's'}`

  return (
    <div className="sticky top-0 z-30 flex items-center justify-between gap-3 bg-rs-toolbar-bg px-4 py-2 text-rs-toolbar-fg">
      <span className="text-sm">
        Editing {what} — {changeSummary}
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
