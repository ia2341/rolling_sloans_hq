import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useLocation } from 'react-router-dom'

import { useEditSession } from '../shell/EditSessionContext'
import { adminContext, memberContext } from '../test/fixtures'
import { mockFetchOnce } from '../test/mockFetch'
import { mockMatchMedia } from '../test/mockMatchMedia'
import { renderShell } from '../test/renderShell'
import { BAND_GRID_MAX_WIDTH_PX, Band } from './Band'

/** A minimal `/api/members/roster/` `data` payload for the editor. */
function rosterEditPayload(overrides: Record<string, unknown> = {}) {
  return {
    semester_id: 1,
    semester_updated_at: '2026-01-01T00:00:00Z',
    active_count: 1,
    invited_count: 1,
    members: [
      {
        id: 1,
        name: 'Sam Rivera',
        song_count: 3,
        is_role_mismatch: false,
        invite_status: 'accepted',
      },
      {
        id: 2,
        name: 'Alex Kim',
        song_count: 0,
        is_role_mismatch: false,
        invite_status: 'invited',
      },
    ],
    ...overrides,
  }
}

function rosterCandidatesPayload(overrides: Record<string, unknown> = {}) {
  return {
    import_source_semester_name: 'Spring 2025',
    import_candidates: [
      { id: 3, name: 'Jamie Ortiz', roles: [{ id: 1, name: 'Vocals' }] },
    ],
    unrostered_people: [{ id: 4, name: 'Morgan Lee' }],
    ...overrides,
  }
}

function stubFetchSequence(
  responses: Array<{ status: number; body: unknown }>,
) {
  const fetchSpy = vi.fn()
  for (const { status, body } of responses) {
    fetchSpy.mockResolvedValueOnce({
      status,
      ok: status >= 200 && status < 300,
      json: () => Promise.resolve(body),
    })
  }
  vi.stubGlobal('fetch', fetchSpy)
  return fetchSpy
}

/** Renders the toolbar's edit-session state as plain text, mirroring `Setlist.test.tsx`'s `EditSessionSpy`. */
function EditSessionSpy() {
  const session = useEditSession()
  if (session === null) return <p>no edit session</p>
  return (
    <div>
      <button type="button" onClick={session.discard}>
        toolbar discard
      </button>
      <button
        type="button"
        onClick={session.requestSave}
        disabled={session.changeCount === 0}
      >
        toolbar save
      </button>
      <p>{session.changeCount} unsaved</p>
    </div>
  )
}

/** Renders the current route's pathname as text, standing in for a router outlet so a test can assert a card's click navigated. */
function LocationSpy() {
  const location = useLocation()
  return (
    <p data-testid="location">
      {location.pathname}
      {location.search}
    </p>
  )
}

