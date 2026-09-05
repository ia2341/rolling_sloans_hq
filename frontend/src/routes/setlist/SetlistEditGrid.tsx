import { useState } from 'react'

import {
  aliveRows,
  rowBadges,
  type EditRow,
} from './setlistEditModel'

type Field = 'title' | 'artist' | 'length' | 'notes'

interface SetlistEditGridProps {
  rows: EditRow[]
  rowErrors: Record<string, Record<string, string[]>>
  onUpdateField: (rowKey: string, field: Field, value: string) => void
  onMoveUp: (rowKey: string) => void
  onMoveDown: (rowKey: string) => void
  onDelete: (rowKey: string) => void
  onUndoDelete: (rowKey: string) => void
  isPhone: boolean
}

/**
 * The setlist editor's grid (issue #335): the Pending Buffer and nothing
 * else -- a struck-through row, a `Moved 5→3` badge, an `Edited` badge and
 * a `New` badge are the edits themselves, so they live here rather than
 * deferred to the Save popup. Up/down steppers are the reordering
 * mechanism on every viewport (issue #335 user story 12); a drag library
 * is deliberately not wired in here -- nothing on this surface may
 * *require* drag to function, and the steppers alone satisfy that.
 */
export function SetlistEditGrid({
  rows,
  rowErrors,
  onUpdateField,
  onMoveUp,
  onMoveDown,
  onDelete,
  onUndoDelete,
  isPhone,
}: SetlistEditGridProps) {
  const alive = aliveRows(rows)

  if (rows.length === 0) {
    return <p className="text-sm text-rs-muted">No songs yet this Semester. Use + Add songs to start.</p>
  }

  if (isPhone) {
    return (
      <ul className="flex flex-col gap-2">
        {rows.map((row) => (
          <SetlistEditCard
            key={row.rowKey}
            row={row}
            aliveIndex={alive.indexOf(row)}
            aliveCount={alive.length}
            errors={rowErrors[row.rowKey] ?? {}}
            onUpdateField={onUpdateField}
            onMoveUp={onMoveUp}
            onMoveDown={onMoveDown}
            onDelete={onDelete}
            onUndoDelete={onUndoDelete}
          />
        ))}
      </ul>
    )
  }

  return (
    <table className="w-full text-left text-sm">
      <thead>
        <tr>
          <th className="pb-2">#</th>
          <th className="pb-2">Title</th>
          <th className="pb-2">Artist</th>
          <th className="pb-2">Length</th>
          <th className="pb-2">Takes</th>
          <th className="pb-2">Changes</th>
          <th className="pb-2" />
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const aliveIndex = alive.indexOf(row)
          const errors = rowErrors[row.rowKey] ?? {}
          const badges = rowBadges(row, aliveIndex)
          return (
            <SetlistEditTableRow
              key={row.rowKey}
              row={row}
              aliveIndex={aliveIndex}
              aliveCount={alive.length}
              errors={errors}
              badges={badges}
              onUpdateField={onUpdateField}
              onMoveUp={onMoveUp}
              onMoveDown={onMoveDown}
              onDelete={onDelete}
              onUndoDelete={onUndoDelete}
            />
          )
        })}
      </tbody>
    </table>
  )
}

function FieldErrors({ messages }: { messages?: string[] }) {
  if (!messages || messages.length === 0) return null
  return (
    <>
      {messages.map((message) => (
        <p key={message} className="text-xs text-rs-danger">
          {message}
        </p>
      ))}
    </>
  )
}

function RowBadges({ badges }: { badges: string[] }) {
  if (badges.length === 0) return null
  return (
    <span className="flex flex-wrap gap-1">
      {badges.map((badge) => (
        <span
          key={badge}
          className="rounded bg-rs-border/60 px-1.5 py-0.5 text-xs font-medium"
        >
          {badge}
        </span>
      ))}
    </span>
  )
}

