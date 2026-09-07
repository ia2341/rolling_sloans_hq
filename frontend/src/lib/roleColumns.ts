/**
 * The fixed instrument-family columns the Setlist and Schedule cast tables
 * share (issue: UI overhaul round 2, per the band's actual Role catalog:
 * Bass, Drums, Female/Male Backing/Leading Vocals, Guitar, Keyboard, Keys,
 * Lead Guitar, Rhythm Guitar, Saxophone, Trumpet, Violin, Vocals).
 *
 * A Role is free-text, admin-declared data (`scheduling/models.py:Role`
 * has no "category" field) — `classifyRole()` below groups one by
 * case-insensitive keyword match on its name rather than a schema field,
 * since adding one purely to support a column layout would be exactly the
 * kind of premature modeling CONTEXT.md's Role definition avoids. A Role
 * name that matches none of these keywords still renders — `buildCastGridColumns()`
 * gives it its own column — so a custom Role can never be silently dropped.
 */
export type FixedColumnKey =
  | 'vocals'
  | 'guitars'
  | 'bass'
  | 'drums'
  | 'keyboards'
  | 'saxophone'
  | 'trumpet'
  | 'violin'

const FIXED_COLUMNS: { key: FixedColumnKey; label: string }[] = [
  { key: 'vocals', label: 'Vocals' },
  { key: 'guitars', label: 'Guitars' },
  { key: 'bass', label: 'Bass' },
  { key: 'drums', label: 'Drums' },
  { key: 'keyboards', label: 'Keyboards' },
  { key: 'saxophone', label: 'Saxophone' },
  { key: 'trumpet', label: 'Trumpet' },
  { key: 'violin', label: 'Violin' },
]

export interface RoleClassification {
  /** `null` when this Role name matches none of the fixed families — it gets its own column instead of joining one. */
  column: FixedColumnKey | null
  /** How this performer is labeled within a merged Vocals/Guitars cell — "Female Leading Vocals" tags `lead`, "Rhythm Guitar" tags nothing (only Lead and Acoustic are called out, per the band's own naming). */
  tag: 'lead' | 'acoustic' | null
}

/** Classifies one Role name into a fixed column (or none) and a merged-cell tag, by case-insensitive keyword. */
export function classifyRole(roleName: string): RoleClassification {
  const name = roleName.toLowerCase()
  if (name.includes('vocal')) {
    return { column: 'vocals', tag: name.includes('lead') ? 'lead' : null }
  }
  if (name.includes('guitar')) {
    if (name.includes('lead')) return { column: 'guitars', tag: 'lead' }
    if (name.includes('acoustic')) return { column: 'guitars', tag: 'acoustic' }
    return { column: 'guitars', tag: null }
  }
  if (name.includes('bass')) return { column: 'bass', tag: null }
  if (name.includes('drum')) return { column: 'drums', tag: null }
  if (name.includes('key')) return { column: 'keyboards', tag: null }
  if (name.includes('sax')) return { column: 'saxophone', tag: null }
  if (name.includes('trumpet')) return { column: 'trumpet', tag: null }
  if (name.includes('violin')) return { column: 'violin', tag: null }
  return { column: null, tag: null }
}

export interface CastGridColumn {
  key: string
  label: string
  /** Every Role id that folds into this one column — more than one for a fixed column (e.g. all four Vocals Roles), exactly one for a custom Role's own column. */
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
 * Builds the Setlist/Schedule cast table's column list from whatever
 * Roles this Semester actually declares: the fixed families that have at
 * least one matching Role, in `FIXED_COLUMNS`' order, followed by any
 * Role that matched none of them, each getting its own column.
 */
export function buildCastGridColumns(
  roles: { id: number; name: string }[],
): CastGridColumn[] {
  const fixedRoleIds = new Map<FixedColumnKey, number[]>()
  const others: CastGridColumn[] = []

  for (const role of roles) {
    const { column } = classifyRole(role.name)
    if (column === null) {
      others.push({
        key: `role-${role.id}`,
        label: role.name,
        roleIds: [role.id],
      })
      continue
    }
    const bucket = fixedRoleIds.get(column)
    if (bucket === undefined) fixedRoleIds.set(column, [role.id])
    else bucket.push(role.id)
  }

  const fixedColumns = FIXED_COLUMNS.filter(({ key }) =>
    fixedRoleIds.has(key),
  ).map(({ key, label }) => ({
    key,
    label,
    roleIds: fixedRoleIds.get(key) ?? [],
  }))

  return [...fixedColumns, ...others]
}

/**
 * Bucket key for the Roster's filter checkboxes (issue #366): one of the
 * fixed instrument-family columns `classifyRole` recognizes, or a
 * `role:`-prefixed key holding a custom Role's lowercased name. `/api/members/`'s
 * `RosterEntry.roles` is `string[]` with no Role id, so — unlike
 * `CastGridColumn.roleIds` — this buckets by name rather than id.
 */
export type RosterFilterKey = FixedColumnKey | `role:${string}`

/** One filter checkbox: its bucket key and the label to render beside it. */
export interface RosterFilterBucket {
  key: RosterFilterKey
  label: string
}

/**
 * Classifies one Role name (by string) into its Roster filter bucket key —
 * a fixed column key via `classifyRole`, or `role:<lowercased name>` for
 * anything that matches none of the fixed families, so a custom Role name
 * always resolves to *some* bucket rather than being dropped.
 */
export function classifyRosterRoleName(roleName: string): RosterFilterKey {
  const { column } = classifyRole(roleName)
  return column ?? (`role:${roleName.toLowerCase()}` as RosterFilterKey)
}

/**
 * Builds the Roster's filter-checkbox buckets from every member's role
 * names: the fixed instrument-family columns with at least one match (in
 * `FIXED_COLUMNS` order), followed by every custom Role name that matched
 * none of them, alphabetically by name. Mirrors `buildCastGridColumns`'s
 * "no Role name is ever silently dropped" guarantee, just keyed by name
 * instead of Role id since a Roster entry carries no id.
 */
export function buildRosterFilterBuckets(
  members: { roles: string[] }[],
): RosterFilterBucket[] {
  const fixedSeen = new Set<FixedColumnKey>()
  const customLabels = new Map<string, string>()

  for (const member of members) {
    for (const roleName of member.roles) {
      const key = classifyRosterRoleName(roleName)
      if (key.startsWith('role:')) {
        const lower = roleName.toLowerCase()
        if (!customLabels.has(lower)) customLabels.set(lower, roleName)
      } else {
        fixedSeen.add(key as FixedColumnKey)
      }
    }
  }

  const fixedBuckets = FIXED_COLUMNS.filter(({ key }) =>
    fixedSeen.has(key),
  ).map(({ key, label }) => ({ key, label }))

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
