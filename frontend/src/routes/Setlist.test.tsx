import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useEditSession } from '../shell/EditSessionContext'
import { adminContext, memberContext } from '../test/fixtures'
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

/** Exposes the registered `EditSession`'s Discard/Save-changes as clickable buttons, standing in for the shell's own `EditToolbar` (issue #335). */
function EditSessionSpy() {
  const session = useEditSession()
  if (session === null) return <p>no edit session</p>
  return (
    <div>
      <button type="button" onClick={session.discard}>
        toolbar discard
      </button>
      <button type="button" onClick={session.requestSave} disabled={session.changeCount === 0}>
        toolbar save
      </button>
      <p>{session.changeCount} unsaved</p>
    </div>
  )
}

describe('Setlist edit mode', () => {
  it('shows "Edit setlist" for an admin and nothing for a member', async () => {
    mockFetchOnce(200, { context: memberContext(), data: setlistPayload() })
    renderShell(<Setlist />, ['/setlist'])
    await screen.findByText('Test Song')
    expect(screen.queryByRole('button', { name: 'Edit setlist' })).not.toBeInTheDocument()
  })

  it('entering edit mode swaps the read views for the grid and shows "+ Add songs"', async () => {
    mockFetchOnce(200, { context: adminContext(), data: setlistPayload() })
    const user = userEvent.setup()
    renderShell(<Setlist />, ['/setlist'])

    await user.click(await screen.findByRole('button', { name: 'Edit setlist' }))

    expect(screen.getByRole('button', { name: '+ Add songs' })).toBeInTheDocument()
    expect(screen.queryByRole('table', { name: '' })).toBeInTheDocument() // the edit grid is still a table on desktop
    expect(screen.getByLabelText('Title for row 1')).toHaveValue('Test Song')
  })

  it('registers an EditSession only while editing, and clears it on Discard', async () => {
    mockFetchOnce(200, { context: adminContext(), data: setlistPayload() })
    const user = userEvent.setup()
    renderShell(
      <>
        <Setlist />
        <EditSessionSpy />
      </>,
      ['/setlist'],
    )
    await screen.findByText('Test Song')
    expect(screen.getByText('no edit session')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Edit setlist' }))
    expect(screen.getByText('0 unsaved')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'toolbar discard' }))
    expect(screen.getByText('no edit session')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Edit setlist' })).toBeInTheDocument()
  })

  it('editing a title field updates the buffer and reports one unsaved change', async () => {
    mockFetchOnce(200, { context: adminContext(), data: setlistPayload() })
    const user = userEvent.setup()
    renderShell(
      <>
        <Setlist />
        <EditSessionSpy />
      </>,
      ['/setlist'],
    )
    await user.click(await screen.findByRole('button', { name: 'Edit setlist' }))

    const titleInput = screen.getByLabelText('Title for row 1')
    await user.clear(titleInput)
    await user.type(titleInput, 'Renamed Song')

    expect(titleInput).toHaveValue('Renamed Song')
    expect(screen.getByText('1 unsaved')).toBeInTheDocument()
  })

  it('deleting a row strikes it through, and Undo restores it with no changes left', async () => {
    mockFetchOnce(200, { context: adminContext(), data: setlistPayload() })
    const user = userEvent.setup()
    renderShell(
      <>
        <Setlist />
        <EditSessionSpy />
      </>,
      ['/setlist'],
    )
    await user.click(await screen.findByRole('button', { name: 'Edit setlist' }))

    await user.click(screen.getByRole('button', { name: 'Delete' }))
    expect(screen.getByText('Test Song · Test Artist')).toBeInTheDocument()
    expect(screen.getByText('1 unsaved')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Undo' }))
    expect(screen.queryByText('Test Song · Test Artist')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Title for row 1')).toBeInTheDocument()
    expect(screen.getByText('0 unsaved')).toBeInTheDocument()
  })

  it('adding a by-hand song through the + Add songs sheet appends a New row to the buffer', async () => {
    mockFetchOnce(200, { context: adminContext(), data: setlistPayload() })
    const user = userEvent.setup()
    renderShell(<Setlist />, ['/setlist'])
    await user.click(await screen.findByRole('button', { name: 'Edit setlist' }))

    await user.click(screen.getByRole('button', { name: '+ Add songs' }))
    await user.click(screen.getByRole('radio', { name: 'By hand' }))
    await user.type(screen.getByLabelText('Title'), 'Hand-Added Song')
    await user.click(screen.getByRole('button', { name: 'Add to the buffer' }))

    expect(screen.getByLabelText('Title for row 2')).toHaveValue('Hand-Added Song')
  })

  it('opening the Save popup calls preview exactly once and renders its changes', async () => {
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce({
        status: 200,
        ok: true,
        json: () => Promise.resolve({ context: adminContext(), data: setlistPayload() }),
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
            fallout: {
              is_blocked: false,
              block_message: '',
              is_stale: false,
              pending_adds: [],
              pending_edits: ['Test Song: title changed'],
              reordered: false,
              pending_deletions: [],
              loud: [],
              quiet: [],
            },
            values: null,
            data: null,
          }),
      })
    vi.stubGlobal('fetch', fetchSpy)
    const user = userEvent.setup()

    renderShell(
      <>
        <Setlist />
        <EditSessionSpy />
      </>,
      ['/setlist'],
    )
    await user.click(await screen.findByRole('button', { name: 'Edit setlist' }))
    const titleInput = screen.getByLabelText('Title for row 1')
    await user.clear(titleInput)
    await user.type(titleInput, 'Test Song 2')

    await user.click(screen.getByRole('button', { name: 'toolbar save' }))

    await waitFor(() => expect(screen.getByText('What changes')).toBeInTheDocument())
    expect(screen.getByText('Test Song: title changed')).toBeInTheDocument()
    expect(fetchSpy).toHaveBeenCalledTimes(2)
    expect(fetchSpy.mock.calls[1]?.[0]).toBe('/api/setlist/preview/')
  })

  it('confirming a save posts to /api/setlist/save/ and returns to read mode on success', async () => {
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce({
        status: 200,
        ok: true,
        json: () => Promise.resolve({ context: adminContext(), data: setlistPayload() }),
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
            fallout: {
              is_blocked: false,
              block_message: '',
              is_stale: false,
              pending_adds: [],
              pending_edits: ['Test Song: title changed'],
              reordered: false,
              pending_deletions: [],
              loud: [],
              quiet: [],
            },
            values: null,
            data: null,
          }),
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
            fallout: null,
            values: null,
            data: null,
          }),
      })
      .mockResolvedValueOnce({
        status: 200,
        ok: true,
        json: () => Promise.resolve({ context: adminContext(), data: setlistPayload() }),
      })
    vi.stubGlobal('fetch', fetchSpy)
    const user = userEvent.setup()

    renderShell(
      <>
        <Setlist />
        <EditSessionSpy />
      </>,
      ['/setlist'],
    )
    await user.click(await screen.findByRole('button', { name: 'Edit setlist' }))
    const titleInput = screen.getByLabelText('Title for row 1')
    await user.clear(titleInput)
    await user.type(titleInput, 'Test Song 2')

    await user.click(screen.getByRole('button', { name: 'toolbar save' }))
    await waitFor(() => expect(screen.getByText('What changes')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() => expect(screen.getByRole('button', { name: 'Edit setlist' })).toBeInTheDocument())
    expect(fetchSpy).toHaveBeenCalledTimes(4)
    expect(fetchSpy.mock.calls[2]?.[0]).toBe('/api/setlist/save/')
    expect(fetchSpy.mock.calls[3]?.[0]).toBe('/api/setlist/')
  })
})
