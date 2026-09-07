import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import type { ScheduleEditorPayload } from '../api/scheduleEditorTypes'
import { EditToolbar } from '../components/ui/EditToolbar'
import { ContextProvider } from '../api/ContextProvider'
import {
  EditSessionProvider,
  useEditSession,
} from '../shell/EditSessionContext'
import { PageTitleProvider } from '../shell/PageTitleContext'
import { adminContext } from '../test/fixtures'
import { mockFetchOnce } from '../test/mockFetch'
import { mockMatchMedia } from '../test/mockMatchMedia'
import { ScheduleEdit } from './ScheduleEdit'

/** Renders the sticky `EditToolbar` from whatever `EditSession` `ScheduleEdit` registers, mirroring `AppShell`'s own wiring — `renderShell()` doesn't include it, and this route's tests need to click Save. */
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

function renderScheduleEdit(initialEntries: string[] = ['/schedule/edit']) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <ContextProvider>
        <EditSessionProvider>
          <PageTitleProvider>
            <ActiveEditToolbar />
            <ScheduleEdit />
          </PageTitleProvider>
        </EditSessionProvider>
      </ContextProvider>
    </MemoryRouter>,
  )
}

function editorPayload(
  overrides: Partial<ScheduleEditorPayload> = {},
): ScheduleEditorPayload {
  return {
    semester_name: 'Fall 2026',
    rehearsals: [
      {
        id: 1,
        date: '2026-03-10',
        start_time: '19:00:00',
        end_time: '21:00:00',
        is_full_setlist: false,
        setup_grace_minutes: null,
        teardown_grace_minutes: null,
        arrival_buffer_minutes: null,
        departure_buffer_minutes: null,
        running_order: [
          {
            rehearsal_song_id: 10,
            song_id: 1,
            song_title: 'First Song',
            slot_count: 1,
            start_time: '19:00:00',
            end_time: '19:30:00',
            is_pinned: false,
            pinned_reasons: [],
          },
          {
            rehearsal_song_id: 11,
            song_id: 2,
            song_title: 'Second Song',
            slot_count: 1,
            start_time: '19:30:00',
            end_time: '20:00:00',
            is_pinned: false,
            pinned_reasons: [],
          },
        ],
      },
      {
        id: 2,
        date: '2026-03-17',
        start_time: '19:00:00',
        end_time: '21:00:00',
        is_full_setlist: false,
        setup_grace_minutes: null,
        teardown_grace_minutes: null,
        arrival_buffer_minutes: null,
        departure_buffer_minutes: null,
        running_order: [],
      },
    ],
    past_rehearsals: [],
    setlist_songs: [
      { id: 1, title: 'First Song', artist: 'Placeholder Artist', position: 1 },
      {
        id: 2,
        title: 'Second Song',
        artist: 'Placeholder Artist',
        position: 2,
      },
      { id: 3, title: 'Third Song', artist: 'Placeholder Artist', position: 3 },
    ],
    semester_defaults: {
      default_rehearsal_duration_minutes: 120,
      default_setup_grace_minutes: 15,
      default_teardown_grace_minutes: 15,
      default_song_slot_count: 8,
      default_arrival_buffer_minutes: 10,
      default_departure_buffer_minutes: 10,
      default_dress_rehearsal_count: 1,
    },
    pattern: null,
    ...overrides,
  }
}

/** A schedule payload for the `/api/schedule/?rehearsal=<id>` read `AssignmentEditor` fires once a row expands, matching Rehearsal 1 from `editorPayload()`. */
function assignmentDetailPayload() {
  return {
    context: adminContext(),
    data: {
      semester_name: 'Fall 2026',
      schedule: { past: [], future: [] },
      selected: {
        id: 1,
        date: '2026-03-10',
        start_time: '19:00:00',
        end_time: '21:00:00',
        is_dress: false,
        is_past: false,
        can_edit_assignments: true,
        timeline: {
          slots: [],
          window_start: '19:00:00',
          window_end: '21:00:00',
          viewer_song_count: 0,
          total_song_count: 0,
          viewer_start_time: null,
          viewer_end_time: null,
          is_dress_rehearsal: false,
        },
        availability: {
          declaration_type: null,
          type_label: null,
          declared_time: null,
          reason: null,
          status: null,
          admin_note: null,
          is_dress: false,
          is_editable: true,
        },
        roles: [],
        rows: [],
      },
    },
  }
}

