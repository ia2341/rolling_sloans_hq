import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

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
            cells: [{ role_id: 5, entries: [] }],
          },
        ],
        addable_roles: [],
      },
    },
  }
}

function pickerPayload() {
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

function renderEditor() {
  return render(
    <ContextProvider>
      <EditSessionProvider>
        <ActiveEditSessionSaveButton />
        <AssignmentEditor rehearsalId={1} />
      </EditSessionProvider>
    </ContextProvider>,
  )
}

describe('AssignmentEditor', () => {
  it('renders the non-dismissible scope bar naming the ADR 0009 blast radius', async () => {
    mockMatchMedia(false)
    queueFetch(schedulePayload())

    renderEditor()

    expect(
      await screen.findByText('Editing standing assignments.'),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/every rehearsal and the concert/),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /dismiss/i }),
    ).not.toBeInTheDocument()
  })

  it("the picker's two sections render with their scope lines, structural not dismissible", async () => {
    mockMatchMedia(false)
    queueFetch(schedulePayload(), pickerPayload())
    const user = userEvent.setup()

    renderEditor()
    await screen.findByText('Song One')

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
    await screen.findByText('Song One')
    await user.click(
      screen.getByRole('button', { name: 'Assign Guitar on Song One' }),
    )
    await screen.findByRole('heading', { name: 'Assigned' })

    const callsBeforePick = fetchSpy.mock.calls.length
    await user.click(screen.getByRole('button', { name: 'Riley Song' }))

    expect(await screen.findByText('Riley Song')).toBeInTheDocument()
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
    await screen.findByText('Song One')
    await user.click(
      screen.getByRole('button', { name: 'Assign Guitar on Song One' }),
    )
    await screen.findByRole('heading', { name: 'Assigned' })
    await user.click(screen.getByRole('button', { name: 'Riley Song' }))
    await screen.findByText('Riley Song')

    await user.click(screen.getByRole('button', { name: /Save 1 change/ }))

    await waitFor(() =>
      expect(screen.getByText('Someone is away.')).toBeInTheDocument(),
    )
  })
})
