import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { resetContextForTests, setContext } from '../api/contextStore'
import {
  getViewingSemesterChangeSnapshot,
  resetViewingSemesterChangeForTests,
} from '../api/viewingSemesterChangeStore'
import { adminContext } from '../test/fixtures'
import { stubFetchSequence } from '../test/mockFetch'
import { mockMatchMedia } from '../test/mockMatchMedia'
import { renderShell } from '../test/renderShell'
import { NewSemesterDialog } from './NewSemesterDialog'

/** Renders the current route's pathname as text, standing in for a router outlet so a test can assert a successful create navigated (issue #374). */
function LocationSpy() {
  const location = useLocation()
  return <p data-testid="location">{location.pathname}</p>
}

const existingOption = {
  id: 10,
  name: 'Spring 2026',
  status: 'live' as const,
  is_viewing: true,
  member_count: 6,
  song_count: 10,
  rehearsal_count: 4,
}
const options = [existingOption]

afterEach(() => {
  resetContextForTests()
  resetViewingSemesterChangeForTests()
  vi.unstubAllGlobals()
  mockMatchMedia(false)
})

describe('NewSemesterDialog', () => {
  it('prefills the name from the most recent Semester', async () => {
    setContext(adminContext({ semester_options: options }))
    stubFetchSequence([
      {
        status: 200,
        body: {
          context: adminContext({ semester_options: options }),
          data: { semester_defaults: null },
        },
      },
    ])
    renderShell(<NewSemesterDialog open onOpenChange={() => {}} />)

    await waitFor(() =>
      expect(screen.getByDisplayValue('Spring 2026')).toBeInTheDocument(),
    )
  })

  it('keeps the dialog open and shows the per-field error on a duplicate name', async () => {
    setContext(adminContext({ semester_options: options }))
    stubFetchSequence([
      {
        status: 200,
        body: {
          context: adminContext({ semester_options: options }),
          data: { semester_defaults: null },
        },
      },
      {
        status: 200,
        body: {
          context: adminContext({ semester_options: options }),
          ok: false,
          errors: {
            name: [
              'A semester named "Spring 2026" already exists — choose a different name.',
            ],
          },
          non_field_errors: [],
          fallout: null,
          values: null,
          data: null,
        },
      },
    ])
    const user = userEvent.setup()
    const onOpenChange = vi.fn()
    renderShell(<NewSemesterDialog open onOpenChange={onOpenChange} />)

    await waitFor(() =>
      expect(screen.getByDisplayValue('Spring 2026')).toBeInTheDocument(),
    )
    await user.click(screen.getByRole('button', { name: /Create/ }))

    expect(
      await screen.findByText(
        'A semester named "Spring 2026" already exists — choose a different name.',
      ),
    ).toBeInTheDocument()
    expect(onOpenChange).not.toHaveBeenCalledWith(false)
  })

  it('closes on success, after which the Viewing control names the new semester', async () => {
    setContext(adminContext({ semester_options: options }))
    stubFetchSequence([
      {
        status: 200,
        body: {
          context: adminContext({ semester_options: options }),
          data: { semester_defaults: null },
        },
      },
      {
        status: 200,
        body: {
          context: adminContext({
            semester_options: [
              {
                id: 12,
                name: 'Fall 2026',
                status: 'draft',
                is_viewing: true,
                member_count: 0,
                song_count: 0,
                rehearsal_count: 0,
              },
              { ...existingOption, is_viewing: false },
            ],
            viewing_semester: {
              id: 12,
              name: 'Fall 2026',
              status: 'draft',
              published_at: null,
              updated_at: '2026-02-01T00:00:00Z',
            },
          }),
          ok: true,
          errors: {},
          non_field_errors: [],
          fallout: null,
          values: null,
          data: null,
        },
      },
    ])
    const user = userEvent.setup()
    const onOpenChange = vi.fn()
    renderShell(<NewSemesterDialog open onOpenChange={onOpenChange} />)

    await waitFor(() =>
      expect(screen.getByDisplayValue('Spring 2026')).toBeInTheDocument(),
    )
    await user.clear(screen.getByLabelText('Name'))
    await user.type(screen.getByLabelText('Name'), 'Fall 2026')
    await user.click(screen.getByRole('button', { name: 'Create Fall 2026' }))

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
  })

  it('navigates to Home on success, so the admin lands on the setup checklist for the new Semester (issue #374)', async () => {
    setContext(adminContext({ semester_options: options }))
    stubFetchSequence([
      {
        status: 200,
        body: {
          context: adminContext({ semester_options: options }),
          data: { semester_defaults: null },
        },
      },
      {
        status: 200,
        body: {
          context: adminContext({ semester_options: options }),
          ok: true,
          errors: {},
          non_field_errors: [],
          fallout: null,
          values: null,
          data: null,
        },
      },
    ])
    const user = userEvent.setup()
    const onOpenChange = vi.fn()
    renderShell(
      <>
        <NewSemesterDialog open onOpenChange={onOpenChange} />
        <LocationSpy />
      </>,
      ['/somewhere-else'],
    )

    await waitFor(() =>
      expect(screen.getByDisplayValue('Spring 2026')).toBeInTheDocument(),
    )
    await user.click(screen.getByRole('button', { name: /Create/ }))

    await waitFor(() =>
      expect(screen.getByTestId('location')).toHaveTextContent('/'),
    )
  })

  it('bumps the viewing-semester-change signal on success, so Home refetches even when the navigate-to-/ is a same-route no-op (issue #402)', async () => {
    setContext(adminContext({ semester_options: options }))
    stubFetchSequence([
      {
        status: 200,
        body: {
          context: adminContext({ semester_options: options }),
          data: { semester_defaults: null },
        },
      },
      {
        status: 200,
        body: {
          context: adminContext({ semester_options: options }),
          ok: true,
          errors: {},
          non_field_errors: [],
          fallout: null,
          values: null,
          data: null,
        },
      },
    ])
    const user = userEvent.setup()
    const before = getViewingSemesterChangeSnapshot()
    renderShell(<NewSemesterDialog open onOpenChange={() => {}} />)

    await waitFor(() =>
      expect(screen.getByDisplayValue('Spring 2026')).toBeInTheDocument(),
    )
    await user.click(screen.getByRole('button', { name: /Create/ }))

    await waitFor(() =>
      expect(getViewingSemesterChangeSnapshot()).toBe(before + 1),
    )
  })
})
