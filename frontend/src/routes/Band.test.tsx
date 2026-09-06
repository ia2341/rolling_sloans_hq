import { screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { adminContext, memberContext } from '../test/fixtures'
import { mockFetchOnce } from '../test/mockFetch'
import { mockMatchMedia } from '../test/mockMatchMedia'
import { renderShell } from '../test/renderShell'
import { Band } from './Band'

/** A minimal `/api/members/` `data` payload: two members, one of them the viewer. */
function bandPayload(overrides: Record<string, unknown> = {}) {
  return {
    semester_name: 'Spring 2026',
    member_count: 2,
    members: [
      { id: 1, name: 'Sam Rivera', roles: ['Singer'], song_count: 3 },
      {
        id: 2,
        name: 'Alex Kim',
        roles: ['Drummer', 'Guitarist'],
        song_count: 1,
      },
    ],
    ...overrides,
  }
}

beforeEach(() => {
  mockMatchMedia(false)
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('Band', () => {
  it('renders the page head with the Semester name and member count', async () => {
    mockFetchOnce(200, { context: memberContext(), data: bandPayload() })

    renderShell(<Band />, ['/members'])

    expect(
      await screen.findByText('Spring 2026 · 2 members'),
    ).toBeInTheDocument()
  })

  it('renders the table on desktop, not cards', async () => {
    mockFetchOnce(200, { context: memberContext(), data: bandPayload() })

    renderShell(<Band />, ['/members'])

    expect(await screen.findByRole('table')).toBeInTheDocument()
  })

  it('renders phone cards, not a table, at the phone breakpoint', async () => {
    mockMatchMedia(true)
    mockFetchOnce(200, { context: memberContext(), data: bandPayload() })

    renderShell(<Band />, ['/members'])

    await screen.findByText('Sam Rivera', { exact: false })
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('marks only the viewer’s own row with a you chip', async () => {
    mockFetchOnce(200, { context: memberContext(), data: bandPayload() })

    renderShell(<Band />, ['/members'])

    await screen.findByText('Sam Rivera', { exact: false })
    const youChips = screen.getAllByText('you')
    expect(youChips).toHaveLength(1)
    // memberContext()'s viewer is id 1, "Sam Rivera" — confirm the chip sits inside that row.
    const samRow = screen.getByText('Sam Rivera').closest('tr')
    expect(samRow).toHaveTextContent('you')
    const alexRow = screen.getByText('Alex Kim').closest('tr')
    expect(alexRow).not.toHaveTextContent('you')
  })

  it('links every row to that member’s Person page', async () => {
    mockFetchOnce(200, { context: memberContext(), data: bandPayload() })

    renderShell(<Band />, ['/members'])

    await screen.findByText('Sam Rivera', { exact: false })
    expect(screen.getAllByRole('link', { name: 'Open' })[0]).toHaveAttribute(
      'href',
      '/members/1',
    )
  })

  it('renders an admin-only Edit roster action', async () => {
    mockFetchOnce(200, { context: adminContext(), data: bandPayload() })

    renderShell(<Band />, ['/members'])

    expect(
      await screen.findByRole('button', { name: 'Edit roster' }),
    ).toBeInTheDocument()
  })

  it('renders no Edit roster action for a non-admin', async () => {
    mockFetchOnce(200, { context: memberContext(), data: bandPayload() })

    renderShell(<Band />, ['/members'])

    await screen.findByText('Spring 2026', { exact: false })
    expect(
      screen.queryByRole('button', { name: 'Edit roster' }),
    ).not.toBeInTheDocument()
  })

  it('renders an empty-roster state', async () => {
    mockFetchOnce(200, {
      context: memberContext(),
      data: bandPayload({ members: [], member_count: 0 }),
    })

    renderShell(<Band />, ['/members'])

    expect(
      await screen.findByText('No one is on the Roster yet.'),
    ).toBeInTheDocument()
  })

  it('renders the pre-publish empty state when no Semester is published', async () => {
    mockFetchOnce(200, {
      context: memberContext(),
      data: { semester_name: null, member_count: 0, members: [] },
    })

    renderShell(<Band />, ['/members'])

    expect(
      (await screen.findAllByText('No Semester published yet.')).length,
    ).toBeGreaterThan(0)
  })
})
