import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { resetContextForTests, setContext } from '../api/contextStore'
import { adminContext } from '../test/fixtures'
import { mockFetchOnce } from '../test/mockFetch'
import { mockMatchMedia } from '../test/mockMatchMedia'
import { renderShell } from '../test/renderShell'
import { ManageSemestersSheet } from './ManageSemestersSheet'

function stubFetchSequence(
  responses: Array<{ status: number; body: unknown }>,
) {
  const fetchSpy = vi.fn()
  for (const { status, body } of responses) {
    fetchSpy.mockResolvedValueOnce({
      status,
      ok: status >= 200 && status < 300,
      json: () => Promise.resolve(body),
    })
  }
  vi.stubGlobal('fetch', fetchSpy)
  return fetchSpy
}

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
  vi.unstubAllGlobals()
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

  it('disables Delete on the Live row, and enables it elsewhere', async () => {
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

  it('refetches its rows after a nested Publish succeeds, without closing the sheet', async () => {
    setContext(adminContext())
    const publishedRows = [
      { ...rows[0], status: 'live' as const },
      { ...rows[1], status: 'draft' as const },
    ]
    const fetchSpy = stubFetchSequence([
      { status: 200, body: { context: adminContext(), data: rows } },
      {
        status: 200,
        body: {
          context: adminContext(),
          data: {
            target_semester_id: 11,
            target_semester_name: 'Fall 2026 (draft)',
            is_already_live: false,
            incumbent: { id: 10, name: 'Spring 2026' },
            incumbent_rehearsal_count: 4,
            incumbent_song_count: 10,
            has_no_setlist: false,
            has_no_rehearsals: false,
          },
        },
      },
      {
        status: 200,
        body: {
          context: adminContext(),
          ok: true,
          errors: {},
          non_field_errors: [],
          fallout: null,
          values: null,
          data: null,
        },
      },
      { status: 200, body: { context: adminContext(), data: publishedRows } },
    ])
    const user = userEvent.setup()
    renderShell(<ManageSemestersSheet open onOpenChange={() => {}} />)

    await waitFor(() =>
      expect(screen.getByText('Fall 2026 (draft)')).toBeInTheDocument(),
    )

    const publishButtons = screen.getAllByRole('button', { name: 'Publish' })
    await user.click(publishButtons[0]!)

    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Publish Fall 2026 (draft)' }),
      ).toBeEnabled(),
    )
    await user.click(
      screen.getByRole('button', { name: 'Publish Fall 2026 (draft)' }),
    )

    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(4))
    expect(fetchSpy.mock.calls[3]?.[0]).toBe('/api/semesters/management-rows/')

    // The Manage-semesters sheet itself never closed — only the nested Publish dialog did.
    expect(screen.getByText('Manage semesters')).toBeInTheDocument()
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
