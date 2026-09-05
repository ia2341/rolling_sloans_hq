import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { apiFetch } from '../api/client'
import { useAppContext } from '../api/ContextProvider'
import type { PreviewResult } from '../api/previewTypes'
import type { SetlistPayload } from '../api/setlistTypes'
import type { ReadEnvelope } from '../api/types'
import { CastLine } from '../components/ui/CastLine'
import { PageHead } from '../components/ui/PageHead'
import { RoleLegend } from '../components/ui/RoleLegend'
import { SaveChangesDialog } from '../components/ui/SaveChangesDialog'
import { useIsPhone } from '../hooks/useIsPhone'
import { useRegisterEditSession } from '../shell/EditSessionContext'
import { usePageTitle } from '../shell/PageTitleContext'
import { AddSongsSheet } from './setlist/AddSongsSheet'
import { SetlistEditGrid } from './setlist/SetlistEditGrid'
import {
  buildBufferWire,
  computeChangeCount,
  mapSetlistPreviewToResult,
  moveAliveRow,
  rowsFromPayload,
  type EditRow,
  type SetlistWriteEnvelope,
} from './setlist/setlistEditModel'

type EditField = 'title' | 'artist' | 'length' | 'notes'

/**
 * `/setlist/` (issues #330, #335): the viewing Semester's whole Setlist,
 * fed by one `GET /api/setlist/` round trip, plus (for an admin) its own
 * edit mode -- the same page flips into a Pending-Buffer grid rather than
 * navigating anywhere else (issue #335 user story 2), so nothing shifts
 * underfoot when editing starts. Renders nothing until the initial read
 * arrives.
 */
