import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { apiFetch } from '../api/client'
import type { ConflictAdjudicationIndexRow } from '../api/conflictAdjudicationTypes'
import type { ReadEnvelope } from '../api/types'
import { PageHead } from '../components/ui/PageHead'
import { useIsPhone } from '../hooks/useIsPhone'
import { usePageTitle } from '../shell/PageTitleContext'

/** Formats a wire `HH:MM:SS` time string down to `HH:MM`, or `''` for `null`. */
function formatClockTime(isoTime: string | null): string {
  return isoTime === null ? '' : isoTime.slice(0, 5)
}

/** The rehearsal's date + window, shared by both layouts. */
function windowLabel(row: ConflictAdjudicationIndexRow): string {
  const window =
    row.end_time !== null
      ? `${formatClockTime(row.start_time)}–${formatClockTime(row.end_time)}`
      : formatClockTime(row.start_time)
  return `${row.date} · ${window}`
}

/**
 * `/conflicts/` (issue #340): the admin adjudication index — every
 * adjudicatable Rehearsal (future, non-Dress) with its pending/approved/
 * rejected Conflict counts, fed by one `GET /api/conflicts/` round trip.
 * Never shows a Person, a declaration, a reason or a note (ADR 0005) —
 * that detail lives one click away, on `/conflicts/:rehearsalId`.
 */
export function ConflictAdjudicationIndex() {
  usePageTitle('Conflicts')
  const isPhone = useIsPhone()
  const [rows, setRows] = useState<ConflictAdjudicationIndexRow[] | null>(null)

  useEffect(() => {
    let cancelled = false
    void apiFetch<ReadEnvelope<{ rows: ConflictAdjudicationIndexRow[] }>>(
      '/api/conflicts/',
    ).then((envelope) => {
      if (!cancelled) setRows(envelope.data.rows)
    })
    return () => {
      cancelled = true
    }
  }, [])

  if (rows === null) return null

  return (
    <div>
      <PageHead
        title="Conflicts"
        subline="Adjudicate Conflicts, Rehearsal by Rehearsal."
      />
      {rows.length === 0 ? (
        <p className="text-sm text-rs-muted">
          No adjudicatable Rehearsals this Semester.
        </p>
      ) : isPhone ? (
        <IndexCards rows={rows} />
      ) : (
        <IndexTable rows={rows} />
      )}
    </div>
  )
}

/** Returns `Adjudicate` while any Conflict is still pending, else `Open` (issue #340). */
function actionLabel(row: ConflictAdjudicationIndexRow): string {
  return row.pending_count > 0 ? 'Adjudicate' : 'Open'
}

/** The phone layout: one card per Rehearsal, no horizontal scroll. */
function IndexCards({ rows }: { rows: ConflictAdjudicationIndexRow[] }) {
  return (
    <ul className="flex flex-col gap-3">
      {rows.map((row) => (
        <li
          key={row.rehearsal_id}
          className="rounded border border-rs-border p-3"
        >
          <Link
            to={`/conflicts/${row.rehearsal_id}`}
            className="flex items-center justify-between gap-2"
          >
            <div>
              <p className="font-medium">{windowLabel(row)}</p>
              {row.pending_count > 0 && (
                <span className="mt-1 inline-block rounded-full bg-rs-accent px-2 py-0.5 text-xs font-medium text-rs-accent-fg">
                  {row.pending_count} pending
                </span>
              )}
            </div>
            <span aria-hidden="true" className="text-rs-muted">
              ▸
            </span>
          </Link>
        </li>
      ))}
    </ul>
  )
}

/** The desktop layout: `Rehearsal | Window | Pending | Approved | Rejected | [Adjudicate/Open]`. */
function IndexTable({ rows }: { rows: ConflictAdjudicationIndexRow[] }) {
  return (
    <table className="w-full text-left text-sm">
      <thead>
        <tr>
          <th className="pb-2">Rehearsal</th>
          <th className="pb-2">Window</th>
          <th className="pb-2">Pending</th>
          <th className="pb-2">Approved</th>
          <th className="pb-2">Rejected</th>
          <th className="pb-2" />
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.rehearsal_id}>
            <td className="py-2 align-top">{row.date}</td>
            <td className="py-2 align-top text-rs-muted">
              {row.end_time !== null
                ? `${formatClockTime(row.start_time)}–${formatClockTime(row.end_time)}`
                : formatClockTime(row.start_time)}
            </td>
            <td className="py-2 align-top">{row.pending_count}</td>
            <td className="py-2 align-top">{row.approved_count}</td>
            <td className="py-2 align-top">{row.rejected_count}</td>
            <td className="py-2 align-top">
              <Link
                to={`/conflicts/${row.rehearsal_id}`}
                className="text-rs-accent"
              >
                {actionLabel(row)}
              </Link>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