describe('ScheduleEdit', () => {
  it('clicking anywhere on a Rehearsal row expands it, never navigates', async () => {
    mockMatchMedia(true)
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce({
        status: 200,
        ok: true,
        json: () =>
          Promise.resolve({ context: adminContext(), data: editorPayload() }),
      })
      .mockResolvedValue({
        status: 200,
        ok: true,
        json: () => Promise.resolve(assignmentDetailPayload()),
      })
    vi.stubGlobal('fetch', fetchSpy)

    renderScheduleEdit()
    const user = userEvent.setup()

    await screen.findByRole('button', { name: 'Expand 2026-03-10' })
    expect(
      screen.queryByText('Editing standing assignments.'),
    ).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Expand 2026-03-10' }))

    expect(
      await screen.findByRole('button', { name: 'Collapse 2026-03-10' }),
    ).toBeInTheDocument()
    expect(
      fetchSpy.mock.calls.some(([url]) =>
        String(url).includes('/api/schedule/?rehearsal=1'),
      ),
    ).toBe(true)
  })

  it('shows only one open Rehearsal card at a time', async () => {
    mockMatchMedia(true)
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce({
        status: 200,
        ok: true,
        json: () =>
          Promise.resolve({ context: adminContext(), data: editorPayload() }),
      })
      .mockResolvedValue({
        status: 200,
        ok: true,
        json: () => Promise.resolve(assignmentDetailPayload()),
      })
    vi.stubGlobal('fetch', fetchSpy)

    renderScheduleEdit()

    const user = userEvent.setup()
    await screen.findByRole('button', { name: 'Expand 2026-03-10' })

    await user.click(screen.getByRole('button', { name: 'Expand 2026-03-10' }))
    expect(
      await screen.findByRole('button', { name: 'Collapse 2026-03-10' }),
    ).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Expand 2026-03-17' }))
    expect(
      screen.queryByRole('button', { name: 'Collapse 2026-03-10' }),
    ).not.toBeInTheDocument()
  })

  it('opens the Save popup on Save and fires the preview endpoint exactly once', async () => {
    mockMatchMedia(false)
    const fetchSpy = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url === '/api/schedule/editor/preview/') {
        return Promise.resolve({
          status: 200,
          ok: true,
          json: () =>
            Promise.resolve({
              context: adminContext(),
              ok: true,
              errors: {},
              non_field_errors: [],
              fallout: {
                is_blocked: false,
                block_message: '',
                is_stale: false,
                loud: [],
                quiet: [],
                doomed_recording_groups: [],
              },
              values: null,
              data: null,
            }),
        })
      }
      return Promise.resolve({
        status: 200,
        ok: true,
        json: () =>
          Promise.resolve({ context: adminContext(), data: editorPayload() }),
      })
    })
    vi.stubGlobal('fetch', fetchSpy)

    renderScheduleEdit()
    const user = userEvent.setup()

    await screen.findByRole('button', { name: 'Expand 2026-03-10' })
    await user.click(
      screen.getByRole('button', { name: 'Delete rehearsal on 2026-03-17' }),
    )

    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() =>
      expect(screen.getByText(/Save \d+ change/)).toBeInTheDocument(),
    )
    expect(
      fetchSpy.mock.calls.filter(
        ([url]) => String(url) === '/api/schedule/editor/preview/',
      ),
    ).toHaveLength(1)
  })

  it('disables Save when the Buffer has no unsaved changes', async () => {
    mockMatchMedia(false)
    mockFetchOnce(200, { context: adminContext(), data: editorPayload() })

    renderScheduleEdit()

    await screen.findByRole('button', { name: 'Expand 2026-03-10' })
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled()
  })

  it('renders past rehearsals in a collapsed, non-editable disclosure', async () => {
    mockMatchMedia(false)
    mockFetchOnce(200, {
      context: adminContext(),
      data: editorPayload({
        past_rehearsals: [
          {
            id: 99,
            date: '2026-01-01',
            start_time: '19:00:00',
            end_time: '21:00:00',
            is_full_setlist: false,
            song_count: 3,
          },
        ],
      }),
    })

    renderScheduleEdit()

    await screen.findByRole('button', { name: 'Expand 2026-03-10' })
    expect(
      screen.getByText('Past rehearsals — not editable'),
    ).toBeInTheDocument()
    within(
      screen.getByText('Past rehearsals — not editable').closest('details')!,
    ).getByText(/2026-01-01/)
  })

  it('renders "Randomize Rehearsal Plan" as a single label, with no Re-roll/Generate schedule text and no Flags/Actions columns', async () => {
    mockMatchMedia(false)
    mockFetchOnce(200, { context: adminContext(), data: editorPayload() })

    renderScheduleEdit()

    await screen.findByRole('button', { name: 'Expand 2026-03-10' })
    expect(
      screen.getByRole('button', { name: 'Randomize Rehearsal Plan' }),
    ).toBeInTheDocument()
    expect(screen.queryByText('Re-roll')).not.toBeInTheDocument()
    expect(screen.queryByText('Generate schedule')).not.toBeInTheDocument()
    expect(screen.queryByText('Flags')).not.toBeInTheDocument()
    expect(screen.queryByText('Actions')).not.toBeInTheDocument()
    expect(screen.getAllByLabelText('Date').length).toBeGreaterThan(0)
    expect(screen.getAllByLabelText('Start time').length).toBeGreaterThan(0)
  })

  it('replaces the Remove/Restore button with a trash-can control that still toggles deletion', async () => {
    mockMatchMedia(false)
    mockFetchOnce(200, { context: adminContext(), data: editorPayload() })

    renderScheduleEdit()
    const user = userEvent.setup()

    await screen.findByRole('button', { name: 'Expand 2026-03-10' })
    expect(
      screen.queryByRole('button', { name: 'Remove' }),
    ).not.toBeInTheDocument()

    const deleteButton = screen.getByRole('button', {
      name: 'Delete rehearsal on 2026-03-10',
    })
    await user.click(deleteButton)

    expect(
      screen.getByRole('button', { name: 'Restore rehearsal on 2026-03-10' }),
    ).toBeInTheDocument()
  })

  it('never renders a per-Rehearsal Shuffle button', async () => {
    mockMatchMedia(false)
    mockFetchOnce(200, { context: adminContext(), data: editorPayload() })

    renderScheduleEdit()

    await screen.findByRole('button', { name: 'Expand 2026-03-10' })

    expect(
      screen.queryByRole('button', { name: 'Shuffle' }),
    ).not.toBeInTheDocument()
  })

  it('shows the live stats panel from the debounced stats endpoint', async () => {
    mockMatchMedia(false)
    const fetchSpy = vi.fn().mockImplementation((url: string) => {
      if (url === '/api/schedule/editor/stats/') {
        return Promise.resolve({
          status: 200,
          ok: true,
          json: () =>
            Promise.resolve({
              context: adminContext(),
              ok: true,
              errors: {},
              non_field_errors: [],
              fallout: null,
              values: null,
              data: {
                unresolved_conflict_count: 2,
                old_max_wait_minutes: 30,
                new_max_wait_minutes: 15,
                highest_slot_songs: [
                  { song_id: 1, song_title: 'First Song', total_slot_count: 4 },
                ],
                lowest_slot_songs: [
                  {
                    song_id: 2,
                    song_title: 'Second Song',
                    total_slot_count: 1,
                  },
                ],
              },
            }),
        })
      }
      return Promise.resolve({
        status: 200,
        ok: true,
        json: () =>
          Promise.resolve({ context: adminContext(), data: editorPayload() }),
      })
    })
    vi.stubGlobal('fetch', fetchSpy)

    renderScheduleEdit()

    await screen.findByRole('button', { name: 'Expand 2026-03-10' })
    expect(
      await screen.findByText(/2 assignments overlapping a declared Conflict/),
    ).toBeInTheDocument()
    expect(screen.getByText(/30 min/)).toBeInTheDocument()
    expect(screen.getByText(/15 min/)).toBeInTheDocument()
    expect(screen.getByText(/First Song \(4\)/)).toBeInTheDocument()
    expect(screen.getByText(/Second Song \(1\)/)).toBeInTheDocument()
  })

  it('opens the Generate rehearsal dates modal for ?intent=generate-dates, then strips the param (issue #374)', async () => {
    mockFetchOnce(200, {
      context: adminContext(),
      data: editorPayload(),
    })

    renderScheduleEdit(['/schedule/edit?intent=generate-dates'])

    expect(
      await screen.findByRole('heading', { name: 'Generate rehearsal dates' }),
    ).toBeInTheDocument()
  })

  it('does nothing for a plain load with no ?intent (issue #374)', async () => {
    mockFetchOnce(200, {
      context: adminContext(),
      data: editorPayload(),
    })

    renderScheduleEdit()

    await screen.findByRole('button', { name: 'Generate rehearsal dates…' })
    expect(
      screen.queryByRole('heading', { name: 'Generate rehearsal dates' }),
    ).not.toBeInTheDocument()
  })
})
