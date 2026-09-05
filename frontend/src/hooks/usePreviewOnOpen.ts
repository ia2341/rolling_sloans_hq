import { useEffect, useRef, useState } from 'react'

import type { PreviewResult } from '../api/previewTypes'

export type PreviewOnOpenState<TResult = PreviewResult> =
  | { status: 'idle'; result: null; error: null }
  | { status: 'loading'; result: null; error: null }
  | { status: 'error'; result: null; error: unknown }
  | { status: 'success'; result: TResult; error: null }

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
 */
export function usePreviewOnOpen<TResult = PreviewResult>(
  open: boolean,
  preview: () => Promise<TResult>,
): PreviewOnOpenState<TResult> {
  const [state, setState] = useState<PreviewOnOpenState<TResult>>({
    status: 'idle',
    result: null,
    error: null,
  })
  const wasOpen = useRef(false)
  const latestPreview = useRef(preview)
  useEffect(() => {
    latestPreview.current = preview
  })

  useEffect(() => {
    if (open && !wasOpen.current) {
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
      wasOpen.current = true
      return () => {
        cancelled = true
        wasOpen.current = false
      }
    }
    if (!open) wasOpen.current = false
    return undefined
  }, [open])

  return state
}
