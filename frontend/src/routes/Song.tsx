import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { ApiError, apiFetch } from '../api/client'
import { useAppContext } from '../api/ContextProvider'
import type { PreviewResult } from '../api/previewTypes'
import type { SongPayload } from '../api/setlistTypes'
import type { ReadEnvelope } from '../api/types'
import { RecordingUploadDialog } from '../components/recordings/RecordingUploadDialog'
import { CastTable, RoleMismatchLegend } from '../components/ui/CastLine'
import { PageHead } from '../components/ui/PageHead'
import { SaveChangesDialog } from '../components/ui/SaveChangesDialog'
import { formatClockTime, formatRehearsalDate } from '../lib/formatDate'
import { useRegisterEditSession } from '../shell/EditSessionContext'
import { usePageTitle } from '../shell/PageTitleContext'
import { AddRoleRequirementSheet } from './song/AddRoleRequirementSheet'
import { CastEditor } from './song/CastEditor'
import { CastPickerSheet } from './song/CastPickerSheet'
import { RequirementsEditor } from './song/RequirementsEditor'
import { RequirementsReadOnly } from './song/RequirementsReadOnly'
import {
  addCastEntry,
  buildCastBufferWire,
  castPersonIdsFor,
  computeCastChangeCount,
  EMPTY_CAST_BUFFER,
  mapSongCastPreviewToResult,
  removePendingCastEntry,
  removeSavedCastEntry,
  undoRemoveSavedCastEntry,
  type CastEditBuffer,
  type SongCastWriteEnvelope,
} from './song/songCastEditModel'
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

/**
 * `/songs/<pk>/` (issue #330, #339, #499): one Song's read model, fed by
 * one `GET /api/songs/<pk>/` round trip, plus (for an admin) its Cast and
 * Role Requirements edit modes -- the same route flips into an editable
 * cast card rather than navigating anywhere else, matching the Setlist's
 * same-route toggle convention. Since ADR 0019 this page is where casting
 * happens: "Edit song" opens both editors at once, staged into two
 * Pending Buffers behind one Save popup, because the Song a Requirement
 * describes and the Song its cast fills are the same Song and an admin
 * setting one almost always wants to set the other. A Song outside the viewing Semester 404s
 * server-side (ADR 0001); this renders that as an explicit not-found
 * state rather than an error banner. The Cast section shares `CastLine.tsx`
 * with the Setlist, so it gets the same admin-only `RoleMismatchLegend`/
 * `RoleMismatchBadge` treatment for a mismatched Role Assignment (issue
 * #365, ADR 0002) -- a non-admin sees neither.
 */