function SetlistEditTableRow({
  row,
  aliveIndex,
  aliveCount,
  errors,
  badges,
  onUpdateField,
  onMoveUp,
  onMoveDown,
  onDelete,
  onUndoDelete,
}: {
  row: EditRow
  aliveIndex: number
  aliveCount: number
  errors: Record<string, string[]>
  badges: string[]
  onUpdateField: (rowKey: string, field: Field, value: string) => void
  onMoveUp: (rowKey: string) => void
  onMoveDown: (rowKey: string) => void
  onDelete: (rowKey: string) => void
  onUndoDelete: (rowKey: string) => void
}) {
  const [notesOpen, setNotesOpen] = useState(row.notes !== '')

  if (row.deleted) {
    return (
      <tr className="opacity-60">
        <td className="py-2 align-top" />
        <td className="py-2 align-top line-through" colSpan={4}>
          {row.title} · {row.artist}
        </td>
        <td className="py-2 align-top">
          <RowBadges badges={badges} />
        </td>
        <td className="py-2 align-top">
          <button
            type="button"
            onClick={() => onUndoDelete(row.rowKey)}
            className="text-sm underline"
          >
            Undo
          </button>
        </td>
      </tr>
    )
  }

  return (
    <tr>
      <td className="py-2 align-top">{aliveIndex + 1}</td>
      <td className="py-2 align-top">
        <input
          aria-label={`Title for row ${aliveIndex + 1}`}
          type="text"
          value={row.title}
          onChange={(event) => onUpdateField(row.rowKey, 'title', event.target.value)}
          className="w-full rounded border border-rs-border px-2 py-1"
        />
        <FieldErrors messages={errors.title} />
        <button
          type="button"
          onClick={() => setNotesOpen((open) => !open)}
          className="pt-1 text-xs text-rs-muted underline"
        >
          {notesOpen ? '▾ Notes' : '▸ Notes'}
        </button>
        {notesOpen && (
          <textarea
            aria-label={`Notes for row ${aliveIndex + 1}`}
            value={row.notes}
            onChange={(event) => onUpdateField(row.rowKey, 'notes', event.target.value)}
            className="mt-1 block w-full rounded border border-rs-border px-2 py-1 text-xs"
          />
        )}
      </td>
      <td className="py-2 align-top">
        <input
          aria-label={`Artist for row ${aliveIndex + 1}`}
          type="text"
          value={row.artist}
          onChange={(event) => onUpdateField(row.rowKey, 'artist', event.target.value)}
          className="w-full rounded border border-rs-border px-2 py-1"
        />
        <FieldErrors messages={errors.artist} />
      </td>
      <td className="py-2 align-top">
        <input
          aria-label={`Length for row ${aliveIndex + 1}`}
          type="text"
          value={row.length}
          onChange={(event) => onUpdateField(row.rowKey, 'length', event.target.value)}
          placeholder="3:45"
          className="w-20 rounded border border-rs-border px-2 py-1"
        />
        <FieldErrors messages={errors.length} />
      </td>
      <td className="py-2 align-top">
        {row.recordingCount > 0 ? `${row.recordingCount} takes` : '—'}
      </td>
      <td className="py-2 align-top">
        <RowBadges badges={badges} />
      </td>
      <td className="py-2 align-top">
        <div className="flex flex-col gap-1">
          <div className="flex gap-1">
            <button
              type="button"
              onClick={() => onMoveUp(row.rowKey)}
              disabled={aliveIndex === 0}
              aria-label={`Move row ${aliveIndex + 1} up`}
              className="rounded border border-rs-border px-1.5 py-0.5 text-xs disabled:cursor-not-allowed disabled:opacity-40"
            >
              ↑
            </button>
            <button
              type="button"
              onClick={() => onMoveDown(row.rowKey)}
              disabled={aliveIndex === aliveCount - 1}
              aria-label={`Move row ${aliveIndex + 1} down`}
              className="rounded border border-rs-border px-1.5 py-0.5 text-xs disabled:cursor-not-allowed disabled:opacity-40"
            >
              ↓
            </button>
          </div>
          <button
            type="button"
            onClick={() => onDelete(row.rowKey)}
            className="text-xs text-rs-danger underline"
          >
            Delete
          </button>
        </div>
      </td>
    </tr>
  )
}

