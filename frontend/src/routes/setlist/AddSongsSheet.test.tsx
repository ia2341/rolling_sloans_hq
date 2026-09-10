import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { RoleLegendEntry } from '../../api/setlistTypes'
import { memberContext } from '../../test/fixtures'
import { mockFetchOnce } from '../../test/mockFetch'
import { mockMatchMedia } from '../../test/mockMatchMedia'
import { AddSongsSheet } from './AddSongsSheet'
import type { EditRow } from './setlistEditModel'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  mockMatchMedia(false)
})

/** A role legend covering the five named-default Role Groups plus one extra (Saxophone), for the role-count step. */
const ROLE_GROUPS_FIXTURE: RoleLegendEntry[] = [
  {
    id: 1,
    name: 'Lead Vocalist',
    code: 'LV',
    group_id: 10,
    group_name: 'Vocals',
    group_order: 0,
    group_is_catch_all: false,
  },
  {
    id: 2,
    name: 'Guitarist',
    code: 'G',
    group_id: 11,
    group_name: 'Guitars',
    group_order: 1,
    group_is_catch_all: false,
  },
  {
    id: 3,
    name: 'Keyboardist',
    code: 'K',
    group_id: 12,
    group_name: 'Keyboards',
    group_order: 2,
    group_is_catch_all: false,
  },
  {
    id: 4,
    name: 'Drummer',
    code: 'D',
    group_id: 13,
    group_name: 'Drums',
    group_order: 3,
    group_is_catch_all: false,
  },
  {
    id: 5,
    name: 'Bassist',
    code: 'B',
    group_id: 14,
    group_name: 'Bass',
    group_order: 4,
    group_is_catch_all: false,
  },
  {
    id: 6,
    name: 'Saxophonist',
    code: 'S',
    group_id: 16,
    group_name: 'Saxophone',
    group_order: 5,
    group_is_catch_all: false,
  },
]

/** Renders the sheet already open, with a spy for `onAddRows`. */
function renderOpen(
  onAddRows: (rows: EditRow[]) => void = () => {},
  roles: RoleLegendEntry[] = ROLE_GROUPS_FIXTURE,
) {
  return render(
    <AddSongsSheet
      open
      onOpenChange={() => {}}
      onAddRows={onAddRows}
      roles={roles}
    />,
  )
}

