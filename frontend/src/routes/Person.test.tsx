import { screen, waitFor } from '@testing-library/react'
import { Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { memberContext } from '../test/fixtures'
import { mockMatchMedia } from '../test/mockMatchMedia'
import { renderShell } from '../test/renderShell'
import { Person } from './Person'

/** Renders `Person` behind a real `/members/:personId` route match, so `useParams()` resolves the id in the mocked fetch URL. */
function renderPerson(initialEntry: string) {
  return renderShell(
    <Routes>
      <Route path="/members/:personId" element={<Person />} />
    </Routes>,
    [initialEntry],
  )
}

/** A minimal `/api/members/<pk>/` `data` payload for a teammate viewer: no email, no recordings, no can_edit_roles. */
function teammatePayload(overrides: Record<string, unknown> = {}) {
  return {
    id: 2,
    name: 'Alex Kim',
    is_self: false,
    can_edit_roles: false,
    has_membership: true,
    semester_name: 'Spring 2026',
    roles: [{ id: 1, name: 'Drummer' }],
    songs: [],
    ...overrides,
  }
}

/** A minimal self-viewer payload, rostered, with an empty Recordings block. */
function selfPayload(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    name: 'Sam Rivera',
    is_self: true,
    can_edit_roles: true,
    has_membership: true,
    semester_name: 'Spring 2026',
    email: 'sam@example.com',
    available_roles: [
      { id: 1, name: 'Drummer' },
      { id: 2, name: 'Singer' },
    ],
    roles: [{ id: 2, name: 'Singer' }],
    songs: [],
    recordings: { count: 0, items: [], upload_slots: [] },
    ...overrides,
  }
}

/** An admin-viewing-teammate payload: the teammate key set, plus can_edit_roles: true. */
function adminViewingTeammatePayload(overrides: Record<string, unknown> = {}) {
  return {
    ...teammatePayload(),
    can_edit_roles: true,
    available_roles: [
      { id: 1, name: 'Drummer' },
      { id: 2, name: 'Singer' },
    ],
    ...overrides,
  }
}

/** Stubs `window.fetch` with a dispatcher keyed by a substring of the request URL, for tests that need more than one distinct response in sequence. */
function mockFetchByUrl(
  handlers: Record<string, () => { status: number; body: unknown }>,
) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString()
      const key = Object.keys(handlers).find((candidate) =>
        url.includes(candidate),
      )
      if (key === undefined) {
        throw new Error(`No mock handler registered for fetch(${url})`)
      }
      const { status, body } = handlers[key]!()
      return Promise.resolve({
        status,
        ok: status >= 200 && status < 300,
        json: () => Promise.resolve(body),
      })
    }),
  )
}

