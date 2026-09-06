import { screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { resetContextForTests, setContext } from '../api/contextStore'
import { adminContext } from '../test/fixtures'
import { mockFetchOnce } from '../test/mockFetch'
import { mockMatchMedia } from '../test/mockMatchMedia'
import { renderShell } from '../test/renderShell'
import { ReapplyDefaultsDialog } from './ReapplyDefaultsDialog'

afterEach(() => {
  resetContextForTests()
  mockMatchMedia(false)
})

describe('ReapplyDefaultsDialog', () => {
  it('renders the ADR-0008 provenance line and both fallout tiers, with commit enabled when not blocked', async () => {
    setContext(adminContext())
    mockFetchOnce(200, {
      context: adminContext(),
      ok: true,
      errors: {},
      non_field_errors: [],
      values: null,
      data: null,
      fallout: {
        is_blocked: false,
        block_message: '',
        is_stale: false,
        changed_rehearsal_count: 3,
        loud: ['A Recording’s slot moved.'],
        quiet: ['A Conflict Window no longer overlaps.'],
      },
    })
    renderShell(
      <ReapplyDefaultsDialog
        open
        onOpenChange={() => {}}
        semesterId={11}
        semesterName="Fall 2026"
        semesterUpdatedAt="2026-01-01T00:00:00Z"
      />,
    )

    await waitFor(() =>
      expect(screen.getByText(/upcoming rehearsal/)).toBeInTheDocument(),
    )
    expect(
      screen.getByText(
        /Computed by running the real save and rolling it back \(ADR 0008\)/,
      ),
    ).toBeInTheDocument()
    expect(screen.getByText('Needs your attention · 1')).toBeInTheDocument()
    expect(screen.getByText('Also true · 1')).toBeInTheDocument()
    expect(
      screen.getByText('Past rehearsals are untouched.'),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        'Hand-raised slot counts are never touched, so a song someone widened stays wide.',
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Reapply defaults' }),
    ).toBeEnabled()
  })

  it('disables commit and shows the block message when blocked', async () => {
    setContext(adminContext())
    mockFetchOnce(200, {
      context: adminContext(),
      ok: true,
      errors: {},
      non_field_errors: [],
      values: null,
      data: null,
      fallout: {
        is_blocked: true,
        block_message: 'The default duration leaves no playable time.',
        is_stale: false,
        changed_rehearsal_count: 0,
        loud: [],
        quiet: [],
      },
    })
    renderShell(
      <ReapplyDefaultsDialog
        open
        onOpenChange={() => {}}
        semesterId={11}
        semesterName="Fall 2026"
        semesterUpdatedAt="2026-01-01T00:00:00Z"
      />,
    )

    await waitFor(() =>
      expect(
        screen.getByText('The default duration leaves no playable time.'),
      ).toBeInTheDocument(),
    )
    expect(
      screen.getByRole('button', { name: 'Reapply defaults' }),
    ).toBeDisabled()
  })

  it('posts semester_id and semester_updated_at to the preview endpoint on open', async () => {
    setContext(adminContext())
    const fetchSpy = vi.fn().mockResolvedValue({
      status: 200,
      ok: true,
      json: () =>
        Promise.resolve({
          context: adminContext(),
          ok: true,
          errors: {},
          non_field_errors: [],
          values: null,
          data: null,
          fallout: {
            is_blocked: false,
            block_message: '',
            is_stale: false,
            changed_rehearsal_count: 0,
            loud: [],
            quiet: [],
          },
        }),
    })
    vi.stubGlobal('fetch', fetchSpy)

    renderShell(
      <ReapplyDefaultsDialog
        open
        onOpenChange={() => {}}
        semesterId={11}
        semesterName="Fall 2026"
        semesterUpdatedAt="2026-01-01T00:00:00Z"
      />,
    )

    await waitFor(() =>
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/semesters/reapply-defaults/preview/',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            semester_id: 11,
            semester_updated_at: '2026-01-01T00:00:00Z',
          }),
        }),
      ),
    )
  })
})
