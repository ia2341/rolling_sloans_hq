import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { SchedulePayload } from '../api/scheduleTypes'
import { adminContext, memberContext } from '../test/fixtures'
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
          songs: [
            { id: 1, title: 'First Song' },
            { id: 2, title: 'Second Song' },
          ],
          your_state: { kind: 'not_needed' },
          your_songs: [],
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
      roles: [
        {
          id: 1,
          name: 'Singer',
          code: 'SIN',
          group_id: 18,
          group_name: 'Other',
          group_order: 8,
          group_is_catch_all: true,
        },
      ],
      rows: [
        {
          song_id: 1,
          song_title: 'First Song',
          song_artist: 'First Artist',
          song_position: 1,
          song_length: '3:45',
          start_time: '18:00:00',
          rehearsal_song_id: 100,
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
  it('hides a Role column entirely when no Song in this Rehearsal has a performer for it (issue #436)', async () => {
    // Drummer matches no performer on either Song in this Rehearsal, so it
    // must not render as a column at all, even though it's declared roles.
    const payload = schedulePayload()
    payload.selected!.roles = [
      {
        id: 1,
        name: 'Singer',
        code: 'SIN',
        group_id: 18,
        group_name: 'Other',
        group_order: 8,
        group_is_catch_all: true,
      },
      {
        id: 2,
        name: 'Drummer',
        code: 'DRU',
        group_id: 13,
        group_name: 'Drums',
        group_order: 3,
        group_is_catch_all: false,
      },
    ]
    payload.selected!.rows[0]!.cells.push({ role_id: 2, entries: [] })
    mockFetchOnce(200, { context: memberContext(), data: payload })

    renderShell(<Schedule />, ['/schedule'])

    await screen.findByRole('table')
    expect(
      screen.getByRole('columnheader', { name: 'Singer' }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('columnheader', { name: 'Drums' }),
    ).not.toBeInTheDocument()
  })

  it('keeps a Role column visible when only one Song in this Rehearsal has a performer for it', async () => {
    const payload = schedulePayload()
    payload.selected!.roles = [
      {
        id: 1,
        name: 'Singer',
        code: 'SIN',
        group_id: 18,
        group_name: 'Other',
        group_order: 8,
        group_is_catch_all: true,
      },
      {
        id: 2,
        name: 'Drummer',
        code: 'DRU',
        group_id: 13,
        group_name: 'Drums',
        group_order: 3,
        group_is_catch_all: false,
      },
    ]
    payload.selected!.rows[0]!.cells.push({ role_id: 2, entries: [] })
    payload.selected!.rows.push({
      song_id: 2,
      song_title: 'Second Song',
      song_artist: 'Second Artist',
      song_position: 2,
      song_length: '2:45',
      start_time: '19:00:00',
      rehearsal_song_id: 101,
      cells: [
        { role_id: 1, entries: [] },
        {
          role_id: 2,
          entries: [
            {
              id: 2,
              kind: 'assignment',
              person_id: 2,
              person_name: 'Alex Chen',
              is_role_mismatch: false,
              has_conflict: false,
            },
          ],
        },
      ],
    })
    mockFetchOnce(200, { context: memberContext(), data: payload })

    renderShell(<Schedule />, ['/schedule'])

    await screen.findByRole('table')
    expect(
      screen.getByRole('columnheader', { name: 'Singer' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('columnheader', { name: 'Drums' }),
    ).toBeInTheDocument()
  })

  it('renders one table with the Song length and linked assignment names, with no Running order | Assignments mode switch', async () => {
    mockFetchOnce(200, { context: memberContext(), data: schedulePayload() })

    renderShell(<Schedule />, ['/schedule'])

    expect(await screen.findByRole('table')).toBeInTheDocument()
    expect(screen.getByText('Sam')).toBeInTheDocument()
    expect(screen.getByText('3:45')).toBeInTheDocument()
    expect(screen.queryByText('Running Order')).not.toBeInTheDocument()
    expect(
      screen.queryByRole('tab', { name: 'Assignments' }),
    ).not.toBeInTheDocument()
  })

  it('renders the admin "Edit Rehearsal" button beside the assignments heading, not in the page header', async () => {
    mockFetchOnce(200, { context: adminContext(), data: schedulePayload() })

    renderShell(<Schedule />, ['/schedule'])

    const heading = await screen.findByRole('heading', {
      name: 'Running order & assignments',
    })
    const button = screen.getByRole('button', { name: 'Edit Rehearsal' })
    expect(heading.parentElement).toContainElement(button)

    const pageHead = screen.getByRole('heading', {
      name: /^Schedule:/,
    }).parentElement
    expect(pageHead).not.toContainElement(button)
  })

  it('disables the "Edit Rehearsal" button when the rehearsal is not editable, and enters edit mode on click when it is', async () => {
    const payload = schedulePayload()
    payload.selected!.can_edit_assignments = false
    mockFetchOnce(200, { context: adminContext(), data: payload })

    renderShell(<Schedule />, ['/schedule'])

    expect(
      await screen.findByRole('button', { name: 'Edit Rehearsal' }),
    ).toBeDisabled()
  })

  it('renders no "Edit Rehearsal" button at all for the Dress Rehearsal (ADR 0019)', async () => {
    const payload = schedulePayload()
    payload.selected!.is_dress = true
    payload.selected!.can_edit_assignments = true
    mockFetchOnce(200, { context: adminContext(), data: payload })

    renderShell(<Schedule />, ['/schedule'])

    await screen.findByRole('heading', {
      name: 'Running order & assignments',
    })
    expect(
      screen.queryByRole('button', { name: 'Edit Rehearsal' }),
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

    await screen.findByRole('table')
    expect(fetchSpy).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole('radio', { name: 'All rehearsals' }))

    await screen.findByRole('link', { name: /10th March/ })
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

  it('renders a disabled Declare a conflict button for the Dress Rehearsal', async () => {
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
      await screen.findByRole('button', { name: 'Declare a conflict' }),
    ).toBeDisabled()
  })

  it('does not repeat the date under "You at this rehearsal", but still names dress status in the page subline', async () => {
    const payload = schedulePayload()
    payload.selected!.is_dress = true
    payload.selected!.timeline.is_dress_rehearsal = true
    mockFetchOnce(200, { context: memberContext(), data: payload })

    renderShell(<Schedule />, ['/schedule'])

    expect(
      await screen.findByRole('heading', { name: 'You at this rehearsal' }),
    ).toBeInTheDocument()
    // The date/dress-status sentence used to also appear here, duplicating
    // the SegmentedControl pill above it (issue #427) — now it's gone, and
    // dress status is named only in the PageHead subline.
    expect(screen.queryByText('dress rehearsal')).not.toBeInTheDocument()
    expect(screen.getByText(/· dress rehearsal ·/)).toBeInTheDocument()
    expect(
      screen.getByRole('radio', { name: '10th March, Tuesday' }),
    ).toBeInTheDocument()
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

    // Names shorten to a first name (`shortenNames()`) -- "Teammate" is unique among this table's names.
    const teammateLink = await screen.findByText('Teammate')
    expect(teammateLink.closest('div')).toHaveTextContent('away')
    expect(screen.queryByText(/reason/i)).not.toBeInTheDocument()
  })

  it('renders a Backup as "name" plus a "(backup)" marker with no "covering for" text for a member', async () => {
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

    const backupLink = await screen.findByText('Backup')
    expect(backupLink.closest('div')).toHaveTextContent('(backup)')
    expect(screen.queryByText(/covering for/i)).not.toBeInTheDocument()
  })

  it('renders per-song cards with Roles as rows on a phone viewport, and the page body never scrolls horizontally', async () => {
    mockMatchMedia(true)
    mockFetchOnce(200, { context: memberContext(), data: schedulePayload() })

    renderShell(<Schedule />, ['/schedule'])

    await screen.findByText('Available for the whole rehearsal')
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('renders a position column and no start times for the Dress Rehearsal', async () => {
    const payload = schedulePayload()
    payload.selected!.is_dress = true
    payload.selected!.rows[0]!.start_time = null
    payload.selected!.timeline.is_dress_rehearsal = true
    mockFetchOnce(200, { context: memberContext(), data: payload })

    renderShell(<Schedule />, ['/schedule'])

    await screen.findByRole('table')
    expect(screen.getByRole('columnheader', { name: '#' })).toBeInTheDocument()
  })

  it('renders the All-rehearsals Dress row reading Mandatory with a Dress badge', async () => {
    const payload = schedulePayload()
    payload.schedule.future.push({
      id: 9,
      date: '2026-03-15',
      start_time: '18:00:00',
      end_time: '20:00:00',
      is_dress: true,
      is_past: false,
      song_count: 5,
      songs: [],
      your_state: { kind: 'mandatory' },
      your_songs: [],
      availability: {
        declaration_type: null,
        type_label: null,
        declared_time: null,
        reason: null,
        status: null,
        admin_note: null,
        is_dress: true,
        is_editable: false,
      },
    })
    mockFetchOnce(200, { context: memberContext(), data: payload })

    renderShell(<Schedule />, ['/schedule'])
    fireEvent.click(
      await screen.findByRole('radio', { name: 'All rehearsals' }),
    )

    expect(screen.getByText('Dress')).toBeInTheDocument()
    expect(screen.getByText('Mandatory')).toBeInTheDocument()
  })

  it('renders All-rehearsals as clickable cards that navigate on click, with a "+ Conflict" control that stops propagation', async () => {
    mockFetchOnce(200, { context: memberContext(), data: schedulePayload() })

    renderShell(<Schedule />, ['/schedule'])
    fireEvent.click(
      await screen.findByRole('radio', { name: 'All rehearsals' }),
    )

    const card = await screen.findByRole('link', {
      name: /10th March/,
    })
    expect(
      screen.queryByRole('button', { name: 'Open' }),
    ).not.toBeInTheDocument()

    const conflictButton = screen.getByRole('button', { name: '+ Conflict' })
    fireEvent.click(conflictButton)

    expect(await screen.findByText('Declare a conflict')).toBeInTheDocument()
    // Clicking "+ Conflict" must not also trigger the card's own navigation.
    expect(card).toBeInTheDocument()
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

    await waitFor(() => expect(assignSpy).toHaveBeenCalledWith('/login'))
    expect(screen.queryByText(/error/i)).not.toBeInTheDocument()

    Object.defineProperty(window, 'location', {
      configurable: true,
      value: originalLocation,
    })
  })
})
