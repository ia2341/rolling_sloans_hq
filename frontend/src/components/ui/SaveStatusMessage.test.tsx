import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { SaveStatusMessage } from './SaveStatusMessage'

describe('SaveStatusMessage', () => {
  it('renders a success message with role="status"', () => {
    render(<SaveStatusMessage kind="success" message="Saved successfully" />)

    const status = screen.getByRole('status')
    expect(status).toHaveTextContent('Saved successfully')
  })

  it('renders a failure message with role="alert"', () => {
    render(<SaveStatusMessage kind="error" message="Something went wrong" />)

    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('Something went wrong')
  })

  it('auto-dismisses after the given delay when onDismiss is provided', () => {
    vi.useFakeTimers()
    const onDismiss = vi.fn()
    render(
      <SaveStatusMessage
        kind="success"
        message="Saved"
        onDismiss={onDismiss}
        autoDismissMs={3000}
      />,
    )

    expect(onDismiss).not.toHaveBeenCalled()
    vi.advanceTimersByTime(3000)
    expect(onDismiss).toHaveBeenCalledTimes(1)
    vi.useRealTimers()
  })

  it('a manual dismiss click calls onDismiss immediately', async () => {
    vi.useRealTimers()
    const onDismiss = vi.fn()
    const user = userEvent.setup()
    render(
      <SaveStatusMessage
        kind="error"
        message="Failed"
        onDismiss={onDismiss}
        autoDismissMs={60000}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Dismiss' }))

    expect(onDismiss).toHaveBeenCalledTimes(1)
  })

  it('renders no dismiss button when onDismiss is omitted', () => {
    render(<SaveStatusMessage kind="success" message="Saved" />)

    expect(
      screen.queryByRole('button', { name: 'Dismiss' }),
    ).not.toBeInTheDocument()
  })
})
