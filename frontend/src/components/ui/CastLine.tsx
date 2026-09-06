import { Fragment, useMemo, type ReactNode } from 'react'
import { Link } from 'react-router-dom'

import type { CastEntry } from '../../api/setlistTypes'
import { shortenNames } from '../../lib/names'
import {
  buildCastGridColumns,
  classifyRole,
  type CastGridColumn,
} from '../../lib/roleColumns'

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

/** Collects every performer under `column`'s Roles into one list, lead-tagged performers first (stable otherwise) — the merged-cell shape item 11 of the UI overhaul round 2 asks for. */
function mergedPerformersFor(
  column: CastGridColumn,
  cast: CastEntry[],
): MergedPerformer[] {
  const merged: MergedPerformer[] = []
  for (const entry of cast) {
    if (!column.roleIds.includes(entry.role_id)) continue
    const { tag } = classifyRole(entry.role_name)
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

/** One merged cell (e.g. every Vocals Role's performers together) — an "unfilled" placeholder when empty. */
function CastGridCell({
  column,
  cast,
  viewerId,
  nameFor,
}: {
  column: CastGridColumn
  cast: CastEntry[]
  viewerId?: number
  nameFor: (fullName: string) => string
}) {
  const performers = mergedPerformersFor(column, cast)
  if (performers.length === 0) {
    return <span className="text-xs text-rs-muted">unfilled</span>
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
 * The one Song × Role cast table the Setlist and the Schedule's "Running
 * order & assignments" read view both render (issue: UI overhaul round
 * 2, item 11) — `#`, `Song`, `Length`, then whatever fixed instrument
 * columns this Semester's Roles populate (`buildCastGridColumns()`), then
 * Add Recording. Each row is itself the "Open" control, clicking anywhere
 * on it but a link or button navigates via `onOpenRow`. Performer names
 * are shortened to a first name (or `"First L."` on a collision) by
 * `shortenNames()`, scoped to whoever actually appears in `rows`.
 */
export function CastGridTable({
  roles,
  rows,
  viewerId,
  onOpenRow,
  renderRecordingCell,
}: {
  roles: { id: number; name: string }[]
  rows: CastGridRow[]
  viewerId?: number
  onOpenRow: (songId: number) => void
  renderRecordingCell: (row: CastGridRow) => ReactNode
}) {
  const columns = useMemo(() => buildCastGridColumns(roles), [roles])
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
                  className="border border-rs-border px-2 py-2 align-top"
                >
                  <CastGridCell
                    column={column}
                    cast={row.cast}
                    viewerId={viewerId}
                    nameFor={nameFor}
                  />
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