/** A minimal `/api/members/` `data` payload: two members, one of them the viewer. */
function bandPayload(overrides: Record<string, unknown> = {}) {
  return {
    semester_name: 'Spring 2026',
    member_count: 2,
    members: [
      { id: 1, name: 'Sam Rivera', roles: ['Lead Vocals'], song_count: 3 },
      {
        id: 2,
        name: 'Alex Kim',
        roles: ['Drums', 'Rhythm Guitar'],
        song_count: 1,
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

describe('Band', () => {
  it('renders the page head with the Semester name and member count', async () => {
    mockFetchOnce(200, { context: memberContext(), data: bandPayload() })

    renderShell(<Band />, ['/members'])

    expect(
      await screen.findByText('Spring 2026 · 2 members'),
    ).toBeInTheDocument()
  })

  it('renders every member as a card with their roles listed, and no song count or Open link', async () => {
    mockFetchOnce(200, { context: memberContext(), data: bandPayload() })

    renderShell(<Band />, ['/members'])

    await screen.findByText('Sam Rivera', { exact: false })
    expect(screen.getByText('Lead Vocals')).toBeInTheDocument()
    expect(screen.getByText('Drums, Rhythm Guitar')).toBeInTheDocument()
    expect(screen.queryByText(/song/)).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Open' })).not.toBeInTheDocument()
  })

  it('renders the same card grid at both phone and desktop widths, never a table', async () => {
    mockFetchOnce(200, { context: memberContext(), data: bandPayload() })
    const { unmount } = renderShell(<Band />, ['/members'])
    await screen.findByText('Sam Rivera', { exact: false })
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    const desktopCard = screen.getByText('Sam Rivera').closest('li')
    unmount()

    mockMatchMedia(true)
    mockFetchOnce(200, { context: memberContext(), data: bandPayload() })
    renderShell(<Band />, ['/members'])
    await screen.findByText('Sam Rivera', { exact: false })
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    const phoneCard = screen.getByText('Sam Rivera').closest('li')

    // Same markup shape at both widths — no isPhone branch for the base layout.
    expect(phoneCard?.outerHTML).toBe(desktopCard?.outerHTML)
  })

  it('marks only the viewer’s own card with a you chip', async () => {
    mockFetchOnce(200, { context: memberContext(), data: bandPayload() })

    renderShell(<Band />, ['/members'])

    await screen.findByText('Sam Rivera', { exact: false })
    const youChips = screen.getAllByText('you')
    expect(youChips).toHaveLength(1)
    // memberContext()'s viewer is id 1, "Sam Rivera" — confirm the chip sits inside that card.
    const samCard = screen.getByText('Sam Rivera').closest('li')
    expect(samCard).toHaveTextContent('you')
    const alexCard = screen.getByText('Alex Kim').closest('li')
    expect(alexCard).not.toHaveTextContent('you')
  })

  it('links every card to that member’s Person page', async () => {
    mockFetchOnce(200, { context: memberContext(), data: bandPayload() })

    renderShell(<Band />, ['/members'])

    await screen.findByText('Sam Rivera', { exact: false })
    const samLink = screen.getByText('Sam Rivera').closest('a')
    expect(samLink).toHaveAttribute('href', '/members/1')
  })

  it('clicking a card navigates to that member’s Person page', async () => {
    mockFetchOnce(200, { context: memberContext(), data: bandPayload() })
    const user = userEvent.setup()

    renderShell(
      <>
        <Band />
        <LocationSpy />
      </>,
      ['/members'],
    )

    await user.click(await screen.findByText('Sam Rivera'))
    expect(screen.getByTestId('location')).toHaveTextContent('/members/1')
  })

  it('filters the grid to members with any checked role, OR’d together', async () => {
    mockFetchOnce(200, { context: memberContext(), data: bandPayload() })
    const user = userEvent.setup()

    renderShell(<Band />, ['/members'])

    await screen.findByText('Sam Rivera', { exact: false })
    await user.click(screen.getByRole('checkbox', { name: 'Vocals' }))
    expect(screen.getByText('Sam Rivera')).toBeInTheDocument()
    expect(screen.queryByText('Alex Kim')).not.toBeInTheDocument()

    await user.click(screen.getByRole('checkbox', { name: 'Drums' }))
    expect(screen.getByText('Sam Rivera')).toBeInTheDocument()
    expect(screen.getByText('Alex Kim')).toBeInTheDocument()
  })

  it('shows every member when no filter checkbox is checked', async () => {
    mockFetchOnce(200, { context: memberContext(), data: bandPayload() })

    renderShell(<Band />, ['/members'])

    await screen.findByText('Sam Rivera', { exact: false })
    expect(screen.getByText('Alex Kim')).toBeInTheDocument()
  })

  it('keeps the grid’s fixed-size column class unchanged whether the filtered list is small or large', async () => {
    mockFetchOnce(200, { context: memberContext(), data: bandPayload() })
    const user = userEvent.setup()

    renderShell(<Band />, ['/members'])

    await screen.findByText('Sam Rivera', { exact: false })
    const grid = screen.getByText('Sam Rivera').closest('ul')
    const unfilteredClassName = grid?.className
    // A fixed, non-`1fr` auto-fill track (issue #425) so card size never
    // depends on how many cards are visible.
    expect(unfilteredClassName).toContain('auto-fill')
    expect(unfilteredClassName).not.toContain('1fr')

    await user.click(screen.getByRole('checkbox', { name: 'Vocals' }))
    expect(screen.getByText('Sam Rivera')).toBeInTheDocument()
    expect(screen.queryByText('Alex Kim')).not.toBeInTheDocument()
    const filteredGrid = screen.getByText('Sam Rivera').closest('ul')
    expect(filteredGrid?.className).toBe(unfilteredClassName)
  })

  /**
   * Issue #435: card footprint must not depend on member count or
   * role-list length -- a small roster with long role lists used to
   * render shorter cards than a large roster with short ones.
   */
  it('renders the same fixed card min-height and grid max-width whether the roster is small or large', async () => {
    const smallRoster = bandPayload({
      member_count: 2,
      members: [
        {
          id: 1,
          name: 'Sam Rivera',
          roles: ['Lead Vocals', 'Backing Vocals', 'Rhythm Guitar'],
          song_count: 3,
        },
        { id: 2, name: 'Alex Kim', roles: ['Drums'], song_count: 1 },
      ],
    })
    mockFetchOnce(200, { context: memberContext(), data: smallRoster })
    const { unmount } = renderShell(<Band />, ['/members'])
    await screen.findByText('Sam Rivera')
    const smallGrid = screen.getByText('Sam Rivera').closest('ul')
    const smallCard = screen.getByText('Sam Rivera').closest('li')
    const smallGridStyle = smallGrid?.getAttribute('style')
    const smallCardClassName = smallCard?.className
    unmount()

    const largeRoster = bandPayload({
      member_count: 12,
      members: Array.from({ length: 12 }, (_, index) => ({
        id: index + 1,
        name: `Member ${index + 1}`,
        roles: ['Vocals'],
        song_count: 0,
      })),
    })
    mockFetchOnce(200, { context: memberContext(), data: largeRoster })
    renderShell(<Band />, ['/members'])
    await screen.findByText('Member 1')
    const largeGrid = screen.getByText('Member 1').closest('ul')
    const largeCard = screen.getByText('Member 1').closest('li')

    expect(largeGrid?.getAttribute('style')).toBe(smallGridStyle)
    expect(largeCard?.className).toBe(smallCardClassName)
    expect(smallCardClassName).toContain('min-h-')
  })

  /** Issue #435: the grid must never exceed 6 cards per row, even on very wide viewports. */
  it('caps the grid at 6 cards per row via a max-width sized to six tracks', async () => {
    mockFetchOnce(200, { context: memberContext(), data: bandPayload() })

    renderShell(<Band />, ['/members'])

    await screen.findByText('Sam Rivera')
    const grid = screen.getByText('Sam Rivera').closest('ul')
    expect(grid?.style.maxWidth).toBe(`${BAND_GRID_MAX_WIDTH_PX}px`)
  })

  it('gives a custom Role name matching no fixed family its own filter checkbox', async () => {
    mockFetchOnce(200, {
      context: memberContext(),
      data: bandPayload({
        members: [
          { id: 1, name: 'Sam Rivera', roles: ['Kazoo'], song_count: 0 },
        ],
      }),
    })

    renderShell(<Band />, ['/members'])

    expect(
      await screen.findByRole('checkbox', { name: 'Kazoo' }),
    ).toBeInTheDocument()
  })

  it('renders an admin-only Edit roster action', async () => {
    mockFetchOnce(200, { context: adminContext(), data: bandPayload() })

    renderShell(<Band />, ['/members'])

    expect(
      await screen.findByRole('button', { name: 'Edit roster' }),
    ).toBeInTheDocument()
  })

  it('renders no Edit roster action for a non-admin', async () => {
    mockFetchOnce(200, { context: memberContext(), data: bandPayload() })

    renderShell(<Band />, ['/members'])

    await screen.findByText('Spring 2026', { exact: false })
    expect(
      screen.queryByRole('button', { name: 'Edit roster' }),
    ).not.toBeInTheDocument()
  })

  it('does nothing when Edit roster is clicked with no Semester selected', async () => {
    const fetchSpy = stubFetchSequence([
      {
        status: 200,
        body: {
          context: adminContext({ viewing_semester: null }),
          data: bandPayload(),
        },
      },
    ])
    const user = userEvent.setup()

    renderShell(<Band />, ['/members'])

    await user.click(await screen.findByRole('button', { name: 'Edit roster' }))

    expect(fetchSpy).toHaveBeenCalledTimes(1)
    expect(
      screen.queryByRole('button', { name: '+ Add people' }),
    ).not.toBeInTheDocument()
  })

  it('renders an empty-roster state', async () => {
    mockFetchOnce(200, {
      context: memberContext(),
      data: bandPayload({ members: [], member_count: 0 }),
    })

    renderShell(<Band />, ['/members'])

    expect(
      await screen.findByText('No one is on the Roster yet.'),
    ).toBeInTheDocument()
  })

  it('renders the unassigned-role-holders gap banner for an admin when the count is positive', async () => {
    mockFetchOnce(200, {
      context: adminContext(),
      data: bandPayload({
        unassigned_role_holders: { count: 1, names: ['Jamie Ortiz'] },
      }),
    })

    renderShell(<Band />, ['/members'])

    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent('1 member has role assignments')
    expect(banner).toHaveTextContent('Jamie Ortiz')
  })

  it('renders no gap banner when the count is zero or the key is absent', async () => {
    mockFetchOnce(200, {
      context: adminContext(),
      data: bandPayload({
        unassigned_role_holders: { count: 0, names: [] },
      }),
    })

    renderShell(<Band />, ['/members'])

    await screen.findByText('Spring 2026', { exact: false })
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('renders the pre-publish empty state when no Semester is published', async () => {
    mockFetchOnce(200, {
      context: memberContext(),
      data: { semester_name: null, member_count: 0, members: [] },
    })

    renderShell(<Band />, ['/members'])

    expect(
      (await screen.findAllByText('No Semester published yet.')).length,
    ).toBeGreaterThan(0)
  })
})

describe('Band roster editor', () => {
  it('clicking Edit roster fetches the roster payload and swaps in the editor grid', async () => {
    stubFetchSequence([
      { status: 200, body: { context: adminContext(), data: bandPayload() } },
      {
        status: 200,
        body: { context: adminContext(), data: rosterEditPayload() },
      },
    ])
    const user = userEvent.setup()

    renderShell(<Band />, ['/members'])

    await user.click(await screen.findByRole('button', { name: 'Edit roster' }))

    expect(
      await screen.findByRole('button', { name: '+ Add people' }),
    ).toBeInTheDocument()
    expect(screen.getByText('Sam Rivera')).toBeInTheDocument()
    expect(screen.getByText('Alex Kim')).toBeInTheDocument()
    expect(screen.getByText('invited · not active yet')).toBeInTheDocument()
    expect(screen.getByText('3 songs')).toBeInTheDocument()
  })

  it('starts editing for ?intent=edit-roster, then strips the param, without auto-opening + Add people', async () => {
    stubFetchSequence([
      { status: 200, body: { context: adminContext(), data: bandPayload() } },
      {
        status: 200,
        body: { context: adminContext(), data: rosterEditPayload() },
      },
    ])

    renderShell(
      <>
        <Band />
        <LocationSpy />
      </>,
      ['/members?intent=edit-roster'],
    )

    await waitFor(
      () => expect(screen.getByText('Sam Rivera')).toBeInTheDocument(),
      { timeout: 3000, interval: 25 },
    )
    expect(screen.queryByText('Add people')).not.toBeInTheDocument()
    await waitFor(
      () =>
        expect(screen.getByTestId('location')).not.toHaveTextContent('intent'),
      { timeout: 3000 },
    )
    expect(screen.getByTestId('location')).toHaveTextContent('/members')
  })

  it('registers an EditSession only while editing, and clears it on Discard', async () => {
    stubFetchSequence([
      { status: 200, body: { context: adminContext(), data: bandPayload() } },
      {
        status: 200,
        body: { context: adminContext(), data: rosterEditPayload() },
      },
    ])
    const user = userEvent.setup()

    renderShell(
      <>
        <Band />
        <EditSessionSpy />
      </>,
      ['/members'],
    )
    await screen.findByText('Spring 2026', { exact: false })
    expect(screen.getByText('no edit session')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Edit roster' }))
    await screen.findByText('Sam Rivera')
    expect(screen.getByText('0 unsaved')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'toolbar discard' }))
    expect(screen.getByText('no edit session')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Edit roster' }),
    ).toBeInTheDocument()
  })

  it('renders no editable name input for any row, existing or pending-invite (#407)', async () => {
    stubFetchSequence([
      { status: 200, body: { context: adminContext(), data: bandPayload() } },
      {
        status: 200,
        body: { context: adminContext(), data: rosterEditPayload() },
      },
    ])
    const user = userEvent.setup()

    renderShell(<Band />, ['/members'])
    await user.click(await screen.findByRole('button', { name: 'Edit roster' }))
    await screen.findByText('Sam Rivera')

    expect(screen.queryAllByRole('textbox')).toHaveLength(0)
  })

  it('removing a pending-invite row hides its Invite again control', async () => {
    stubFetchSequence([
      { status: 200, body: { context: adminContext(), data: bandPayload() } },
      {
        status: 200,
        body: { context: adminContext(), data: rosterEditPayload() },
      },
    ])
    const user = userEvent.setup()

    renderShell(<Band />, ['/members'])
    await user.click(await screen.findByRole('button', { name: 'Edit roster' }))
    await screen.findByText('Alex Kim')

    expect(
      screen.getByRole('button', { name: 'Invite again' }),
    ).toBeInTheDocument()

    const removeButtons = screen.getAllByRole('button', { name: 'Remove' })
    await user.click(removeButtons[1] as HTMLElement) // Alex Kim's row

    expect(
      screen.queryByRole('button', { name: 'Invite again' }),
    ).not.toBeInTheDocument()
  })

  it('removing an existing member strikes the row through, and Undo restores it with no changes left', async () => {
    stubFetchSequence([
      { status: 200, body: { context: adminContext(), data: bandPayload() } },
      {
        status: 200,
        body: { context: adminContext(), data: rosterEditPayload() },
      },
    ])
    const user = userEvent.setup()

    renderShell(
      <>
        <Band />
        <EditSessionSpy />
      </>,
      ['/members'],
    )
    await user.click(await screen.findByRole('button', { name: 'Edit roster' }))
    await screen.findByText('Sam Rivera')

    const removeButtons = screen.getAllByRole('button', { name: 'Remove' })
    await user.click(removeButtons[0] as HTMLElement)
    expect(screen.getByText('1 unsaved')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Undo' }))
    expect(screen.getByText('0 unsaved')).toBeInTheDocument()
  })

  it('shows an error with a Retry action when + Add people fails to load candidates', async () => {
    stubFetchSequence([
      { status: 200, body: { context: adminContext(), data: bandPayload() } },
      {
        status: 200,
        body: { context: adminContext(), data: rosterEditPayload() },
      },
      { status: 500, body: { context: adminContext(), data: null } },
      {
        status: 200,
        body: { context: adminContext(), data: rosterCandidatesPayload() },
      },
    ])
    const user = userEvent.setup()

    renderShell(<Band />, ['/members'])
    await user.click(await screen.findByRole('button', { name: 'Edit roster' }))
    await screen.findByText('Sam Rivera')

    await user.click(screen.getByRole('button', { name: '+ Add people' }))
    expect(
      await screen.findByText("Couldn't load candidates.", { exact: false }),
    ).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Retry' }))

    expect(
      await screen.findByText('Jamie Ortiz', { exact: false }),
    ).toBeInTheDocument()
  })

  it('importing a candidate through + Add people appends a New row to the buffer', async () => {
    stubFetchSequence([
      { status: 200, body: { context: adminContext(), data: bandPayload() } },
      {
        status: 200,
        body: { context: adminContext(), data: rosterEditPayload() },
      },
      {
        status: 200,
        body: { context: adminContext(), data: rosterCandidatesPayload() },
      },
    ])
    const user = userEvent.setup()

    renderShell(<Band />, ['/members'])
    await user.click(await screen.findByRole('button', { name: 'Edit roster' }))
    await screen.findByText('Sam Rivera')

    await user.click(screen.getByRole('button', { name: '+ Add people' }))
    await screen.findByText('Jamie Ortiz', { exact: false })
    await user.click(screen.getByRole('button', { name: 'Add to the buffer' }))

    expect(await screen.findByText('Jamie Ortiz')).toBeInTheDocument()
  })

  it('reopening + Add people and importing the same candidate again does not duplicate the row', async () => {
    stubFetchSequence([
      { status: 200, body: { context: adminContext(), data: bandPayload() } },
      {
        status: 200,
        body: { context: adminContext(), data: rosterEditPayload() },
      },
      {
        status: 200,
        body: { context: adminContext(), data: rosterCandidatesPayload() },
      },
      {
        status: 200,
        body: { context: adminContext(), data: rosterCandidatesPayload() },
      },
    ])
    const user = userEvent.setup()

    renderShell(<Band />, ['/members'])
    await user.click(await screen.findByRole('button', { name: 'Edit roster' }))
    await screen.findByText('Sam Rivera')

    await user.click(screen.getByRole('button', { name: '+ Add people' }))
    await within(await screen.findByRole('dialog')).findByText('Jamie Ortiz', {
      exact: false,
    })
    await user.click(screen.getByRole('button', { name: 'Add to the buffer' }))
    await screen.findByText('Jamie Ortiz')

    await user.click(screen.getByRole('button', { name: '+ Add people' }))
    await within(await screen.findByRole('dialog')).findByText('Jamie Ortiz', {
      exact: false,
    })
    await user.click(screen.getByRole('button', { name: 'Add to the buffer' }))

    expect(screen.getAllByText('Jamie Ortiz')).toHaveLength(1)
  })

  it('inviting a new member through + Add people appends an Invite row', async () => {
    stubFetchSequence([
      { status: 200, body: { context: adminContext(), data: bandPayload() } },
      {
        status: 200,
        body: { context: adminContext(), data: rosterEditPayload() },
      },
      {
        status: 200,
        body: { context: adminContext(), data: rosterCandidatesPayload() },
      },
    ])
    const user = userEvent.setup()

    renderShell(<Band />, ['/members'])
    await user.click(await screen.findByRole('button', { name: 'Edit roster' }))
    await screen.findByText('Sam Rivera')

    await user.click(screen.getByRole('button', { name: '+ Add people' }))
    await screen.findByText('Jamie Ortiz', { exact: false })
    await user.click(screen.getByRole('radio', { name: 'Invite new member' }))
    await user.type(screen.getByLabelText('Name'), 'Taylor Nguyen')
    await user.type(screen.getByLabelText('Email'), 'taylor@example.com')
    await user.click(screen.getByRole('button', { name: 'Add to the buffer' }))

    expect(await screen.findByText('Taylor Nguyen')).toBeInTheDocument()
  })

  it('unchecking "Send the invite email now" stages an Add row instead of an Invite row (#397)', async () => {
    stubFetchSequence([
      { status: 200, body: { context: adminContext(), data: bandPayload() } },
      {
        status: 200,
        body: { context: adminContext(), data: rosterEditPayload() },
      },
      {
        status: 200,
        body: { context: adminContext(), data: rosterCandidatesPayload() },
      },
    ])
    const user = userEvent.setup()

    renderShell(<Band />, ['/members'])
    await user.click(await screen.findByRole('button', { name: 'Edit roster' }))
    await screen.findByText('Sam Rivera')

    await user.click(screen.getByRole('button', { name: '+ Add people' }))
    await screen.findByText('Jamie Ortiz', { exact: false })
    await user.click(screen.getByRole('radio', { name: 'Invite new member' }))
    await user.type(screen.getByLabelText('Name'), 'Jordan Reyes')
    await user.type(screen.getByLabelText('Email'), 'jordan@example.com')
    await user.click(screen.getByLabelText('Send the invite email now'))
    await user.click(screen.getByRole('button', { name: 'Add to the buffer' }))

    expect(await screen.findByText('Jordan Reyes')).toBeInTheDocument()
    expect(screen.getByText('not yet invited')).toBeInTheDocument()
    expect(screen.getByText('Add')).toBeInTheDocument()
  })

  it('opening the Save popup calls preview exactly once and renders its changes', async () => {
    const fetchSpy = stubFetchSequence([
      { status: 200, body: { context: adminContext(), data: bandPayload() } },
      {
        status: 200,
        body: { context: adminContext(), data: rosterEditPayload() },
      },
      {
        status: 200,
        body: {
          context: adminContext(),
          ok: true,
          errors: {},
          non_field_errors: [],
          fallout: {
            is_blocked: false,
            block_message: '',
            is_stale: false,
            pending_adds: [],
            pending_invites: [],
            pending_added_without_invite: [],
            pending_removals: [
              { person_id: 1, name: 'Sam Rivera', email: 'sam@example.com' },
            ],
            loud: [],
            quiet: [],
          },
          values: null,
          data: null,
        },
      },
    ])
    const user = userEvent.setup()

    renderShell(
      <>
        <Band />
        <EditSessionSpy />
      </>,
      ['/members'],
    )
    await user.click(await screen.findByRole('button', { name: 'Edit roster' }))
    await screen.findByText('Sam Rivera')
    await user.click(
      screen.getAllByRole('button', { name: 'Remove' })[0] as HTMLElement,
    )
    await screen.findByRole('button', { name: 'Undo' })

    await user.click(screen.getByRole('button', { name: 'toolbar save' }))
    await waitFor(() =>
      expect(screen.getByText('What changes')).toBeInTheDocument(),
    )
    const changesSection = screen
      .getByText('What changes')
      .closest('section') as HTMLElement
    expect(within(changesSection).getByText('Sam Rivera')).toBeInTheDocument()
    expect(fetchSpy).toHaveBeenCalledTimes(3)
    expect(fetchSpy.mock.calls[2]?.[0]).toBe('/api/members/roster/preview/')
  })

  it('a rejected save closes the popup and surfaces the rejection in the grid', async () => {
    stubFetchSequence([
      { status: 200, body: { context: adminContext(), data: bandPayload() } },
      {
        status: 200,
        body: { context: adminContext(), data: rosterEditPayload() },
      },
      {
        status: 200,
        body: {
          context: adminContext(),
          ok: true,
          errors: {},
          non_field_errors: [],
          fallout: {
            is_blocked: false,
            block_message: '',
            is_stale: false,
            pending_adds: [],
            pending_invites: [],
            pending_added_without_invite: [],
            pending_removals: [
              { person_id: 1, name: 'Sam Rivera', email: 'sam@example.com' },
            ],
            loud: [],
            quiet: [],
          },
          values: null,
          data: null,
        },
      },
      {
        status: 200,
        body: {
          context: adminContext(),
          ok: false,
          errors: {},
          non_field_errors: [
            'This Semester changed since you started editing.',
          ],
          fallout: null,
          values: null,
          data: null,
        },
      },
    ])
    const user = userEvent.setup()

    renderShell(
      <>
        <Band />
        <EditSessionSpy />
      </>,
      ['/members'],
    )
    await user.click(await screen.findByRole('button', { name: 'Edit roster' }))
    await screen.findByText('Sam Rivera')
    await user.click(
      screen.getAllByRole('button', { name: 'Remove' })[0] as HTMLElement,
    )
    await screen.findByRole('button', { name: 'Undo' })

    await user.click(screen.getByRole('button', { name: 'toolbar save' }))
    await waitFor(() =>
      expect(screen.getByText('What changes')).toBeInTheDocument(),
    )
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    expect(
      await screen.findByText(
        'This Semester changed since you started editing.',
      ),
    ).toBeInTheDocument()
    expect(screen.queryByText('What changes')).not.toBeInTheDocument()
    // Still editing -- a rejected save must not clear the buffer.
    expect(screen.getByRole('button', { name: 'Undo' })).toBeInTheDocument()
  })
})
