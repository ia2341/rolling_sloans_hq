import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { AssignmentPickerPayload } from '../../api/assignmentEditorTypes'
import { ContextProvider } from '../../api/ContextProvider'
import {
  EditSessionProvider,
  useEditSession,
} from '../../shell/EditSessionContext'
import { adminContext } from '../../test/fixtures'
import { mockMatchMedia } from '../../test/mockMatchMedia'
import { AssignmentEditor } from './AssignmentEditor'

/** Mirrors the shell's own `EditToolbar` wiring so a test can trigger the registered `EditSession`'s Save. */
function ActiveEditSessionSaveButton() {
  const session = useEditSession()
  if (session === null) return null
  return (
    <button type="button" onClick={session.requestSave}>
      {`Save ${session.changeCount} change${session.changeCount === 1 ? '' : 's'}`}
    </button>
  )
}

function schedulePayload() {
  return {
    context: adminContext(),
    data: {
      semester_name: 'Fall 2026',
      schedule: { past: [], future: [] },
      selected: {
        id: 1,
        date: '2026-03-10',
        start_time: '19:00:00',
        end_time: '21:00:00',
        is_dress: false,
        is_past: false,
        can_edit_assignments: true,
        timeline: {
          slots: [],
          window_start: '19:00:00',
          window_end: '21:00:00',
          viewer_song_count: 0,
          total_song_count: 0,
          viewer_start_time: null,
          viewer_end_time: null,
          is_dress_rehearsal: false,
        },
        availability: {
          declaration_type: null,
          type_label: null,
          declared_time: null,
          reason: null,
          status: null,
          admin_note: null,
          is_dress: false,
          is_editable: true,
        },
        roles: [{ id: 5, name: 'Guitar', code: 'GTR' }],
        rows: [
          {
            song_id: 100,
            song_title: 'Song One',
            start_time: '19:00:00',
            rehearsal_song_id: 200,
            cells: [{ role_id: 5, entries: [] }],
          },
        ],
        addable_roles: [],
        available_songs: [
          {
            id: 100,
            title: 'Song One',
            cells: [{ role_id: 5, role_name: 'Guitar', entries: [] }],
          },
          {
            id: 102,
            title: 'Song Three',
            cells: [
              {
                role_id: 5,
                role_name: 'Guitar',
                entries: [
                  {
                    id: 55,
                    kind: 'assignment',
                    person_id: 30,
                    person_name: 'Alex Three',
                    is_role_mismatch: false,
                    has_conflict: false,
                  },
                ],
              },
            ],
          },
        ],
      },
    },
  }
}

/** A two-Song variant of `schedulePayload()`, so the Running Order editor has something to reorder. */
function twoSongSchedulePayload() {
  const payload = schedulePayload()
  payload.data.selected.rows = [
    {
      song_id: 100,
      song_title: 'Song One',
      start_time: '19:00:00',
      rehearsal_song_id: 200,
      cells: [{ role_id: 5, entries: [] }],
    },
    {
      song_id: 101,
      song_title: 'Song Two',
      start_time: '19:30:00',
      rehearsal_song_id: 201,
      cells: [{ role_id: 5, entries: [] }],
    },
  ]
  return payload
}

function pickerPayload(): {
  context: ReturnType<typeof adminContext>
  data: AssignmentPickerPayload
} {
  return {
    context: adminContext(),
    data: {
      song_id: 100,
      song_title: 'Song One',
      role_id: 5,
      role_name: 'Guitar',
      rehearsal_song_id: 200,
      declared: [
        {
          person_id: 9,
          person_name: 'Riley Song',
          has_declared_role: true,
          has_conflict: false,
        },
      ],
      others: [],
      backup_declared: [
        {
          person_id: 12,
          person_name: 'Jordan Wren',
          has_declared_role: true,
          has_conflict: false,
        },
      ],
      backup_others: [],
    },
  }
}

function queueFetch(...bodies: unknown[]) {
  const fetchSpy = vi.fn()
  for (const body of bodies) {
    fetchSpy.mockResolvedValueOnce({
      status: 200,
      ok: true,
      json: () => Promise.resolve(body),
    })
  }
  vi.stubGlobal('fetch', fetchSpy)
  return fetchSpy
}

/** Mirrors the shell's own `EditToolbar` wiring so a test can trigger the registered `EditSession`'s Discard. */
function ActiveEditSessionDiscardButton() {
  const session = useEditSession()
  if (session === null) return null
  return (
    <button type="button" onClick={session.discard}>
      Discard
    </button>
  )
}

function renderEditor(onDone: () => void = vi.fn(), compact = false) {
  return render(
    <ContextProvider>
      <EditSessionProvider>
        <ActiveEditSessionSaveButton />
        <ActiveEditSessionDiscardButton />
        <AssignmentEditor rehearsalId={1} onDone={onDone} compact={compact} />
      </EditSessionProvider>
    </ContextProvider>,
  )
}

