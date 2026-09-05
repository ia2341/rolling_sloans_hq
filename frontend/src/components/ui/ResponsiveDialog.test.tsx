import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockMatchMedia } from '../../test/mockMatchMedia'
import { ResponsiveDialog } from './ResponsiveDialog'

afterEach(() => {
  mockMatchMedia(false)
})

describe('ResponsiveDialog', () => {
  it('renders as a modal above the phone breakpoint', () => {
    mockMatchMedia(false)
    render(
      <ResponsiveDialog open onOpenChange={() => {}} title="Save changes">
        body
      </ResponsiveDialog>,
    )

    expect(screen.getByRole('dialog')).toHaveClass('top-1/2')
  })

  it('renders as a bottom sheet below the phone breakpoint', () => {
    mockMatchMedia(true)
    render(
      <ResponsiveDialog open onOpenChange={() => {}} title="Save changes">
        body
      </ResponsiveDialog>,
    )

    expect(screen.getByRole('dialog')).toHaveClass('bottom-0')
  })

  it('dismisses on Escape and returns focus to the trigger', async () => {
    const user = userEvent.setup()

    function Harness() {
      const [open, setOpen] = useState(false)
      return (
        <>
          <button onClick={() => setOpen(true)}>Open</button>
          <ResponsiveDialog
            open={open}
            onOpenChange={setOpen}
            title="Save changes"
          >
            body
          </ResponsiveDialog>
        </>
      )
    }

    render(<Harness />)
    const trigger = screen.getByRole('button', { name: 'Open' })
    await user.click(trigger)
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    // Radix restores focus asynchronously (a rAF/microtask after unmount).
    await waitFor(() => expect(trigger).toHaveFocus())
  })

  it('calls onOpenChange(false) on backdrop click', async () => {
    const user = userEvent.setup()
    const onOpenChange = vi.fn()
    const { baseElement } = render(
      <ResponsiveDialog open onOpenChange={onOpenChange} title="Save changes">
        body
      </ResponsiveDialog>,
    )

    const overlay = baseElement.querySelector('.fixed.inset-0')
    expect(overlay).not.toBeNull()
    await user.click(overlay as Element)

    expect(onOpenChange).toHaveBeenCalledWith(false)
  })
})
