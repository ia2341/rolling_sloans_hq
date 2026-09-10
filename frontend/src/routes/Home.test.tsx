import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { HomePayload } from '../api/homeTypes'
import { ContextProvider } from '../api/ContextProvider'
import { resetViewingSemesterChangeForTests } from '../api/viewingSemesterChangeStore'
import { DeleteSemesterDialog } from '../shell/DeleteSemesterDialog'
import { EditSessionProvider } from '../shell/EditSessionContext'
import { NewSemesterDialog } from '../shell/NewSemesterDialog'
import { PageTitleProvider } from '../shell/PageTitleContext'
import { adminContext, memberContext } from '../test/fixtures'
import { mockFetchOnce } from '../test/mockFetch'
import { mockMatchMedia } from '../test/mockMatchMedia'
import { renderShell } from '../test/renderShell'
import { Home } from './Home'

/** A stand-in for the `/schedule` destination, showing its full path so a click-to-navigate test can assert on it. */
function LocationMarker() {
  const location = useLocation()
  return (
    <div data-testid="location">
      {location.pathname}
      {location.search}
    </div>
  )
}

/** Like `renderShell`, but with a real `<Routes>` so navigating off Home is observable (issue #358 follow-up: whole-row click navigation). */
function renderHomeWithRouting() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <ContextProvider>
        <EditSessionProvider>
          <PageTitleProvider>
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/schedule" element={<LocationMarker />} />
            </Routes>
          </PageTitleProvider>
        </EditSessionProvider>
      </ContextProvider>
    </MemoryRouter>,
  )
}

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
  resetViewingSemesterChangeForTests()
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

  it("renders the Next-rehearsal card's date sentence, arrival/departure line, and timeline slots", async () => {
    mockFetchOnce(200, { context: memberContext(), data: homePayload() })

    renderShell(<Home />, ['/'])

    // Home has no SegmentedControl pill naming the date, unlike Schedule
    // (issue #427), so this card keeps its own date sentence -- also
    // named in the Upcoming-rehearsals table below it, hence getAllByText.
    await screen.findByText(/Arrive around/)
    expect(screen.getAllByText('10th March, Tuesday').length).toBeGreaterThan(0)
    expect(screen.queryByRole('link', { name: 'Open' })).not.toBeInTheDocument()
    expect(screen.getAllByText('First Song').length).toBeGreaterThan(0)
  })

  it('makes the whole Next-rehearsal card navigate to the Schedule, without a separate Open button', async () => {
    mockFetchOnce(200, { context: memberContext(), data: homePayload() })

    renderHomeWithRouting()

    await screen.findByText(/Arrive around/)
    const card = screen.getByRole('link', { name: /Arrive around/ })
    expect(card.tagName).not.toBe('A')

    fireEvent.click(card)

    await waitFor(() =>
      expect(screen.getByTestId('location')).toHaveTextContent(
        '/schedule?rehearsal=1',
      ),
    )
  })

  it("labels each timeline segment with the Song's name and carries no title tooltip", async () => {
    mockFetchOnce(200, { context: memberContext(), data: homePayload() })

    renderShell(<Home />, ['/'])

    await screen.findByText(/Arrive around/)
    const timeline = screen.getByTestId('next-rehearsal-timeline')
    const songLink = within(timeline).getByRole('link', { name: 'First Song' })
    expect(songLink).not.toHaveAttribute('title')
    expect(songLink).toHaveAttribute('href', '/songs/1')
  })

  it('navigates a clicked Upcoming-rehearsals row to its Schedule rehearsal', async () => {
    mockFetchOnce(200, { context: memberContext(), data: homePayload() })

    renderHomeWithRouting()

    await screen.findByText('All rehearsals →')
    fireEvent.click(
      screen.getByText('Whole window').closest('tr') as HTMLElement,
    )

    await waitFor(() =>
      expect(screen.getByTestId('location')).toHaveTextContent(
        '/schedule?rehearsal=2',
      ),
    )
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

    const songProgress = await screen.findByTestId('song-progress-section')
    await within(songProgress).findByText('Second Song')
    const toggle = screen.getByRole('button', { name: 'My songs only' })
    expect(toggle).toHaveAttribute('aria-pressed', 'false')

    fireEvent.click(toggle)

    expect(toggle).toHaveAttribute('aria-pressed', 'true')
    await waitFor(() =>
      expect(
        within(songProgress).queryByText('Second Song'),
      ).not.toBeInTheDocument(),
    )
    expect(
      within(songProgress).getAllByText('First Song').length,
    ).toBeGreaterThan(0)
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

  it('shows the setup checklist for an admin viewing an empty draft Semester, with numbered items and Get Started/Review buttons', async () => {
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

    const rosterRow = screen.getByText('1. Roster').closest('li') as HTMLElement
    const rosterLink = within(rosterRow).getByRole('link', { name: 'Review' })
    expect(rosterLink).toBeInTheDocument()
    // A done step's "Review" lands on the plain read surface (issue #455),
    // never silently re-entering the edit workflow "Get Started" uses.
    expect(rosterLink).toHaveAttribute('href', '/members')

    const setlistRow = screen
      .getByText('2. Setlist')
      .closest('li') as HTMLElement
    const setlistLink = within(setlistRow).getByRole('link', {
      name: 'Get Started',
    })
    expect(setlistLink).toBeInTheDocument()
    expect(setlistLink).toHaveAttribute('href', '/setlist?intent=add-songs')

    const patternRow = screen
      .getByText('3. Rehearsal pattern')
      .closest('li') as HTMLElement
    const patternLink = within(patternRow).getByRole('link', {
      name: 'Get Started',
    })
    expect(patternLink).toHaveAttribute(
      'href',
      '/schedule/edit?intent=generate-dates',
    )

    const datesRow = screen
      .getByText('4. Rehearsal dates')
      .closest('li') as HTMLElement
    const datesLink = within(datesRow).getByRole('link', {
      name: 'Get Started',
    })
    expect(datesLink).toHaveAttribute('href', '/schedule/edit')

    const castingRow = screen
      .getByText('5. Casting')
      .closest('li') as HTMLElement
    const castingLink = within(castingRow).getByRole('link', {
      name: 'Get Started',
    })
    expect(castingLink).toHaveAttribute('href', '/schedule/edit')
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

  it("shows the newly created Semester's setup checklist immediately after Create, with Home already mounted on / (issue #402)", async () => {
    const checklist = (semesterName: string) => ({
      semester_name: semesterName,
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
    })
    let homeCallCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input.toString()
        if (url.includes('/api/semesters/create/')) {
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
                data: null,
              }),
          })
        }
        homeCallCount += 1
        return Promise.resolve({
          status: 200,
          ok: true,
          json: () =>
            Promise.resolve({
              context: adminContext(),
              data: homePayload({
                setup_checklist: checklist(
                  homeCallCount === 1 ? 'Fall 2026' : 'Spring 2027',
                ),
              }),
            }),
        })
      }),
    )
    const user = userEvent.setup()

    renderShell(
      <>
        <Home />
        <NewSemesterDialog open onOpenChange={() => {}} />
      </>,
      ['/'],
    )

    await screen.findByText('Setting up Fall 2026')

    await user.clear(screen.getByLabelText('Name'))
    await user.type(screen.getByLabelText('Name'), 'Spring 2027')
    await user.click(screen.getByRole('button', { name: 'Create Spring 2027' }))

    await screen.findByText('Setting up Spring 2027')
  })

  it("reflects a deleted Semester's fallback immediately, with Home already mounted on / (issue #402)", async () => {
    const checklist = (semesterName: string) => ({
      semester_name: semesterName,
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
    })
    let homeCallCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input.toString()
        if (url.includes('/deletion-summary/')) {
          return Promise.resolve({
            status: 200,
            ok: true,
            json: () =>
              Promise.resolve({
                context: adminContext(),
                data: {
                  member_count: 5,
                  song_count: 8,
                  rehearsal_count: 3,
                  recording_count: 0,
                },
              }),
          })
        }
        if (url.includes('/delete/')) {
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
                data: null,
              }),
          })
        }
        homeCallCount += 1
        return Promise.resolve({
          status: 200,
          ok: true,
          json: () =>
            Promise.resolve({
              context: adminContext(),
              data: homePayload({
                setup_checklist:
                  homeCallCount === 1 ? checklist('Fall 2026 (draft)') : null,
              }),
            }),
        })
      }),
    )
    const user = userEvent.setup()

    renderShell(
      <>
        <Home />
        <DeleteSemesterDialog
          open
          onOpenChange={() => {}}
          semesterId={11}
          semesterName="Fall 2026 (draft)"
        />
      </>,
      ['/'],
    )

    await screen.findByText('Setting up Fall 2026 (draft)')

    await waitFor(() =>
      expect(screen.getByText('This permanently deletes')).toBeInTheDocument(),
    )
    await user.click(
      screen.getByRole('button', {
        name: 'Delete Fall 2026 (draft) permanently',
      }),
    )

    await waitFor(() =>
      expect(
        screen.queryByText('Setting up Fall 2026 (draft)'),
      ).not.toBeInTheDocument(),
    )
  })
})