describe('AssignmentEditor', () => {
  it('renders the non-dismissible scope bar naming the Backup escape hatch', async () => {
    mockMatchMedia(false)
    queueFetch(schedulePayload())

    renderEditor()

    expect(
      await screen.findByText('Editing standing assignments.'),
    ).toBeInTheDocument()
    expect(screen.getByText(/To cover one evening only/)).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /dismiss/i }),
    ).not.toBeInTheDocument()
  })

  it("the picker's two sections render with their scope lines, structural not dismissible", async () => {
    mockMatchMedia(false)
    queueFetch(schedulePayload(), pickerPayload())
    const user = userEvent.setup()

    renderEditor()
    await screen.findAllByText('Song One')

    await user.click(
      screen.getByRole('button', { name: 'Assign Guitar on Song One' }),
    )

    expect(
      await screen.findByRole('heading', { name: 'Assigned' }),
    ).toBeInTheDocument()
    expect(screen.getByText('Every rehearsal + concert')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Backup' })).toBeInTheDocument()
    expect(
      screen.getByText(
        'This rehearsal only — the standing assignment above is unaffected',
      ),
    ).toBeInTheDocument()
  })

  it('picking a declared member adds a pending pill with no further round trip', async () => {
    mockMatchMedia(false)
    const fetchSpy = queueFetch(schedulePayload(), pickerPayload())
    const user = userEvent.setup()

    renderEditor()
    await screen.findAllByText('Song One')
    await user.click(
      screen.getByRole('button', { name: 'Assign Guitar on Song One' }),
    )
    await screen.findByRole('heading', { name: 'Assigned' })

    const callsBeforePick = fetchSpy.mock.calls.length
    await user.click(screen.getByRole('button', { name: 'Riley' }))

    expect(await screen.findByText('Riley')).toBeInTheDocument()
    expect(fetchSpy.mock.calls.length).toBe(callsBeforePick)
  })

  it('opens the Save popup on Save and fires the preview endpoint exactly once', async () => {
    mockMatchMedia(false)
    queueFetch(schedulePayload(), pickerPayload(), {
      context: adminContext(),
      ok: true,
      errors: {},
      non_field_errors: [],
      fallout: {
        is_blocked: false,
        block_message: '',
        is_stale: false,
        loud: ['Someone is away.'],
        quiet: [],
      },
      values: null,
      data: null,
    })
    const user = userEvent.setup()

    renderEditor()
    await screen.findAllByText('Song One')
    await user.click(
      screen.getByRole('button', { name: 'Assign Guitar on Song One' }),
    )
    await screen.findByRole('heading', { name: 'Assigned' })
    await user.click(screen.getByRole('button', { name: 'Riley' }))
    await screen.findByText('Riley')

    await user.click(screen.getByRole('button', { name: /Save 1 change/ }))

    await waitFor(() =>
      expect(screen.getByText('Someone is away.')).toBeInTheDocument(),
    )
  })

  it('picking someone who has not declared the Role shows the mismatch marker on the pending pill', async () => {
    mockMatchMedia(false)
    const undeclaredPickerPayload = pickerPayload()
    undeclaredPickerPayload.data.declared = []
    undeclaredPickerPayload.data.others = [
      {
        person_id: 20,
        person_name: 'Casey Undeclared',
        has_declared_role: false,
        has_conflict: false,
      },
    ]
    queueFetch(schedulePayload(), undeclaredPickerPayload)
    const user = userEvent.setup()

    renderEditor()
    await screen.findAllByText('Song One')
    await user.click(
      screen.getByRole('button', { name: 'Assign Guitar on Song One' }),
    )
    await user.click(screen.getByRole('button', { name: 'Show all members' }))
    await user.click(screen.getByRole('button', { name: /Casey/ }))

    const pill = await screen.findByText('Casey')
    expect(pill.closest('span')).toHaveTextContent('◦')
  })

  it('Running order renders each Song with Move up/down controls, disabled at the ends', async () => {
    mockMatchMedia(false)
    queueFetch(twoSongSchedulePayload())

    renderEditor()
    await screen.findByRole('button', { name: 'Move Song One up' })

    expect(
      screen.getByRole('button', { name: 'Move Song One up' }),
    ).toBeDisabled()
    expect(
      screen.getByRole('button', { name: 'Move Song One down' }),
    ).not.toBeDisabled()
    expect(
      screen.getByRole('button', { name: 'Move Song Two down' }),
    ).toBeDisabled()
  })

  it('reordering via Move down marks the surface dirty, gating the Save button on changeCount', async () => {
    mockMatchMedia(false)
    queueFetch(twoSongSchedulePayload())
    const user = userEvent.setup()

    renderEditor()
    await screen.findByRole('button', { name: 'Move Song One up' })
    expect(
      screen.getByRole('button', { name: /Save 0 change/ }),
    ).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Move Song One down' }))

    expect(
      screen.getByRole('button', { name: /Save 1 change/ }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /Save 0 change/ }),
    ).not.toBeInTheDocument()
  })

  it('Save posts the Running Order Preview endpoint too once a reorder is pending', async () => {
    mockMatchMedia(false)
    const fetchSpy = queueFetch(twoSongSchedulePayload(), {
      context: adminContext(),
      ok: true,
      errors: {},
      non_field_errors: [],
      fallout: {
        is_blocked: false,
        block_message: '',
        is_stale: false,
        loud: [],
        quiet: [],
      },
      values: null,
      data: null,
    })
    fetchSpy.mockResolvedValueOnce({
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
            loud: [],
            quiet: [],
            doomed_recording_groups: [],
          },
          values: null,
          data: null,
        }),
    })
    const user = userEvent.setup()

    renderEditor()
    await screen.findByRole('button', { name: 'Move Song One up' })
    await user.click(screen.getByRole('button', { name: 'Move Song One down' }))

    await user.click(screen.getByRole('button', { name: /Save 1 change/ }))

    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(3))
    const urls = fetchSpy.mock.calls.map(([url]) => String(url))
    expect(urls.some((url) => url.includes('/assignments/preview/'))).toBe(true)
    expect(urls.some((url) => url.includes('/running-order/preview/'))).toBe(
      true,
    )
  })

  it('compact mode (issue #405) hides the scope card, the legend, and the drag helper text, but keeps reordering', async () => {
    mockMatchMedia(false)
    queueFetch(twoSongSchedulePayload())

    renderEditor(vi.fn(), true)
    await screen.findByRole('button', { name: 'Move Song One up' })

    expect(
      screen.queryByText('Editing standing assignments.'),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByText('backup — covers one evening only'),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByText(/Drag a row, or use its arrows/),
    ).not.toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Move Song One down' }),
    ).not.toBeDisabled()
  })

  it('picking a different song in the swap dropdown rerenders its cells instantly with no extra fetch (issue #406)', async () => {
    mockMatchMedia(false)
    const fetchSpy = queueFetch(schedulePayload())
    const user = userEvent.setup()

    renderEditor()
    await screen.findAllByText('Song One')

    const callsBeforeSwap = fetchSpy.mock.calls.length
    await user.selectOptions(
      screen.getByRole('combobox', { name: 'Song for Song One' }),
      'Song Three',
    )

    expect(await screen.findByText('Alex Three')).toBeInTheDocument()
    expect(fetchSpy.mock.calls.length).toBe(callsBeforeSwap)
  })

  it('a pending song swap marks the surface dirty, gating Save on changeCount', async () => {
    mockMatchMedia(false)
    queueFetch(schedulePayload())
    const user = userEvent.setup()

    renderEditor()
    await screen.findAllByText('Song One')
    expect(
      screen.getByRole('button', { name: /Save 0 change/ }),
    ).toBeInTheDocument()

    await user.selectOptions(
      screen.getByRole('combobox', { name: 'Song for Song One' }),
      'Song Three',
    )

    expect(
      screen.getByRole('button', { name: /Save 1 change/ }),
    ).toBeInTheDocument()
  })

  it('Save posts the swap as a song_overrides entry on the Running Order endpoint', async () => {
    mockMatchMedia(false)
    const okFallout = (extra: Record<string, unknown> = {}) => ({
      context: adminContext(),
      ok: true,
      errors: {},
      non_field_errors: [],
      fallout: {
        is_blocked: false,
        block_message: '',
        is_stale: false,
        loud: [],
        quiet: [],
        ...extra,
      },
      values: null,
      data: null,
    })
    const fetchSpy = queueFetch(
      schedulePayload(),
      okFallout(), // assignments/preview
      okFallout({ doomed_recording_groups: [] }), // running-order/preview
      okFallout(), // assignments/save
      okFallout({ doomed_recording_groups: [] }), // running-order/save
      schedulePayload(), // load() after a successful save
    )
    const user = userEvent.setup()

    renderEditor()
    await screen.findAllByText('Song One')
    await user.selectOptions(
      screen.getByRole('combobox', { name: 'Song for Song One' }),
      'Song Three',
    )

    await user.click(screen.getByRole('button', { name: /Save 1 change/ }))
    await user.click(
      await screen.findByRole('button', { name: 'Save changes' }),
    )

    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(6))
    const reorderCall = fetchSpy.mock.calls.find(([url]) =>
      String(url).includes('/running-order/save/'),
    )
    expect(reorderCall).toBeDefined()
    const body = JSON.parse(String(reorderCall?.[1]?.body))
    expect(body.song_overrides).toEqual([
      { rehearsal_song_id: 200, song_id: 102 },
    ])
  })

  it('Discard reloads and calls onDone, since Discard is the only way to leave edit mode (issue: UI overhaul round 2, item 2)', async () => {
    mockMatchMedia(false)
    const fetchSpy = queueFetch(schedulePayload(), schedulePayload())
    const onDone = vi.fn()
    const user = userEvent.setup()

    renderEditor(onDone)
    await screen.findByText('Editing standing assignments.')

    await user.click(screen.getByRole('button', { name: 'Discard' }))

    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2))
    expect(onDone).toHaveBeenCalledTimes(1)
  })
})
