import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { resetContextForTests, setContext } from '../api/contextStore'
import {
  getViewingSemesterChangeSnapshot,
  resetViewingSemesterChangeForTests,
} from '../api/viewingSemesterChangeStore'
import { adminContext } from '../test/fixtures'
import { mockFetchOnce, stubFetchSequence } from '../test/mockFetch'
import { mockMatchMedia } from '../test/mockMatchMedia'
import { renderShell } from '../test/renderShell'
import { DeleteSemesterDialog } from './DeleteSemesterDialog'

afterEach(() => {
  resetContextForTests()
  resetViewingSemesterChangeForTests()
  vi.unstubAllGlobals()
  mockMatchMedia(false)
})

describe('DeleteSemesterDialog', () => {
  it('renders the doomed Recordings block first, then the four-count list, then the accounts reassurance', async () => {
    setContext(adminContext())
    mockFetchOnce(200, {
      context: adminContext(),
      data: {
        member_count: 5,
        song_count: 8,
        rehearsal_count: 3,
        recording_count: 4,
      },
    })
    renderShell(
      <DeleteSemesterDialog
        open
        onOpenChange={() => {}}
        semesterId={11}
        semesterName="Fall 2026"
      />,
    )

    await waitFor(() =>
      expect(screen.getByText(/recordings are destroyed/)).toBeInTheDocument(),
    )

    const dialog = screen.getByRole('dialog')
    const text = dialog.textContent ?? ''
    const doomedIndex = text.indexOf('recordings are destroyed')
    const permanentIndex = text.indexOf('This permanently deletes')
    const untouchedIndex = text.indexOf('Person accounts are untouched')
    expect(doomedIndex).toBeGreaterThanOrEqual(0)
    expect(doomedIndex).toBeLessThan(permanentIndex)
    expect(permanentIndex).toBeLessThan(untouchedIndex)

    expect(screen.getByText(/5 membership/)).toBeInTheDocument()
    expect(
      screen.getByText(/8 song.*role requirements and/),
    ).toBeInTheDocument()
    expect(screen.getByText(/3 rehearsal.*running/)).toBeInTheDocument()
    expect(screen.getByText('4 recordings')).toBeInTheDocument()
  })

  it('omits the doomed block when there are no recordings', async () => {
    setContext(adminContext())
    mockFetchOnce(200, {
      context: adminContext(),
      data: {
        member_count: 5,
        song_count: 8,
        rehearsal_count: 3,
        recording_count: 0,
      },
    })
    renderShell(
      <DeleteSemesterDialog
        open
        onOpenChange={() => {}}
        semesterId={11}
        semesterName="Fall 2026"
      />,
    )

    await waitFor(() =>
      expect(screen.getByText('This permanently deletes')).toBeInTheDocument(),
    )
    expect(
      screen.queryByText(/recordings are destroyed/),
    ).not.toBeInTheDocument()
  })

  it('bumps the viewing-semester-change signal on a successful delete, so Home knows to refetch even without navigating (issue #402)', async () => {
    setContext(adminContext())
    stubFetchSequence([
      {
        status: 200,
        body: {
          context: adminContext(),
          data: {
            member_count: 5,
            song_count: 8,
            rehearsal_count: 3,
            recording_count: 0,
          },
        },
      },
      {
        status: 200,
        body: {
          context: adminContext(),
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
    renderShell(
      <DeleteSemesterDialog
        open
        onOpenChange={() => {}}
        semesterId={11}
        semesterName="Fall 2026"
      />,
    )

    await waitFor(() =>
      expect(screen.getByText('This permanently deletes')).toBeInTheDocument(),
    )
    await user.click(
      screen.getByRole('button', { name: 'Delete Fall 2026 permanently' }),
    )

    await waitFor(() =>
      expect(getViewingSemesterChangeSnapshot()).toBe(before + 1),
    )
  })
})
