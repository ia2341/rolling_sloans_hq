import { Fragment, useMemo, type ReactNode } from 'react'
import { Link } from 'react-router-dom'

import type { CastEntry } from '../../api/setlistTypes'
import { shortenNames } from '../../lib/names'
import {
  buildCastGridColumns,
  visibleCastGridColumns,
  type CastGridColumn,
  type CastGridRole,
} from '../../lib/roleColumns'

/**
 * One Role's performers as plain, linked text — no pills (UI overhaul: the
 * app no longer color-codes performers as pills). An unfilled Role renders
 * its short code plus a plain "-" (issue #365 -- a member should never read
 * the word "unfilled" as if a slot were broken); a filled one stacks each
 * performer's name, linking to their person page, with the viewer's own
 * name marked "(you)" and, for an admin viewer only, a compact
 * `RoleMismatchBadge` (ADR 0002) beside a mismatched performer's name -- the
 * underlying fact is never rendered to a non-admin (issue #365). Shared by
 * the Setlist table (one `CastCell` per role column) and the Song page's
 * `CastTable` (one `CastCell` per row).
 */
export function CastCell({
  entry,
  viewerId,
  isAdmin,
}: {
  entry: CastEntry
  viewerId?: number
  isAdmin: boolean
}) {
  if (entry.performers.length === 0) {
    return <span className="text-xs text-rs-muted">{entry.code} -</span>
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
          {performer.is_role_mismatch && isAdmin && <RoleMismatchBadge />}
        </div>
      ))}
    </div>
  )
}

/**
 * Compact visual marker for a Role Assignment saved outside the assigned
 * Person's declared Roles (person-level, ADR 0014; ADR 0002's
 * `is_role_mismatch`) -- admin-only, since the underlying fact is never
 * shown to a non-admin (issue #365).
 * Exported so a future admin-only grid (issue #366, Band tab redesign) can
 * reuse the same visual vocabulary instead of inventing its own; a caller
 * must only mount this once the viewer is confirmed to be an admin, and
 * should pair it with `RoleMismatchLegend` near the table it appears in.
 */
export function RoleMismatchBadge() {
  return (
    <span
      title="Assigned outside this member's usual roles"
      aria-label="Assigned outside this member's usual roles"
      className="ml-1 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-rs-warning-bg text-[10px] font-bold leading-none text-rs-warning-fg"
    >
      !
    </span>
  )
}

/**
 * One-line, admin-only explainer for `RoleMismatchBadge`, meant to be
 * rendered once near a cast table/grid rather than repeated per cell. It
 * renders unconditionally itself -- the caller is responsible for only
 * mounting it once the viewer is confirmed to be an admin, exactly like
 * `RoleMismatchBadge` itself.
 */
