import { describe, expect, it } from 'vitest'

import {
  buildCastGridColumns,
  visibleCastGridColumns,
  type CastGridColumnRow,
} from './roleColumns'

describe('visibleCastGridColumns', () => {
  const roles = [
    { id: 1, name: 'Singer' },
    { id: 2, name: 'Drummer' },
  ]

  it('drops a column with zero matches across all rows', () => {
    const columns = buildCastGridColumns(roles)
    const rows: CastGridColumnRow[] = [
      {
        cast: [
          { role_id: 1, performers: [{ id: 1 }] },
          { role_id: 2, performers: [] },
        ],
      },
    ]

    const visible = visibleCastGridColumns(columns, rows)

    expect(visible.map((column) => column.label)).toEqual(['Singer'])
  })

  it('keeps a column with a match in only one row', () => {
    const columns = buildCastGridColumns(roles)
    const rows: CastGridColumnRow[] = [
      {
        cast: [
          { role_id: 1, performers: [] },
          { role_id: 2, performers: [] },
        ],
      },
      {
        cast: [
          { role_id: 1, performers: [] },
          { role_id: 2, performers: [{ id: 1 }] },
        ],
      },
    ]

    const visible = visibleCastGridColumns(columns, rows)

    expect(visible.map((column) => column.label)).toEqual(['Drums'])
  })

  it('never mutates the input column list, so the same columns can still be evaluated against another table', () => {
    const columns = buildCastGridColumns(roles)
    const emptyRows: CastGridColumnRow[] = [
      { cast: [{ role_id: 1, performers: [] }] },
    ]
    const filledRows: CastGridColumnRow[] = [
      { cast: [{ role_id: 1, performers: [{ id: 1 }] }] },
    ]

    expect(visibleCastGridColumns(columns, emptyRows)).toEqual([])
    expect(
      visibleCastGridColumns(columns, filledRows).map((column) => column.label),
    ).toEqual(['Singer'])
  })
})
