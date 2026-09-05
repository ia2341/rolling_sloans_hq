import { screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { resetContextForTests, setContext } from '../api/contextStore'
import { adminContext } from '../test/fixtures'
import { mockFetchOnce } from '../test/mockFetch'
import { mockMatchMedia } from '../test/mockMatchMedia'
import { renderShell } from '../test/renderShell'
import { ManageSemestersSheet } from './ManageSemestersSheet'

const rows = [
  {
    id: 11,
    name: 'Fall 2026 (draft)',
    status: 'draft' as const,
    is_viewing: true,
    member_count: 5,
    song_count: 8,
    rehearsal_count: 3,
    recording_count: 0,
    updated_at: '2026-01-05T00:00:00Z',
  },
  {
    id: 10,
    name: 'Spring 2026',
    status: 'live' as const,
    is_viewing: false,
    member_count: 6,
    song_count: 10,
    rehearsal_count: 4,
    recording_count: 12,
    updated_at: '2025-09-01T00:00:00Z',
  },
]

afterEach(() => {
  resetContextForTests()
  mockMatchMedia(false)
})

describe('ManageSemestersSheet', () => {
  it('renders four counts per row and no Switch-to control', async () => {
    setContext(adminContext())
    mockFetchOnce(200, { context: adminContext(), data: rows })
    renderShell(<ManageSemestersSheet open onOpenChange={() => {}} />)

    await waitFor(() =>
      expect(screen.getByText('Fall 2026 (draft)')).toBeInTheDocument(),
    )
    expect(
      screen.getByText('5 members · 8 songs · 3 rehearsals · 0 recordings'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('6 members · 10 songs · 4 rehearsals · 12 recordings'),
    ).toBeInTheDocument()
    expect(screen.queryByText(/Switch to/)).not.toBeInTheDocument()
  })

  it('disables Delete on the Live row with the ADR-0011 reason, and enables it elsewhere', async () => {
    setContext(adminContext())
    mockFetchOnce(200, { context: adminContext(), data: rows })
    renderShell(<ManageSemestersSheet open onOpenChange={() => {}} />)

    await waitFor(() =>
      expect(screen.getByText('Spring 2026')).toBeInTheDocument(),
    )

    const deleteButtons = screen.getAllByRole('button', { name: 'Delete' })
    // rows[0] (Fall, draft) is first, rows[1] (Spring, live) is second.
    expect(deleteButtons[0]).toBeEnabled()
    expect(deleteButtons[1]).toBeDisabled()
    expect(deleteButtons[1]).toHaveAttribute(
      'title',
      'The Live Semester cannot be deleted - publish another one first (ADR 0011)',
    )
  })

  it('shows "Editing" on the viewing row and enables Reapply defaults on every row', async () => {
    setContext(adminContext())
    mockFetchOnce(200, { context: adminContext(), data: rows })
    renderShell(<ManageSemestersSheet open onOpenChange={() => {}} />)

    await waitFor(() => expect(screen.getByText('Editing')).toBeInTheDocument())

    const reapplyButtons = screen.getAllByRole('button', {
      name: 'Reapply defaults',
    })
    expect(reapplyButtons[0]).toBeEnabled()
    expect(reapplyButtons[1]).toBeEnabled()
  })

  it("labels the Live row's publish action Re-publish", async () => {
    setContext(adminContext())
    mockFetchOnce(200, { context: adminContext(), data: rows })
    renderShell(<ManageSemestersSheet open onOpenChange={() => {}} />)

    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Re-publish' }),
      ).toBeInTheDocument(),
    )
    expect(screen.getByRole('button', { name: 'Publish' })).toBeInTheDocument()
  })
})
