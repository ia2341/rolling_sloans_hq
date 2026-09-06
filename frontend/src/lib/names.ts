/** Splits a full display name into its first name and last-initial, for `shortenNames()`'s collision check. */
function firstNameAndInitial(name: string): { first: string; initial: string } {
  const parts = name.trim().split(/\s+/)
  const first = parts[0] ?? name
  const last = parts.length > 1 ? (parts[parts.length - 1] ?? '') : ''
  const initial = last.length > 0 ? (last[0] ?? '').toUpperCase() : ''
  return { first, initial }
}

/**
 * Maps each full name in `names` to a short display form: first name
 * alone, or `"First L."` when that first name collides with another name
 * in the same list (issue: UI overhaul round 2 — the Setlist and Schedule
 * cast tables show only first names, disambiguated by last initial only
 * when this semester's membership actually has two of them).
 *
 * The uniqueness check is scoped to whatever `names` this table actually
 * rendered, not the whole roster — two members sharing a first name who
 * never appear in the same table never need disambiguating there.
 */
export function shortenNames(names: string[]): Map<string, string> {
  const distinct = [...new Set(names)]
  const byFirst = new Map<string, string[]>()
  for (const name of distinct) {
    const { first } = firstNameAndInitial(name)
    const bucket = byFirst.get(first)
    if (bucket === undefined) byFirst.set(first, [name])
    else bucket.push(name)
  }

  const result = new Map<string, string>()
  for (const name of distinct) {
    const { first, initial } = firstNameAndInitial(name)
    const bucket = byFirst.get(first) ?? []
    result.set(
      name,
      bucket.length > 1 && initial !== '' ? `${first} ${initial}.` : first,
    )
  }
  return result
}
