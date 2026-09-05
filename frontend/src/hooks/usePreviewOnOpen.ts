import { useEffect, useRef, useState } from 'react'

import type { PreviewResult } from '../api/previewTypes'

export type PreviewOnOpenState =
  | { status: 'idle'; result: null; error: null }
  | { status: 'loading'; result: null; error: null }
  | { status: 'error'; result: null; error: unknown }
  | { status: 'success'; result: PreviewResult; error: null }

/**
 * Calls `preview()` exactly once per `open` transition from `false` to
 * `true` (issue #334) — never on a re-render while already open, and
 * never debounced/repeated on every keystroke, which is exactly the
 * pattern this ticket forbids. Guards with a ref keyed on the previous
 * `open` value rather than an empty dependency array, since `open` itself
 * must stay a dependency for the effect to notice a reopen at all.
 */
export function usePreviewOnOpen(
  open: boolean,
  preview: () => Promise<PreviewResult>,
): PreviewOnOpenState {
  const [state, setState] = useState<PreviewOnOpenState>({
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
      }
    }
    if (!open) wasOpen.current = false
    return undefined
  }, [open])

  return state
}
