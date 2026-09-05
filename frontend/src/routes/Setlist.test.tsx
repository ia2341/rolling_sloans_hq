import { screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { memberContext } from '../test/fixtures'
import { mockFetchOnce } from '../test/mockFetch'
import { mockMatchMedia } from '../test/mockMatchMedia'
import { renderShell } from '../test/renderShell'
import { Setlist } from './Setlist'

/** A minimal `/api/setlist/` `data` payload, one Song with a partial cast (Singer filled, Drummer unfilled). */
function setlistPayload(overrides: Record<string, unknown> = {}) {
  return {
    semester_name: 'Spring 2026',
    song_count: 1,
    total_running_time: '3:30',
    roles: [
      { id: 1, name: 'Singer', code: 'SIN' },
      { id: 2, name: 'Drummer', code: 'DRU' },
    ],
    songs: [
      {
        id: 1,
        title: 'Test Song',
        artist: 'Test Artist',
        length: '3:30',
        position: 1,
        notes: '',
        cast: [
          {
            role_id: 1,
            role_name: 'Singer',
            code: 'SIN',
            performers: [
              { id: 1, name: 'Sam Rivera', is_role_mismatch: false },
            ],
          },
          { role_id: 2, role_name: 'Drummer', code: 'DRU', performers: [] },
        ],
        recording_count: 0,
      },
    ],
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

describe('Setlist', () => {
  it('renders all Roles in fixed order, including an unfilled one, for a partial cast', async () => {
    mockFetchOnce(200, { context: memberContext(), data: setlistPayload() })

    renderShell(<Setlist />, ['/setlist'])

    await screen.findByText('Test Song')
    expect(screen.queryByText('SIN unfilled')).not.toBeInTheDocument() // Singer is filled
    expect(screen.getByText('Sam Rivera')).toBeInTheDocument()
    expect(screen.getByText('DRU unfilled')).toBeInTheDocument()
  })

  it('renders a Song with no notes with no notes row at all', async () => {
    mockFetchOnce(200, { context: memberContext(), data: setlistPayload() })

    renderShell(<Setlist />, ['/setlist'])

    await screen.findByText('Test Song')
    expect(
      screen.queryByText('notes', { exact: false }),
    ).not.toBeInTheDocument()
  })

  it('renders a Song note only when it has one', async () => {
    const payload = setlistPayload()
    payload.songs[0]!.notes = 'Watch the tempo change.'
    mockFetchOnce(200, { context: memberContext(), data: payload })

    renderShell(<Setlist />, ['/setlist'])

    expect(
      await screen.findByText('Watch the tempo change.'),
    ).toBeInTheDocument()
  })

  it('renders "no takes yet" on phone instead of a play control for a Song with no takes', async () => {
    mockMatchMedia(true)
    mockFetchOnce(200, { context: memberContext(), data: setlistPayload() })

    renderShell(<Setlist />, ['/setlist'])

    expect(await screen.findByText('no takes yet')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Play/ })).not.toBeInTheDocument()
  })

  it('renders "—" on desktop instead of a play control for a Song with no takes', async () => {
    mockFetchOnce(200, { context: memberContext(), data: setlistPayload() })

    renderShell(<Setlist />, ['/setlist'])

    expect(await screen.findByText('—')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Play/ })).not.toBeInTheDocument()
  })

  it('renders ▶ with a count and + with the right targets for a Song with takes', async () => {
    const payload = setlistPayload()
    payload.songs[0]!.recording_count = 3
    mockFetchOnce(200, { context: memberContext(), data: payload })

    renderShell(<Setlist />, ['/setlist'])

    const playLink = await screen.findByRole('link', {
      name: /Play Test Song's takes/,
    })
    expect(playLink).toHaveAttribute('href', '/songs/1')
    const addLink = screen.getByRole('link', {
      name: /Add a recording of Test Song/,
    })
    expect(addLink).toHaveAttribute('href', '/profile?song=1')
  })

  it('renders an explicit empty state for a Semester with no Songs', async () => {
    mockFetchOnce(200, {
      context: memberContext(),
      data: setlistPayload({ songs: [], song_count: 0 }),
    })

    renderShell(<Setlist />, ['/setlist'])

    expect(
      await screen.findByText('No songs yet this Semester.'),
    ).toBeInTheDocument()
  })

  it('renders an explicit empty state when no Semester is published at all', async () => {
    mockFetchOnce(200, {
      context: memberContext(),
      data: {
        semester_name: null,
        song_count: 0,
        total_running_time: '0:00',
        roles: [],
        songs: [],
      },
    })

    renderShell(<Setlist />, ['/setlist'])

    expect(
      await screen.findByText('No Semester published yet.'),
    ).toBeInTheDocument()
  })

  it('renders phone cards on a phone viewport and the table on desktop, with no horizontal scroll on the body', async () => {
    mockMatchMedia(true)
    mockFetchOnce(200, { context: memberContext(), data: setlistPayload() })

    renderShell(<Setlist />, ['/setlist'])

    await screen.findByText(/Test Song/)
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('renders the table on desktop', async () => {
    mockFetchOnce(200, { context: memberContext(), data: setlistPayload() })

    renderShell(<Setlist />, ['/setlist'])

    expect(await screen.findByRole('table')).toBeInTheDocument()
  })

  it('a 401 from the mocked fetch layer triggers a full-page navigation, not an error banner', async () => {
    mockFetchOnce(401, { error: 'authentication_required' })
    const assignSpy = vi.fn()
    const originalLocation = window.location
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...originalLocation, assign: assignSpy },
    })

    renderShell(<Setlist />, ['/setlist'])

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
