import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { apiFetch } from '../api/client'
import { useAppContext } from '../api/ContextProvider'
import type { PreviewResult } from '../api/previewTypes'
import type { SetlistPayload } from '../api/setlistTypes'
import type { ReadEnvelope } from '../api/types'
import { RecordingUploadDialog } from '../components/recordings/RecordingUploadDialog'
import {
  CastCell,
  CastGridTable,
  RoleMismatchLegend,
  type CastGridRow,
} from '../components/ui/CastLine'
import { PageHead } from '../components/ui/PageHead'
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
  moveAliveRowTo,
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
 * arrives. An admin viewer also gets a `RoleMismatchLegend` above the cast
 * table/cards, explaining the per-cell `RoleMismatchBadge` (issue #365,
 * ADR 0002) -- a non-admin sees neither, since the underlying fact is
 * never rendered to a non-admin.
 */
export function Setlist() {
  usePageTitle('Setlist')
  const appContext = useAppContext()
  const isPhone = useIsPhone()
  const [data, setData] = useState<SetlistPayload | null>(null)
  const [isEditing, setIsEditing] = useState(false)
  const [rows, setRows] = useState<EditRow[]>([])
  const [rowErrors, setRowErrors] = useState<
    Record<string, Record<string, string[]>>
  >({})
  const [addSheetOpen, setAddSheetOpen] = useState(false)
  const [saveDialogOpen, setSaveDialogOpen] = useState(false)
  const [uploadSongId, setUploadSongId] = useState<number | null>(null)

  const load = useCallback(() => {
    void apiFetch<ReadEnvelope<SetlistPayload>>('/api/setlist/').then(
      (envelope) => {
        setData(envelope.data)
      },
    )
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

  const updateField = useCallback(
    (rowKey: string, field: EditField, value: string) => {
      setRows((current) =>
        current.map((row) =>
          row.rowKey === rowKey ? { ...row, [field]: value } : row,
        ),
      )
    },
    [],
  )

  const reorderRow = useCallback((rowKey: string, toAliveIndex: number) => {
    setRows((current) => moveAliveRowTo(current, rowKey, toAliveIndex))
  }, [])

  const deleteRow = useCallback((rowKey: string) => {
    setRows((current) => {
      const row = current.find((candidate) => candidate.rowKey === rowKey)
      if (!row) return current
      // A never-saved row has nothing to undo to -- delete just removes it.
      if (row.songId === null)
        return current.filter((candidate) => candidate.rowKey !== rowKey)
      return current.map((candidate) =>
        candidate.rowKey === rowKey
          ? { ...candidate, deleted: true }
          : candidate,
      )
    })
  }, [])

  const undoDelete = useCallback((rowKey: string) => {
    setRows((current) =>
      current.map((row) =>
        row.rowKey === rowKey ? { ...row, deleted: false } : row,
      ),
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
    const body = buildBufferWire(
      viewingSemester.id,
      viewingSemester.updated_at,
      rows,
    )
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
    const body = buildBufferWire(
      viewingSemester.id,
      viewingSemester.updated_at,
      rows,
    )
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
  const isAdmin = appContext?.viewer.is_admin ?? false

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
      {isEditing ? (
        <SetlistEditGrid
          rows={rows}
          rowErrors={rowErrors}
          onUpdateField={updateField}
          onReorder={reorderRow}
          onDelete={deleteRow}
          onUndoDelete={undoDelete}
          isPhone={isPhone}
        />
      ) : data.songs.length === 0 ? (
        <p className="text-sm text-rs-muted">No songs yet this Semester.</p>
      ) : (
        <>
          {isAdmin && <RoleMismatchLegend />}
          {isPhone ? (
            <SetlistCards
              songs={data.songs}
              viewerId={appContext?.viewer.id}
              isAdmin={isAdmin}
              onAddRecording={setUploadSongId}
            />
          ) : (
            <SetlistTable
              roles={data.roles}
              songs={data.songs}
              viewerId={appContext?.viewer.id}
              isAdmin={isAdmin}
              onAddRecording={setUploadSongId}
            />
          )}
        </>
      )}

      <AddSongsSheet
        open={addSheetOpen}
        onOpenChange={setAddSheetOpen}
        onAddRows={addRows}
      />

      {uploadSongId !== null && (
        <RecordingUploadDialog
          onOpenChange={(open) => {
            if (!open) setUploadSongId(null)
          }}
          preselectedSongId={uploadSongId}
          onUploaded={load}
        />
      )}

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

/**
 * The phone layout: one card per Song, no horizontal scroll (issue #330).
 * The whole card navigates to `/songs/{id}` on activation (UI overhaul
 * round 2) -- Recordings are read on that page now rather than shown here,
 * so the only entry point this card keeps is the "+" upload trigger, which
 * stops the click from bubbling into the card's own navigation and opens
 * the shared Recording-upload popup (issue: UI overhaul round 2) rather
 * than navigating to `/profile?song={id}`. `isAdmin` gates each `CastCell`'s
 * role-mismatch badge (issue #365, ADR 0002).
 */
function SetlistCards({
  songs,
  viewerId,
  isAdmin,
  onAddRecording,
}: {
  songs: SetlistPayload['songs']
  viewerId?: number
  isAdmin: boolean
  onAddRecording: (songId: number) => void
}) {
  const navigate = useNavigate()
  return (
    <ul className="flex flex-col gap-3">
      {songs.map((song) => (
        <li
          key={song.id}
          onClick={(event) => {
            if ((event.target as HTMLElement).closest('a, button')) return
            navigate(`/songs/${song.id}`)
          }}
          onKeyDown={(event) => {
            if (event.key !== 'Enter' && event.key !== ' ') return
            if ((event.target as HTMLElement).closest('a, button')) return
            event.preventDefault()
            navigate(`/songs/${song.id}`)
          }}
          tabIndex={0}
          role="button"
          aria-label={`Open ${song.title}`}
          className="cursor-pointer rounded border border-rs-border p-3 hover:bg-rs-border/10"
        >
          <div className="flex items-start justify-between gap-2">
            <p className="font-medium">
              {song.position}. {song.title}
            </p>
            <div className="flex items-center gap-3">
              <span className="text-sm text-rs-muted">{song.length}</span>
              <button
                type="button"
                aria-label={`Add a recording of ${song.title}`}
                onClick={(event) => {
                  event.stopPropagation()
                  onAddRecording(song.id)
                }}
                className="text-rs-accent"
              >
                +
              </button>
            </div>
          </div>
          <p className="text-sm text-rs-muted">{song.artist}</p>
          <ul className="flex flex-col gap-2 pt-2">
            {song.cast.map((entry) => (
              <li key={entry.role_id} className="text-sm">
                <p className="text-xs font-semibold uppercase text-rs-muted">
                  {entry.role_name}
                </p>
                <CastCell entry={entry} viewerId={viewerId} isAdmin={isAdmin} />
              </li>
            ))}
          </ul>
          {song.notes !== '' && (
            <p className="pt-2 text-sm text-rs-muted">{song.notes}</p>
          )}
        </li>
      ))}
    </ul>
  )
}

/**
 * The desktop layout: the shared `CastGridTable` (issue: UI overhaul round
 * 2, item 11) -- `#`, `Song`, `Length`, the fixed instrument columns, then
 * Add Recording. Each Song row is itself the "Open" control -- clicking
 * anywhere on it but a link or button navigates to `/songs/{id}`; the
 * trailing column's "+" opens the shared Recording-upload popup instead of
 * navigating to `/profile?song={id}`. `isAdmin` gates each cell's
 * role-mismatch badge (issue #365, ADR 0002).
 */
function SetlistTable({
  roles,
  songs,
  viewerId,
  isAdmin,
  onAddRecording,
}: {
  roles: SetlistPayload['roles']
  songs: SetlistPayload['songs']
  viewerId?: number
  isAdmin: boolean
  onAddRecording: (songId: number) => void
}) {
  const navigate = useNavigate()
  const rows: CastGridRow[] = songs.map((song) => ({
    id: song.id,
    position: song.position,
    title: song.title,
    artist: song.artist,
    length: song.length,
    notes: song.notes,
    cast: song.cast,
  }))
  return (
    <CastGridTable
      roles={roles}
      rows={rows}
      viewerId={viewerId}
      isAdmin={isAdmin}
      onOpenRow={(songId) => navigate(`/songs/${songId}`)}
      renderRecordingCell={(row) => (
        <button
          type="button"
          aria-label={`Add a recording of ${row.title}`}
          onClick={(event) => {
            event.stopPropagation()
            onAddRecording(row.id)
          }}
          className="text-rs-accent"
        >
          +
        </button>
      )}
    />
  )
}
