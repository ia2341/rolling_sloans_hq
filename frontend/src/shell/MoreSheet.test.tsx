import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'

import { resetContextForTests, setContext } from '../api/contextStore'
import { adminContext, memberContext } from '../test/fixtures'
import { mockFetchOnce } from '../test/mockFetch'
import { renderShell } from '../test/renderShell'
import { MoreSheet } from './MoreSheet'

const semesterOptions = [
  {
    id: 11,
    name: 'Fall 2026 (draft)',
    status: 'draft' as const,
    is_viewing: true,
    member_count: 5,
    song_count: 8,
    rehearsal_count: 3,
  },
]

afterEach(() => {
  resetContextForTests()
})

describe('MoreSheet', () => {
  it('holds only Profile and Log out for a member', () => {
    setContext(memberContext())
    renderShell(<MoreSheet open onOpenChange={() => {}} />)

    expect(screen.getByText('Profile')).toBeInTheDocument()
    expect(screen.getByText('Log out')).toBeInTheDocument()
    expect(screen.queryByText('Switch semester')).not.toBeInTheDocument()
    expect(screen.queryByText('New semester')).not.toBeInTheDocument()
    expect(screen.queryByText('Manage semesters')).not.toBeInTheDocument()
  })

  it('holds the three semester items plus Profile and Log out for an admin', () => {
    setContext(adminContext())
    renderShell(<MoreSheet open onOpenChange={() => {}} />)

    expect(screen.getByText('Switch semester')).toBeInTheDocument()
    expect(screen.getByText('New semester')).toBeInTheDocument()
    expect(screen.getByText('Manage semesters')).toBeInTheDocument()
    expect(screen.getByText('Profile')).toBeInTheDocument()
    expect(screen.getByText('Log out')).toBeInTheDocument()
  })

  it('"Switch semester" closes the More sheet and opens the Viewing list', async () => {
    setContext(adminContext({ semester_options: semesterOptions }))
    const user = userEvent.setup()
    renderShell(<MoreSheet open onOpenChange={() => {}} />)

    await user.click(screen.getByText('Switch semester'))

    expect(screen.getByRole('heading', { name: 'Viewing' })).toBeInTheDocument()
    expect(
      screen.queryByRole('heading', { name: 'More' }),
    ).not.toBeInTheDocument()
    expect(screen.getByText('Fall 2026 (draft)')).toBeInTheDocument()
  })

  it('"New semester" closes the More sheet and opens NewSemesterDialog', async () => {
    setContext(adminContext({ semester_options: semesterOptions }))
    mockFetchOnce(200, {
      context: adminContext({ semester_options: semesterOptions }),
      data: { semester_defaults: null },
    })
    const user = userEvent.setup()
    renderShell(<MoreSheet open onOpenChange={() => {}} />)

    await user.click(screen.getByText('New semester'))

    expect(
      await screen.findByRole('heading', { name: 'New semester' }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('heading', { name: 'More' }),
    ).not.toBeInTheDocument()
  })

  it('"Manage semesters" closes the More sheet and opens ManageSemestersSheet', async () => {
    setContext(adminContext({ semester_options: semesterOptions }))
    mockFetchOnce(200, {
      context: adminContext({ semester_options: semesterOptions }),
      data: [],
    })
    const user = userEvent.setup()
    renderShell(<MoreSheet open onOpenChange={() => {}} />)

    await user.click(screen.getByText('Manage semesters'))

    expect(
      await screen.findByRole('heading', { name: 'Manage semesters' }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('heading', { name: 'More' }),
    ).not.toBeInTheDocument()
    await waitFor(() =>
      expect(
        screen.getByText(/Publishing changes what every member sees/),
      ).toBeInTheDocument(),
    )
  })
})
