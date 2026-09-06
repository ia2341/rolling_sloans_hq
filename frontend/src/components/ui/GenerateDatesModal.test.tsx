import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { RehearsalGenerationDiff } from '../../api/scheduleEditorTypes'
import { GenerateDatesModal } from './GenerateDatesModal'

const diff: RehearsalGenerationDiff = {
  creates: [
    {
      date: '2026-04-07',
      start_time: '19:00:00',
      end_time: '21:00:00',
      is_dress_rehearsal: false,
    },
  ],
  keeps: [
    {
      rehearsal_id: 1,
      date: '2026-03-10',
      start_time: '19:00:00',
      end_time: '21:00:00',
    },
  ],
  retimes: [],
  orphans: [
    {
      rehearsal_id: 2,
      date: '2026-03-17',
      start_time: '19:00:00',
      end_time: '21:00:00',
      song_count: 2,
      conflict_count: 0,
      recording_count: 1,
      delete_disabled: true,
    },
  ],
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

describe('GenerateDatesModal', () => {
  it("renders a locked orphan's checkbox disabled and unticked", async () => {
    stubFetchSequence([
      {
        status: 200,
        body: {
          ok: true,
          errors: {},
          non_field_errors: [],
          fallout: null,
          values: null,
          data: null,
        },
      },
      { status: 200, body: { data: diff } },
    ])
    const user = userEvent.setup()
    render(
      <GenerateDatesModal
        open
        onOpenChange={() => {}}
        pattern={null}
        onApply={() => {}}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Preview' }))

    const checkbox = await screen.findByRole('checkbox', {
      name: /2026-03-17 — carries Recordings, remove it by hand from the grid instead/,
    })
    expect(checkbox).toBeDisabled()
    expect(checkbox).not.toBeChecked()
  })

  it('shows the pattern-save error and never fetches the diff when the pattern is rejected', async () => {
    const fetchSpy = stubFetchSequence([
      {
        status: 200,
        body: {
          ok: false,
          errors: {},
          non_field_errors: ['Weekly times collide on Monday.'],
          fallout: null,
          values: null,
          data: null,
        },
      },
    ])
    const user = userEvent.setup()
    render(
      <GenerateDatesModal
        open
        onOpenChange={() => {}}
        pattern={null}
        onApply={() => {}}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Preview' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Weekly times collide on Monday.',
    )
    expect(fetchSpy).toHaveBeenCalledTimes(1)
  })

  it('adds a weekly time and a skip date, previews, and applies only the ticked items', async () => {
    stubFetchSequence([
      {
        status: 200,
        body: {
          ok: true,
          errors: {},
          non_field_errors: [],
          fallout: null,
          values: null,
          data: null,
        },
      },
      { status: 200, body: { data: diff } },
    ])
    const user = userEvent.setup()
    const onApply = vi.fn()
    render(
      <GenerateDatesModal
        open
        onOpenChange={() => {}}
        pattern={null}
        onApply={onApply}
      />,
    )

    await user.click(screen.getByText('+ Add weekly time'))
    expect(screen.getByLabelText('Day of week')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '+ Add skip date' }))
    const skipDateInput = screen.getByLabelText('Add skip date')
    await user.type(skipDateInput, '2026-03-24')
    expect(await screen.findByText('2026-03-24')).toBeInTheDocument()

    // The picker stays open (unbounded add) so a second date can be added
    // without clicking "+ Add skip date" again.
    await user.type(screen.getByLabelText('Add skip date'), '2026-03-25')
    expect(await screen.findByText('2026-03-25')).toBeInTheDocument()
    expect(screen.getByText('2026-03-24')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Preview' }))
    await screen.findByText('Create · 1')

    // The locked orphan defaults to unticked; everything else defaults ticked.
    await user.click(
      screen.getByRole('button', { name: 'Apply ticked to the grid' }),
    )

    expect(onApply).toHaveBeenCalledWith({
      creates: diff.creates,
      retimes: [],
      orphanIds: [],
    })
  })
})
