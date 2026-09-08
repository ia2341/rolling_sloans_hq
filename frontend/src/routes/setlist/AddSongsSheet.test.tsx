import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { memberContext } from '../../test/fixtures'
import { mockFetchOnce } from '../../test/mockFetch'
import { AddSongsSheet } from './AddSongsSheet'
import type { EditRow } from './setlistEditModel'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

/** Renders the sheet already open, with a spy for `onAddRows`. */
function renderOpen(onAddRows: (rows: EditRow[]) => void = () => {}) {
  return render(
    <AddSongsSheet open onOpenChange={() => {}} onAddRows={onAddRows} />,
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

    expect(onAddRows).toHaveBeenCalledTimes(1)
    const rows = onAddRows.mock.calls[0]?.[0] as EditRow[]
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ title: 'Only Song' })
  })

  it('Cancel resets the form without calling onAddRows', async () => {
    const onOpenChange = vi.fn()
    const onAddRows = vi.fn()
    const user = userEvent.setup()
    render(
      <AddSongsSheet open onOpenChange={onOpenChange} onAddRows={onAddRows} />,
    )

    await user.click(screen.getByRole('radio', { name: 'By hand' }))
    await user.type(screen.getByLabelText('Title'), 'Hand Song')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(onAddRows).not.toHaveBeenCalled()
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
  })
})
