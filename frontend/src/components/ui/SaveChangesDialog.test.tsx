import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { PreviewResult } from '../../api/previewTypes'
import { mockMatchMedia } from '../../test/mockMatchMedia'
import { SaveChangesDialog } from './SaveChangesDialog'

afterEach(() => {
  mockMatchMedia(false)
})

const okResult: PreviewResult = {
  ok: true,
  changes: [
    { op: 'Edit', object: 'Blackbird', why: 'title changed' },
    { op: 'Add', object: 'New Song' },
  ],
  fallout: { loud: ['Deleting X destroys 2 recordings.'], quiet: ['Reordering changes concert position only.'] },
}

const doomedResult: PreviewResult = {
  ...okResult,
  doomed: {
    heading: '2 Recordings will be permanently deleted',
    items: ['Take 1 (uploaded by Alex)', 'Take 2 (uploaded by Sam)'],
  },
}

const rejectedResult: PreviewResult = {
  ok: false,
  changes: [],
  fallout: { loud: [], quiet: [] },
  errors: { 'row-1': { length: ['Enter a length as M:SS.'] } },
  nonFieldErrors: ['semester_id is required.'],
}

describe('SaveChangesDialog', () => {
  it('calls preview exactly once when opened, and again on reopen', async () => {
    const preview = vi.fn().mockResolvedValue(okResult)
    const { rerender } = render(
      <SaveChangesDialog
        open={false}
        onOpenChange={() => {}}
        title="Save changes?"
        preview={preview}
        onConfirm={() => {}}
      />,
    )
    expect(preview).not.toHaveBeenCalled()

    rerender(
      <SaveChangesDialog
        open
        onOpenChange={() => {}}
        title="Save changes?"
        preview={preview}
        onConfirm={() => {}}
      />,
    )
    await waitFor(() => expect(screen.getByText('What changes')).toBeInTheDocument())
    expect(preview).toHaveBeenCalledTimes(1)

    // Re-render while still open must not re-call preview.
    rerender(
      <SaveChangesDialog
        open
        onOpenChange={() => {}}
        title="Save changes? (updated)"
        preview={preview}
        onConfirm={() => {}}
      />,
    )
    expect(preview).toHaveBeenCalledTimes(1)

    // Close then reopen calls it again, once.
    rerender(
      <SaveChangesDialog
        open={false}
        onOpenChange={() => {}}
        title="Save changes?"
        preview={preview}
        onConfirm={() => {}}
      />,
    )
    rerender(
      <SaveChangesDialog
        open
        onOpenChange={() => {}}
        title="Save changes?"
        preview={preview}
        onConfirm={() => {}}
      />,
    )
    await waitFor(() => expect(preview).toHaveBeenCalledTimes(2))
  })

  it('renders one What-changes line per entry with its op token and why', async () => {
    const preview = vi.fn().mockResolvedValue(okResult)
    render(
      <SaveChangesDialog
        open
        onOpenChange={() => {}}
        title="Save changes?"
        preview={preview}
        onConfirm={() => {}}
      />,
    )

    await waitFor(() => expect(screen.getByText('Blackbird')).toBeInTheDocument())
    expect(screen.getByText('Edit')).toBeInTheDocument()
    expect(screen.getByText(/title changed/)).toBeInTheDocument()
    expect(screen.getByText('New Song')).toBeInTheDocument()
    expect(screen.getByText('Add')).toBeInTheDocument()
  })

  it('renders both fallout tiers with counts and keeps confirm enabled', async () => {
    const preview = vi.fn().mockResolvedValue(okResult)
    render(
      <SaveChangesDialog
        open
        onOpenChange={() => {}}
        title="Save changes?"
        preview={preview}
        onConfirm={() => {}}
      />,
    )

    await waitFor(() => expect(screen.getByText(/Needs your attention/)).toBeInTheDocument())
    expect(screen.getByText('Needs your attention · 1')).toBeInTheDocument()
    expect(screen.getByText('Also true · 1')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeEnabled()
  })

  it('renders the doomed block and flips the confirm label when doomed is present', async () => {
    const preview = vi.fn().mockResolvedValue(doomedResult)
    render(
      <SaveChangesDialog
        open
        onOpenChange={() => {}}
        title="Save changes?"
        preview={preview}
        onConfirm={() => {}}
      />,
    )

    await waitFor(() =>
      expect(
        screen.getByText('2 Recordings will be permanently deleted'),
      ).toBeInTheDocument(),
    )
    expect(screen.getByText(/leave storage when this commits/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save anyway' })).toBeEnabled()
  })

  it('renders neither doomed block nor "Save anyway" when doomed is absent', async () => {
    const preview = vi.fn().mockResolvedValue(okResult)
    render(
      <SaveChangesDialog
        open
        onOpenChange={() => {}}
        title="Save changes?"
        preview={preview}
        onConfirm={() => {}}
      />,
    )

    await waitFor(() => expect(screen.getByText('What changes')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Save anyway' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeInTheDocument()
  })

  it('renders errors with no confirm affordance and no What-changes/Fallout sections on ok: false', async () => {
    const preview = vi.fn().mockResolvedValue(rejectedResult)
    render(
      <SaveChangesDialog
        open
        onOpenChange={() => {}}
        title="Save changes?"
        preview={preview}
        onConfirm={() => {}}
      />,
    )

    await waitFor(() => expect(screen.getByText('Validation errors')).toBeInTheDocument())
    expect(screen.getByText('semester_id is required.')).toBeInTheDocument()
    expect(screen.getByText(/length: Enter a length as M:SS\./)).toBeInTheDocument()
    expect(screen.queryByText('What changes')).not.toBeInTheDocument()
    expect(screen.queryByText(/Needs your attention/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled()
  })

  it('Keep editing calls onOpenChange(false) without calling onConfirm', async () => {
    const user = userEvent.setup()
    const preview = vi.fn().mockResolvedValue(okResult)
    const onOpenChange = vi.fn()
    const onConfirm = vi.fn()
    render(
      <SaveChangesDialog
        open
        onOpenChange={onOpenChange}
        title="Save changes?"
        preview={preview}
        onConfirm={onConfirm}
      />,
    )
    await waitFor(() => expect(screen.getByText('What changes')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Keep editing' }))

    expect(onOpenChange).toHaveBeenCalledWith(false)
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it('disables confirm while loading, enables it once loaded successfully regardless of fallout size', async () => {
    let resolvePreview: (value: PreviewResult) => void = () => {}
    const preview = vi.fn(
      () =>
        new Promise<PreviewResult>((resolve) => {
          resolvePreview = resolve
        }),
    )
    render(
      <SaveChangesDialog
        open
        onOpenChange={() => {}}
        title="Save changes?"
        preview={preview}
        onConfirm={() => {}}
      />,
    )

    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled()

    resolvePreview(okResult)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Save changes' })).toBeEnabled(),
    )
  })

  it('renders the "Buffer is intact" note on a rejected preview promise and leaves Save enabled', async () => {
    const preview = vi.fn().mockRejectedValue(new Error('network down'))
    render(
      <SaveChangesDialog
        open
        onOpenChange={() => {}}
        title="Save changes?"
        preview={preview}
        onConfirm={() => {}}
      />,
    )

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByText(/Buffer is intact/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeEnabled()
  })

  it('renders the bottom-sheet variant at a phone viewport', async () => {
    mockMatchMedia(true)
    const preview = vi.fn().mockResolvedValue(okResult)
    render(
      <SaveChangesDialog
        open
        onOpenChange={() => {}}
        title="Save changes?"
        preview={preview}
        onConfirm={() => {}}
      />,
    )

    await waitFor(() => expect(screen.getByRole('dialog')).toHaveClass('bottom-0'))
  })
})