beforeEach(() => {
  mockMatchMedia(false)
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('Person', () => {
  it('renders no email and no Recordings region for a teammate viewer', async () => {
    mockFetchByUrl({
      '/api/members/2/': () => ({
        status: 200,
        body: { context: memberContext(), data: teammatePayload() },
      }),
    })

    renderPerson('/members/2')

    await screen.findByRole('heading', { name: 'Alex Kim' })
    expect(screen.queryByText('sam@example.com')).not.toBeInTheDocument()
    expect(screen.queryByText('Email')).not.toBeInTheDocument()
    expect(screen.queryByText('Your recordings')).not.toBeInTheDocument()
  })

  it('shows the read-only copy for a teammate’s declared Roles', async () => {
    mockFetchByUrl({
      '/api/members/2/': () => ({
        status: 200,
        body: { context: memberContext(), data: teammatePayload() },
      }),
    })

    renderPerson('/members/2')

    expect(
      await screen.findByText('Only they (or an admin) can change these.'),
    ).toBeInTheDocument()
    expect(screen.queryByLabelText('Add a role')).not.toBeInTheDocument()
  })

  it('renders the email and Your recordings section for the self viewer', async () => {
    mockFetchByUrl({
      '/api/members/1/': () => ({
        status: 200,
        body: { context: memberContext(), data: selfPayload() },
      }),
    })

    renderPerson('/members/1')

    await screen.findByText('sam@example.com')
    expect(await screen.findByText('Your recordings')).toBeInTheDocument()
  })

  it('renders the editable Roles card, with can-edit affordances, for an admin viewing a teammate', async () => {
    mockFetchByUrl({
      '/api/members/2/': () => ({
        status: 200,
        body: {
          context: memberContext({
            viewer: { ...memberContext().viewer, is_admin: true },
          }),
          data: adminViewingTeammatePayload(),
        },
      }),
    })

    renderPerson('/members/2')

    await screen.findByRole('heading', { name: 'Alex Kim' })
    expect(screen.queryByText('sam@example.com')).not.toBeInTheDocument()
    expect(screen.queryByText('Email')).not.toBeInTheDocument()
    expect(screen.queryByText('Your recordings')).not.toBeInTheDocument()
    expect(
      await screen.findByRole('button', { name: 'Save roles' }),
    ).toBeInTheDocument()
  })

  it('renders the "Deliberately absent" card for a teammate viewer', async () => {
    mockFetchByUrl({
      '/api/members/2/': () => ({
        status: 200,
        body: { context: memberContext(), data: teammatePayload() },
      }),
    })
    renderPerson('/members/2')
    expect(await screen.findByText(/Deliberately absent\./)).toBeInTheDocument()
  })

  it('renders the "Deliberately absent" card for the self viewer', async () => {
    mockFetchByUrl({
      '/api/members/1/': () => ({
        status: 200,
        body: { context: memberContext(), data: selfPayload() },
      }),
    })
    renderPerson('/members/1')
    expect(await screen.findByText(/Deliberately absent\./)).toBeInTheDocument()
  })

  it('renders the "Deliberately absent" card for an admin viewing a teammate', async () => {
    mockFetchByUrl({
      '/api/members/2/': () => ({
        status: 200,
        body: {
          context: memberContext({
            viewer: { ...memberContext().viewer, is_admin: true },
          }),
          data: adminViewingTeammatePayload(),
        },
      }),
    })
    renderPerson('/members/2')
    expect(await screen.findByText(/Deliberately absent\./)).toBeInTheDocument()
  })

  it('renders "Not on any song yet." for an empty Songs list', async () => {
    mockFetchByUrl({
      '/api/members/2/': () => ({
        status: 200,
        body: {
          context: memberContext(),
          data: teammatePayload({ songs: [] }),
        },
      }),
    })
    renderPerson('/members/2')
    expect(await screen.findByText('Not on any song yet.')).toBeInTheDocument()
  })

  it('omits the Roles-list, Songs and Recordings sections entirely for a not-yet-rostered self viewer', async () => {
    mockFetchByUrl({
      '/api/members/1/': () => ({
        status: 200,
        body: {
          context: memberContext(),
          data: {
            id: 1,
            name: 'Sam Rivera',
            is_self: true,
            can_edit_roles: true,
            has_membership: false,
            semester_name: 'Spring 2026',
            email: 'sam@example.com',
            available_roles: [{ id: 1, name: 'Drummer' }],
          },
        },
      }),
    })

    renderPerson('/members/1')

    await screen.findByText('sam@example.com')
    expect(screen.queryByText('Not on any song yet.')).not.toBeInTheDocument()
    expect(screen.queryByText('Your recordings')).not.toBeInTheDocument()
    // The always-inline Roles form still renders, so a newly invited member can declare roles.
    expect(screen.getByLabelText('Add a role')).toBeInTheDocument()
  })

  it('stages a Role chip removal locally and only commits it on Save roles', async () => {
    const roleFetch = vi.fn()
    mockFetchByUrl({
      '/api/members/1/roles/': () => {
        roleFetch()
        return {
          status: 200,
          body: {
            context: memberContext(),
            ok: true,
            errors: {},
            non_field_errors: [],
            fallout: null,
            values: null,
            data: selfPayload({ roles: [] }),
          },
        }
      },
      '/api/members/1/': () => ({
        status: 200,
        body: { context: memberContext(), data: selfPayload() },
      }),
    })

    const user = (await import('@testing-library/user-event')).default.setup()
    renderPerson('/members/1')

    await screen.findByText('Singer')
    await user.click(screen.getByRole('button', { name: 'Remove Singer' }))

    // Staged locally: the chip disappears immediately, but nothing has hit the network yet.
    expect(
      screen.queryByRole('button', { name: 'Remove Singer' }),
    ).not.toBeInTheDocument()
    expect(roleFetch).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Save roles' }))
    await waitFor(() => expect(roleFetch).toHaveBeenCalledTimes(1))
  })

  it('disables Save recording until the mocked upload resolves, then enables it', async () => {
    const payload = selfPayload({
      recordings: {
        count: 0,
        items: [],
        upload_slots: [
          {
            id: 10,
            song_id: 5,
            song_title: 'Test Song',
            rehearsal_date: '2026-03-01',
            start_time: null,
            end_time: null,
          },
        ],
      },
    })
    mockFetchByUrl({
      '/api/members/1/': () => ({
        status: 200,
        body: { context: memberContext(), data: payload },
      }),
      '/api/members/recordings/presign/': () => ({
        status: 200,
        body: {
          context: memberContext(),
          data: {
            upload_url: 'https://storage.example.com/upload',
            fields: { key: 'recordings/abc.mp3' },
            object_key: 'recordings/abc.mp3',
          },
        },
      }),
      'storage.example.com': () => ({ status: 204, body: {} }),
    })

    const user = (await import('@testing-library/user-event')).default.setup()
    renderPerson('/members/1')

    await screen.findByText('Upload a take')
    const saveButton = screen.getByRole('button', { name: 'Save recording' })
    expect(saveButton).toBeDisabled()

    const file = new File(['audio-bytes'], 'take.mp3', { type: 'audio/mpeg' })
    const fileInput = screen.getByLabelText(/Drop an audio file/i, {
      selector: 'input',
    })
    await user.upload(fileInput, file)

    await waitFor(() => expect(saveButton).not.toBeDisabled())
  })

  it('narrows the slot picker to the ?song=<id> Song when arriving from the Setlist/Song "+" deep link', async () => {
    const payload = selfPayload({
      recordings: {
        count: 0,
        items: [],
        upload_slots: [
          {
            id: 10,
            song_id: 5,
            song_title: 'Other Song',
            rehearsal_date: '2026-03-01',
            start_time: null,
            end_time: null,
          },
          {
            id: 11,
            song_id: 7,
            song_title: 'Preselected Song',
            rehearsal_date: '2026-03-08',
            start_time: null,
            end_time: null,
          },
        ],
      },
    })
    mockFetchByUrl({
      '/api/members/1/': () => ({
        status: 200,
        body: { context: memberContext(), data: payload },
      }),
    })

    renderPerson('/members/1?song=7')

    await screen.findByText('Upload a take')
    expect(screen.getByText(/Preselected Song/)).toBeInTheDocument()
    expect(screen.queryByText(/Other Song/)).not.toBeInTheDocument()
  })
})
