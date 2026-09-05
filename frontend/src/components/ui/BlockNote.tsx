import { TriangleAlert } from 'lucide-react'

interface BlockNoteProps {
  message: string
  onReloadAndReapply?: () => void
  /** Collapses to the `⚠` glyph alone, keeping it visible in the rail (issue #328 user story 27). */
  collapsed?: boolean
}

/**
 * The stale-Semester "Can't save" note (issue #328 user stories 24-27):
 * rendered above the semester panel, never near the grid being edited, so a
 * blocking Validation-Error-class condition stays visually separate from
 * Fallout by structure rather than styling (ADR 0008). `role="alert"` so
 * assistive tech announces it as soon as it mounts.
 */
export function BlockNote({
  message,
  onReloadAndReapply,
  collapsed = false,
}: BlockNoteProps) {
  if (collapsed) {
    return (
      <div
        role="alert"
        title={message}
        className="flex justify-center bg-rs-warning-bg py-2 text-rs-warning-fg"
      >
        <TriangleAlert size={16} aria-hidden="true" />
        <span className="sr-only">{message}</span>
      </div>
    )
  }

  return (
    <div
      role="alert"
      className="flex flex-col gap-2 border border-rs-warning-border bg-rs-warning-bg px-3 py-2 text-sm text-rs-warning-fg"
    >
      <div className="flex items-start gap-2">
        <TriangleAlert
          size={16}
          aria-hidden="true"
          className="mt-0.5 shrink-0"
        />
        <span>{message}</span>
      </div>
      {onReloadAndReapply !== undefined && (
        <button
          type="button"
          onClick={onReloadAndReapply}
          className="self-start rounded border border-rs-warning-border px-2 py-1 text-xs font-medium hover:bg-rs-warning-border/30"
        >
          Reload and re-apply
        </button>
      )}
    </div>
  )
}