export function Setlist() {
  usePageTitle('Setlist')
  const appContext = useAppContext()
  const isPhone = useIsPhone()
  const [data, setData] = useState<SetlistPayload | null>(null)
  const [isEditing, setIsEditing] = useState(false)
  const [rows, setRows] = useState<EditRow[]>([])
  const [rowErrors, setRowErrors] = useState<Record<string, Record<string, string[]>>>({})
  const [addSheetOpen, setAddSheetOpen] = useState(false)
  const [saveDialogOpen, setSaveDialogOpen] = useState(false)

  const load = useCallback(() => {
    void apiFetch<ReadEnvelope<SetlistPayload>>('/api/setlist/').then((envelope) => {
      setData(envelope.data)
    })
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const viewingSemester = appContext?.viewing_semester ?? null

  const startEditing = useCallback(() => {
    if (data === null) return
    setRows(rowsFromPayload(data.songs))
    setRowErrors({})
    setIsEditing(true)
  }, [data])

  const discard = useCallback(() => {
    setIsEditing(false)
    setRows([])
    setRowErrors({})
  }, [])

  const requestSave = useCallback(() => setSaveDialogOpen(true), [])

  const updateField = useCallback((rowKey: string, field: EditField, value: string) => {
    setRows((current) =>
      current.map((row) => (row.rowKey === rowKey ? { ...row, [field]: value } : row)),
    )
  }, [])

  const moveUp = useCallback((rowKey: string) => {
    setRows((current) => moveAliveRow(current, rowKey, -1))
  }, [])

  const moveDown = useCallback((rowKey: string) => {
    setRows((current) => moveAliveRow(current, rowKey, 1))
  }, [])

  const deleteRow = useCallback((rowKey: string) => {
    setRows((current) => {
      const row = current.find((candidate) => candidate.rowKey === rowKey)
      if (!row) return current
      // A never-saved row has nothing to undo to -- delete just removes it.
      if (row.songId === null) return current.filter((candidate) => candidate.rowKey !== rowKey)
      return current.map((candidate) =>
        candidate.rowKey === rowKey ? { ...candidate, deleted: true } : candidate,
      )
    })
  }, [])

  const undoDelete = useCallback((rowKey: string) => {
    setRows((current) =>
      current.map((row) => (row.rowKey === rowKey ? { ...row, deleted: false } : row)),
    )
  }, [])

  const addRows = useCallback((newRows: EditRow[]) => {
    setRows((current) => [...current, ...newRows])
  }, [])

  const previewSetlist = useCallback((): Promise<PreviewResult> => {
    if (viewingSemester === null) {
      return Promise.resolve({
        ok: false,
        changes: [],
        fallout: { loud: [], quiet: [] },
        nonFieldErrors: ['No Semester is selected to save against.'],
      })
    }
    const body = buildBufferWire(viewingSemester.id, viewingSemester.updated_at, rows)
    return apiFetch<SetlistWriteEnvelope>('/api/setlist/preview/', {
      method: 'POST',
      body: JSON.stringify(body),
    }).then((envelope) => {
      setRowErrors(envelope.errors)
      return mapSetlistPreviewToResult(envelope)
    })
  }, [rows, viewingSemester])

  const confirmSave = useCallback(() => {
    if (viewingSemester === null) return
    const body = buildBufferWire(viewingSemester.id, viewingSemester.updated_at, rows)
    void apiFetch<SetlistWriteEnvelope>('/api/setlist/save/', {
      method: 'POST',
      body: JSON.stringify(body),
    }).then((envelope) => {
      if (!envelope.ok) return
      setSaveDialogOpen(false)
      setIsEditing(false)
      setRows([])
      setRowErrors({})
      load()
    })
  }, [rows, viewingSemester, load])

  const changeCount = useMemo(() => computeChangeCount(rows), [rows])

  if (data === null) return null

  const subline =
    data.semester_name === null
      ? 'No Semester published yet.'
      : `${data.semester_name} · ${data.song_count} song${data.song_count === 1 ? '' : 's'} · ${data.total_running_time}`

  return (
    <div>
      {isEditing && viewingSemester !== null && (
        <SetlistEditSessionRegistrar
          semesterName={viewingSemester.name}
          changeCount={changeCount}
          discard={discard}
          requestSave={requestSave}
        />
      )}
      <PageHead
        title="Setlist"
        subline={subline}
        action={
          !appContext?.viewer.is_admin ? undefined : isEditing ? (
            <button
              type="button"
              onClick={() => setAddSheetOpen(true)}
              className="rounded bg-rs-accent px-3 py-1.5 text-sm font-medium text-rs-accent-fg"
            >
              + Add songs
            </button>
          ) : (
            <button
              type="button"
              onClick={startEditing}
              className="rounded bg-rs-accent px-3 py-1.5 text-sm font-medium text-rs-accent-fg"
            >
              Edit setlist
            </button>
          )
        }
      />
      {data.roles.length > 0 && !isEditing && (
        <div className="flex flex-wrap pb-4">
          <RoleLegend
            roles={data.roles.map((role, index) => ({
              index,
              name: role.name,
            }))}
          />
        </div>
      )}
      {isEditing ? (
        <SetlistEditGrid
          rows={rows}
          rowErrors={rowErrors}
          onUpdateField={updateField}
          onMoveUp={moveUp}
          onMoveDown={moveDown}
          onDelete={deleteRow}
          onUndoDelete={undoDelete}
          isPhone={isPhone}
        />
      ) : data.songs.length === 0 ? (
        <p className="text-sm text-rs-muted">No songs yet this Semester.</p>
      ) : isPhone ? (
        <SetlistCards songs={data.songs} viewerId={appContext?.viewer.id} />
      ) : (
        <SetlistTable songs={data.songs} viewerId={appContext?.viewer.id} />
      )}

      <AddSongsSheet open={addSheetOpen} onOpenChange={setAddSheetOpen} onAddRows={addRows} />

      {viewingSemester !== null && (
        <SaveChangesDialog
          open={saveDialogOpen}
          onOpenChange={setSaveDialogOpen}
          title={`Save ${changeCount} change${changeCount === 1 ? '' : 's'} to ${viewingSemester.name}?`}
          preview={previewSetlist}
          onConfirm={confirmSave}
        />
      )}
    </div>
  )
}

/**
 * Mounts only while the Setlist editor is active, so the shell's edit
 * toolbar appears and disappears with it -- `useRegisterEditSession`
 * itself always registers on every render it's called from, so an
 * always-mounted call would show a stray empty toolbar outside edit mode.
 */
function SetlistEditSessionRegistrar({
  semesterName,
  changeCount,
  discard,
  requestSave,
}: {
  semesterName: string
  changeCount: number
  discard: () => void
  requestSave: () => void
}) {
  useRegisterEditSession({
    what: semesterName,
    changeCount,
    blockedReason: null,
    discard,
    requestSave,
  })
  return null
}

/** The phone layout: one card per Song, no horizontal scroll (issue #330). */
function SetlistCards({
  songs,
  viewerId,
}: {
  songs: SetlistPayload['songs']
  viewerId?: number
}) {
  return (
    <ul className="flex flex-col gap-3">
      {songs.map((song) => (
        <li key={song.id} className="rounded border border-rs-border p-3">
          <div className="flex items-start justify-between gap-2">
            <p className="font-medium">
              {song.position}. {song.title}
            </p>
            <span className="text-sm text-rs-muted">{song.length}</span>
          </div>
          <p className="text-sm text-rs-muted">{song.artist}</p>
          <div className="pt-2">
            <CastLine cast={song.cast} viewerId={viewerId} />
          </div>
          {song.notes !== '' && (
            <p className="pt-2 text-sm text-rs-muted">{song.notes}</p>
          )}
          <RecordingEntryPoints song={song} label="no takes yet" />
        </li>
      ))}
    </ul>
  )
}

/** The desktop layout: one table row per Song, plus a second full-width row for its notes when it has any (issue #330). */
function SetlistTable({
  songs,
  viewerId,
}: {
  songs: SetlistPayload['songs']
  viewerId?: number
}) {
  return (
    <table className="w-full text-left text-sm">
      <thead>
        <tr>
          <th className="pb-2">#</th>
          <th className="pb-2">Song</th>
          <th className="pb-2">Cast</th>
          <th className="pb-2">Length</th>
          <th className="pb-2">Recordings</th>
          <th className="pb-2" />
        </tr>
      </thead>
      <tbody>
        {songs.map((song) => (
          <Fragment key={song.id}>
            <tr>
              <td className="py-2 align-top">{song.position}</td>
              <td className="py-2 align-top">
                <p className="font-medium">{song.title}</p>
                <p className="text-rs-muted">{song.artist}</p>
              </td>
              <td className="py-2 align-top">
                <CastLine cast={song.cast} viewerId={viewerId} />
              </td>
              <td className="py-2 align-top">{song.length}</td>
              <td className="py-2 align-top">
                <RecordingEntryPoints song={song} label="—" />
              </td>
              <td className="py-2 align-top">
                <Link to={`/songs/${song.id}`}>Open</Link>
              </td>
            </tr>
            {song.notes !== '' && (
              <tr>
                <td colSpan={6} className="pb-2 text-rs-muted">
                  {song.notes}
                </td>
              </tr>
            )}
          </Fragment>
        ))}
      </tbody>
    </table>
  )
}

/** ▶ (play, with a count) and + (upload preselected to this Song) — the Setlist's two Recordings entry points (issue #330). */
function RecordingEntryPoints({
  song,
  label,
}: {
  song: SetlistPayload['songs'][number]
  label: string
}) {
  return (
    <div className="flex items-center gap-3 pt-2 text-sm">
      {song.recording_count > 0 ? (
        <Link
          to={`/songs/${song.id}`}
          aria-label={`Play ${song.title}'s takes`}
        >
          ▶ {song.recording_count}
        </Link>
      ) : (
        <span className="text-rs-muted">{label}</span>
      )}
      <Link
        to={`/profile?song=${song.id}`}
        aria-label={`Add a recording of ${song.title}`}
      >
        +
      </Link>
    </div>
  )
}
