import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { ApiError, apiFetch } from '../api/client'
import { useAppContext } from '../api/ContextProvider'
import type { PreviewResult } from '../api/previewTypes'
import type { SongPayload } from '../api/setlistTypes'
import type { ReadEnvelope } from '../api/types'
import { CastLine } from '../components/ui/CastLine'
import { PageHead } from '../components/ui/PageHead'
import { SaveChangesDialog } from '../components/ui/SaveChangesDialog'
import { useRegisterEditSession } from '../shell/EditSessionContext'
import { usePageTitle } from '../shell/PageTitleContext'
import { AddRoleRequirementSheet } from './song/AddRoleRequirementSheet'
import { RequirementsEditor } from './song/RequirementsEditor'
import { RequirementsReadOnly } from './song/RequirementsReadOnly'
import {
  addRequirementRow,
  buildRequirementBufferWire,
  computeChangeCount,
  mapSongRoleRequirementPreviewToResult,
  removeRequirementRow,
  rowsFromPayload,
  undoRemoveRequirementRow,
  updateRequirementCount,
  type RequirementEditRow,
  type SongRoleRequirementWriteEnvelope,
} from './song/songRoleRequirementsEditModel'

type LoadState =
  | { status: 'loading' }
  | { status: 'not_found' }
  | { status: 'loaded'; data: SongPayload }

/** Trims a wire `HH:MM:SS` time string down to `HH:MM` for display (issue #330's "date + HH:MM–HH:MM" group header). */
function formatClockTime(isoTime: string): string {
  return isoTime.slice(0, 5)
}

/**
 * `/songs/<pk>/` (issue #330, #339): one Song's read model, fed by one
 * `GET /api/songs/<pk>/` round trip, plus (for an admin) its own Role
 * Requirements edit mode -- the same route flips into an editable cast
 * card rather than navigating anywhere else, matching the Setlist's
 * same-route toggle convention. A Song outside the viewing Semester 404s
 * server-side (ADR 0001); this renders that as an explicit not-found
 * state rather than an error banner.
 */