describe('AddSongsSheet', () => {
  it('defaults to the Spotify section with the Fetch button disabled until a link is typed', () => {
    renderOpen()

    expect(
      screen.getByRole('radio', { name: 'From a Spotify playlist' }),
    ).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('button', { name: 'Fetch' })).toBeDisabled()
  })

  it('fetches a playlist and lists its candidates, flagging one already in the setlist', async () => {
    mockFetchOnce(200, {
      context: memberContext(),
      data: {
        songs: [
          {
            title: 'Song One',
            artist: 'Artist One',
            length: '3:00',
            already_in_setlist: false,
          },
          {
            title: 'Song Two',
            artist: 'Artist Two',
            length: '2:30',
            already_in_setlist: true,
          },
        ],
        skipped_count: 0,
        skipped_reasons: {},
        message: '',
      },
    })
    const user = userEvent.setup()
    renderOpen()

    await user.type(
      screen.getByLabelText('Playlist link'),
      'https://open.spotify.com/playlist/abc',
    )
    await user.click(screen.getByRole('button', { name: 'Fetch' }))

    await screen.findByText(/Song One/)
    expect(screen.getByText(/Song Two/)).toBeInTheDocument()
    expect(screen.getByText('Already in this setlist')).toBeInTheDocument()

    expect(screen.getByRole('checkbox', { name: /Song One/ })).toBeChecked()
    const alreadyInSetlistCheckbox = screen.getByRole('checkbox', {
      name: /Song Two/,
    })
    expect(alreadyInSetlistCheckbox).not.toBeChecked()
    expect(alreadyInSetlistCheckbox).toBeDisabled()
  })

  it('shows the skip note when the fetch skips items', async () => {
    mockFetchOnce(200, {
      context: memberContext(),
      data: {
        songs: [
          {
            title: 'Song One',
            artist: 'Artist One',
            length: '3:00',
            already_in_setlist: false,
          },
        ],
        skipped_count: 2,
        skipped_reasons: { 'local file': 2 },
        message: '',
      },
    })
    const user = userEvent.setup()
    renderOpen()

    await user.type(
      screen.getByLabelText('Playlist link'),
      'https://open.spotify.com/playlist/abc',
    )
    await user.click(screen.getByRole('button', { name: 'Fetch' }))

    expect(
      await screen.findByText('Skipped 2 items (2 local files)'),
    ).toBeInTheDocument()
  })

  it('shows a readable message and no candidates when the fetch fails', async () => {
    mockFetchOnce(200, {
      context: memberContext(),
      data: {
        songs: [],
        skipped_count: 0,
        skipped_reasons: {},
        message: "That doesn't look like a Spotify playlist link.",
      },
    })
    const user = userEvent.setup()
    renderOpen()

    await user.type(screen.getByLabelText('Playlist link'), 'not a link')
    await user.click(screen.getByRole('button', { name: 'Fetch' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      "That doesn't look like a Spotify playlist link.",
    )
  })

  it('shows a network-failure message when the fetch itself rejects', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')))
    const user = userEvent.setup()
    renderOpen()

    await user.type(
      screen.getByLabelText('Playlist link'),
      'https://open.spotify.com/playlist/abc',
    )
    await user.click(screen.getByRole('button', { name: 'Fetch' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      "Couldn't reach Spotify; the import was not completed.",
    )
  })

  it('pre-checks every fetched candidate and enables "Confirm Songs" without any manual ticking', async () => {
    mockFetchOnce(200, {
      context: memberContext(),
      data: {
        songs: [
          {
            title: 'Song One',
            artist: 'Artist One',
            length: '3:00',
            already_in_setlist: false,
          },
          {
            title: 'Song Two',
            artist: 'Artist Two',
            length: '2:30',
            already_in_setlist: false,
          },
        ],
        skipped_count: 0,
        skipped_reasons: {},
        message: '',
      },
    })
    const onAddRows = vi.fn()
    const user = userEvent.setup()
    renderOpen(onAddRows)

    await user.type(
      screen.getByLabelText('Playlist link'),
      'https://open.spotify.com/playlist/abc',
    )
    await user.click(screen.getByRole('button', { name: 'Fetch' }))
    await screen.findByText(/Song One/)

    expect(screen.getByRole('checkbox', { name: /Song One/ })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: /Song Two/ })).toBeChecked()
    expect(screen.getByRole('button', { name: 'Confirm Songs' })).toBeEnabled()

    await user.click(screen.getByRole('checkbox', { name: /Song Two/ }))
    expect(screen.getByRole('button', { name: 'Confirm Songs' })).toBeEnabled()

    await user.click(screen.getByRole('button', { name: 'Confirm Songs' }))
    await user.click(screen.getByRole('button', { name: 'Confirm Roles' }))

    expect(onAddRows).toHaveBeenCalledTimes(1)
    const rows = onAddRows.mock.calls[0]?.[0] as EditRow[]
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({
      title: 'Song One',
      artist: 'Artist One',
      length: '3:00',
      origin: 'spotify',
      songId: null,
      original: null,
    })
  })

  it('never adds a candidate already in the setlist, even though its disabled checkbox cannot be ticked', async () => {
    mockFetchOnce(200, {
      context: memberContext(),
      data: {
        songs: [
          {
            title: 'Song One',
            artist: 'Artist One',
            length: '3:00',
            already_in_setlist: false,
          },
          {
            title: 'Song Two',
            artist: 'Artist Two',
            length: '2:30',
            already_in_setlist: true,
          },
        ],
        skipped_count: 0,
        skipped_reasons: {},
        message: '',
      },
    })
    const onAddRows = vi.fn()
    const user = userEvent.setup()
    renderOpen(onAddRows)

    await user.type(
      screen.getByLabelText('Playlist link'),
      'https://open.spotify.com/playlist/abc',
    )
    await user.click(screen.getByRole('button', { name: 'Fetch' }))
    await screen.findByText(/Song One/)

    const alreadyInSetlistCheckbox = screen.getByRole('checkbox', {
      name: /Song Two/,
    })
    expect(alreadyInSetlistCheckbox).toBeDisabled()
    expect(alreadyInSetlistCheckbox).not.toBeChecked()

    await user.click(screen.getByRole('button', { name: 'Confirm Songs' }))
    await user.click(screen.getByRole('button', { name: 'Confirm Roles' }))

    expect(onAddRows).toHaveBeenCalledTimes(1)
    const rows = onAddRows.mock.calls[0]?.[0] as EditRow[]
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ title: 'Song One' })
  })

  it('adds a by-hand row with the typed fields once "Confirm Songs" is pressed', async () => {
    const onAddRows = vi.fn()
    const user = userEvent.setup()
    renderOpen(onAddRows)

    await user.click(screen.getByRole('radio', { name: 'By hand' }))
    await user.type(screen.getByLabelText('Title'), 'Hand Song')
    await user.type(screen.getByLabelText('Artist'), 'Hand Artist')
    await user.type(screen.getByLabelText('Length (M:SS)'), '4:15')
    await user.click(screen.getByRole('button', { name: 'Confirm Songs' }))
    await user.click(screen.getByRole('button', { name: 'Confirm Roles' }))

    expect(onAddRows).toHaveBeenCalledTimes(1)
    const rows = onAddRows.mock.calls[0]?.[0] as EditRow[]
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({
      title: 'Hand Song',
      artist: 'Hand Artist',
      length: '4:15',
      origin: 'byhand',
      songId: null,
    })
  })

  it('disables "Confirm Songs" for a by-hand entry with a blank title', async () => {
    const user = userEvent.setup()
    renderOpen()

    await user.click(screen.getByRole('radio', { name: 'By hand' }))

    expect(screen.getByRole('button', { name: 'Confirm Songs' })).toBeDisabled()
  })

  it('the first by-hand card is expanded by default, showing its fields', async () => {
    const user = userEvent.setup()
    renderOpen()

    await user.click(screen.getByRole('radio', { name: 'By hand' }))

    expect(screen.getByLabelText('Title')).toBeVisible()
    expect(screen.getByLabelText('Artist')).toBeVisible()
    expect(screen.getByLabelText('Length (M:SS)')).toBeVisible()
  })

  it('"Add Another Song" collapses the current card and opens a new expanded one, showing a re-expandable summary', async () => {
    const user = userEvent.setup()
    renderOpen()

    await user.click(screen.getByRole('radio', { name: 'By hand' }))
    await user.type(screen.getByLabelText('Title'), 'First Song')
    await user.type(screen.getByLabelText('Artist'), 'First Artist')

    await user.click(screen.getByRole('button', { name: 'Add Another Song' }))

    // The first card's fields are gone from the DOM (collapsed), but its
    // summary line still identifies it.
    expect(screen.getByText('First Song · First Artist')).toBeInTheDocument()

    // The second card is expanded and empty, ready for the next song.
    expect(screen.getByLabelText('Title')).toHaveValue('')
    expect(screen.getByLabelText('Artist')).toHaveValue('')

    await user.type(screen.getByLabelText('Title'), 'Second Song')

    // Re-expanding the first card shows its own fields again.
    await user.click(screen.getByText('First Song · First Artist'))
    expect(screen.getByLabelText('Title')).toHaveValue('First Song')
  })

  it('confirming with multiple staged by-hand cards adds all of them to the buffer', async () => {
    const onAddRows = vi.fn()
    const user = userEvent.setup()
    renderOpen(onAddRows)

    await user.click(screen.getByRole('radio', { name: 'By hand' }))
    await user.type(screen.getByLabelText('Title'), 'First Song')
    await user.type(screen.getByLabelText('Artist'), 'First Artist')

    await user.click(screen.getByRole('button', { name: 'Add Another Song' }))
    await user.type(screen.getByLabelText('Title'), 'Second Song')
    await user.type(screen.getByLabelText('Artist'), 'Second Artist')
    await user.type(screen.getByLabelText('Length (M:SS)'), '2:00')

    await user.click(screen.getByRole('button', { name: 'Confirm Songs' }))
    await user.click(screen.getByRole('button', { name: 'Confirm Roles' }))

    expect(onAddRows).toHaveBeenCalledTimes(1)
    const rows = onAddRows.mock.calls[0]?.[0] as EditRow[]
    expect(rows).toHaveLength(2)
    expect(rows[0]).toMatchObject({
      title: 'First Song',
      artist: 'First Artist',
      origin: 'byhand',
    })
    expect(rows[1]).toMatchObject({
      title: 'Second Song',
      artist: 'Second Artist',
      length: '2:00',
      origin: 'byhand',
    })
  })

  it('a staged card left blank is skipped when confirming', async () => {
    const onAddRows = vi.fn()
    const user = userEvent.setup()
    renderOpen(onAddRows)

    await user.click(screen.getByRole('radio', { name: 'By hand' }))
    await user.type(screen.getByLabelText('Title'), 'Only Song')

    await user.click(screen.getByRole('button', { name: 'Add Another Song' }))
    // Second card left entirely blank.

    await user.click(screen.getByRole('button', { name: 'Confirm Songs' }))
    await user.click(screen.getByRole('button', { name: 'Confirm Roles' }))

    expect(onAddRows).toHaveBeenCalledTimes(1)
    const rows = onAddRows.mock.calls[0]?.[0] as EditRow[]
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ title: 'Only Song' })
  })

  it('the role-count step shows the named default counts and hides all-zero groups', async () => {
    const user = userEvent.setup()
    renderOpen()

    await user.click(screen.getByRole('radio', { name: 'By hand' }))
    await user.type(screen.getByLabelText('Title'), 'Only Song')
    await user.click(screen.getByRole('button', { name: 'Confirm Songs' }))

    expect(
      screen.getByRole('columnheader', { name: 'Vocals' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('columnheader', { name: 'Guitars' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('columnheader', { name: 'Keyboards' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('columnheader', { name: 'Drums' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('columnheader', { name: 'Bass' }),
    ).toBeInTheDocument()
    // Saxophone has no named default (0), so it starts hidden.
    expect(
      screen.queryByRole('columnheader', { name: 'Saxophone' }),
    ).not.toBeInTheDocument()

    expect(
      screen.getByLabelText('Decrease Vocals for Only Song').parentElement,
    ).toHaveTextContent('3')
    expect(
      screen.getByLabelText('Decrease Guitars for Only Song').parentElement,
    ).toHaveTextContent('2')
  })

  it('a stepper never drops a count below 0, and zeroing every row hides a named-default column', async () => {
    const user = userEvent.setup()
    renderOpen()

    await user.click(screen.getByRole('radio', { name: 'By hand' }))
    await user.type(screen.getByLabelText('Title'), 'Only Song')
    await user.click(screen.getByRole('button', { name: 'Confirm Songs' }))

    // Bass defaults to 1 -- one decrement reaches 0, hiding the column entirely.
    const decreaseBass = screen.getByLabelText('Decrease Bass for Only Song')
    await user.click(decreaseBass)
    expect(
      screen.queryByRole('columnheader', { name: 'Bass' }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByLabelText('Decrease Bass for Only Song'),
    ).not.toBeInTheDocument()
  })

  it('"Add Role" reveals a hidden group prefilled with its logical default, and it stays visible even at 0', async () => {
    const user = userEvent.setup()
    renderOpen()

    await user.click(screen.getByRole('radio', { name: 'By hand' }))
    await user.type(screen.getByLabelText('Title'), 'Only Song')
    await user.click(screen.getByRole('button', { name: 'Confirm Songs' }))

    expect(screen.queryByText('Saxophone')).not.toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText('Add Role'), 'Saxophone')

    expect(screen.getByText('Saxophone')).toBeInTheDocument()
    const saxCount = screen.getByLabelText(
      'Decrease Saxophone for Only Song',
    ).parentElement
    expect(saxCount).toHaveTextContent('0')

    // A group explicitly added stays visible at 0, unlike a named default.
    expect(
      screen.getByLabelText('Decrease Saxophone for Only Song'),
    ).toBeDisabled()
    expect(screen.getByText('Saxophone')).toBeInTheDocument()

    await user.click(screen.getByLabelText('Increase Saxophone for Only Song'))
    expect(saxCount).toHaveTextContent('1')
  })

  it('"Confirm Roles" writes the staged rows to the buffer and closes the popup', async () => {
    const onAddRows = vi.fn()
    const onOpenChange = vi.fn()
    const user = userEvent.setup()
    render(
      <AddSongsSheet
        open
        onOpenChange={onOpenChange}
        onAddRows={onAddRows}
        roles={ROLE_GROUPS_FIXTURE}
      />,
    )

    await user.click(screen.getByRole('radio', { name: 'By hand' }))
    await user.type(screen.getByLabelText('Title'), 'Only Song')
    await user.click(screen.getByRole('button', { name: 'Confirm Songs' }))

    expect(onAddRows).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Confirm Roles' }))

    expect(onAddRows).toHaveBeenCalledTimes(1)
    const rows = onAddRows.mock.calls[0]?.[0] as EditRow[]
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ title: 'Only Song' })
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
  })

  it('"Confirm Roles" merges the named default counts into a by-hand row\'s roleGroupCounts (issue #462)', async () => {
    const onAddRows = vi.fn()
    const user = userEvent.setup()
    renderOpen(onAddRows)

    await user.click(screen.getByRole('radio', { name: 'By hand' }))
    await user.type(screen.getByLabelText('Title'), 'Hand Song')
    await user.click(screen.getByRole('button', { name: 'Confirm Songs' }))
    await user.click(screen.getByRole('button', { name: 'Confirm Roles' }))

    const rows = onAddRows.mock.calls[0]?.[0] as EditRow[]
    expect(rows).toHaveLength(1)
    expect(rows[0]?.roleGroupCounts).toEqual(
      expect.arrayContaining([
        { roleGroupId: 10, count: 3 }, // Vocals
        { roleGroupId: 11, count: 2 }, // Guitars
        { roleGroupId: 12, count: 1 }, // Keyboards
        { roleGroupId: 13, count: 1 }, // Drums
        { roleGroupId: 14, count: 1 }, // Bass
      ]),
    )
    expect(rows[0]?.roleGroupCounts).toHaveLength(5)
  })

  it('"Confirm Roles" merges role counts into a Spotify-sourced row\'s roleGroupCounts (issue #462)', async () => {
    mockFetchOnce(200, {
      context: memberContext(),
      data: {
        songs: [
          {
            title: 'Spotify Song',
            artist: 'Spotify Artist',
            length: '3:00',
            already_in_setlist: false,
          },
        ],
        skipped_count: 0,
        skipped_reasons: {},
        message: '',
      },
    })
    const onAddRows = vi.fn()
    const user = userEvent.setup()
    renderOpen(onAddRows)

    await user.type(
      screen.getByLabelText('Playlist link'),
      'https://open.spotify.com/playlist/abc',
    )
    await user.click(screen.getByRole('button', { name: 'Fetch' }))
    await screen.findByText(/Spotify Song/)

    await user.click(screen.getByRole('button', { name: 'Confirm Songs' }))
    // Zero out one named default and increase another before confirming.
    await user.click(screen.getByLabelText('Decrease Bass for Spotify Song'))
    await user.click(screen.getByLabelText('Increase Vocals for Spotify Song'))
    await user.click(screen.getByRole('button', { name: 'Confirm Roles' }))

    const rows = onAddRows.mock.calls[0]?.[0] as EditRow[]
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ origin: 'spotify', songId: null })
    expect(rows[0]?.roleGroupCounts).toEqual(
      expect.arrayContaining([
        { roleGroupId: 10, count: 4 }, // Vocals, bumped from 3
        { roleGroupId: 11, count: 2 }, // Guitars
        { roleGroupId: 12, count: 1 }, // Keyboards
        { roleGroupId: 13, count: 1 }, // Drums
      ]),
    )
    // Bass was zeroed out, so it carries no entry at all.
    expect(rows[0]?.roleGroupCounts).toHaveLength(4)
  })

  it('adding a non-default Role Group column and setting a count includes it in roleGroupCounts (issue #462)', async () => {
    const onAddRows = vi.fn()
    const user = userEvent.setup()
    renderOpen(onAddRows)

    await user.click(screen.getByRole('radio', { name: 'By hand' }))
    await user.type(screen.getByLabelText('Title'), 'Only Song')
    await user.click(screen.getByRole('button', { name: 'Confirm Songs' }))

    await user.selectOptions(screen.getByLabelText('Add Role'), 'Saxophone')
    await user.click(screen.getByLabelText('Increase Saxophone for Only Song'))
    await user.click(screen.getByRole('button', { name: 'Confirm Roles' }))

    const rows = onAddRows.mock.calls[0]?.[0] as EditRow[]
    expect(rows[0]?.roleGroupCounts).toEqual(
      expect.arrayContaining([{ roleGroupId: 16, count: 1 }]),
    )
  })

  it("an all-zero-count song sends no roleGroupCounts entries at all, matching today's no-role-step behavior (issue #462)", async () => {
    const onAddRows = vi.fn()
    const user = userEvent.setup()
    renderOpen(onAddRows)

    await user.click(screen.getByRole('radio', { name: 'By hand' }))
    await user.type(screen.getByLabelText('Title'), 'Only Song')
    await user.click(screen.getByRole('button', { name: 'Confirm Songs' }))

    // Zero out every named default.
    await user.click(screen.getByLabelText('Decrease Vocals for Only Song'))
    await user.click(screen.getByLabelText('Decrease Vocals for Only Song'))
    await user.click(screen.getByLabelText('Decrease Vocals for Only Song'))
    await user.click(screen.getByLabelText('Decrease Guitars for Only Song'))
    await user.click(screen.getByLabelText('Decrease Guitars for Only Song'))
    await user.click(screen.getByLabelText('Decrease Keyboards for Only Song'))
    await user.click(screen.getByLabelText('Decrease Drums for Only Song'))
    await user.click(screen.getByLabelText('Decrease Bass for Only Song'))
    await user.click(screen.getByRole('button', { name: 'Confirm Roles' }))

    const rows = onAddRows.mock.calls[0]?.[0] as EditRow[]
    expect(rows[0]?.roleGroupCounts).toEqual([])
  })

  it('the role-count step renders as a bottom sheet with working steppers below the phone breakpoint', async () => {
    mockMatchMedia(true)
    const onAddRows = vi.fn()
    const user = userEvent.setup()
    renderOpen(onAddRows)

    expect(screen.getByRole('dialog')).toHaveClass('bottom-0')

    await user.click(screen.getByRole('radio', { name: 'By hand' }))
    await user.type(screen.getByLabelText('Title'), 'Only Song')
    await user.click(screen.getByRole('button', { name: 'Confirm Songs' }))

    expect(screen.getByRole('dialog')).toHaveClass('bottom-0')
    expect(
      screen.getByRole('columnheader', { name: 'Vocals' }),
    ).toBeInTheDocument()

    await user.click(screen.getByLabelText('Increase Vocals for Only Song'))
    expect(
      screen.getByLabelText('Decrease Vocals for Only Song').parentElement,
    ).toHaveTextContent('4')

    await user.click(screen.getByRole('button', { name: 'Confirm Roles' }))
    expect(onAddRows).toHaveBeenCalledTimes(1)
  })

  it('"Back" from the role-count step returns to the songs step without adding rows', async () => {
    const onAddRows = vi.fn()
    const user = userEvent.setup()
    renderOpen(onAddRows)

    await user.click(screen.getByRole('radio', { name: 'By hand' }))
    await user.type(screen.getByLabelText('Title'), 'Only Song')
    await user.click(screen.getByRole('button', { name: 'Confirm Songs' }))

    await user.click(screen.getByRole('button', { name: 'Back' }))

    expect(screen.getByLabelText('Title')).toBeInTheDocument()
    expect(onAddRows).not.toHaveBeenCalled()
  })

  it('Cancel resets the form without calling onAddRows', async () => {
    const onOpenChange = vi.fn()
    const onAddRows = vi.fn()
    const user = userEvent.setup()
    render(
      <AddSongsSheet
        open
        onOpenChange={onOpenChange}
        onAddRows={onAddRows}
        roles={ROLE_GROUPS_FIXTURE}
      />,
    )

    await user.click(screen.getByRole('radio', { name: 'By hand' }))
    await user.type(screen.getByLabelText('Title'), 'Hand Song')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(onAddRows).not.toHaveBeenCalled()
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
  })
})
