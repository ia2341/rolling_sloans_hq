/** Slices an `HH:MM:SS` (or `HH:MM`) wire time down to `HH:MM`; `null` renders as `''`. */
export function formatClockTime(isoTime: string): string
export function formatClockTime(isoTime: string | null): string
export function formatClockTime(isoTime: string | null): string {
  return isoTime === null ? '' : isoTime.slice(0, 5)
}

function ordinal(day: number): string {
  const suffixes = ['th', 'st', 'nd', 'rd']
  const remainder = day % 100
  return `${day}${suffixes[(remainder - 20) % 10] ?? suffixes[remainder] ?? suffixes[0]}`
}

/**
 * Formats a `YYYY-MM-DD` wire date as `"23rd September, Wednesday"` — the
 * one date format used throughout the app (rehearsal rows, page titles,
 * the Schedule nav label). Parses the date-only string as local calendar
 * components (not via `new Date(iso)`, which reads `YYYY-MM-DD` as UTC
 * midnight and can land on the wrong day west of UTC).
 */
export function formatRehearsalDate(isoDate: string): string {
  const [year = 0, month = 1, day = 1] = isoDate.split('-').map(Number)
  const date = new Date(year, month - 1, day)
  const monthName = date.toLocaleDateString('en-US', { month: 'long' })
  const weekday = date.toLocaleDateString('en-US', { weekday: 'long' })
  return `${ordinal(day)} ${monthName}, ${weekday}`
}

/**
 * Formats a `YYYY-MM-DD` wire date as `MM/DD` — a compact form for tight
 * columns (Home's Song-progress table, issue: UI overhaul round 2), where
 * `formatRehearsalDate()`'s full form ("23rd September, Wednesday") would
 * crowd out the space a wider Notes column needs.
 */
export function formatShortDate(isoDate: string): string {
  const [, month = 1, day = 1] = isoDate.split('-').map(Number)
  return `${String(month).padStart(2, '0')}/${String(day).padStart(2, '0')}`
}
