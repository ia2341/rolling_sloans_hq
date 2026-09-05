import type {
  PreviewChange,
  PreviewResult,
} from '../../api/previewTypes'
import type {
  SetlistEditBufferWire,
  SetlistEditFalloutWire,
  SetlistSong,
} from '../../api/setlistTypes'
import type { AppContext } from '../../api/types'

/**
 * `/api/setlist/{preview,save}/`'s write envelope, specialized over this
 * surface's own `errors` shape (`{row_key: {field: [messages]}}`) rather
 * than the generic envelope's flat `Record<string, string[]>` — every
 * error here is a per-row, per-field Validation Error (issue #334's
 * `SetlistBufferValidationError.row_errors`), never a bare field name.
 */
export interface SetlistWriteEnvelope {
  context: AppContext
  ok: boolean
  errors: Record<string, Record<string, string[]>>
  non_field_errors: string[]
  fallout: SetlistEditFalloutWire | null
  values: unknown
  data: null
}

/**
 * One row of the setlist editor's Pending Buffer, held entirely in client
 * state (issue #335). The grid *is* this Buffer and nothing else -- a
 * struck-through row, a `Moved 5→3` badge, an `Edited` badge and a `New`
 * badge are all derived from the fields here, never from a second,
 * server-computed shape (ADR 0008: only the server's Preview computes
 * Fallout; this is display-only bookkeeping).
 */
export interface EditRow {
  rowKey: string
  songId: number | null
  title: string
  artist: string
  /** `M:SS`/`H:MM:SS`, exactly what was typed -- never parsed client-side (issue #335's wire-primitives rule). */
  length: string
  notes: string
  /** Struck through and kept in place with Undo, rather than removed from the array (issue #335 user story 15). */
  deleted: boolean
  /** Where this row came from, only to badge a brand-new one (`New` vs. `New · from Spotify`). */
  origin: 'existing' | 'byhand' | 'spotify'
  /** `SetlistSong.recording_count` for an existing row; 0 for a row that was never saved. */
  recordingCount: number
  /** The saved values at load time, for an existing row -- `null` for a brand-new one, which has nothing to diff against. */
  original: { title: string; artist: string; length: string; notes: string } | null
  /** This row's 1-based concert position at load time -- `null` for a brand-new row. */
  originalPosition: number | null
}

let rowKeySequence = 0

/** Returns a fresh, render-stable row key (issue #335) -- never reused within one editing session. */
export function nextRowKey(prefix: string): string {
  rowKeySequence += 1
  return `${prefix}-${rowKeySequence}`
}

/** Builds the editor's initial Buffer rows from a freshly-loaded `/api/setlist/` payload. */
export function rowsFromPayload(songs: SetlistSong[]): EditRow[] {
  return songs.map((song) => ({
    rowKey: `song-${song.id}`,
    songId: song.id,
    title: song.title,
    artist: song.artist,
    length: song.length,
    notes: song.notes,
    deleted: false,
    origin: 'existing',
    recordingCount: song.recording_count,
    original: {
      title: song.title,
      artist: song.artist,
      length: song.length,
      notes: song.notes,
    },
    originalPosition: song.position,
  }))
}

/** Returns the rows that would survive a save, in final concert-position order. */
export function aliveRows(rows: EditRow[]): EditRow[] {
  return rows.filter((row) => !row.deleted)
}

/**
 * Swaps `rowKey`'s row with the next surviving row in `direction` (issue
 * #335 user stories 12-13, the up/down steppers). Deleted rows keep their
 * exact array slot and are skipped over rather than swapped with, so a
 * struck-through row never moves just because a neighbour reordered
 * around it. Returns `rows` unchanged if there's nowhere to move.
 */
export function moveAliveRow(rows: EditRow[], rowKey: string, direction: -1 | 1): EditRow[] {
  const aliveIndices = rows.reduce<number[]>((indices, row, index) => {
    if (!row.deleted) indices.push(index)
    return indices
  }, [])
  const fromFullIndex = rows.findIndex((row) => row.rowKey === rowKey)
  const fromAliveIndex = aliveIndices.indexOf(fromFullIndex)
  const toAliveIndex = fromAliveIndex + direction
  if (fromAliveIndex === -1 || toAliveIndex < 0 || toAliveIndex >= aliveIndices.length) return rows

  const toFullIndex = aliveIndices[toAliveIndex] as number
  const next = [...rows]
  const fromRow = next[fromFullIndex] as EditRow
  const toRow = next[toFullIndex] as EditRow
  next[fromFullIndex] = toRow
  next[toFullIndex] = fromRow
  return next
}

/** True if `row` differs from its saved snapshot; always `false` for a brand-new row (nothing to diff against). */
export function isEdited(row: EditRow): boolean {
  if (row.original === null) return false
  return (
    row.title !== row.original.title ||
    row.artist !== row.original.artist ||
    row.length !== row.original.length ||
    row.notes !== row.original.notes
  )
}