/** The phone layout: an accordion card per row -- summary line, then every desktop field plus Move up/down and Delete/Undo (issue #335 user stories 18-19). */
function SetlistEditCard({
  row,
  aliveIndex,
  aliveCount,
  errors,
  onUpdateField,
  onMoveUp,
  onMoveDown,
  onDelete,
  onUndoDelete,
}: {
  row: EditRow
  aliveIndex: number
  aliveCount: number
  errors: Record<string, string[]>
  onUpdateField: (rowKey: string, field: Field, value: string) => void
  onMoveUp: (rowKey: string) => void
  onMoveDown: (rowKey: string) => void
  onDelete: (rowKey: string) => void
  onUndoDelete: (rowKey: string) => void
}) {
  const [open, setOpen] = useState(false)
  const badges = rowBadges(row, aliveIndex)

  if (row.deleted) {
    return (
      <li className="rounded border border-rs-border p-3 opacity-60">
        <p className="line-through">
          {aliveIndex >= 0 ? `${aliveIndex + 1}. ` : ''}
          {row.title}
        </p>
        <button type="button" onClick={() => onUndoDelete(row.rowKey)} className="text-sm underline">
          Undo
        </button>
      </li>
    )
  }

  return (
    <li className="rounded border border-rs-border p-3">
      <button
        type="button"
        onClick={() => setOpen((next) => !next)}
        className="flex w-full items-start justify-between gap-2 text-left"
      >
        <span>
          <span className="font-medium">
            {aliveIndex + 1}. {row.title}
          </span>
          <span className="block text-rs-muted">
            {row.artist} · {row.length}
            {row.recordingCount > 0 ? ` · ${row.recordingCount} takes` : ''}
          </span>
          <RowBadges badges={badges} />
        </span>
        <span aria-hidden="true">{open ? '▾' : '▸'}</span>
      </button>

      {open && (
        <div className="mt-2 flex flex-col gap-2 border-t border-rs-border pt-2">
          <div>
            <label className="text-xs" htmlFor={`title-${row.rowKey}`}>
              Title
            </label>
            <input
              id={`title-${row.rowKey}`}
              type="text"
              value={row.title}
              onChange={(event) => onUpdateField(row.rowKey, 'title', event.target.value)}
              className="mt-1 block w-full rounded border border-rs-border px-2 py-1 text-sm"
            />
            <FieldErrors messages={errors.title} />
          </div>
          <div>
            <label className="text-xs" htmlFor={`artist-${row.rowKey}`}>
              Artist
            </label>
            <input
              id={`artist-${row.rowKey}`}
              type="text"
              value={row.artist}
              onChange={(event) => onUpdateField(row.rowKey, 'artist', event.target.value)}
              className="mt-1 block w-full rounded border border-rs-border px-2 py-1 text-sm"
            />
            <FieldErrors messages={errors.artist} />
          </div>
          <div>
            <label className="text-xs" htmlFor={`length-${row.rowKey}`}>
              Length
            </label>
            <input
              id={`length-${row.rowKey}`}
              type="text"
              value={row.length}
              onChange={(event) => onUpdateField(row.rowKey, 'length', event.target.value)}
              className="mt-1 block w-full rounded border border-rs-border px-2 py-1 text-sm"
            />
            <FieldErrors messages={errors.length} />
          </div>
          <p className="text-xs text-rs-muted">Position {aliveIndex + 1} of {aliveCount}</p>
          <div>
            <label className="text-xs" htmlFor={`notes-${row.rowKey}`}>
              Notes
            </label>
            <textarea
              id={`notes-${row.rowKey}`}
              value={row.notes}
              onChange={(event) => onUpdateField(row.rowKey, 'notes', event.target.value)}
              className="mt-1 block w-full rounded border border-rs-border px-2 py-1 text-sm"
            />
          </div>
          <div className="flex items-center justify-between pt-1">
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => onMoveUp(row.rowKey)}
                disabled={aliveIndex === 0}
                className="rounded border border-rs-border px-2 py-1 text-xs disabled:cursor-not-allowed disabled:opacity-40"
              >
                ↑ Move up
              </button>
              <button
                type="button"
                onClick={() => onMoveDown(row.rowKey)}
                disabled={aliveIndex === aliveCount - 1}
                className="rounded border border-rs-border px-2 py-1 text-xs disabled:cursor-not-allowed disabled:opacity-40"
              >
                ↓ Move down
              </button>
            </div>
            <button
              type="button"
              onClick={() => onDelete(row.rowKey)}
              className="text-xs text-rs-danger underline"
            >
              Delete
            </button>
          </div>
        </div>
      )}
    </li>
  )
}
