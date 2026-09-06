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