/** True if `row`'s position among the surviving rows differs from where it was saved. */
export function isMoved(row: EditRow, aliveIndex: number): boolean {
  return row.originalPosition !== null && row.originalPosition !== aliveIndex + 1
}

/** Returns the badges a grid row should render, in display order (issue #335 user stories 14, 31). */
export function rowBadges(row: EditRow, aliveIndex: number): string[] {
  if (row.deleted) return ['Deleted']
  if (row.original === null) {
    return [row.origin === 'spotify' ? 'New · from Spotify' : 'New']
  }
  const badges: string[] = []
  if (isMoved(row, aliveIndex)) badges.push(`Moved ${row.originalPosition}→${aliveIndex + 1}`)
  if (isEdited(row)) badges.push('Edited')
  return badges
}

/**
 * How many unsaved changes the toolbar should report (issue #335 user
 * story 3): every new row, every edit to an existing row, every deletion,
 * plus one flat count for "the order changed at all" -- a whole-Buffer
 * reorder is one change, not N, mirroring `SetlistEditFallout.reordered`'s
 * own boolean shape rather than inventing a finer-grained count the
 * server doesn't compute either.
 */
export function computeChangeCount(rows: EditRow[]): number {
  let count = 0
  let anyMoved = false
  const alive = aliveRows(rows)
  alive.forEach((row, index) => {
    if (row.original === null) {
      count += 1
      return
    }
    if (isEdited(row)) count += 1
    if (isMoved(row, index)) anyMoved = true
  })
  count += rows.filter((row) => row.deleted).length
  if (anyMoved) count += 1
  return count
}

/** Builds the `/api/setlist/{preview,save}/` request body from the current Buffer (issue #335). */
export function buildBufferWire(
  semesterId: number,
  semesterUpdatedAt: string,
  rows: EditRow[],
): SetlistEditBufferWire {
  const survivors = aliveRows(rows)
  return {
    semester_id: semesterId,
    semester_updated_at: semesterUpdatedAt,
    rows: survivors.map((row) => ({
      row_key: row.rowKey,
      song_id: row.songId,
      title: row.title,
      artist: row.artist,
      length: row.length,
      notes: row.notes,
    })),
    deleted_song_ids: rows
      .filter((row) => row.deleted && row.songId !== null)
      .map((row) => row.songId as number),
  }
}

const STALE_MESSAGE = 'The setlist changed while you were editing — reload and reapply.'

/**
 * Maps `/api/setlist/preview/`'s write envelope onto `SaveChangesDialog`'s
 * surface-agnostic `PreviewResult` (issue #335; `previewTypes.ts` supplies
 * no such mapping since it's specific to this one surface's server
 * shape). A stale Semester (`fallout.is_stale`) is folded into `ok: false`
 * with a `nonFieldErrors` message -- `SaveChangesDialog` disables Save
 * for any `!result.ok`, which is exactly issue #335 user story 6's
 * requirement, without this surface reaching into that shared
 * component's internals to add a bespoke "stale" state it doesn't have.
 */
export function mapSetlistPreviewToResult(
  envelope: SetlistWriteEnvelope,
): PreviewResult {
  if (!envelope.ok || envelope.fallout === null) {
    return {
      ok: false,
      changes: [],
      fallout: { loud: [], quiet: [] },
      errors: envelope.errors,
      nonFieldErrors: envelope.non_field_errors,
    }
  }

  const fallout = envelope.fallout
  if (fallout.is_stale) {
    return {
      ok: false,
      changes: [],
      fallout: { loud: [], quiet: [] },
      nonFieldErrors: [STALE_MESSAGE],
    }
  }

  const changes: PreviewChange[] = [
    ...fallout.pending_adds.map((title): PreviewChange => ({ op: 'Add', object: title })),
    ...fallout.pending_edits.map((description): PreviewChange => ({ op: 'Edit', object: description })),
    ...fallout.pending_deletions.map((deletion): PreviewChange => ({ op: 'Delete', object: deletion.title })),
  ]
  if (fallout.reordered) {
    changes.push({
      op: 'Move',
      object: 'Setlist order',
      why: 'concert position only',
    })
  }

  const destructive = fallout.pending_deletions.filter((deletion) => deletion.recording_count > 0)
  const totalRecordings = destructive.reduce((sum, deletion) => sum + deletion.recording_count, 0)
  const doomed =
    destructive.length > 0
      ? {
          heading: `${totalRecordings} Recording${totalRecordings === 1 ? '' : 's'} ${totalRecordings === 1 ? 'is' : 'are'} destroyed by this save`,
          items: destructive.map(
            (deletion) =>
              `${deletion.title} — ${deletion.recording_count} take${deletion.recording_count === 1 ? '' : 's'} from ${deletion.uploader_count} uploader${deletion.uploader_count === 1 ? '' : 's'}`,
          ),
        }
      : undefined

  return {
    ok: true,
    changes,
    fallout: { loud: fallout.loud, quiet: fallout.quiet },
    doomed,
  }
}
