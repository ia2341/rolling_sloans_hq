import { renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { PreviewResult } from '../api/previewTypes'
import { usePreviewOnOpen } from './usePreviewOnOpen'

const okResult: PreviewResult = {
  ok: true,
  changes: [],
  fallout: { loud: [], quiet: [] },
}

describe('usePreviewOnOpen', () => {
  it('does not call preview while closed', () => {
    const preview = vi.fn().mockResolvedValue(okResult)
    renderHook(() => usePreviewOnOpen(false, preview))

    expect(preview).not.toHaveBeenCalled()
  })

  it('calls preview exactly once when open transitions to true', async () => {
    const preview = vi.fn().mockResolvedValue(okResult)
    const { rerender, result } = renderHook(
      ({ open }) => usePreviewOnOpen(open, preview),
      { initialProps: { open: false } },
    )

    rerender({ open: true })
    expect(preview).toHaveBeenCalledTimes(1)

    await vi.waitFor(() => expect(result.current.status).toBe('success'))
  })

  it('does not call preview again on a re-render while still open', () => {
    const preview = vi.fn().mockResolvedValue(okResult)
    const { rerender } = renderHook(
      ({ open }) => usePreviewOnOpen(open, preview),
      { initialProps: { open: true } },
    )

    rerender({ open: true })
    rerender({ open: true })

    expect(preview).toHaveBeenCalledTimes(1)
  })

  it('calls preview again on close-then-reopen (once each time)', () => {
    const preview = vi.fn().mockResolvedValue(okResult)
    const { rerender } = renderHook(
      ({ open }) => usePreviewOnOpen(open, preview),
      { initialProps: { open: true } },
    )
    expect(preview).toHaveBeenCalledTimes(1)

    rerender({ open: false })
    rerender({ open: true })

    expect(preview).toHaveBeenCalledTimes(2)
  })

  it('resolves to a success state carrying the preview result', async () => {
    const preview = vi.fn().mockResolvedValue(okResult)
    const { result, rerender } = renderHook(
      ({ open }) => usePreviewOnOpen(open, preview),
      { initialProps: { open: false } },
    )

    rerender({ open: true })
    expect(result.current.status).toBe('loading')

    await vi.waitFor(() => expect(result.current.status).toBe('success'))
    expect(result.current.result).toEqual(okResult)
  })

  it('resolves to an error state when preview rejects', async () => {
    const preview = vi.fn().mockRejectedValue(new Error('network down'))
    const { result, rerender } = renderHook(
      ({ open }) => usePreviewOnOpen(open, preview),
      { initialProps: { open: false } },
    )

    rerender({ open: true })

    await vi.waitFor(() => expect(result.current.status).toBe('error'))
  })
})