export function Song() {
  usePageTitle('Song')
  const { songId } = useParams<{ songId: string }>()
  const appContext = useAppContext()
  const [state, setState] = useState<LoadState>({ status: 'loading' })
  const [isEditing, setIsEditing] = useState(false)
  const [rows, setRows] = useState<RequirementEditRow[]>([])
  const [rowErrors, setRowErrors] = useState<Record<string, Record<string, string[]>>>({})
  const [addSheetOpen, setAddSheetOpen] = useState(false)
  const [saveDialogOpen, setSaveDialogOpen] = useState(false)

  const load = useCallback(() => {
    void apiFetch<ReadEnvelope<SongPayload>>(`/api/songs/${songId}/`)
      .then((envelope) => {
        setState({ status: 'loaded', data: envelope.data })
      })
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 404) {
          setState({ status: 'not_found' })
          return
        }
        throw error
      })
  }, [songId])

  useEffect(() => {
    load()
  }, [load])

  const viewingSemester = appContext?.viewing_semester ?? null
  const song = state.status === 'loaded' ? state.data : null

  const startEditing = useCallback(() => {
    if (song === null) return
    setRows(rowsFromPayload(song.role_requirements))
    setRowErrors({})
    setIsEditing(true)
  }, [song])

  const discard = useCallback(() => {
    setIsEditing(false)
    setRows([])
    setRowErrors({})
  }, [])

  const requestSave = useCallback(() => setSaveDialogOpen(true), [])

  const updateCount = useCallback((roleId: number, count: number) => {
    setRows((current) => updateRequirementCount(current, roleId, count))
  }, [])

  const removeRow = useCallback((roleId: number) => {
    setRows((current) => removeRequirementRow(current, roleId))
  }, [])

  const undoRemove = useCallback((roleId: number) => {
    setRows((current) => undoRemoveRequirementRow(current, roleId))
  }, [])

  const addRole = useCallback((role: { id: number; name: string }) => {
    setRows((current) => addRequirementRow(current, role))
  }, [])

  const previewRequirements = useCallback((): Promise<PreviewResult> => {
    if (viewingSemester === null || song === null) {
      return Promise.resolve({
        ok: false,
        changes: [],
        fallout: { loud: [], quiet: [] },
        nonFieldErrors: ['No Semester is selected to save against.'],
      })
    }
    const body = buildRequirementBufferWire(viewingSemester.id, viewingSemester.updated_at, rows)
    return apiFetch<SongRoleRequirementWriteEnvelope>(`/api/songs/${song.id}/requirements/preview/`, {
      method: 'POST',
      body: JSON.stringify(body),
    }).then((envelope) => {
      setRowErrors(envelope.errors)
      return mapSongRoleRequirementPreviewToResult(envelope)
    })
  }, [rows, viewingSemester, song])

  const confirmSave = useCallback(() => {
    if (viewingSemester === null || song === null) return
    const body = buildRequirementBufferWire(viewingSemester.id, viewingSemester.updated_at, rows)
    void apiFetch<SongRoleRequirementWriteEnvelope>(`/api/songs/${song.id}/requirements/save/`, {
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
  }, [rows, viewingSemester, song, load])

  const changeCount = useMemo(() => computeChangeCount(rows), [rows])
  const existingRoleIds = useMemo(() => new Set(rows.map((row) => row.roleId)), [rows])
  const availableRoles = useMemo(
    () => (song?.available_roles ?? []).filter((role) => !existingRoleIds.has(role.id)),
    [song, existingRoleIds],
  )

  if (state.status === 'loading') return null
  if (state.status === 'not_found') return <PageHead title="Song not found" />
  if (song === null) return null

  const positionLine = `${song.artist} · ${song.length} · position ${song.position} in the setlist`

  return (
    <div>
      {isEditing && viewingSemester !== null && (
        <SongEditSessionRegistrar
          title={song.title}
          changeCount={changeCount}
          discard={discard}
          requestSave={requestSave}
        />
      )}
      <PageHead
        title={song.title}
        subline={positionLine}
        action={
          appContext?.viewer.is_admin && !isEditing ? (
            <button
              type="button"
              onClick={startEditing}
              className="rounded bg-rs-accent px-3 py-1.5 text-sm font-medium text-rs-accent-fg"
            >
              Edit song
            </button>
          ) : undefined
        }
      />
      <Link to="/setlist" className="text-sm text-rs-accent">
        ← Setlist
      </Link>

      <section className="pt-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase text-rs-muted">
            Cast
          </h2>
          <span className="text-xs text-rs-muted">Read-only here</span>
        </div>
        <div className="pt-2">
          <CastLine cast={song.cast} viewerId={appContext?.viewer.id} />
        </div>
        {isEditing ? (
          <RequirementsEditor
            rows={rows}
            rowErrors={rowErrors}
            onUpdateCount={updateCount}
            onRemove={removeRow}
            onUndoRemove={undoRemove}
            onOpenAddSheet={() => setAddSheetOpen(true)}
          />
        ) : (
          <RequirementsReadOnly requirements={song.role_requirements} />
        )}
        {song.next_rehearsal !== undefined && (
          <div className="mt-3 rounded border border-rs-warning-border bg-rs-warning-bg p-3 text-sm text-rs-warning-fg">
            <p>
              <strong>Casting happens on a rehearsal, not here.</strong> A cell
              edited there changes every rehearsal and the concert (ADR 0009) —
              the availability check that makes it safe is only computable
              through a Rehearsal.
            </p>
            {song.next_rehearsal !== null && (
              <Link
                to={`/schedule?rehearsal=${song.next_rehearsal.id}`}
                className="mt-2 inline-block font-medium text-rs-accent"
              >
                Cast on {song.next_rehearsal.date} →
              </Link>
            )}
          </div>
        )}
      </section>

      {song.notes !== '' && (
        <section className="pt-4">
          <h2 className="text-sm font-semibold uppercase text-rs-muted">
            Notes
          </h2>
          <p className="pt-1 text-sm">{song.notes}</p>
        </section>
      )}

      <section className="pt-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase text-rs-muted">
            Recordings
          </h2>
          <Link
            to={`/profile?song=${song.id}`}
            className="text-sm text-rs-accent"
          >
            + Add a recording
          </Link>
        </div>
        {song.recording_groups.length === 0 ? (
          <p className="pt-2 text-sm text-rs-muted">No recordings yet.</p>
        ) : (
          <ul className="flex flex-col gap-3 pt-2">
            {song.recording_groups.map((group) => (
              <li
                key={group.rehearsal_id}
                className="rounded border border-rs-border p-3"
              >
                <p className="text-sm font-medium">
                  {group.date}
                  {group.start_time !== null && group.end_time !== null
                    ? ` · ${formatClockTime(group.start_time)}–${formatClockTime(group.end_time)}`
                    : ''}{' '}
                  · {group.take_count} take{group.take_count === 1 ? '' : 's'}
                </p>
                <ul className="flex flex-col gap-2 pt-2">
                  {group.recordings.map((recording) => (
                    <li key={recording.id} className="text-sm">
                      <audio
                        controls
                        src={recording.playback_url}
                        className="w-full"
                      />
                      <p className="text-rs-muted">
                        {recording.uploaded_by_name}
                        {recording.note !== '' && ` — ${recording.note}`}
                      </p>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="pt-4">
        <h2 className="text-sm font-semibold uppercase text-rs-muted">
          Rehearsed at
        </h2>
        {song.rehearsed_at.length === 0 ? (
          <p className="pt-2 text-sm text-rs-muted">
            Not scheduled at any rehearsal yet.
          </p>
        ) : (
          <ul className="pt-2 text-sm">
            {song.rehearsed_at.map((row) => (
              <li key={row.rehearsal_id}>
                {row.date}
                {' — '}
                {row.is_dress_rehearsal
                  ? 'whole setlist'
                  : `${row.start_time !== null ? formatClockTime(row.start_time) : ''}–${
                      row.end_time !== null ? formatClockTime(row.end_time) : ''
                    }`}
              </li>
            ))}
          </ul>
        )}
      </section>

      <AddRoleRequirementSheet
        open={addSheetOpen}
        onOpenChange={setAddSheetOpen}
        availableRoles={availableRoles}
        existingRoleIds={existingRoleIds}
        onAddRole={addRole}
      />

      {viewingSemester !== null && (
        <SaveChangesDialog
          open={saveDialogOpen}
          onOpenChange={setSaveDialogOpen}
          title={`Save ${changeCount} change${changeCount === 1 ? '' : 's'} to ${song.title}?`}
          preview={previewRequirements}
          onConfirm={confirmSave}
        />
      )}
    </div>
  )
}

/**
 * Mounts only while the Requirements editor is active, so the shell's edit
 * toolbar appears and disappears with it (mirrors Setlist's own
 * registrar).
 */
function SongEditSessionRegistrar({
  title,
  changeCount,
  discard,
  requestSave,
}: {
  title: string
  changeCount: number
  discard: () => void
  requestSave: () => void
}) {
  useRegisterEditSession({
    what: title,
    changeCount,
    blockedReason: null,
    discard,
    requestSave,
  })
  return null
}
