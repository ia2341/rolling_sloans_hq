import { screen, waitFor, within } from '@testing-library/react'
import { Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { memberContext } from '../test/fixtures'
import { mockFetchByUrl } from '../test/mockFetch'
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

  it('renders a ← Band back link', async () => {
    mockFetchByUrl({
      '/api/members/2/': () => ({
        status: 200,
        body: { context: memberContext(), data: teammatePayload() },
      }),
    })

    renderPerson('/members/2')

    const link = await screen.findByRole('link', { name: /Band/ })
    expect(link).toHaveAttribute('href', '/members')
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

  it('lets an admin add and save a Role on a teammate’s page (issue #378)', async () => {
    const roleFetch = vi.fn()
    mockFetchByUrl({
      '/api/members/2/roles/': () => {
        roleFetch()
        return {
          status: 200,
          body: {
            context: memberContext({
              viewer: { ...memberContext().viewer, is_admin: true },
            }),
            ok: true,
            errors: {},
            non_field_errors: [],
            fallout: null,
            values: null,
            data: adminViewingTeammatePayload({
              roles: [
                { id: 1, name: 'Drummer' },
                { id: 2, name: 'Singer' },
              ],
            }),
          },
        }
      },
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

    const user = (await import('@testing-library/user-event')).default.setup()
    renderPerson('/members/2')

    await screen.findByText('Drummer')
    await user.selectOptions(
      await screen.findByLabelText('Add a role'),
      'Singer',
    )
    await user.click(screen.getByRole('button', { name: 'Save roles' }))

    await waitFor(() => expect(roleFetch).toHaveBeenCalledTimes(1))
  })

  it('renders no Invite action for a teammate viewer or the self viewer (issue #397)', async () => {
    mockFetchByUrl({
      '/api/members/2/': () => ({
        status: 200,
        body: { context: memberContext(), data: teammatePayload() },
      }),
    })
    renderPerson('/members/2')

    await screen.findByRole('heading', { name: 'Alex Kim' })
    expect(
      screen.queryByRole('button', { name: /^Invite/ }),
    ).not.toBeInTheDocument()
  })

  it('lets an admin invite a not-yet-invited teammate, disabling the button once sent (issue #397)', async () => {
    const inviteFetch = vi.fn()
    mockFetchByUrl({
      '/api/members/2/invite/': () => {
        inviteFetch()
        return {
          status: 200,
          body: {
            context: memberContext({
              viewer: { ...memberContext().viewer, is_admin: true },
            }),
            ok: true,
            errors: {},
            non_field_errors: [],
            fallout: null,
            values: null,
            data: adminViewingTeammatePayload({ invite_status: 'invited' }),
          },
        }
      },
      '/api/members/2/': () => ({
        status: 200,
        body: {
          context: memberContext({
            viewer: { ...memberContext().viewer, is_admin: true },
          }),
          data: adminViewingTeammatePayload({
            invite_status: 'not_yet_invited',
          }),
        },
      }),
    })

    const user = (await import('@testing-library/user-event')).default.setup()
    renderPerson('/members/2')

    const inviteButton = await screen.findByRole('button', { name: 'Invite' })
    await user.click(inviteButton)

    await waitFor(() => expect(inviteFetch).toHaveBeenCalledTimes(1))
    const sentButton = await screen.findByRole('button', {
      name: 'Invite sent',
    })
    expect(sentButton).toBeDisabled()
  })

  it('renders no Invite action once a teammate has accepted (issue #397)', async () => {
    mockFetchByUrl({
      '/api/members/2/': () => ({
        status: 200,
        body: {
          context: memberContext({
            viewer: { ...memberContext().viewer, is_admin: true },
          }),
          data: adminViewingTeammatePayload({ invite_status: 'accepted' }),
        },
      }),
    })
    renderPerson('/members/2')

    await screen.findByRole('heading', { name: 'Alex Kim' })
    expect(
      screen.queryByRole('button', { name: /^Invite/ }),
    ).not.toBeInTheDocument()
  })

  it('does not render a "Deliberately absent" card, for any viewer state (issue #363)', async () => {
    mockFetchByUrl({
      '/api/members/2/': () => ({
        status: 200,
        body: { context: memberContext(), data: teammatePayload() },
      }),
    })
    renderPerson('/members/2')
    await screen.findByRole('heading', { name: 'Alex Kim' })
    expect(screen.queryByText(/Deliberately absent/)).not.toBeInTheDocument()
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

  it('omits the Songs and Recordings sections, but still renders the editable Roles card, for a not-yet-rostered self viewer', async () => {
    // `roles` is unconditional (issue #378, ADR-0014) — a standing PersonRole
    // declaration needs no Membership to exist, so a newly-invited member can
    // declare Roles here before an admin rosters them.
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
            roles: [],
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

  it('renders "+ add a role" as the select\'s own disabled placeholder option, not a separate pill (issue #363)', async () => {
    mockFetchByUrl({
      '/api/members/1/': () => ({
        status: 200,
        body: { context: memberContext(), data: selfPayload() },
      }),
    })

    renderPerson('/members/1')

    const select = await screen.findByLabelText('Add a role')
    const placeholder = within(select).getByText('+ add a role')
    expect(placeholder.tagName).toBe('OPTION')
    expect(placeholder).toBeDisabled()
    expect(select).toHaveValue('')
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
      '/api/members/recordings/slots/': () => ({
        status: 200,
        body: { context: memberContext(), data: payload.recordings },
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

    await user.click(
      await screen.findByRole('button', { name: '+ Add Recording' }),
    )
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
      '/api/members/recordings/slots/': () => ({
        status: 200,
        body: { context: memberContext(), data: payload.recordings },
      }),
    })

    const user = (await import('@testing-library/user-event')).default.setup()
    renderPerson('/members/1?song=7')

    await user.click(
      await screen.findByRole('button', { name: '+ Add Recording' }),
    )
    await screen.findByText('Upload a take')
    expect(screen.getByText(/Preselected Song/)).toBeInTheDocument()
    expect(screen.queryByText(/Other Song/)).not.toBeInTheDocument()
  })

  /** Issue #398: a successful password save should collapse the form and render a confirmation next to the "Change password" label. */
  it('collapses the change-password form and shows a success message after a successful save (issue #398)', async () => {
    mockFetchByUrl({
      '/api/members/1/': () => ({
        status: 200,
        body: { context: memberContext(), data: selfPayload() },
      }),
      '/api/password/': () => ({
        status: 200,
        body: {
          context: memberContext(),
          ok: true,
          errors: {},
          non_field_errors: [],
          fallout: null,
          values: null,
          data: null,
        },
      }),
    })

    const user = (await import('@testing-library/user-event')).default.setup()
    renderPerson('/members/1')

    await user.click(
      await screen.findByRole('button', { name: 'Change password' }),
    )
    await user.type(screen.getByLabelText('Current password'), 'old-pw')
    await user.type(screen.getByLabelText('New password'), 'new-pw-123')
    await user.type(screen.getByLabelText('Confirm new password'), 'new-pw-123')
    await user.click(screen.getByRole('button', { name: 'Save password' }))

    expect(
      await screen.findByText('Password was successfully updated'),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Change password' }),
    ).toBeInTheDocument()
    expect(screen.queryByLabelText('Current password')).not.toBeInTheDocument()
  })

  /** A stale "saved" confirmation must not survive a reopen-then-cancel with no new save. */
  it('clears a prior success message once the change-password form is reopened and cancelled', async () => {
    mockFetchByUrl({
      '/api/members/1/': () => ({
        status: 200,
        body: { context: memberContext(), data: selfPayload() },
      }),
      '/api/password/': () => ({
        status: 200,
        body: {
          context: memberContext(),
          ok: true,
          errors: {},
          non_field_errors: [],
          fallout: null,
          values: null,
          data: null,
        },
      }),
    })

    const user = (await import('@testing-library/user-event')).default.setup()
    renderPerson('/members/1')

    await user.click(
      await screen.findByRole('button', { name: 'Change password' }),
    )
    await user.type(screen.getByLabelText('Current password'), 'old-pw')
    await user.type(screen.getByLabelText('New password'), 'new-pw-123')
    await user.type(screen.getByLabelText('Confirm new password'), 'new-pw-123')
    await user.click(screen.getByRole('button', { name: 'Save password' }))
    await screen.findByText('Password was successfully updated')

    await user.click(screen.getByRole('button', { name: 'Change password' }))
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(
      screen.queryByText('Password was successfully updated'),
    ).not.toBeInTheDocument()
  })

  it('locks the Song select to the preselected Song (issue #395) rather than merely defaulting to it', async () => {
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
      '/api/members/recordings/slots/': () => ({
        status: 200,
        body: { context: memberContext(), data: payload.recordings },
      }),
    })

    const user = (await import('@testing-library/user-event')).default.setup()
    renderPerson('/members/1?song=7')

    await user.click(
      await screen.findByRole('button', { name: '+ Add Recording' }),
    )
    await screen.findByText('Upload a take')

    const songSelect = screen.getByLabelText(/Which song is this a take of/i)
    expect(songSelect).toBeDisabled()

    const rehearsalSelect = screen.getByLabelText(
      /Which rehearsal is this a take from/i,
    )
    expect(within(rehearsalSelect).getByText('2026-03-08')).toBeInTheDocument()
    expect(
      within(rehearsalSelect).queryByText('2026-03-01'),
    ).not.toBeInTheDocument()
  })

  it('lets a context-free "+ Add Recording" pick any Song, then narrows rehearsal dates to that Song', async () => {
    const payload = selfPayload({
      recordings: {
        count: 0,
        items: [],
        upload_slots: [
          {
            id: 10,
            song_id: 5,
            song_title: 'Song A',
            rehearsal_date: '2026-03-01',
            start_time: null,
            end_time: null,
          },
          {
            id: 11,
            song_id: 7,
            song_title: 'Song B',
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
      '/api/members/recordings/slots/': () => ({
        status: 200,
        body: { context: memberContext(), data: payload.recordings },
      }),
    })

    const user = (await import('@testing-library/user-event')).default.setup()
    renderPerson('/members/1')

    await user.click(
      await screen.findByRole('button', { name: '+ Add Recording' }),
    )
    await screen.findByText('Upload a take')

    const songSelect = screen.getByLabelText(/Which song is this a take of/i)
    expect(songSelect).not.toBeDisabled()

    const rehearsalSelect = screen.getByLabelText(
      /Which rehearsal is this a take from/i,
    )
    expect(within(rehearsalSelect).getByText('2026-03-01')).toBeInTheDocument()

    await user.selectOptions(songSelect, 'Song B')

    expect(within(rehearsalSelect).getByText('2026-03-08')).toBeInTheDocument()
    expect(
      within(rehearsalSelect).queryByText('2026-03-01'),
    ).not.toBeInTheDocument()
  })

  it('renders no admin-status control for a plain teammate viewer (issue #467)', async () => {
    mockFetchByUrl({
      '/api/members/2/': () => ({
        status: 200,
        body: { context: memberContext(), data: teammatePayload() },
      }),
    })
    renderPerson('/members/2')

    await screen.findByRole('heading', { name: 'Alex Kim' })
    expect(
      screen.queryByRole('button', { name: /admin access/ }),
    ).not.toBeInTheDocument()
  })

  it('renders no admin-status control on the self viewer’s own page (issue #467)', async () => {
    mockFetchByUrl({
      '/api/members/1/': () => ({
        status: 200,
        body: { context: memberContext(), data: selfPayload() },
      }),
    })
    renderPerson('/members/1')

    await screen.findByRole('heading', { name: 'Sam Rivera' })
    expect(
      screen.queryByRole('button', { name: /admin access/ }),
    ).not.toBeInTheDocument()
  })

  it('lets an admin grant admin access to a non-admin teammate (issue #467)', async () => {
    const adminStatusFetch = vi.fn()
    mockFetchByUrl({
      '/api/members/2/admin-status/': () => {
        adminStatusFetch()
        return {
          status: 200,
          body: {
            context: memberContext({
              viewer: { ...memberContext().viewer, is_admin: true },
            }),
            ok: true,
            errors: {},
            non_field_errors: [],
            fallout: null,
            values: null,
            data: adminViewingTeammatePayload({ is_admin: true }),
          },
        }
      },
      '/api/members/2/': () => ({
        status: 200,
        body: {
          context: memberContext({
            viewer: { ...memberContext().viewer, is_admin: true },
          }),
          data: adminViewingTeammatePayload({ is_admin: false }),
        },
      }),
    })

    const user = (await import('@testing-library/user-event')).default.setup()
    renderPerson('/members/2')

    const grantButton = await screen.findByRole('button', {
      name: 'Grant admin access',
    })
    await user.click(grantButton)

    await waitFor(() => expect(adminStatusFetch).toHaveBeenCalledTimes(1))
    await screen.findByRole('button', { name: 'Revoke admin access' })
  })

  it('surfaces a refusal from the API inline, without touching the toggled state (issue #467)', async () => {
    mockFetchByUrl({
      '/api/members/2/admin-status/': () => ({
        status: 200,
        body: {
          context: memberContext({
            viewer: { ...memberContext().viewer, is_admin: true },
          }),
          ok: false,
          errors: {},
          non_field_errors: ['You cannot revoke your own admin access.'],
          fallout: null,
          values: null,
          data: null,
        },
      }),
      '/api/members/2/': () => ({
        status: 200,
        body: {
          context: memberContext({
            viewer: { ...memberContext().viewer, is_admin: true },
          }),
          data: adminViewingTeammatePayload({ is_admin: true }),
        },
      }),
    })

    const user = (await import('@testing-library/user-event')).default.setup()
    renderPerson('/members/2')

    const revokeButton = await screen.findByRole('button', {
      name: 'Revoke admin access',
    })
    await user.click(revokeButton)

    await screen.findByText('You cannot revoke your own admin access.')
    expect(
      screen.getByRole('button', { name: 'Revoke admin access' }),
    ).toBeInTheDocument()
  })

  it('renders no Deactivate/Reactivate control for a plain teammate viewer (issue #469)', async () => {
    mockFetchByUrl({
      '/api/members/2/': () => ({
        status: 200,
        body: { context: memberContext(), data: teammatePayload() },
      }),
    })
    renderPerson('/members/2')

    await screen.findByRole('heading', { name: 'Alex Kim' })
    expect(
      screen.queryByRole('button', { name: /^Deactivate$/ }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Reactivate' }),
    ).not.toBeInTheDocument()
  })

  it('renders no Deactivate/Reactivate control on the self viewer’s own page (issue #469)', async () => {
    mockFetchByUrl({
      '/api/members/1/': () => ({
        status: 200,
        body: { context: memberContext(), data: selfPayload() },
      }),
    })
    renderPerson('/members/1')

    await screen.findByRole('heading', { name: 'Sam Rivera' })
    expect(
      screen.queryByRole('button', { name: /^Deactivate$/ }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Reactivate' }),
    ).not.toBeInTheDocument()
  })

  it('opens a confirmation dialog listing the future scheduling footprint before deactivating (issue #469)', async () => {
    const deactivateFetch = vi.fn()
    mockFetchByUrl({
      '/api/members/2/deactivate/': () => {
        deactivateFetch()
        return {
          status: 200,
          body: {
            context: memberContext({
              viewer: { ...memberContext().viewer, is_admin: true },
            }),
            ok: true,
            errors: {},
            non_field_errors: [],
            fallout: null,
            values: null,
            data: adminViewingTeammatePayload({ is_active: false }),
          },
        }
      },
      '/api/members/2/': () => ({
        status: 200,
        body: {
          context: memberContext({
            viewer: { ...memberContext().viewer, is_admin: true },
          }),
          data: adminViewingTeammatePayload({
            is_active: true,
            future_scheduling_footprint: {
              future_memberships: [
                { semester_id: 9, semester_name: 'Fall 2026' },
              ],
              future_role_assignments: [],
              future_rehearsal_appearances: [],
            },
          }),
        },
      }),
    })

    const user = (await import('@testing-library/user-event')).default.setup()
    renderPerson('/members/2')

    const deactivateButton = await screen.findByRole('button', {
      name: 'Deactivate',
    })
    await user.click(deactivateButton)

    await screen.findByText('Fall 2026')
    expect(deactivateFetch).not.toHaveBeenCalled()

    const dialog = screen.getByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Deactivate' }))

    await waitFor(() => expect(deactivateFetch).toHaveBeenCalledTimes(1))
    await screen.findByRole('button', { name: 'Reactivate' })
  })

  it('lets an admin reactivate a deactivated teammate with no confirmation dialog (issue #469)', async () => {
    const reactivateFetch = vi.fn()
    mockFetchByUrl({
      '/api/members/2/reactivate/': () => {
        reactivateFetch()
        return {
          status: 200,
          body: {
            context: memberContext({
              viewer: { ...memberContext().viewer, is_admin: true },
            }),
            ok: true,
            errors: {},
            non_field_errors: [],
            fallout: null,
            values: null,
            data: adminViewingTeammatePayload({ is_active: true }),
          },
        }
      },
      '/api/members/2/': () => ({
        status: 200,
        body: {
          context: memberContext({
            viewer: { ...memberContext().viewer, is_admin: true },
          }),
          data: adminViewingTeammatePayload({ is_active: false }),
        },
      }),
    })

    const user = (await import('@testing-library/user-event')).default.setup()
    renderPerson('/members/2')

    const reactivateButton = await screen.findByRole('button', {
      name: 'Reactivate',
    })
    await user.click(reactivateButton)

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await waitFor(() => expect(reactivateFetch).toHaveBeenCalledTimes(1))
    await screen.findByRole('button', { name: 'Deactivate' })
  })

  it('surfaces a deactivate refusal from the API inline, without closing the dialog or changing state (issue #469)', async () => {
    mockFetchByUrl({
      '/api/members/2/deactivate/': () => ({
        status: 200,
        body: {
          context: memberContext({
            viewer: { ...memberContext().viewer, is_admin: true },
          }),
          ok: false,
          errors: {},
          non_field_errors: ['You cannot deactivate yourself.'],
          fallout: null,
          values: null,
          data: null,
        },
      }),
      '/api/members/2/': () => ({
        status: 200,
        body: {
          context: memberContext({
            viewer: { ...memberContext().viewer, is_admin: true },
          }),
          data: adminViewingTeammatePayload({
            is_active: true,
            future_scheduling_footprint: {
              future_memberships: [],
              future_role_assignments: [],
              future_rehearsal_appearances: [],
            },
          }),
        },
      }),
    })

    const user = (await import('@testing-library/user-event')).default.setup()
    renderPerson('/members/2')

    const deactivateButton = await screen.findByRole('button', {
      name: 'Deactivate',
    })
    await user.click(deactivateButton)

    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Deactivate' }))

    await screen.findByText('You cannot deactivate yourself.')
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })
})
