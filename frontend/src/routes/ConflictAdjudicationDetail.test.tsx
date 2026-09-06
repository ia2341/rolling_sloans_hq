import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ConflictAdjudicationDetailPayload } from '../api/conflictAdjudicationTypes'
import { EditToolbar } from '../components/ui/EditToolbar'
import { useEditSession } from '../shell/EditSessionContext'
import { adminContext } from '../test/fixtures'
import { mockFetchOnce } from '../test/mockFetch'
import { mockMatchMedia } from '../test/mockMatchMedia'
import { renderShell } from '../test/renderShell'
import { ConflictAdjudicationDetail } from './ConflictAdjudicationDetail'

/** Mirrors `ScheduleEdit.test.tsx`'s toolbar wiring, since these tests need to click Save. */
function ActiveEditToolbar() {
  const session = useEditSession()
  if (session === null) return null
  return (
    <EditToolbar
      what={session.what}
      changeCount={session.changeCount}
      blockedReason={session.blockedReason}
      onDiscard={session.discard}
      onRequestSave={session.requestSave}
    />
  )
}

function renderDetail(rehearsalId = '42') {
  return renderShell(
    <>
      <ActiveEditToolbar />
      <Routes>
        <Route
          path="/conflicts/:rehearsalId"
          element={<ConflictAdjudicationDetail />}
        />
      </Routes>
    </>,
    [`/conflicts/${rehearsalId}`],
  )
}

