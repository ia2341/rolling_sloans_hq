import { screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { adminContext, memberContext } from '../test/fixtures'
import { mockFetchOnce } from '../test/mockFetch'
import { mockMatchMedia } from '../test/mockMatchMedia'
import { renderShell } from '../test/renderShell'
import { Song } from './Song'

/** A minimal `/api/songs/<pk>/` `data` payload: one Song with an unfilled cast, no recordings, no rehearsals. */
function songPayload(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    title: 'Test Song',
    artist: 'Test Artist',
    length: '3:30',
    position: 1,
    notes: '',
    cast: [{ role_id: 1, role_name: 'Singer', code: 'SIN', performers: [] }],
    recording_groups: [],
    rehearsed_at: [],
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

describe('Song', () => {
  it('renders the title, artist, length and setlist position', async () => {
    mockFetchOnce(200, { context: memberContext(), data: songPayload() })

    renderShell(<Song />, ['/songs/1'])

    await screen.findByRole('heading', { name: 'Test Song' })
    expect(
      screen.getByText(/Test Artist · 3:30 · position 1 in the setlist/),
    ).toBeInTheDocument()
  })

  it('renders a ← Setlist back link', async () => {
    mockFetchOnce(200, { context: memberContext(), data: songPayload() })

    renderShell(<Song />, ['/songs/1'])

    const link = await screen.findByRole('link', { name: /Setlist/ })
    expect(link).toHaveAttribute('href', '/setlist')
  })

  it('renders the ADR-0009 pointer block for an admin', async () => {
    mockFetchOnce(200, {
      context: adminContext(),
      data: songPayload({ next_rehearsal: { id: 5, date: '2026-03-01' } }),
    })

    renderShell(<Song />, ['/songs/1'])

    expect(
      await screen.findByText(/Casting happens on a rehearsal, not here/),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: /Cast on 2026-03-01/ }),
    ).toHaveAttribute('href', '/schedule?rehearsal=5')
  })

  it('does not render the ADR-0009 pointer block for a member', async () => {
    mockFetchOnce(200, { context: memberContext(), data: songPayload() })

    renderShell(<Song />, ['/songs/1'])

    await screen.findByRole('heading', { name: 'Test Song' })
    expect(
      screen.queryByText(/Casting happens on a rehearsal/),
    ).not.toBeInTheDocument()
  })

  it('renders notes as one paragraph, absent entirely when empty', async () => {
    mockFetchOnce(200, { context: memberContext(), data: songPayload() })

    renderShell(<Song />, ['/songs/1'])

    await screen.findByRole('heading', { name: 'Test Song' })
    expect(screen.queryByText('Notes')).not.toBeInTheDocument()
  })

  it('renders the notes section when the Song has notes', async () => {
    mockFetchOnce(200, {
      context: memberContext(),
      data: songPayload({ notes: 'Watch the key change.' }),
    })

    renderShell(<Song />, ['/songs/1'])

    expect(await screen.findByText('Watch the key change.')).toBeInTheDocument()
  })

  it('groups Recordings by slot, with the date, window and take count in the group header', async () => {
    mockFetchOnce(200, {
      context: memberContext(),
      data: songPayload({
        recording_groups: [
          {
            rehearsal_id: 9,
            date: '2026-02-10',
            start_time: '18:00:00',
            end_time: '18:15:00',
            take_count: 2,
            recordings: [
              {
                id: 1,
                uploaded_by_name: 'Sam Rivera',
                note: '',
                playback_url: 'https://example.com/a.mp3',
              },
              {
                id: 2,
                uploaded_by_name: 'Alex Kim',
                note: 'Good take',
                playback_url: 'https://example.com/b.mp3',
              },
            ],
          },
        ],
      }),
    })

    renderShell(<Song />, ['/songs/1'])

    expect(
      await screen.findByText(/2026-02-10.*18:00–18:15.*2 takes/),
    ).toBeInTheDocument()
    expect(screen.getByText('Sam Rivera')).toBeInTheDocument()
    expect(screen.getByText(/Alex Kim — Good take/)).toBeInTheDocument()
  })

  it('renders "no recordings yet" explicitly for a Song with none', async () => {
    mockFetchOnce(200, { context: memberContext(), data: songPayload() })

    renderShell(<Song />, ['/songs/1'])

    expect(await screen.findByText('No recordings yet.')).toBeInTheDocument()
  })

  it('renders the Dress Rehearsal row in Rehearsed at as "whole setlist" with no slot time', async () => {
    mockFetchOnce(200, {
      context: memberContext(),
      data: songPayload({
        rehearsed_at: [
          {
            rehearsal_id: 3,
            date: '2026-04-01',
            is_dress_rehearsal: true,
            start_time: null,
            end_time: null,
          },
        ],
      }),
    })

    renderShell(<Song />, ['/songs/1'])

    expect(
      await screen.findByText(/2026-04-01 — whole setlist/),
    ).toBeInTheDocument()
  })

  it('renders a 404 not-found state for a Song outside the viewing Semester', async () => {
    mockFetchOnce(404, { error: 'not_found' })

    renderShell(<Song />, ['/songs/999'])

    expect(await screen.findByText('Song not found')).toBeInTheDocument()
  })

  it('a 401 from the mocked fetch layer triggers a full-page navigation, not an error banner', async () => {
    mockFetchOnce(401, { error: 'authentication_required' })
    const assignSpy = vi.fn()
    const originalLocation = window.location
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...originalLocation, assign: assignSpy },
    })

    renderShell(<Song />, ['/songs/1'])

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
