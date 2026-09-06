import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { resetContextForTests, setContext } from '../api/contextStore'
import { adminContext } from '../test/fixtures'
import { mockMatchMedia } from '../test/mockMatchMedia'
import { renderShell } from '../test/renderShell'
import { SemesterPanel } from './SemesterPanel'

const draftOption = {
  id: 11,
  name: 'Fall 2026 (draft)',
  status: 'draft' as const,
  is_viewing: true,
  member_count: 5,
  song_count: 8,
  rehearsal_count: 3,
}
const liveOption = {
  id: 10,
  name: 'Spring 2026',
  status: 'live' as const,
  is_viewing: false,
  member_count: 6,
  song_count: 10,
  rehearsal_count: 4,
}
const options = [draftOption, liveOption]

afterEach(() => {
  resetContextForTests()
  vi.unstubAllGlobals()
  mockMatchMedia(false)
})

describe('SemesterPanel', () => {
  // Admin-only gating (`isAdmin && <SemesterPanel />`) lives in `Sidebar`,
  // not in this component — see `Sidebar.test.tsx`'s "renders the semester
  // panel only for an admin".

  it('names the viewing Semester and warns when it is not live', () => {
    setContext(adminContext({ semester_options: options }))
    renderShell(<SemesterPanel collapsed={false} />)

    expect(screen.getByText(/Viewing: Fall 2026/)).toBeInTheDocument()
    expect(
      screen.getByText('Not what members see — they see Spring 2026'),
    ).toBeInTheDocument()
  })

  it('lists dropdown options newest-first with a status chip, counts and a tick on the viewing option', async () => {
    setContext(adminContext({ semester_options: options }))
    const user = userEvent.setup()
    renderShell(<SemesterPanel collapsed={false} />)

    await user.click(screen.getByRole('button', { name: /Viewing: Fall 2026/ }))

    const menuItems = screen.getAllByRole('menuitem')
    expect(menuItems).toHaveLength(2)
    const [firstItem, secondItem] = menuItems as [HTMLElement, HTMLElement]
    expect(within(firstItem).getByText('Fall 2026 (draft)')).toBeInTheDocument()
    expect(within(firstItem).getByText('Draft')).toBeInTheDocument()
    expect(
      within(firstItem).getByText('5 members · 8 songs · 3 rehearsals'),
    ).toBeInTheDocument()
    expect(within(secondItem).getByText('Spring 2026')).toBeInTheDocument()
    expect(within(secondItem).getByText('Live')).toBeInTheDocument()
  })

  it('posts a select on picking an option and the panel updates from the response context', async () => {
    setContext(adminContext({ semester_options: options }))
    const fetchSpy = vi.fn().mockResolvedValue({
      status: 200,
      ok: true,
      json: () =>
        Promise.resolve({
          context: adminContext({
            viewing_semester: {
              id: 10,
              name: 'Spring 2026',
              status: 'live',
              published_at: '2026-01-01T00:00:00Z',
              updated_at: '2026-01-01T00:00:00Z',
            },
            semester_options: [
              { ...draftOption, is_viewing: false },
              { ...liveOption, is_viewing: true },
            ],
          }),
          ok: true,
          errors: {},
          non_field_errors: [],
          fallout: null,
          values: null,
          data: null,
        }),
    })
    vi.stubGlobal('fetch', fetchSpy)

    const user = userEvent.setup()
    renderShell(<SemesterPanel collapsed={false} />)

    await user.click(screen.getByRole('button', { name: /Viewing: Fall 2026/ }))
    await user.click(screen.getByText('Spring 2026'))

    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/semesters/select/',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ semester_id: 10 }),
      }),
    )
    await waitFor(() =>
      expect(screen.getByText(/Viewing: Spring 2026/)).toBeInTheDocument(),
    )
  })

  it('renders with only + New semester before any Semester exists', () => {
    setContext(
      adminContext({
        viewing_semester: null,
        live_semester: null,
        semester_warning: false,
        semester_options: [],
      }),
    )
    renderShell(<SemesterPanel collapsed={false} />)

    expect(screen.getByText('No Semester published yet.')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: '+ New semester' }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Publish' }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Save changes' }),
    ).not.toBeInTheDocument()
  })
})
