import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { EditToolbar } from './EditToolbar'

describe('EditToolbar', () => {
  it('shows "no changes yet" with Save changes disabled when there is nothing pending', () => {
    render(
      <EditToolbar
        what="the setlist"
        changeCount={0}
        blockedReason={null}
        onDiscard={vi.fn()}
        onRequestSave={vi.fn()}
      />,
    )

    expect(
      screen.getByText('Editing the setlist — no changes yet'),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled()
  })

  it('pluralizes the change count once changes exist', () => {
    const { rerender } = render(
      <EditToolbar
        what="the roster"
        changeCount={1}
        blockedReason={null}
        onDiscard={vi.fn()}
        onRequestSave={vi.fn()}
      />,
    )
    expect(
      screen.getByText('Editing the roster — 1 unsaved change'),
    ).toBeInTheDocument()

    rerender(
      <EditToolbar
        what="the roster"
        changeCount={3}
        blockedReason={null}
        onDiscard={vi.fn()}
        onRequestSave={vi.fn()}
      />,
    )
    expect(
      screen.getByText('Editing the roster — 3 unsaved changes'),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeEnabled()
  })

  it('disables Save changes while blocked, even with pending changes', () => {
    render(
      <EditToolbar
        what="the rehearsals"
        changeCount={2}
        blockedReason="The rehearsals changed while you were editing — reload and reapply."
        onDiscard={vi.fn()}
        onRequestSave={vi.fn()}
      />,
    )

    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled()
  })
})