export function RoleMismatchLegend() {
  return (
    <p className="flex items-center gap-1 pb-2 text-xs text-rs-muted">
      <RoleMismatchBadge /> Highlighted cells are assigned outside that member's
      usual roles.
    </p>
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
  isAdmin,
}: {
  cast: CastEntry[]
  viewerId?: number
  isAdmin: boolean
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
              <CastCell entry={entry} viewerId={viewerId} isAdmin={isAdmin} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** One `CastGridTable` row — the Setlist's `SetlistSong` and the Schedule's `MatrixRow` both adapt into this shape. */
export interface CastGridRow {
  /** The Song id — both the row's key and what `onOpenRow`/`renderRecordingCell` act on. */
  id: number
  position: number
  title: string
  artist: string
  length: string
  /** Renders as a second full-width row underneath, exactly like the Setlist table always has — omitted entirely (no row) when absent or empty. */
  notes?: string
  cast: CastEntry[]
}

interface MergedPerformer {
  key: string
  id: number
  name: string
  is_role_mismatch: boolean
  kind?: 'assignment' | 'backup'
  has_conflict?: boolean
  tag: 'lead' | 'acoustic' | null
}

/**
 * Tags a Role name "lead" or "acoustic" for a merged cell's per-performer
 * label — "Female Leading Vocals" tags `lead`, "Rhythm Guitar" tags
 * nothing (only Lead and Acoustic are called out, per the band's own
 * naming). A display nuance within a merged column, independent of which
 * RoleGroup (issue #457) the Role belongs to.
 */
function tagForRoleName(roleName: string): 'lead' | 'acoustic' | null {
  const name = roleName.toLowerCase()
  if (name.includes('vocal')) return name.includes('lead') ? 'lead' : null
  if (name.includes('guitar')) {
    if (name.includes('lead')) return 'lead'
    if (name.includes('acoustic')) return 'acoustic'
  }
  return null
}

/** Collects every performer under `column`'s Roles into one list, lead-tagged performers first (stable otherwise) — the merged-cell shape item 11 of the UI overhaul round 2 asks for. */
function mergedPerformersFor(
  column: CastGridColumn,
  cast: CastEntry[],
): MergedPerformer[] {
  const merged: MergedPerformer[] = []
  for (const entry of cast) {
    if (!column.roleIds.includes(entry.role_id)) continue
    const tag = tagForRoleName(entry.role_name)
    for (const performer of entry.performers) {
      merged.push({
        key: `${entry.role_id}-${performer.kind ?? 'assignment'}-${performer.id}`,
        id: performer.id,
        name: performer.name,
        is_role_mismatch: performer.is_role_mismatch,
        kind: performer.kind,
        has_conflict: performer.has_conflict,
        tag,
      })
    }
  }
  return merged
    .map((performer, index) => ({ performer, index }))
    .sort((a, b) => {
      const aRank = a.performer.tag === 'lead' ? 0 : 1
      const bRank = b.performer.tag === 'lead' ? 0 : 1
      return aRank !== bRank ? aRank - bRank : a.index - b.index
    })
    .map(({ performer }) => performer)
}

/**
 * One merged cell (e.g. every Vocals Role's performers together) — a plain
 * "-" placeholder when empty and read-only, or, when `editable` (an
 * `onOpenCastCell` cell, issue #506), a "+ Cast" pill with its own small
 * background so an empty cell still visibly invites a click rather than
 * reading as inert dead space -- and, for an admin viewer only, a
 * `RoleMismatchBadge` beside a mismatched performer's name instead of an
 * inline text line.
 */
function CastGridCell({
  column,
  cast,
  viewerId,
  nameFor,
  isAdmin,
  editable,
}: {
  column: CastGridColumn
  cast: CastEntry[]
  viewerId?: number
  nameFor: (fullName: string) => string
  isAdmin: boolean
  editable: boolean
}) {
  const performers = mergedPerformersFor(column, cast)
  if (performers.length === 0) {
    return editable ? (
      <span className="rounded bg-rs-accent/10 px-1.5 py-0.5 text-xs font-medium text-rs-accent">
        + Cast
      </span>
    ) : (
      <span className="text-xs text-rs-muted">-</span>
    )
  }
  return (
    <div className="flex flex-col gap-1">
      {performers.map((performer) => (
        <div key={performer.key} className="text-sm">
          <Link to={`/members/${performer.id}`} className="text-rs-accent">
            {nameFor(performer.name)}
          </Link>
          {performer.tag !== null && (
            <span className="text-xs text-rs-muted"> ({performer.tag})</span>
          )}
          {performer.id === viewerId && (
            <span className="text-xs text-rs-muted"> (you)</span>
          )}
          {performer.kind === 'backup' && (
            <span className="text-xs text-rs-muted"> (backup)</span>
          )}
          {performer.has_conflict === true && (
            <span className="text-xs text-rs-muted"> away</span>
          )}
          {performer.is_role_mismatch && isAdmin && <RoleMismatchBadge />}
        </div>
      ))}
    </div>
  )
}

/**
 * The one Song × Role cast table the Setlist and the Schedule's "Running
 * order & assignments" read view both render (issue: UI overhaul round
 * 2, item 11) — `#`, `Song`, `Length`, then whatever fixed instrument
 * columns this Semester's Roles populate (`buildCastGridColumns()`), narrowed
 * to the ones any row in *this* table instance actually needs -- the
 * Setlist keys that on the Requirement's existence rather than whether
 * anyone is cast (issue #506), the Schedule's read-only matrix (which
 * carries no per-(Song, Role) Requirement data) on "has a performer"
 * (`visibleCastGridColumns()`, issue #436) -- a Role can still be declared
 * band-wide yet unused by every Song this particular Rehearsal or the
 * Setlist renders. Add Recording. Each row is itself the "Open" control, clicking anywhere
 * on it but a link or button navigates via `onOpenRow`. Performer names
 * are shortened to a first name (or `"First L."` on a collision) by
 * `shortenNames()`, scoped to whoever actually appears in `rows`.
 *
 * `isAdmin` gates the per-cell `RoleMismatchBadge` (issue #365, ADR 0002) --
 * the underlying fact is never shown to a non-admin, so both callers (the
 * Setlist and the Schedule's "Running order & assignments" view) must pass
 * the viewer's actual admin status; there's no default that could be safe
 * for both an admin and a non-admin caller.
 *
 * `onOpenCastCell` (issue #499, ADR 0019) turns each Role column's cell
 * into its own click target, opening the caller's inline cast popover for
 * that one (Song, column) pair instead of navigating. Every other cell
 * (`#`, `Song`, `Length`, `Add Recording`) keeps `onOpenRow` untouched.
 * Omit it — as the Schedule's read view does — and the Role cells behave
 * exactly as they always have.
 */
export function CastGridTable({
  roles,
  rows,
  viewerId,
  onOpenRow,
  onOpenCastCell,
  renderRecordingCell,
  isAdmin,
}: {
  roles: CastGridRole[]
  rows: CastGridRow[]
  viewerId?: number
  onOpenRow: (songId: number) => void
  onOpenCastCell?: (songId: number, column: CastGridColumn) => void
  renderRecordingCell: (row: CastGridRow) => ReactNode
  isAdmin: boolean
}) {
  const columns = useMemo(
    () => visibleCastGridColumns(buildCastGridColumns(roles), rows),
    [roles, rows],
  )
  const nameFor = useMemo(() => {
    const names = rows.flatMap((row) =>
      row.cast.flatMap((entry) =>
        entry.performers.map((performer) => performer.name),
      ),
    )
    const shortened = shortenNames(names)
    return (fullName: string) => shortened.get(fullName) ?? fullName
  }, [rows])

  const columnCount = 3 + columns.length + 1

  return (
    <table className="w-full border-collapse text-left text-sm">
      <thead>
        <tr>
          <th className="border border-rs-border px-2 py-2">#</th>
          <th className="border border-rs-border px-2 py-2">Song</th>
          <th className="border border-rs-border px-2 py-2">Length</th>
          {columns.map((column) => (
            <th key={column.key} className="border border-rs-border px-2 py-2">
              {column.label}
            </th>
          ))}
          <th className="border border-rs-border px-2 py-2">Add Recording</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <Fragment key={row.id}>
            <tr
              onClick={(event) => {
                if ((event.target as HTMLElement).closest('a, button')) return
                onOpenRow(row.id)
              }}
              onKeyDown={(event) => {
                if (event.key !== 'Enter' && event.key !== ' ') return
                if ((event.target as HTMLElement).closest('a, button')) return
                event.preventDefault()
                onOpenRow(row.id)
              }}
              tabIndex={0}
              role="button"
              aria-label={`Open ${row.title}`}
              className="cursor-pointer hover:bg-rs-border/10"
            >
              <td className="border border-rs-border px-2 py-2 align-top">
                {row.position}
              </td>
              <td className="border border-rs-border px-2 py-2 align-top">
                <p className="font-medium">{row.title}</p>
                <p className="text-rs-muted">{row.artist}</p>
              </td>
              <td className="border border-rs-border px-2 py-2 align-top">
                {row.length}
              </td>
              {columns.map((column) => (
                <td
                  key={column.key}
                  // No padding on the cell itself: the padding belongs to whichever
                  // element fills it below, so the editable variant's click target
                  // covers the whole cell rather than leaving a padded gutter that
                  // falls through to the row's own `onOpenRow` (PR #502 review).
                  className="border border-rs-border align-top"
                >
                  {onOpenCastCell === undefined ? (
                    <div className="px-2 py-2">
                      <CastGridCell
                        column={column}
                        cast={row.cast}
                        viewerId={viewerId}
                        nameFor={nameFor}
                        isAdmin={isAdmin}
                        editable={false}
                      />
                    </div>
                  ) : (
                    // A div, not a <button>: the cell's own content already
                    // contains person links, and an <a> inside a <button> is
                    // invalid HTML. The click/key handlers stop propagation so
                    // the enclosing row's `onOpenRow` doesn't also fire — its
                    // own `closest('a, button')` guard can't see through a div.
                    // It carries the cell's padding (see the <td> above) so the
                    // whole cell, gutters included, opens the cast editor.
                    <div
                      role="button"
                      tabIndex={0}
                      aria-label={`Edit ${column.label} on ${row.title}`}
                      onClick={(event) => {
                        if ((event.target as HTMLElement).closest('a')) return
                        event.stopPropagation()
                        onOpenCastCell(row.id, column)
                      }}
                      onKeyDown={(event) => {
                        if (event.key !== 'Enter' && event.key !== ' ') return
                        if ((event.target as HTMLElement).closest('a')) return
                        event.preventDefault()
                        event.stopPropagation()
                        onOpenCastCell(row.id, column)
                      }}
                      className="h-full w-full cursor-pointer px-2 py-2 text-left hover:bg-rs-border/20"
                    >
                      <CastGridCell
                        column={column}
                        cast={row.cast}
                        viewerId={viewerId}
                        nameFor={nameFor}
                        isAdmin={isAdmin}
                        editable
                      />
                    </div>
                  )}
                </td>
              ))}
              <td className="border border-rs-border px-2 py-2 align-top">
                {renderRecordingCell(row)}
              </td>
            </tr>
            {row.notes !== undefined && row.notes !== '' && (
              <tr>
                <td
                  colSpan={columnCount}
                  className="border border-rs-border px-2 pb-2 text-rs-muted"
                >
                  {row.notes}
                </td>
              </tr>
            )}
          </Fragment>
        ))}
      </tbody>
    </table>
  )
}
