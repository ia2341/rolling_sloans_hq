import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { SchedulePayload } from '../api/scheduleTypes'
import { memberContext } from '../test/fixtures'
import { mockFetchOnce } from '../test/mockFetch'
import { mockMatchMedia } from '../test/mockMatchMedia'
import { renderShell } from '../test/renderShell'
import { Schedule } from './Schedule'

/** A minimal `/api/schedule/` `data` payload: one non-Dress Rehearsal, the viewer on its first Song. */
function schedulePayload(
  overrides: Partial<SchedulePayload> = {},
): SchedulePayload {
  return {
    semester_name: 'Spring 2026',
    schedule: {
      past: [],
      future: [
        {
          id: 1,
          date: '2026-03-10',
          start_time: '18:00:00',
          end_time: '20:00:00',
          is_dress: false,
          is_past: false,
          song_count: 2,
          your_state: { kind: 'not_needed' },
        },
      ],
    },
    selected: {
      id: 1,
      date: '2026-03-10',
      start_time: '18:00:00',
      end_time: '20:00:00',
      is_dress: false,
      is_past: false,
      can_edit_assignments: false,
      timeline: {
        slots: [
          {
            song_id: 1,
            song_title: 'First Song',
            start_time: '18:00:00',
            end_time: '19:00:00',
            is_viewer: true,
          },
          {
            song_id: 2,
            song_title: 'Second Song',
            start_time: '19:00:00',
            end_time: '20:00:00',
            is_viewer: false,
          },
        ],
        window_start: '18:00:00',
        window_end: '20:00:00',
        viewer_song_count: 1,
        total_song_count: 2,
        viewer_start_time: '18:00:00',
        viewer_end_time: '19:00:00',
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
      roles: [{ id: 1, name: 'Singer', code: 'SIN' }],
      rows: [
        {
          song_id: 1,
          song_title: 'First Song',
          start_time: '18:00:00',
          cells: [
            {
              role_id: 1,
              entries: [
                {
                  id: 1,
                  kind: 'assignment',
                  person_id: 1,
                  person_name: 'Sam Rivera',
                  is_role_mismatch: false,
                  has_conflict: false,
                },
              ],
            },
          ],
        },
      ],
    },
    ...overrides,
  }
}

beforeEach(() => {
  mockMatchMedia(false)
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('Schedule', () => {
  it('renders one table with start times and assignment pills, with no Running order | Assignments mode switch', async () => {
    mockFetchOnce(200, { context: memberContext(), data: schedulePayload() })

    renderShell(<Schedule />, ['/schedule'])

    await screen.findByText('First Song')
    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.getByText('Sam Rivera')).toBeInTheDocument()
    expect(screen.getAllByText('18:00').length).toBeGreaterThan(0)
    expect(screen.queryByText('Running Order')).not.toBeInTheDocument()
    expect(
      screen.queryByRole('tab', { name: 'Assignments' }),
    ).not.toBeInTheDocument()
  })

  it('switches sub-views via the segmented control without a second fetch', async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      status: 200,
      ok: true,
      json: () =>
        Promise.resolve({ context: memberContext(), data: schedulePayload() }),
    })
    vi.stubGlobal('fetch', fetchSpy)

    renderShell(<Schedule />, ['/schedule'])

    await screen.findByText('First Song')
    expect(fetchSpy).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole('radio', { name: 'All rehearsals' }))

    await screen.findByRole('columnheader', { name: 'Date' })
    expect(fetchSpy).toHaveBeenCalledTimes(1)
  })

  it('renders "Available for the whole rehearsal" with a Declare button when nothing is declared', async () => {
    mockFetchOnce(200, { context: memberContext(), data: schedulePayload() })

    renderShell(<Schedule />, ['/schedule'])

    expect(
      await screen.findByText('Available for the whole rehearsal'),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Declare a conflict' }),
    ).toBeInTheDocument()
  })

  it('renders a pending declaration with its verdict line', async () => {
    const payload = schedulePayload()
    payload.selected!.availability = {
      declaration_type: 'full_absence',
      type_label: 'Full absence',
      declared_time: null,
      reason: 'Out of town.',
      status: 'pending',
      admin_note: null,
      is_dress: false,
      is_editable: true,
    }
    mockFetchOnce(200, { context: memberContext(), data: payload })

    renderShell(<Schedule />, ['/schedule'])

    expect(
      await screen.findByText('Unavailable for entire rehearsal'),
    ).toBeInTheDocument()
    expect(screen.getByText('Awaiting an admin decision')).toBeInTheDocument()
  })

  it('renders an approved declaration with its admin note', async () => {
    const payload = schedulePayload()
    payload.selected!.availability = {
      declaration_type: 'full_absence',
      type_label: 'Full absence',
      declared_time: null,
      reason: '',
      status: 'approved',
      admin_note: 'Noted, thanks.',
      is_dress: false,
      is_editable: true,
    }
    mockFetchOnce(200, { context: memberContext(), data: payload })

    renderShell(<Schedule />, ['/schedule'])

    expect(await screen.findByText('Approved')).toBeInTheDocument()
    expect(screen.getByText(/Noted, thanks\./)).toBeInTheDocument()
  })

  it('renders a rejected declaration', async () => {
    const payload = schedulePayload()
    payload.selected!.availability = {
      declaration_type: 'full_absence',
      type_label: 'Full absence',
      declared_time: null,
      reason: '',
      status: 'rejected',
      admin_note: null,
      is_dress: false,
      is_editable: true,
    }
    mockFetchOnce(200, { context: memberContext(), data: payload })

    renderShell(<Schedule />, ['/schedule'])

    expect(await screen.findByText('Not approved')).toBeInTheDocument()
  })

  it('renders the Dress Rehearsal locked availability copy and no declare control', async () => {
    const payload = schedulePayload()
    payload.selected!.is_dress = true
    payload.selected!.availability = {
      declaration_type: null,
      type_label: null,
      declared_time: null,
      reason: null,
      status: null,
      admin_note: null,
      is_dress: true,
      is_editable: false,
    }
    mockFetchOnce(200, { context: memberContext(), data: payload })

    renderShell(<Schedule />, ['/schedule'])

    expect(
      await screen.findByText(
        'Attendance is required at the dress rehearsal. There is nothing to declare here (ADR 0006).',
      ),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Declare a conflict' }),
    ).not.toBeInTheDocument()
  })

  it('renders "This rehearsal has passed." for a past Rehearsal with nothing declared', async () => {
    const payload = schedulePayload()
    payload.selected!.is_past = true
    payload.selected!.availability = {
      declaration_type: null,
      type_label: null,
      declared_time: null,
      reason: null,
      status: null,
      admin_note: null,
      is_dress: false,
      is_editable: false,
    }
    mockFetchOnce(200, { context: memberContext(), data: payload })

    renderShell(<Schedule />, ['/schedule'])

    expect(
      await screen.findByText('This rehearsal has passed.'),
    ).toBeInTheDocument()
  })

  it('shows a time field for late_arrival and none for full_absence in the declare dialog', async () => {
    mockFetchOnce(200, { context: memberContext(), data: schedulePayload() })

    renderShell(<Schedule />, ['/schedule'])
    fireEvent.click(
      await screen.findByRole('button', { name: 'Declare a conflict' }),
    )

    expect(screen.queryByLabelText('Arrival time')).not.toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('Arrive late at'))
    expect(screen.getByLabelText('Arrival time')).toBeInTheDocument()
  })

  it('carries the ADR 0005 privacy note and the ADR 0006 exclusion note in the declare dialog', async () => {
    mockFetchOnce(200, { context: memberContext(), data: schedulePayload() })

    renderShell(<Schedule />, ['/schedule'])
    fireEvent.click(
      await screen.findByRole('button', { name: 'Declare a conflict' }),
    )

    expect(
      screen.getByText(/Only admins ever see this reason/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/The dress rehearsal takes no conflict/),
    ).toBeInTheDocument()
  })

  it('an invalid late_arrival submission returns a per-field error and keeps the typed reason', async () => {
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce({
        status: 200,
        ok: true,
        json: () =>
          Promise.resolve({
            context: memberContext(),
            data: schedulePayload(),
          }),
      })
      .mockResolvedValueOnce({
        status: 200,
        ok: true,
        json: () =>
          Promise.resolve({
            context: memberContext(),
            ok: false,
            errors: {
              arrival_time: [
                "Must fall within the Rehearsal's time span, after it starts.",
              ],
            },
            non_field_errors: [],
            fallout: null,
            values: null,
            data: null,
          }),
      })
    vi.stubGlobal('fetch', fetchSpy)

    renderShell(<Schedule />, ['/schedule'])
    fireEvent.click(
      await screen.findByRole('button', { name: 'Declare a conflict' }),
    )
    fireEvent.click(screen.getByLabelText('Arrive late at'))
    fireEvent.change(screen.getByLabelText('Reason (optional)'), {
      target: { value: 'Stuck in traffic.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await screen.findByText(
      "Must fall within the Rehearsal's time span, after it starts.",
    )
    expect(screen.getByLabelText('Reason (optional)')).toHaveValue(
      'Stuck in traffic.',
    )
  })

  it("renders a teammate's Conflict as a marker with no reason anywhere in the DOM", async () => {
    const payload = schedulePayload()
    payload.selected!.rows[0]!.cells[0]!.entries.push({
      id: 2,
      kind: 'assignment',
      person_id: 2,
      person_name: 'Teammate Placeholder',
      is_role_mismatch: false,
      has_conflict: true,
    })
    mockFetchOnce(200, { context: memberContext(), data: payload })

    renderShell(<Schedule />, ['/schedule'])

    const teammatePill = await screen.findByText('Teammate Placeholder')
    expect(
      within(teammatePill.closest('span')!).getByTitle(
        'Unavailable for part of this',
      ),
    ).toBeInTheDocument()
    expect(screen.queryByText(/reason/i)).not.toBeInTheDocument()
  })

  it('renders a Backup as "name (backup)" with no "covering for" text for a member', async () => {
    const payload = schedulePayload()
    payload.selected!.rows[0]!.cells[0]!.entries = [
      {
        id: 5,
        kind: 'backup',
        person_id: 3,
        person_name: 'Backup Placeholder',
        is_role_mismatch: false,
        has_conflict: false,
      },
    ]
    mockFetchOnce(200, { context: memberContext(), data: payload })

    renderShell(<Schedule />, ['/schedule'])

    expect(await screen.findByText(/Backup Placeholder/)).toHaveTextContent(
      'Backup Placeholder (backup)',
    )
    expect(screen.queryByText(/covering for/i)).not.toBeInTheDocument()
  })

  it('renders per-song cards with Roles as rows on a phone viewport, and the page body never scrolls horizontally', async () => {
    mockMatchMedia(true)
    mockFetchOnce(200, { context: memberContext(), data: schedulePayload() })

    renderShell(<Schedule />, ['/schedule'])

    await screen.findByText(/First Song/)
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('renders a position column, the ADR 0003 note, and no start times for the Dress Rehearsal', async () => {
    const payload = schedulePayload()
    payload.selected!.is_dress = true
    payload.selected!.rows[0]!.start_time = null
    mockFetchOnce(200, { context: memberContext(), data: payload })

    renderShell(<Schedule />, ['/schedule'])

    await screen.findByText(/First Song/)
    expect(
      screen.getByText(
        'The dress rehearsal has no running order of its own — it runs the setlist as it stands today (ADR 0003).',
      ),
    ).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: '#' })).toBeInTheDocument()
  })

  it('renders the All-rehearsals Dress row reading Mandatory with a Dress · required chip', async () => {
    const payload = schedulePayload()
    payload.schedule.future.push({
      id: 9,
      date: '2026-03-15',
      start_time: '18:00:00',
      end_time: '20:00:00',
      is_dress: true,
      is_past: false,
      song_count: 5,
      your_state: { kind: 'mandatory' },
    })
    mockFetchOnce(200, { context: memberContext(), data: payload })

    renderShell(<Schedule />, ['/schedule'])
    fireEvent.click(
      await screen.findByRole('radio', { name: 'All rehearsals' }),
    )

    expect(screen.getByText('Dress · required')).toBeInTheDocument()
    expect(screen.getByText('Mandatory')).toBeInTheDocument()
  })

  it('a 401 from the mocked fetch layer triggers a full-page navigation, not an error banner', async () => {
    mockFetchOnce(401, { error: 'authentication_required' })
    const assignSpy = vi.fn()
    const originalLocation = window.location
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...originalLocation, assign: assignSpy },
    })

    renderShell(<Schedule />, ['/schedule'])

    await waitFor(() =>
      expect(assignSpy).toHaveBeenCalledWith('/accounts/login/'),
    )
    expect(screen.queryByText(/error/i)).not.toBeInTheDocument()

    Object.defineProperty(window, 'location', {
      configurable: true,
      value: originalLocation,
    })
  })
})
