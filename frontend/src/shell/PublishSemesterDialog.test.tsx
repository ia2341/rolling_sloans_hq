import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'

import { resetContextForTests, setContext } from '../api/contextStore'
import { adminContext } from '../test/fixtures'
import { mockFetchOnce } from '../test/mockFetch'
import { mockMatchMedia } from '../test/mockMatchMedia'
import { renderShell } from '../test/renderShell'
import { PublishSemesterDialog } from './PublishSemesterDialog'

afterEach(() => {
  resetContextForTests()
  mockMatchMedia(false)
})

describe('PublishSemesterDialog', () => {
  it('renders both the loud and quiet tiers when superseding an incumbent', async () => {
    setContext(adminContext())
    mockFetchOnce(200, {
      context: adminContext(),
      data: {
        target_semester_id: 11,
        target_semester_name: 'Fall 2026',
        is_already_live: false,
        incumbent: { id: 10, name: 'Spring 2026' },
        incumbent_rehearsal_count: 4,
        incumbent_song_count: 10,
        has_no_setlist: false,
        has_no_rehearsals: false,
      },
    })
    renderShell(
      <PublishSemesterDialog
        open
        onOpenChange={() => {}}
        semesterId={11}
        semesterName="Fall 2026"
      />,
    )

    await waitFor(() =>
      expect(
        screen.getByText(/stop showing them Spring 2026/),
      ).toBeInTheDocument(),
    )
    expect(
      screen.getByText(
        /is not deleted or changed; publishing it again puts it back/,
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('heading', { name: 'Publish Fall 2026?' }),
    ).toBeInTheDocument()
  })

  it('shows the already-live single line and titles the dialog Re-publish', async () => {
    setContext(adminContext())
    mockFetchOnce(200, {
      context: adminContext(),
      data: {
        target_semester_id: 10,
        target_semester_name: 'Spring 2026',
        is_already_live: true,
        incumbent: null,
        incumbent_rehearsal_count: 0,
        incumbent_song_count: 0,
        has_no_setlist: false,
        has_no_rehearsals: false,
      },
    })
    renderShell(
      <PublishSemesterDialog
        open
        onOpenChange={() => {}}
        semesterId={10}
        semesterName="Spring 2026"
      />,
    )

    await waitFor(() =>
      expect(
        screen.getByText(/re-stamping it is harmless/),
      ).toBeInTheDocument(),
    )
    expect(
      screen.getByRole('heading', { name: 'Re-publish Spring 2026?' }),
    ).toBeInTheDocument()
  })

  it('shows the empty-setlist and no-rehearsals warnings when flagged', async () => {
    setContext(adminContext())
    mockFetchOnce(200, {
      context: adminContext(),
      data: {
        target_semester_id: 11,
        target_semester_name: 'Fall 2026',
        is_already_live: false,
        incumbent: null,
        incumbent_rehearsal_count: 0,
        incumbent_song_count: 0,
        has_no_setlist: true,
        has_no_rehearsals: true,
      },
    })
    renderShell(
      <PublishSemesterDialog
        open
        onOpenChange={() => {}}
        semesterId={11}
        semesterName="Fall 2026"
      />,
    )

    await waitFor(() =>
      expect(
        screen.getByText('Fall 2026 has no setlist yet.'),
      ).toBeInTheDocument(),
    )
    expect(
      screen.getByText('Fall 2026 has no rehearsals scheduled yet.'),
    ).toBeInTheDocument()
  })

  it('posts to publish/ on confirm', async () => {
    setContext(adminContext())
    mockFetchOnce(200, {
      context: adminContext(),
      data: {
        target_semester_id: 11,
        target_semester_name: 'Fall 2026',
        is_already_live: false,
        incumbent: null,
        incumbent_rehearsal_count: 0,
        incumbent_song_count: 0,
        has_no_setlist: false,
        has_no_rehearsals: false,
      },
    })
    const user = userEvent.setup()
    const onOpenChange = () => {}
    renderShell(
      <PublishSemesterDialog
        open
        onOpenChange={onOpenChange}
        semesterId={11}
        semesterName="Fall 2026"
      />,
    )

    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Publish Fall 2026' }),
      ).toBeEnabled(),
    )

    mockFetchOnce(200, {
      context: adminContext(),
      ok: true,
      errors: {},
      non_field_errors: [],
      fallout: null,
      values: null,
      data: null,
    })
    await user.click(screen.getByRole('button', { name: 'Publish Fall 2026' }))
  })
})
