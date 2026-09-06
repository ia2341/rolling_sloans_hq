import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { HomePayload } from '../api/homeTypes'
import { adminContext, memberContext } from '../test/fixtures'
import { mockFetchOnce } from '../test/mockFetch'
import { mockMatchMedia } from '../test/mockMatchMedia'
import { renderShell } from '../test/renderShell'
import { Home } from './Home'

/** A minimal `/api/` `data` payload: one non-Dress upcoming Rehearsal, the viewer on its first Song. */
function homePayload(overrides: Partial<HomePayload> = {}): HomePayload {
  return {
    semester_name: 'Spring 2026',
    next_rehearsal: {
      rehearsal_id: 1,
      date: '2026-03-10',
      is_dress: false,
      arrival_time: '18:00:00',
      departure_time: '19:00:00',
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
    },
    upcoming_rehearsals: [
      {
        id: 1,
        date: '2026-03-10',
        start_time: '18:00:00',
        end_time: '20:00:00',
        is_dress: false,
        is_past: false,
        your_window: { arrival_time: '18:00:00', departure_time: '19:00:00' },
      },
      {
        id: 2,
        date: '2026-03-17',
        start_time: '18:00:00',
        end_time: '20:00:00',
        is_dress: true,
        is_past: false,
        your_window: null,
      },
    ],
    song_progress: [
      {
        id: 1,
        title: 'First Song',
        artist: 'Artist A',
        length: '3:45',
        position: 1,
        completed: 2,
        total: 5,
        has_assignment: true,
        notes: '',
        next_rehearsal: null,
      },
      {
        id: 2,
        title: 'Second Song',
        artist: 'Artist B',
        length: '4:10',
        position: 2,
        completed: 0,
        total: 5,
        has_assignment: false,
        notes: '',
        next_rehearsal: null,
      },
    ],
    setup_checklist: null,
    just_created: false,
    ...overrides,
  }
}

