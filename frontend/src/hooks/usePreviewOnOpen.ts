import { useCallback, useEffect, useRef, useState } from 'react'

import type { PreviewResult } from '../api/previewTypes'

type PreviewOnOpenResult<TResult> =
  | { status: 'idle'; result: null; error: null }
  | { status: 'loading'; result: null; error: null }
  | { status: 'error'; result: null; error: unknown }
  | { status: 'success'; result: TResult; error: null }

export type PreviewOnOpenState<TResult = PreviewResult> =
  PreviewOnOpenResult<TResult> & {
    /** Re-runs `preview()` while still open — for a surface whose underlying data can change without a close/reopen (e.g. `ManageSemestersSheet` after a nested lifecycle dialog's own POST succeeds). A no-op while closed. */
    refetch: () => void
  }

/**
 * Calls `preview()` exactly once per `open` transition from `false` to
 * `true` (issue #334) — never on a re-render while already open, and
 * never debounced/repeated on every keystroke, which is exactly the
 * pattern this ticket forbids. Guards with a ref keyed on the previous
 * `open` value rather than an empty dependency array, since `open` itself
 * must stay a dependency for the effect to notice a reopen at all.
 *
 * Generic over its result type (issue #329): `SaveChangesDialog` calls
 * this with a `PreviewResult`-returning `preview`, but a surface whose
 * Fallout doesn't fit that shape (the Reapply-defaults popup's
 * `SemesterDefaultsFallout`, which has no `changes` list) can call it with
 * its own result type instead — the open/loading/error/success state
 * machine itself is the part every Preview popup shares.
 *
 * Also returns `refetch` (issue #329 follow-up): a manual re-run for a
 * surface whose data can go stale without the dialog itself closing —
 * `ManageSemestersSheet` stays open while its nested Publish/Delete/Reapply
 * dialogs make their own writes, so it calls `refetch` from each one's
 * success path rather than relying on an open/close cycle that never
 * happens.
 */
export function usePreviewOnOpen<TResult = PreviewResult>(
  open: boolean,
  preview: () => Promise<TResult>,
): PreviewOnOpenState<TResult> {
  const [state, setState] = useState<PreviewOnOpenResult<TResult>>({
    status: 'idle',
    result: null,
    error: null,
  })
  const wasOpen = useRef(false)
  const latestPreview = useRef(preview)
  useEffect(() => {
    latestPreview.current = preview
  })

  const run = useCallback(() => {
    setState({ status: 'loading', result: null, error: null })
    let cancelled = false
    latestPreview.current().then(
      (result) => {
        if (!cancelled) setState({ status: 'success', result, error: null })
      },
      (error: unknown) => {
        if (!cancelled) setState({ status: 'error', result: null, error })
      },
    )
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (open && !wasOpen.current) {
      wasOpen.current = true
      const cancel = run()
      return () => {
        cancel()
        wasOpen.current = false
      }
    }
    if (!open) wasOpen.current = false
    return undefined
  }, [open, run])

  const refetch = useCallback(() => {
    if (wasOpen.current) run()
  }, [run])

  return { ...state, refetch }
}
