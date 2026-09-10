import type { RoleLegendEntry } from '../../api/setlistTypes'

/** One column of the Add Songs role-count stepper table (issue #460, #462). */
export interface RoleGroupOption {
  /** The RoleGroup's id -- carried through so "Confirm Roles" can build a `role_group_counts` wire entry without a second lookup (issue #462). */
  id: number
  name: string
  order: number
}

/**
 * Every named Role Group's logical default count, applied to each staged
 * song when the role-count step opens (issue #460) -- any group not
 * listed here (including the catch-all) defaults to 0.
 */
const NAMED_DEFAULT_COUNTS: Record<string, number> = {
  Vocals: 3,
  Guitars: 2,
  Keyboards: 1,
  Drums: 1,
  Bass: 1,
}

/** A Role Group's logical default count -- 0 for anything not named above. */
export function defaultCountFor(groupName: string): number {
  return NAMED_DEFAULT_COUNTS[groupName] ?? 0
}

/**
 * Derives the distinct Role Groups from a Setlist payload's role legend
 * (issue #460) -- `active_roles_for()` returns every active Role
 * site-wide regardless of Semester, so this is the full current Role
 * Group catalog, not just groups already used by this Setlist's songs.
 * Ordered by the backend's `group_order`, matching the cast tables'
 * column order. Carries each group's `id` (issue #462) so "Confirm
 * Roles" can build a `role_group_counts` wire entry straight from this
 * list.
 */
export function roleGroupsFromRoles(
  roles: RoleLegendEntry[],
): RoleGroupOption[] {
  const byName = new Map<string, { id: number; order: number }>()
  for (const role of roles) {
    if (!byName.has(role.group_name))
      byName.set(role.group_name, {
        id: role.group_id,
        order: role.group_order,
      })
  }
  return Array.from(byName.entries())
    .map(([name, { id, order }]) => ({ id, name, order }))
    .sort((a, b) => a.order - b.order)
}

/** One staged song's per-group role counts, keyed by Role Group name. */
export type RoleCountRow = Record<string, number>

/** Builds a fresh counts row for one staged song, applying every group's logical default. */
export function initialRoleCounts(groups: RoleGroupOption[]): RoleCountRow {
  const row: RoleCountRow = {}
  for (const group of groups) row[group.name] = defaultCountFor(group.name)
  return row
}

/**
 * Which Role Group columns the table should render: a group with a
 * nonzero count for at least one staged song, or one the admin explicitly
 * revealed via "Add Role" -- an all-zero group is otherwise hidden, even
 * one of the five named defaults if every row's count was stepped down to
 * 0 (issue #460's acceptance criteria).
 */
export function visibleRoleGroups(
  groups: RoleGroupOption[],
  countsByRowKey: Record<string, RoleCountRow>,
  addedGroupNames: Set<string>,
): RoleGroupOption[] {
  return groups.filter((group) => {
    if (addedGroupNames.has(group.name)) return true
    return Object.values(countsByRowKey).some(
      (counts) => (counts[group.name] ?? 0) > 0,
    )
  })
}

/** Never below 0 (issue #460's stepper rule). */
export function clampCount(count: number): number {
  return Math.max(0, count)
}

/**
 * Builds one staged song's `role_group_counts` wire entries from its
 * counts row (issue #462) -- `AddSongsSheet`'s "Confirm Roles" calls this
 * once per staged row to merge the role-count step's state into the
 * setlist edit Buffer, in exactly the shape `EditRow.roleGroupCounts`
 * (and, from there, `buildBufferWire()`) expects.
 *
 * Deliberately omits any group with a count of 0 -- the backend's
 * `build_setlist_buffer_from_request()` rejects a `role_group_counts`
 * entry whose `count` is below 1 (`SongRoleRequirement.count` is never
 * meaningfully zero), so a group left at its default of 0, or stepped
 * back down to 0 after being revealed, must never reach the wire. This
 * is also what keeps today's "add songs with no role step" behavior
 * unregressed: a song with every count at 0 produces an empty list, the
 * same as a row that never went through this step at all.
 */
export function roleGroupCountsWireFor(
  groups: RoleGroupOption[],
  counts: RoleCountRow | undefined,
): { roleGroupId: number; count: number }[] {
  if (!counts) return []
  const entries: { roleGroupId: number; count: number }[] = []
  for (const group of groups) {
    const count = counts[group.name] ?? 0
    if (count > 0) entries.push({ roleGroupId: group.id, count })
  }
  return entries
}
