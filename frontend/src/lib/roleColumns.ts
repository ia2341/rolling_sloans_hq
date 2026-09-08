/**
 * The Setlist and Schedule cast tables' shared column-building logic (issue #457): a
 * merged column per non-catch-all RoleGroup a Semester's Roles populate, ordered by
 * that group's `group_order`, followed by one column per catch-all-group Role — a
 * Role whose group is the catch-all still renders, in its own column, so a Role
 * naming nothing this band's fixed families cover is never silently dropped.
 *
 * The grouping itself is now a persisted server fact (`Role.group`, ADR-0016) —
 * this module only arranges the API-provided groups into columns; it no longer
 * classifies a Role name by keyword the way the retired `classifyRole()` did.
 */

/** The Role fields a cast table needs to place a Role into its column. */
export interface CastGridRole {
  id: number
  name: string
  group_name: string
  group_order: number
  group_is_catch_all: boolean
}

export interface CastGridColumn {
  key: string
  label: string
  /** Every Role id that folds into this one column — more than one for a merged group column, exactly one for a catch-all Role's own column. */
  roleIds: number[]
}

/** A `CastGridRow`-shaped value narrow enough for `columnHasPerformers`/`visibleCastGridColumns` to check without depending on `CastLine.tsx`'s full row type. */
export interface CastGridColumnRow {
  cast: { role_id: number; performers: unknown[] }[]
}

/** Whether at least one row's cast has a performer under any of `column`'s Role ids. */
function columnHasPerformers(
  column: CastGridColumn,
  rows: CastGridColumnRow[],
): boolean {
  return rows.some((row) =>
    row.cast.some(
      (entry) =>
        column.roleIds.includes(entry.role_id) && entry.performers.length > 0,
    ),
  )
}

/**
 * Narrows `columns` (from `buildCastGridColumns()`) to those with at least
 * one performer somewhere across `rows` — evaluated per table instance
 * (issue #436), since a Role can be globally declared yet unused by every
 * row a particular Setlist/Rehearsal table renders (e.g. a rehearsal whose
 * songs never call for Flute). A different table (another rehearsal, or
 * the Setlist) still gets its own pass over its own rows, so the same Role
 * can be hidden on one and shown on another.
 */
export function visibleCastGridColumns(
  columns: CastGridColumn[],
  rows: CastGridColumnRow[],
): CastGridColumn[] {
  return columns.filter((column) => columnHasPerformers(column, rows))
}

/**
 * Builds the Setlist/Schedule cast table's column list from whatever Roles
 * this Semester actually declares: one merged column per non-catch-all
 * RoleGroup present, ordered by `group_order`, followed by one column per
 * catch-all-group Role (each keeping its own name as its label, in the
 * order it appears in `roles`).
 */
export function buildCastGridColumns(roles: CastGridRole[]): CastGridColumn[] {
  const groupBuckets = new Map<string, { order: number; roleIds: number[] }>()
  const others: CastGridColumn[] = []

  for (const role of roles) {
    if (role.group_is_catch_all) {
      others.push({
        key: `role-${role.id}`,
        label: role.name,
        roleIds: [role.id],
      })
      continue
    }
    const bucket = groupBuckets.get(role.group_name)
    if (bucket === undefined) {
      groupBuckets.set(role.group_name, {
        order: role.group_order,
        roleIds: [role.id],
      })
    } else {
      bucket.roleIds.push(role.id)
    }
  }

  const groupColumns = [...groupBuckets.entries()]
    .sort(
      ([nameA, a], [nameB, b]) =>
        a.order - b.order || nameA.localeCompare(nameB),
    )
    .map(([name, bucket]) => ({
      key: `group-${name}`,
      label: name,
      roleIds: bucket.roleIds,
    }))

  return [...groupColumns, ...others]
}

/**
 * The fixed instrument-family buckets the Roster's filter checkboxes group
 * by (issue #366) — kept as this module's own case-insensitive keyword
 * match rather than the API-provided RoleGroup (issue #457), since
 * `/api/members/`'s `RosterEntry.roles` is `string[]` with no Role id: a
 * member's declared Role names carry no group to read. A Role name that
 * matches none of these keywords still gets its own bucket rather than
 * being dropped — see `classifyRosterRoleName()`.
 */
export type RosterFilterKey =
  | 'vocals'
  | 'guitars'
  | 'bass'
  | 'drums'
  | 'keyboards'
  | 'saxophone'
  | 'trumpet'
  | 'violin'
  | `role:${string}`

const ROSTER_FIXED_BUCKETS: {
  key: Exclude<RosterFilterKey, `role:${string}`>
  label: string
}[] = [
  { key: 'vocals', label: 'Vocals' },
  { key: 'guitars', label: 'Guitars' },
  { key: 'bass', label: 'Bass' },
  { key: 'drums', label: 'Drums' },
  { key: 'keyboards', label: 'Keyboards' },
  { key: 'saxophone', label: 'Saxophone' },
  { key: 'trumpet', label: 'Trumpet' },
  { key: 'violin', label: 'Violin' },
]

/** One filter checkbox: its bucket key and the label to render beside it. */
export interface RosterFilterBucket {
  key: RosterFilterKey
  label: string
}

/**
 * Classifies one Role name (by string) into its Roster filter bucket key —
 * a fixed instrument-family key by case-insensitive keyword, or
 * `role:<lowercased name>` for anything that matches none of them, so a
 * custom Role name always resolves to *some* bucket rather than being
 * dropped.
 */
export function classifyRosterRoleName(roleName: string): RosterFilterKey {
  const name = roleName.toLowerCase()
  if (name.includes('vocal')) return 'vocals'
  if (name.includes('guitar')) return 'guitars'
  if (name.includes('bass')) return 'bass'
  if (name.includes('drum')) return 'drums'
  if (name.includes('key')) return 'keyboards'
  if (name.includes('sax')) return 'saxophone'
  if (name.includes('trumpet')) return 'trumpet'
  if (name.includes('violin')) return 'violin'
  return `role:${name}` as RosterFilterKey
}

/**
 * Builds the Roster's filter-checkbox buckets from every member's role
 * names: the fixed instrument-family buckets with at least one match (in
 * `ROSTER_FIXED_BUCKETS` order), followed by every custom Role name that
 * matched none of them, alphabetically by name.
 */
export function buildRosterFilterBuckets(
  members: { roles: string[] }[],
): RosterFilterBucket[] {
  const fixedSeen = new Set<RosterFilterKey>()
  const customLabels = new Map<string, string>()

  for (const member of members) {
    for (const roleName of member.roles) {
      const key = classifyRosterRoleName(roleName)
      if (key.startsWith('role:')) {
        const lower = roleName.toLowerCase()
        if (!customLabels.has(lower)) customLabels.set(lower, roleName)
      } else {
        fixedSeen.add(key)
      }
    }
  }

  const fixedBuckets = ROSTER_FIXED_BUCKETS.filter(({ key }) =>
    fixedSeen.has(key),
  )

  const customBuckets = [...customLabels.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([lower, label]) => ({
      key: `role:${lower}` as RosterFilterKey,
      label,
    }))

  return [...fixedBuckets, ...customBuckets]
}

/**
 * Whether a member's role names match any of the checked filter buckets,
 * OR'd together. An empty `checked` set means "no filter" — everyone
 * matches.
 */
export function memberMatchesRosterFilter(
  roles: string[],
  checked: ReadonlySet<RosterFilterKey>,
): boolean {
  if (checked.size === 0) return true
  return roles.some((roleName) => checked.has(classifyRosterRoleName(roleName)))
}
