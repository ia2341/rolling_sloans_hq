import { describe, expect, it } from 'vitest'

import type { RoleLegendEntry } from '../../api/setlistTypes'
import {
  clampCount,
  defaultCountFor,
  initialRoleCounts,
  roleGroupCountsWireFor,
  roleGroupsFromRoles,
  visibleRoleGroups,
} from './roleCountStepModel'

/** Builds a `RoleLegendEntry` fixture (defaulting to a Vocals-group role), overriding just the fields a test cares about. */
function role(overrides: Partial<RoleLegendEntry>): RoleLegendEntry {
  return {
    id: 1,
    name: 'Lead Vocalist',
    code: 'LV',
    group_id: 100,
    group_name: 'Vocals',
    group_order: 0,
    group_is_catch_all: false,
    ...overrides,
  }
}

describe('defaultCountFor', () => {
  it("returns the named defaults for the five spec'd groups", () => {
    expect(defaultCountFor('Vocals')).toBe(3)
    expect(defaultCountFor('Guitars')).toBe(2)
    expect(defaultCountFor('Keyboards')).toBe(1)
    expect(defaultCountFor('Drums')).toBe(1)
    expect(defaultCountFor('Bass')).toBe(1)
  })

  it('defaults every other group to 0', () => {
    expect(defaultCountFor('Saxophone')).toBe(0)
    expect(defaultCountFor('Other')).toBe(0)
  })
})

describe('roleGroupsFromRoles', () => {
  it('dedupes roles into their groups, ordered by group_order, carrying each group id', () => {
    const roles = [
      role({ id: 1, group_id: 11, group_name: 'Guitars', group_order: 1 }),
      role({ id: 2, group_id: 10, group_name: 'Vocals', group_order: 0 }),
      role({ id: 3, group_id: 10, group_name: 'Vocals', group_order: 0 }),
      role({
        id: 4,
        group_id: 18,
        group_name: 'Other',
        group_order: 8,
        group_is_catch_all: true,
      }),
    ]

    expect(roleGroupsFromRoles(roles)).toEqual([
      { id: 10, name: 'Vocals', order: 0 },
      { id: 11, name: 'Guitars', order: 1 },
      { id: 18, name: 'Other', order: 8 },
    ])
  })

  it('returns an empty list for no roles', () => {
    expect(roleGroupsFromRoles([])).toEqual([])
  })
})

describe('initialRoleCounts', () => {
  it("applies each group's logical default", () => {
    const groups = [
      { id: 10, name: 'Vocals', order: 0 },
      { id: 16, name: 'Saxophone', order: 5 },
    ]
    expect(initialRoleCounts(groups)).toEqual({ Vocals: 3, Saxophone: 0 })
  })
})

describe('visibleRoleGroups', () => {
  const groups = [
    { id: 10, name: 'Vocals', order: 0 },
    { id: 16, name: 'Saxophone', order: 5 },
    { id: 18, name: 'Other', order: 8 },
  ]

  it('shows a group with a nonzero count on at least one row', () => {
    const counts = { 'song-1': { Vocals: 3, Saxophone: 0, Other: 0 } }
    expect(visibleRoleGroups(groups, counts, new Set())).toEqual([
      { id: 10, name: 'Vocals', order: 0 },
    ])
  })

  it('hides a named default that every row zeroed out', () => {
    const counts = { 'song-1': { Vocals: 0, Saxophone: 0, Other: 0 } }
    expect(visibleRoleGroups(groups, counts, new Set())).toEqual([])
  })

  it('keeps an explicitly-added group visible even at all zero', () => {
    const counts = { 'song-1': { Vocals: 3, Saxophone: 0, Other: 0 } }
    expect(visibleRoleGroups(groups, counts, new Set(['Saxophone']))).toEqual([
      { id: 10, name: 'Vocals', order: 0 },
      { id: 16, name: 'Saxophone', order: 5 },
    ])
  })
})

describe('clampCount', () => {
  it('never goes below 0', () => {
    expect(clampCount(-1)).toBe(0)
    expect(clampCount(0)).toBe(0)
    expect(clampCount(4)).toBe(4)
  })
})

describe('roleGroupCountsWireFor', () => {
  const groups = [
    { id: 10, name: 'Vocals', order: 0 },
    { id: 11, name: 'Guitars', order: 1 },
    { id: 16, name: 'Saxophone', order: 5 },
  ]

  it('emits one wire entry per group with a nonzero count, mapping name to id', () => {
    const counts = { Vocals: 3, Guitars: 2, Saxophone: 0 }
    expect(roleGroupCountsWireFor(groups, counts)).toEqual([
      { roleGroupId: 10, count: 3 },
      { roleGroupId: 11, count: 2 },
    ])
  })

  it('omits every all-zero group, regardless of whether it was ever revealed', () => {
    const counts = { Vocals: 0, Guitars: 0, Saxophone: 0 }
    expect(roleGroupCountsWireFor(groups, counts)).toEqual([])
  })

  it('returns an empty list for an undefined counts row', () => {
    expect(roleGroupCountsWireFor(groups, undefined)).toEqual([])
  })

  it('treats a group missing from the counts row as 0', () => {
    expect(roleGroupCountsWireFor(groups, { Vocals: 3 })).toEqual([
      { roleGroupId: 10, count: 3 },
    ])
  })
})
