import { describe, expect, it } from 'vitest'

import {
  buildCastGridColumns,
  visibleCastGridColumns,
  type CastGridColumnRow,
  type CastGridRole,
} from './roleColumns'

describe('buildCastGridColumns', () => {
  it('merges every Role sharing a non-catch-all group into one column', () => {
    const roles: CastGridRole[] = [
      {
        id: 1,
        name: 'Male Lead Vocalist',
        group_name: 'Vocals',
        group_order: 0,
        group_is_catch_all: false,
      },
      {
        id: 2,
        name: 'Female Backing Vocalist',
        group_name: 'Vocals',
        group_order: 0,
        group_is_catch_all: false,
      },
    ]

    const columns = buildCastGridColumns(roles)

    expect(columns).toEqual([
      { key: 'group-Vocals', label: 'Vocals', roleIds: [1, 2] },
    ])
  })

  it('gives a catch-all-group Role its own column, keyed and labeled by the Role itself', () => {
    const roles: CastGridRole[] = [
      {
        id: 5,
        name: 'Tambourine',
        group_name: 'Other',
        group_order: 8,
        group_is_catch_all: true,
      },
    ]

    const columns = buildCastGridColumns(roles)

    expect(columns).toEqual([
      { key: 'role-5', label: 'Tambourine', roleIds: [5] },
    ])
  })

  it('orders merged group columns by group_order, ahead of every catch-all Role column', () => {
    const roles: CastGridRole[] = [
      {
        id: 1,
        name: 'Tambourine',
        group_name: 'Other',
        group_order: 8,
        group_is_catch_all: true,
      },
      {
        id: 2,
        name: 'Drummer',
        group_name: 'Drums',
        group_order: 3,
        group_is_catch_all: false,
      },
      {
        id: 3,
        name: 'Lead Vocalist',
        group_name: 'Vocals',
        group_order: 0,
        group_is_catch_all: false,
      },
    ]

    const columns = buildCastGridColumns(roles)

    expect(columns.map((column) => column.label)).toEqual([
      'Vocals',
      'Drums',
      'Tambourine',
    ])
  })

  it('breaks a group_order tie by group name, since display_order is not unique', () => {
    const roles: CastGridRole[] = [
      {
        id: 1,
        name: 'Drummer',
        group_name: 'Zzz Percussion',
        group_order: 1,
        group_is_catch_all: false,
      },
      {
        id: 2,
        name: 'Guitarist',
        group_name: 'Aaa Strings',
        group_order: 1,
        group_is_catch_all: false,
      },
    ]

    const columns = buildCastGridColumns(roles)

    expect(columns.map((column) => column.label)).toEqual([
      'Aaa Strings',
      'Zzz Percussion',
    ])
  })
})

describe('visibleCastGridColumns', () => {
  const roles = [
    {
      id: 1,
      name: 'Singer',
      group_name: 'Other',
      group_order: 8,
      group_is_catch_all: true,
    },
    {
      id: 2,
      name: 'Drummer',
      group_name: 'Drums',
      group_order: 3,
      group_is_catch_all: false,
    },
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
