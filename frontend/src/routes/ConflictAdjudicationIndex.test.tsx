import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { ConflictAdjudicationIndexRow } from '../api/conflictAdjudicationTypes'
import { adminContext } from '../test/fixtures'
import { mockFetchOnce } from '../test/mockFetch'
import { mockMatchMedia } from '../test/mockMatchMedia'
import { renderShell } from '../test/renderShell'
import { ConflictAdjudicationIndex } from './ConflictAdjudicationIndex'

function row(
  overrides: Partial<ConflictAdjudicationIndexRow> = {},
): ConflictAdjudicationIndexRow {
  return {
    rehearsal_id: 1,
    date: '2026-03-10',
    start_time: '19:00:00',
    end_time: '21:00:00',
    pending_count: 0,
    approved_count: 0,
    rejected_count: 0,
    ...overrides,
  }
}

describe('ConflictAdjudicationIndex', () => {
  it('renders a Rehearsal with zero Conflicts normally, not specially', async () => {
    mockMatchMedia(false)
    mockFetchOnce(200, { context: adminContext(), data: { rows: [row()] } })

    renderShell(<ConflictAdjudicationIndex />, ['/conflicts'])

    await screen.findByText('2026-03-10')
    expect(screen.getByText('19:00–21:00')).toBeInTheDocument()
    const zeros = screen.getAllByRole('cell', { name: '0' })
    expect(zeros).toHaveLength(3)
  })

  it('shows Adjudicate when pending_count > 0, Open otherwise', async () => {
    mockMatchMedia(false)
    mockFetchOnce(200, {
      context: adminContext(),
      data: {
        rows: [
          row({ rehearsal_id: 1, pending_count: 2 }),
          row({ rehearsal_id: 2, pending_count: 0 }),
        ],
      },
    })

    renderShell(<ConflictAdjudicationIndex />, ['/conflicts'])

    await screen.findByText('Adjudicate')
    expect(screen.getByText('Open')).toBeInTheDocument()
  })

  it('renders an empty-state sentence when there are no adjudicatable Rehearsals', async () => {
    mockMatchMedia(false)
    mockFetchOnce(200, { context: adminContext(), data: { rows: [] } })

    renderShell(<ConflictAdjudicationIndex />, ['/conflicts'])

    expect(
      await screen.findByText('No adjudicatable Rehearsals this Semester.'),
    ).toBeInTheDocument()
  })

  it('renders phone cards, not a table, at the phone breakpoint', async () => {
    mockMatchMedia(true)
    mockFetchOnce(200, {
      context: adminContext(),
      data: { rows: [row({ pending_count: 1 })] },
    })

    renderShell(<ConflictAdjudicationIndex />, ['/conflicts'])

    await screen.findByText('2026-03-10', { exact: false })
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.getByText('1 pending')).toBeInTheDocument()
  })
})
