import { screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { resetContextForTests, setContext } from '../api/contextStore'
import { adminContext } from '../test/fixtures'
import { mockFetchOnce } from '../test/mockFetch'
import { mockMatchMedia } from '../test/mockMatchMedia'
import { renderShell } from '../test/renderShell'
import { DeleteSemesterDialog } from './DeleteSemesterDialog'

afterEach(() => {
  resetContextForTests()
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
})
