import { Link } from 'react-router-dom'

import type { CastEntry } from '../../api/setlistTypes'

/**
 * One Role's performers as plain, linked text — no pills (UI overhaul: the
 * app no longer color-codes performers as pills). An unfilled Role shows
 * its short code plus "unfilled"; a filled one stacks each performer's
 * name, linking to their person page, with the viewer's own name marked
 * "(you)" and a role-mismatch marker (ADR 0002) on its own line. Shared by
 * the Setlist table (one `CastCell` per role column) and the Song page's
 * `CastTable` (one `CastCell` per row).
 */
export function CastCell({
  entry,
  viewerId,
}: {
  entry: CastEntry
  viewerId?: number
}) {
  if (entry.performers.length === 0) {
    return <span className="text-xs text-rs-muted">{entry.code} unfilled</span>
  }
  return (
    <div className="flex flex-col gap-1">
      {entry.performers.map((performer) => (
        <div key={performer.id} className="text-sm">
          <Link to={`/members/${performer.id}`} className="text-rs-accent">
            {performer.name}
          </Link>
          {performer.id === viewerId && (
            <span className="text-xs text-rs-muted"> (you)</span>
          )}
          {performer.is_role_mismatch && (
            <div className="text-xs text-rs-muted">
              ◦ role not on membership
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

/**
 * A Song's full cast as a Role | Performer(s) table (issue: pills/tables
 * UI overhaul) — the Song page's read-only cast section. Rows are Roles,
 * in the same fixed order the Setlist uses for its columns.
 */
export function CastTable({
  cast,
  viewerId,
}: {
  cast: CastEntry[]
  viewerId?: number
}) {
  return (
    <table className="w-full border-collapse text-left text-sm">
      <thead>
        <tr>
          <th className="border border-rs-border px-2 py-2">Role</th>
          <th className="border border-rs-border px-2 py-2">Performer(s)</th>
        </tr>
      </thead>
      <tbody>
        {cast.map((entry) => (
          <tr key={entry.role_id}>
            <td className="border border-rs-border px-2 py-2 align-top">
              {entry.role_name}
            </td>
            <td className="border border-rs-border px-2 py-2 align-top">
              <CastCell entry={entry} viewerId={viewerId} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
