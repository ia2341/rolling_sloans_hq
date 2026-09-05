import type { PreviewResult } from '../../api/previewTypes'
import { usePreviewOnOpen } from '../../hooks/usePreviewOnOpen'
import { ResponsiveDialog } from './ResponsiveDialog'

interface SaveChangesDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** The fully-formed dialog title, e.g. "Save 4 changes to Fall 2026?" — string composition is the caller's job. */
  title: string
  /** Runs the real save and rolls it back (ADR 0008); called exactly once per dialog open. */
  preview: () => Promise<PreviewResult>
  onConfirm: () => void
}

/**
 * The one Save popup every admin edit surface's `EditSession.requestSave`
 * opens (issue #334): built on `ResponsiveDialog`, so it's a centred modal
 * on desktop and a bottom sheet on phone for free. Runs `preview` exactly
 * once per open (`usePreviewOnOpen`), never on a keystroke, and renders
 * whatever the server actually computed — never a client-side
 * reimplementation of Fallout. No real surface wires `requestSave` to this
 * component yet (that's #335-#340); this ticket proves the mechanism only.
 */
export function SaveChangesDialog({
  open,
  onOpenChange,
  title,
  preview,
  onConfirm,
}: SaveChangesDialogProps) {
  const state = usePreviewOnOpen(open, preview)

  const isLoading = state.status === 'loading' || state.status === 'idle'
  const failedToLoad = state.status === 'error'
  const result = state.status === 'success' ? state.result : null
  const rejected = result !== null && !result.ok
  const doomed = result?.doomed
  const confirmDisabled = isLoading || rejected

  return (
    <ResponsiveDialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      footer={
        <>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="rounded border border-rs-border px-3 py-1.5 text-sm font-medium hover:bg-rs-border/40"
          >
            Keep editing
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={confirmDisabled}
            className="rounded bg-rs-accent px-3 py-1.5 text-sm font-medium text-rs-accent-fg disabled:cursor-not-allowed disabled:opacity-50"
          >
            {doomed ? 'Save anyway' : 'Save changes'}
          </button>
        </>
      }
    >
      <p className="mb-3 text-sm text-rs-muted">
        Computed by running the real save and rolling it back (ADR 0008).
        Nothing has been written, and no file has been deleted, by opening
        this.
      </p>

      {isLoading && (
        <div
          data-testid="save-popup-loading"
          className="animate-pulse space-y-2"
        >
          <div className="h-4 w-3/4 rounded bg-rs-border/60" />
          <div className="h-4 w-1/2 rounded bg-rs-border/60" />
        </div>
      )}

      {failedToLoad && (
        <p role="alert" className="text-sm text-rs-danger">
          Something went wrong computing what this save would do. Your
          Buffer is intact — nothing has been changed.
        </p>
      )}

      {result && !result.ok && (
        <div className="rounded border border-rs-danger/40 bg-rs-danger/5 p-3">
          <h3 className="mb-2 text-sm font-semibold text-rs-danger">
            Validation errors
          </h3>
          {result.nonFieldErrors?.map((message) => (
            <p key={message} className="text-sm text-rs-danger">
              {message}
            </p>
          ))}
          {result.errors &&
            Object.entries(result.errors).map(([rowKey, fieldErrors]) =>
              Object.entries(fieldErrors).map(([field, messages]) => (
                <p key={`${rowKey}-${field}`} className="text-sm text-rs-danger">
                  {field}: {messages.join(', ')}
                </p>
              )),
            )}
        </div>
      )}

      {result && result.ok && (
        <>
          <section className="mb-3">
            <h3 className="mb-1 text-sm font-semibold">What changes</h3>
            <ul className="space-y-1">
              {result.changes.map((change, index) => (
                <li key={`${change.op}-${change.object}-${index}`} className="text-sm">
                  <span className="mr-1 rounded bg-rs-border/60 px-1.5 py-0.5 text-xs font-medium uppercase">
                    {change.op}
                  </span>
                  <span className="font-semibold">{change.object}</span>
                  {change.why && (
                    <span className="text-rs-muted"> — {change.why}</span>
                  )}
                </li>
              ))}
            </ul>
          </section>

          <section className="mb-3">
            {result.fallout.loud.length > 0 && (
              <div className="mb-2">
                <h4 className="mb-1 text-sm font-semibold">
                  Needs your attention · {result.fallout.loud.length}
                </h4>
                <ul className="space-y-1">
                  {result.fallout.loud.map((message) => (
                    <li key={message} className="text-sm">
                      {message}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {result.fallout.quiet.length > 0 && (
              <div>
                <h4 className="mb-1 text-sm font-semibold text-rs-muted">
                  Also true · {result.fallout.quiet.length}
                </h4>
                <ul className="space-y-1">
                  {result.fallout.quiet.map((message) => (
                    <li key={message} className="text-sm text-rs-muted">
                      {message}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>

          {doomed && (
            <section className="rounded border-2 border-rs-danger p-3">
              <h3 className="mb-1 text-sm font-semibold text-rs-danger">
                {doomed.heading}
              </h3>
              <ul className="mb-2 space-y-1">
                {doomed.items.map((item) => (
                  <li key={item} className="text-sm">
                    {item}
                  </li>
                ))}
              </ul>
              <p className="text-sm font-medium text-rs-danger">
                The files leave storage when this commits. There is no
                undo and no export.
              </p>
            </section>
          )}
        </>
      )}
    </ResponsiveDialog>
  )
}
