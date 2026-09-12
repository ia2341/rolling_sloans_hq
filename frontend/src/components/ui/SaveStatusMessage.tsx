import { CheckCircle2, XCircle } from 'lucide-react'
import { useEffect } from 'react'

interface SaveStatusMessageProps {
  kind: 'success' | 'error'
  message: string
  /** Called to clear the message, either by the auto-dismiss timer or the dismiss button. Omit to make the message stick until its caller clears it some other way (no dismiss button rendered). */
  onDismiss?: () => void
  /** Auto-dismiss delay in ms; 0 (or omitted) disables the timer. Ignored without `onDismiss`. */
  autoDismissMs?: number
}

/**
 * A small, reusable inline status message (issue #506): a green check for
 * success or a red X for failure, matching the accessible inline-alert
 * pattern already used across this app (e.g. `Person.tsx`'s per-field error
 * spans) rather than a floating toast/snackbar library — this repo bans
 * external CDN dependencies, and a plain inline message needs no portal or
 * stacking-context machinery a toast library would bring.
 *
 * `role="status"` (success, non-interrupting) vs `role="alert"` (error,
 * interrupting) mirrors the existing convention on this page (e.g. the
 * password-reset reveal dialog's `role="alert"` warning). Auto-dismisses
 * after `autoDismissMs` when `onDismiss` is given and the delay is
 * positive; always offers a manual dismiss (×) button in that case too, so
 * a viewer isn't stuck waiting out the timer to move on.
 */
export function SaveStatusMessage({
  kind,
  message,
  onDismiss,
  autoDismissMs = 4000,
}: SaveStatusMessageProps) {
  useEffect(() => {
    if (onDismiss === undefined || autoDismissMs <= 0) return
    const timer = setTimeout(onDismiss, autoDismissMs)
    return () => clearTimeout(timer)
  }, [onDismiss, autoDismissMs, message])

  const isSuccess = kind === 'success'

  return (
    <p
      role={isSuccess ? 'status' : 'alert'}
      className={`mt-2 flex items-center gap-1.5 rounded border px-3 py-1.5 text-sm ${
        isSuccess
          ? 'border-rs-success-border bg-rs-success-bg text-rs-success-fg'
          : 'border-rs-danger/40 bg-rs-danger/5 text-rs-danger'
      }`}
    >
      {isSuccess ? (
        <CheckCircle2 size={16} aria-hidden="true" className="shrink-0" />
      ) : (
        <XCircle size={16} aria-hidden="true" className="shrink-0" />
      )}
      <span className="flex-1">{message}</span>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss"
          className="shrink-0 text-xs opacity-70 hover:opacity-100"
        >
          ✕
        </button>
      )}
    </p>
  )
}
