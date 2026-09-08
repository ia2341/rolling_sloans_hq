import { describe, expect, it } from 'vitest'

import type { RoleLegendEntry } from '../../api/setlistTypes'
import {
  clampCount,
  defaultCountFor,
  initialRoleCounts,
  roleGroupsFromRoles,
  visibleRoleGroups,
} from './roleCountStepModel'

function role(overrides: Partial<RoleLegendEntry>): RoleLegendEntry {
  return {
    id: 1,
    name: 'Lead Vocalist',
    code: 'LV',
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
  it('dedupes roles into their groups, ordered by group_order', () => {
    const roles = [
      role({ id: 1, group_name: 'Guitars', group_order: 1 }),
      role({ id: 2, group_name: 'Vocals', group_order: 0 }),
      role({ id: 3, group_name: 'Vocals', group_order: 0 }),
      role({
        id: 4,
        group_name: 'Other',
        group_order: 8,
        group_is_catch_all: true,
      }),
    ]

    expect(roleGroupsFromRoles(roles)).toEqual([
      { name: 'Vocals', order: 0 },
      { name: 'Guitars', order: 1 },
      { name: 'Other', order: 8 },
    ])
  })

  it('returns an empty list for no roles', () => {
    expect(roleGroupsFromRoles([])).toEqual([])
  })
})

describe('initialRoleCounts', () => {
  it("applies each group's logical default", () => {
    const groups = [
      { name: 'Vocals', order: 0 },
      { name: 'Saxophone', order: 5 },
    ]
    expect(initialRoleCounts(groups)).toEqual({ Vocals: 3, Saxophone: 0 })
  })
})

describe('visibleRoleGroups', () => {
  const groups = [
    { name: 'Vocals', order: 0 },
    { name: 'Saxophone', order: 5 },
    { name: 'Other', order: 8 },
  ]

  it('shows a group with a nonzero count on at least one row', () => {
    const counts = { 'song-1': { Vocals: 3, Saxophone: 0, Other: 0 } }
    expect(visibleRoleGroups(groups, counts, new Set())).toEqual([
      { name: 'Vocals', order: 0 },
    ])
  })

  it('hides a named default that every row zeroed out', () => {
    const counts = { 'song-1': { Vocals: 0, Saxophone: 0, Other: 0 } }
    expect(visibleRoleGroups(groups, counts, new Set())).toEqual([])
  })

  it('keeps an explicitly-added group visible even at all zero', () => {
    const counts = { 'song-1': { Vocals: 3, Saxophone: 0, Other: 0 } }
    expect(visibleRoleGroups(groups, counts, new Set(['Saxophone']))).toEqual([
      { name: 'Vocals', order: 0 },
      { name: 'Saxophone', order: 5 },
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