function detailPayload(
  overrides: Partial<ConflictAdjudicationDetailPayload> = {},
): ConflictAdjudicationDetailPayload {
  return {
    rehearsal_id: 42,
    date: '2026-03-10',
    start_time: '19:00:00',
    end_time: '21:00:00',
    pending_count: 2,
    semester_updated_at: '2026-02-01T00:00:00Z',
    rows: [
      {
        conflict_id: 10,
        person_id: 1,
        person_name: 'Sam Rivera',
        type_label: 'Full night',
        declared_time: null,
        reason: 'Family event out of town',
        status: 'pending',
        note: '',
      },
      {
        conflict_id: 11,
        person_id: 2,
        person_name: 'Alex Kim',
        type_label: 'Partial',
        declared_time: '18:00:00',
        reason: 'Late shift at work',
        status: 'pending',
        note: '',
      },
    ],
    feasibility: {
      '10': {
        checked: false,
        verdict: null,
        has_standing_overlap: false,
        overlap_song_id: null,
        overlap_role_id: null,
        overlap_song_title: null,
        overlap_role_name: null,
      },
      '11': {
        checked: false,
        verdict: null,
        has_standing_overlap: false,
        overlap_song_id: null,
        overlap_role_id: null,
        overlap_song_title: null,
        overlap_role_name: null,
      },
    },
    ...overrides,
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('ConflictAdjudicationDetail', () => {
  it('renders all five column headers', async () => {
    mockMatchMedia(false)
    mockFetchOnce(200, { context: adminContext(), data: detailPayload() })

    renderDetail()

    await screen.findByText('Sam Rivera')
    for (const header of [
      'Person',
      'Declaration',
      'Declared',
      'Verdict',
      'Feasibility',
    ]) {
      expect(
        screen.getByRole('columnheader', { name: header }),
      ).toBeInTheDocument()
    }
  })

  it('shows the admin-only region by accessible role/name, with the reason', async () => {
    mockMatchMedia(false)
    mockFetchOnce(200, { context: adminContext(), data: detailPayload() })

    renderDetail()
    await screen.findByText('Sam Rivera')

    const regions = screen.getAllByRole('region', { name: 'Admin only' })
    expect(regions).toHaveLength(2)
    expect(
      within(regions[0]!).getByText('Family event out of town'),
    ).toBeInTheDocument()
  })

  it("fires exactly one preview fetch on a Verdict change, updating every row's feasibility chip", async () => {
    mockMatchMedia(false)
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce({
        status: 200,
        ok: true,
        json: () =>
          Promise.resolve({ context: adminContext(), data: detailPayload() }),
      })
      .mockResolvedValueOnce({
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
              loud: [],
              quiet: [],
              feasibility: {
                '10': {
                  checked: true,
                  verdict: 'infeasible',
                  has_standing_overlap: true,
                  overlap_song_id: 5,
                  overlap_role_id: 7,
                  overlap_song_title: 'Wonderwall',
                  overlap_role_name: 'Drummer',
                },
                '11': {
                  checked: true,
                  verdict: 'feasible',
                  has_standing_overlap: false,
                  overlap_song_id: null,
                  overlap_role_id: null,
                  overlap_song_title: null,
                  overlap_role_name: null,
                },
              },
            },
          }),
      })
    vi.stubGlobal('fetch', fetchSpy)

    renderDetail()
    await screen.findByText('Sam Rivera')

    expect(screen.getAllByText('Not checked')).toHaveLength(2)

    const user = userEvent.setup()
    // Sam Rivera's row is first — its Verdict control is the first "Approve" radio.
    await user.click(screen.getAllByRole('radio', { name: 'Approve' })[0]!)

    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2))
    expect(fetchSpy.mock.calls[1]?.[0]).toBe('/api/conflicts/42/preview/')

    await screen.findByText('Infeasible')
    expect(screen.getByText('Feasible')).toBeInTheDocument()
    expect(screen.queryByText('Not checked')).not.toBeInTheDocument()

    // The advisory shows only for the row that's Approved with a standing overlap.
    expect(screen.getByText(/Still assigned/)).toBeInTheDocument()
    expect(screen.getByText('Drummer')).toBeInTheDocument()
    expect(screen.getByText('Wonderwall')).toBeInTheDocument()
    const backupLink = screen.getByRole('link', { name: 'Add a Backup…' })
    expect(backupLink.getAttribute('href')).toBe('/schedule?rehearsal=42')
    expect(backupLink.textContent).not.toMatch(/Sam Rivera/)
  })

  it('fires no preview fetch when typing in a note field', async () => {
    mockMatchMedia(false)
    const fetchSpy = vi.fn().mockResolvedValue({
      status: 200,
      ok: true,
      json: () =>
        Promise.resolve({ context: adminContext(), data: detailPayload() }),
    })
    vi.stubGlobal('fetch', fetchSpy)

    renderDetail()
    await screen.findByText('Sam Rivera')
    expect(fetchSpy).toHaveBeenCalledTimes(1)

    const user = userEvent.setup()
    const noteInputs = screen.getAllByLabelText('Note')
    await user.type(noteInputs[0]!, 'checked with them')

    expect(fetchSpy).toHaveBeenCalledTimes(1)
  })

  it('opens the Save popup with the right verdict count and both Fallout tiers, Save still enabled', async () => {
    mockMatchMedia(false)
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce({
        status: 200,
        ok: true,
        json: () =>
          Promise.resolve({ context: adminContext(), data: detailPayload() }),
      })
      .mockResolvedValue({
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
              loud: [
                'Still assigned Drummer on Wonderwall during this window, with no Backup.',
              ],
              quiet: ['Sam Rivera is now Approved.'],
              feasibility: detailPayload().feasibility,
            },
          }),
      })
    vi.stubGlobal('fetch', fetchSpy)

    renderDetail()
    await screen.findByText('Sam Rivera')

    const user = userEvent.setup()
    await user.click(screen.getAllByRole('radio', { name: 'Approve' })[0]!)
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2))

    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    expect(await screen.findByText('Save 1 verdict')).toBeInTheDocument()
    const dialog = screen.getByRole('dialog')
    await waitFor(() =>
      expect(
        within(dialog).getByText(/Needs your attention/),
      ).toBeInTheDocument(),
    )
    expect(within(dialog).getByText(/Also true/)).toBeInTheDocument()
    expect(
      within(dialog).getByRole('button', { name: 'Save changes' }),
    ).not.toBeDisabled()
  })

  it('disables Save when nothing is pending (no verdict has changed)', async () => {
    mockMatchMedia(false)
    mockFetchOnce(200, { context: adminContext(), data: detailPayload() })

    renderDetail()
    await screen.findByText('Sam Rivera')

    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled()
  })

  it('renders phone cards, verdict-first, with no horizontally-scrolling table wrapper', async () => {
    mockMatchMedia(true)
    mockFetchOnce(200, { context: adminContext(), data: detailPayload() })

    renderDetail()
    await screen.findByText('Sam Rivera')

    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.getAllByRole('radiogroup').length).toBeGreaterThan(0)
  })
})