beforeEach(() => {
  mockMatchMedia(false)
  window.localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('Home', () => {
  it('renders the no-Semester empty state', async () => {
    mockFetchOnce(200, {
      context: memberContext(),
      data: {
        semester_name: null,
        next_rehearsal: null,
        upcoming_rehearsals: [],
        song_progress: [],
        setup_checklist: null,
        just_created: false,
      },
    })

    renderShell(<Home />, ['/'])

    await screen.findByText('No Semester published yet.')
  })

  it('shows the one-off "created / Draft" status card exactly when just_created is true', async () => {
    mockFetchOnce(200, {
      context: memberContext(),
      data: homePayload({ just_created: true }),
    })

    renderShell(<Home />, ['/'])

    await screen.findByText(/created \/ Draft/)
    expect(screen.getByText(/Members still see/)).toBeInTheDocument()
  })

  it("renders the Next-rehearsal card's arrival/departure line and timeline slots", async () => {
    mockFetchOnce(200, { context: memberContext(), data: homePayload() })

    renderShell(<Home />, ['/'])

    await screen.findByText(/Arrive around/)
    expect(screen.getByRole('link', { name: 'Open' })).toHaveAttribute(
      'href',
      '/schedule?rehearsal=1',
    )
    expect(screen.getAllByText('First Song').length).toBeGreaterThan(0)
  })

  it('reports the explicit not-needed state when there is no qualifying next Rehearsal', async () => {
    mockFetchOnce(200, {
      context: memberContext(),
      data: homePayload({ next_rehearsal: null }),
    })

    renderShell(<Home />, ['/'])

    await screen.findByText('You are not needed at any upcoming rehearsal.')
  })

  it('lists exactly the upcoming rows, marking the Dress Rehearsal with a chip', async () => {
    mockFetchOnce(200, { context: memberContext(), data: homePayload() })

    renderShell(<Home />, ['/'])

    await screen.findByText('All rehearsals →')
    expect(screen.getByText('Dress')).toBeInTheDocument()
    expect(screen.getByText('Whole window')).toBeInTheDocument()
  })

  it('filters Song progress with the My songs only toggle, and flips aria-pressed', async () => {
    mockFetchOnce(200, { context: memberContext(), data: homePayload() })

    renderShell(<Home />, ['/'])

    await screen.findByText('Second Song')
    const toggle = screen.getByRole('button', { name: 'My songs only' })
    expect(toggle).toHaveAttribute('aria-pressed', 'false')

    fireEvent.click(toggle)

    expect(toggle).toHaveAttribute('aria-pressed', 'true')
    await waitFor(() =>
      expect(screen.queryByText('Second Song')).not.toBeInTheDocument(),
    )
    expect(screen.getAllByText('First Song').length).toBeGreaterThan(0)
  })

  it('renders Song progress (and Upcoming rehearsals) as tables on desktop, and lists on phone', async () => {
    mockFetchOnce(200, { context: memberContext(), data: homePayload() })
    renderShell(<Home />, ['/'])
    await waitFor(() => expect(screen.getAllByRole('table')).toHaveLength(2))

    mockMatchMedia(true)
    mockFetchOnce(200, { context: memberContext(), data: homePayload() })
    renderShell(<Home />, ['/'])
    await waitFor(() => expect(screen.queryAllByRole('table')).toHaveLength(0))
  })

  it('shows the setup checklist for an admin viewing an empty draft Semester, with numbered items and Open/Review buttons', async () => {
    mockFetchOnce(200, {
      context: adminContext(),
      data: homePayload({
        setup_checklist: {
          semester_name: 'Fall 2026 (draft)',
          items: [
            {
              key: 'roster',
              label: 'Roster',
              is_done: true,
              status: '3 on the roster',
              destination: '/members',
              waiting_on: null,
            },
            {
              key: 'setlist',
              label: 'Setlist',
              is_done: false,
              status: 'Empty — paste a Spotify playlist, or add songs by hand',
              destination: '/setlist',
              waiting_on: null,
            },
            {
              key: 'rehearsal_pattern',
              label: 'Rehearsal pattern',
              is_done: false,
              status: 'Not set — the days and times rehearsals happen',
              destination: '/schedule/edit',
              waiting_on: null,
            },
            {
              key: 'rehearsal_dates',
              label: 'Rehearsal dates',
              is_done: false,
              status: 'Nothing scheduled — generated from the pattern',
              destination: '/schedule/edit',
              waiting_on: 'Needs the pattern first',
            },
            {
              key: 'casting',
              label: 'Casting',
              is_done: false,
              status: 'Nobody assigned to a song yet',
              destination: '/schedule/edit',
              waiting_on: 'Needs the roster and the setlist',
            },
          ],
        },
      }),
    })

    renderShell(<Home />, ['/'])

    await screen.findByText('Setting up Fall 2026 (draft)')
    expect(screen.getByText('1. Roster')).toBeInTheDocument()
    expect(screen.getByText('5. Casting')).toBeInTheDocument()
    expect(
      screen.getByText('Needs the pattern first', { exact: false }),
    ).toBeInTheDocument()

    const rosterRow = screen.getByText('1. Roster').closest('li') as HTMLElement
    expect(
      within(rosterRow).getByRole('link', { name: 'Review' }),
    ).toBeInTheDocument()
    const setlistRow = screen
      .getByText('2. Setlist')
      .closest('li') as HTMLElement
    expect(
      within(setlistRow).getByRole('link', { name: 'Open' }),
    ).toBeInTheDocument()
  })

  it('never disables a checklist item and Dismiss removes the panel', async () => {
    mockFetchOnce(200, {
      context: adminContext(),
      data: homePayload({
        setup_checklist: {
          semester_name: 'Fall 2026 (draft)',
          items: [
            {
              key: 'roster',
              label: 'Roster',
              is_done: false,
              status: 'Empty',
              destination: '/members',
              waiting_on: null,
            },
          ],
        },
      }),
    })

    renderShell(<Home />, ['/'])

    await screen.findByText('Setting up Fall 2026 (draft)')
    for (const link of screen.getAllByRole('link')) {
      expect(link).not.toHaveAttribute('aria-disabled', 'true')
    }

    fireEvent.click(screen.getByRole('button', { name: 'Dismiss this panel' }))

    expect(
      screen.queryByText('Setting up Fall 2026 (draft)'),
    ).not.toBeInTheDocument()
  })

  it('renders no setup checklist for a member', async () => {
    mockFetchOnce(200, { context: memberContext(), data: homePayload() })

    renderShell(<Home />, ['/'])

    await screen.findByText(/Arrive around/)
    expect(screen.queryByText(/^Setting up/)).not.toBeInTheDocument()
  })
})