export function Song() {
  usePageTitle('Song')
  const { songId } = useParams<{ songId: string }>()
  const appContext = useAppContext()
  const [state, setState] = useState<LoadState>({ status: 'loading' })
  const [isEditing, setIsEditing] = useState(false)
  const [rows, setRows] = useState<RequirementEditRow[]>([])
  const [rowErrors, setRowErrors] = useState<
    Record<string, Record<string, string[]>>
  >({})
  const [addSheetOpen, setAddSheetOpen] = useState(false)
  const [saveDialogOpen, setSaveDialogOpen] = useState(false)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [castBuffer, setCastBuffer] =
    useState<CastEditBuffer>(EMPTY_CAST_BUFFER)
  const [castPickerRole, setCastPickerRole] = useState<{
    id: number
    name: string
  } | null>(null)

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
    setCastBuffer(EMPTY_CAST_BUFFER)
    setIsEditing(true)
  }, [song])

  const discard = useCallback(() => {
    setIsEditing(false)
    setRows([])
    setRowErrors({})
    setCastBuffer(EMPTY_CAST_BUFFER)
    setCastPickerRole(null)
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

  /** Stages one picked candidate onto the open cell, then closes the picker. */
  const pickCastMember = useCallback(
    (option: Parameters<typeof addCastEntry>[2]) => {
      if (castPickerRole === null) return
      setCastBuffer((current) =>
        addCastEntry(current, castPickerRole.id, option),
      )
      setCastPickerRole(null)
    },
    [castPickerRole],
  )

  /** Runs the Cast Buffer's own Preview, or resolves an empty result when nothing is staged. */
  const previewCast = useCallback((): Promise<PreviewResult | null> => {
    if (song === null || computeCastChangeCount(castBuffer) === 0) {
      return Promise.resolve(null)
    }
    return apiFetch<SongCastWriteEnvelope>(
      `/api/songs/${song.id}/cast/preview/`,
      {
        method: 'POST',
        body: JSON.stringify(buildCastBufferWire(song.updated_at, castBuffer)),
      },
    ).then(mapSongCastPreviewToResult)
  }, [song, castBuffer])

  const previewRequirements = useCallback((): Promise<PreviewResult> => {
    if (viewingSemester === null || song === null) {
      return Promise.resolve({
        ok: false,
        changes: [],
        fallout: { loud: [], quiet: [] },
        nonFieldErrors: ['No Semester is selected to save against.'],
      })
    }
    const body = buildRequirementBufferWire(
      viewingSemester.id,
      viewingSemester.updated_at,
      rows,
    )
    return apiFetch<SongRoleRequirementWriteEnvelope>(
      `/api/songs/${song.id}/requirements/preview/`,
      {
        method: 'POST',
        body: JSON.stringify(body),
      },
    ).then((envelope) => {
      setRowErrors(envelope.errors)
      return mapSongRoleRequirementPreviewToResult(envelope)
    })
  }, [rows, viewingSemester, song])

  /** Previews both Buffers and merges them into the one result the shared Save popup renders (ADR 0008 — each Preview runs its own surface's real save and rolls it back). */
  const preview = useCallback(async (): Promise<PreviewResult> => {
    const requirementsResult = await previewRequirements()
    if (!requirementsResult.ok) return requirementsResult
    const castResult = await previewCast()
    if (castResult === null) return requirementsResult
    if (!castResult.ok) return castResult
    return {
      ok: true,
      changes: [...requirementsResult.changes, ...castResult.changes],
      fallout: {
        loud: [...requirementsResult.fallout.loud, ...castResult.fallout.loud],
        quiet: [
          ...requirementsResult.fallout.quiet,
          ...castResult.fallout.quiet,
        ],
      },
    }
  }, [previewRequirements, previewCast])

  const confirmSave = useCallback(() => {
    if (viewingSemester === null || song === null) return
    /** Leaves edit mode and reloads the Song, once every staged Buffer has committed. */
    const finish = () => {
      setSaveDialogOpen(false)
      setIsEditing(false)
      setRows([])
      setRowErrors({})
      setCastBuffer(EMPTY_CAST_BUFFER)
      load()
    }
    const saveCast = () => {
      if (computeCastChangeCount(castBuffer) === 0) {
        finish()
        return
      }
      void apiFetch<SongCastWriteEnvelope>(`/api/songs/${song.id}/cast/save/`, {
        method: 'POST',
        body: JSON.stringify(buildCastBufferWire(song.updated_at, castBuffer)),
      }).then((envelope) => {
        if (envelope.ok) finish()
      })
    }
    const body = buildRequirementBufferWire(
      viewingSemester.id,
      viewingSemester.updated_at,
      rows,
    )
    void apiFetch<SongRoleRequirementWriteEnvelope>(
      `/api/songs/${song.id}/requirements/save/`,
      {
        method: 'POST',
        body: JSON.stringify(body),
      },
    ).then((envelope) => {
      if (!envelope.ok) return
      saveCast()
    })
  }, [rows, viewingSemester, song, load, castBuffer])

  const changeCount = useMemo(
    () => computeChangeCount(rows) + computeCastChangeCount(castBuffer),
    [rows, castBuffer],
  )
  const existingRoleIds = useMemo(
    () => new Set(rows.map((row) => row.roleId)),
    [rows],
  )
  const availableRoles = useMemo(
    () =>
      (song?.available_roles ?? []).filter(
        (role) => !existingRoleIds.has(role.id),
      ),
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
        </div>
        {appContext?.viewer.is_admin === true && <RoleMismatchLegend />}
        {isEditing ? (
          <CastEditor
            cast={song.cast}
            roleRequirements={song.role_requirements}
            buffer={castBuffer}
            onOpenPicker={setCastPickerRole}
            onRemoveSaved={(assignmentId) =>
              setCastBuffer((current) =>
                removeSavedCastEntry(current, assignmentId),
              )
            }
            onUndoRemoveSaved={(assignmentId) =>
              setCastBuffer((current) =>
                undoRemoveSavedCastEntry(current, assignmentId),
              )
            }
            onRemovePending={(key) =>
              setCastBuffer((current) => removePendingCastEntry(current, key))
            }
          />
        ) : (
          <div className="pt-2">
            <CastTable
              cast={song.cast}
              viewerId={appContext?.viewer.id}
              isAdmin={appContext?.viewer.is_admin ?? false}
            />
          </div>
        )}
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
          <button
            type="button"
            onClick={() => setUploadOpen(true)}
            className="text-sm text-rs-accent"
          >
            + Add a recording
          </button>
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
                <p className="font-medium">
                  {formatRehearsalDate(group.date)}
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
                {formatRehearsalDate(row.date)}
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

      {castPickerRole !== null && (
        <CastPickerSheet
          songId={song.id}
          role={castPickerRole}
          excludePersonIds={castPersonIdsFor(
            song.cast,
            castBuffer,
            castPickerRole.id,
          )}
          onOpenChange={(open) => {
            if (!open) setCastPickerRole(null)
          }}
          onPick={pickCastMember}
        />
      )}

      {uploadOpen && (
        <RecordingUploadDialog
          onOpenChange={(open) => {
            if (!open) setUploadOpen(false)
          }}
          preselectedSongId={song.id}
          onUploaded={load}
        />
      )}

      {viewingSemester !== null && (
        <SaveChangesDialog
          open={saveDialogOpen}
          onOpenChange={setSaveDialogOpen}
          title={`Save ${changeCount} change${changeCount === 1 ? '' : 's'} to ${song.title}?`}
          preview={preview}
          onConfirm={confirmSave}
        />
      )}
    </div>
  )
}

/**
 * Mounts only while the Song's edit mode is active, so the shell's edit
 * toolbar appears and disappears with it (mirrors Setlist's own
 * registrar). One registration covers both Buffers this page stages —
 * the Cast editor and the Requirements editor share one toolbar, one
 * change count and one Save (issue #499).
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
