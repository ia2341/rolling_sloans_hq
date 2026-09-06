import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { RehearsalContextBar, stepRehearsalIndex } from './RehearsalContextBar'

const REGULAR_REHEARSAL = {
  id: 1,
  label: '2026-03-10',
  startTime: '18:00:00',
  endTime: '20:00:00',
  songCount: 4,
  isDressRehearsal: false,
}

const DRESS_REHEARSAL = {
  id: 2,
  label: '2026-05-01',
  startTime: '18:00:00',
  endTime: '21:00:00',
  songCount: 0,
  isDressRehearsal: true,
}

describe('RehearsalContextBar', () => {
  it('renders the window and song count on the left', () => {
    render(
      <RehearsalContextBar
        rehearsal={REGULAR_REHEARSAL}
        mode="running-order"
        onModeChange={() => {}}
      />,
    )

    expect(screen.getByText('18:00–20:00 · 4 songs')).toBeInTheDocument()
  })

  it('renders "Dress" instead of a song count for the Dress Rehearsal', () => {
    render(
      <RehearsalContextBar
        rehearsal={DRESS_REHEARSAL}
        mode="running-order"
        onModeChange={() => {}}
      />,
    )

    expect(screen.getByText('18:00–21:00 · Dress')).toBeInTheDocument()
  })

  it('disables the Assignments half on the Dress Rehearsal with the ADR 0003 reason', () => {
    render(
      <RehearsalContextBar
        rehearsal={DRESS_REHEARSAL}
        mode="running-order"
        onModeChange={() => {}}
      />,
    )

    const assignmentsOption = screen.getByRole('radio', { name: 'Assignments' })
    expect(assignmentsOption).toBeDisabled()
    expect(assignmentsOption).toHaveAttribute(
      'title',
      'A Dress Rehearsal has no per-song slots to assign against (ADR 0003).',
    )
  })

  it('calls onModeChange with the new mode and the rehearsal id', async () => {
    const user = userEvent.setup()
    const onModeChange = vi.fn()
    render(
      <RehearsalContextBar
        rehearsal={REGULAR_REHEARSAL}
        mode="running-order"
        onModeChange={onModeChange}
      />,
    )

    await user.click(screen.getByRole('radio', { name: 'Assignments' }))

    expect(onModeChange).toHaveBeenCalledWith('assignments', 1)
  })

  it('renders the steppers only in assignments mode', () => {
    const { rerender } = render(
      <RehearsalContextBar
        rehearsal={REGULAR_REHEARSAL}
        mode="running-order"
        onModeChange={() => {}}
      />,
    )

    expect(
      screen.queryByRole('button', { name: 'Previous rehearsal' }),
    ).not.toBeInTheDocument()

    rerender(
      <RehearsalContextBar
        rehearsal={REGULAR_REHEARSAL}
        mode="assignments"
        onModeChange={() => {}}
        onStep={() => {}}
      />,
    )

    expect(
      screen.getByRole('button', { name: 'Previous rehearsal' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Next rehearsal' }),
    ).toBeInTheDocument()
  })

  it('calls onStep with the clicked direction', async () => {
    const user = userEvent.setup()
    const onStep = vi.fn()
    render(
      <RehearsalContextBar
        rehearsal={REGULAR_REHEARSAL}
        mode="assignments"
        onModeChange={() => {}}
        onStep={onStep}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Next rehearsal' }))
    await user.click(screen.getByRole('button', { name: 'Previous rehearsal' }))

    expect(onStep).toHaveBeenNthCalledWith(1, 1)
    expect(onStep).toHaveBeenNthCalledWith(2, -1)
  })
})

describe('stepRehearsalIndex', () => {
  const rehearsals = [
    { isDressRehearsal: false },
    { isDressRehearsal: false },
    { isDressRehearsal: true },
  ]

  it('skips the Dress Rehearsal when stepping forward', () => {
    expect(stepRehearsalIndex(rehearsals, 1, 1)).toBe(0)
  })

  it('skips the Dress Rehearsal when stepping backward, wrapping around the list', () => {
    expect(stepRehearsalIndex(rehearsals, 0, -1)).toBe(1)
  })

  it('returns the current index unchanged when every entry is the Dress Rehearsal', () => {
    const onlyDress = [{ isDressRehearsal: true }]

    expect(stepRehearsalIndex(onlyDress, 0, 1)).toBe(0)
  })
})
