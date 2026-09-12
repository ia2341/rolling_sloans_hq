import { useCallback, useEffect, useMemo, useState } from 'react'

import { apiFetch } from '../../api/client'
import type { PreviewResult } from '../../api/previewTypes'
import type { SongCastPickerOption, SongPayload } from '../../api/setlistTypes'
import type { ReadEnvelope } from '../../api/types'
import { ResponsiveDialog } from '../../components/ui/ResponsiveDialog'
import { SaveChangesDialog } from '../../components/ui/SaveChangesDialog'
import { useRegisterEditSession } from '../../shell/EditSessionContext'
import { CastEditor } from '../song/CastEditor'
import { CastPickerSheet } from '../song/CastPickerSheet'
import {
  addCastEntry,
  buildCastBufferWire,
  castableRolesFromRequirements,
  castPersonIdsFor,
  computeCastChangeCount,
  EMPTY_CAST_BUFFER,
  mapSongCastPreviewToResult,
  removePendingCastEntry,
  removeSavedCastEntry,
  undoRemoveSavedCastEntry,
  type CastEditBuffer,
  type SongCastWriteEnvelope,
} from '../song/songCastEditModel'

interface SetlistCastPopoverProps {
  songId: number
  songTitle: string
  /** The clicked column's Role ids — the popover edits only these, not the Song's whole cast. */
  roleIds: number[]
  columnLabel: string
  onClose: () => void
  /** Called after a committed Save, so the Setlist re-reads the cast it just changed. */
  onSaved: () => void
}

/**
 * The Setlist's inline cast popover (issue #499, ADR 0019): clicking one
 * Role column's cell casts that Song's Role in place, with no navigation
 * away from `/setlist`. Scoped to the clicked column's Roles, so the
 * popover edits exactly the cell the admin pointed at rather than the
 * Song's whole cast (that is what `/songs/:songId` is for).
 *
 * Its own batched edit session: picks stage into one `CastEditBuffer` and
 * reach the server only on Save, through the same `preview/`/`save/` pair
 * the Song page uses — never an immediate write per pick. `useRegisterEditSession`
 * puts it in the shell's edit toolbar like every other edit surface, so
 * "you have unsaved changes" means the same thing here as anywhere else.
 *
 * Fetches `/api/songs/<pk>/` on open rather than reading the Setlist's own
 * payload: it needs the Song's `role_requirements` (only a Role with a
 * Requirement is castable at all, ADR 0015) and its `updated_at`
 * staleness anchor, neither of which a Setlist row would carry usefully
 * by the time a popover opens minutes later.
 */
export function SetlistCastPopover({
  songId,
  songTitle,
  roleIds,
  columnLabel,
  onClose,
  onSaved,
}: SetlistCastPopoverProps) {
  const [song, setSong] = useState<SongPayload | null>(null)
  const [buffer, setBuffer] = useState<CastEditBuffer>(EMPTY_CAST_BUFFER)
  const [pickerRole, setPickerRole] = useState<{
    id: number
    name: string
  } | null>(null)
  const [saveDialogOpen, setSaveDialogOpen] = useState(false)

  useEffect(() => {
    let cancelled = false
    void apiFetch<ReadEnvelope<SongPayload>>(`/api/songs/${songId}/`).then(
      (envelope) => {
        if (!cancelled) setSong(envelope.data)
      },
    )
    return () => {
      cancelled = true
    }
  }, [songId])

  /** The clicked column's castable Roles, from the Song's saved Requirements — this surface edits no Requirement, so saved *is* staged here. */
  const castableRoles = useMemo(
    () =>
      castableRolesFromRequirements(
        (song?.role_requirements ?? []).filter((requirement) =>
          roleIds.includes(requirement.role_id),
        ),
      ),
    [song, roleIds],
  )

  const changeCount = computeCastChangeCount(buffer)

  /** Stages one picked candidate onto the open cell, then closes the picker. */
  const pick = useCallback(
    (option: SongCastPickerOption) => {
      if (pickerRole === null) return
      setBuffer((current) => addCastEntry(current, pickerRole.id, option))
      setPickerRole(null)
    },
    [pickerRole],
  )

  const preview = useCallback((): Promise<PreviewResult> => {
    if (song === null) {
      return Promise.resolve({
        ok: false,
        changes: [],
        fallout: { loud: [], quiet: [] },
        nonFieldErrors: ['This Song is still loading.'],
      })
    }
    return apiFetch<SongCastWriteEnvelope>(
      `/api/songs/${song.id}/cast/preview/`,
      {
        method: 'POST',
        body: JSON.stringify(buildCastBufferWire(song.updated_at, buffer)),
      },
    ).then(mapSongCastPreviewToResult)
  }, [song, buffer])

  const confirmSave = useCallback(() => {
    if (song === null) return
    void apiFetch<SongCastWriteEnvelope>(`/api/songs/${song.id}/cast/save/`, {
      method: 'POST',
      body: JSON.stringify(buildCastBufferWire(song.updated_at, buffer)),
    }).then((envelope) => {
      if (!envelope.ok) return
      setSaveDialogOpen(false)
      onSaved()
      onClose()
    })
  }, [song, buffer, onSaved, onClose])

  const discard = useCallback(() => {
    setBuffer(EMPTY_CAST_BUFFER)
    onClose()
  }, [onClose])

  return (
    <>
      <CastEditSessionRegistrar
        what={`${columnLabel} on ${songTitle}`}
        changeCount={changeCount}
        discard={discard}
        requestSave={() => setSaveDialogOpen(true)}
      />
      <ResponsiveDialog
        open
        onOpenChange={(open) => {
          if (!open) discard()
        }}
        title={`${columnLabel} — ${songTitle}`}
        wide
        footer={
          <>
            <button
              type="button"
              onClick={discard}
              className="rounded border border-rs-border px-3 py-1.5 text-sm font-medium hover:bg-rs-border/40"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => setSaveDialogOpen(true)}
              disabled={changeCount === 0}
              className="rounded bg-rs-accent px-3 py-1.5 text-sm font-medium text-rs-accent-fg disabled:cursor-not-allowed disabled:opacity-50"
            >
              Save changes
            </button>
          </>
        }
      >
        {song === null ? (
          <p className="text-sm text-rs-muted">Loading…</p>
        ) : castableRoles.length === 0 ? (
          <p className="text-sm text-rs-muted">
            No Role Requirement for this column yet — add one on the Song page
            before casting it.
          </p>
        ) : (
          <CastEditor
            cast={song.cast}
            castableRoles={castableRoles}
            buffer={buffer}
            onOpenPicker={setPickerRole}
            onRemoveSaved={(assignmentId) =>
              setBuffer((current) =>
                removeSavedCastEntry(current, assignmentId),
              )
            }
            onUndoRemoveSaved={(assignmentId) =>
              setBuffer((current) =>
                undoRemoveSavedCastEntry(current, assignmentId),
              )
            }
            onRemovePending={(key) =>
              setBuffer((current) => removePendingCastEntry(current, key))
            }
          />
        )}
      </ResponsiveDialog>

      {song !== null && pickerRole !== null && (
        <CastPickerSheet
          songId={song.id}
          role={pickerRole}
          excludePersonIds={castPersonIdsFor(song.cast, buffer, pickerRole.id)}
          onOpenChange={(open) => {
            if (!open) setPickerRole(null)
          }}
          onPick={pick}
        />
      )}

      <SaveChangesDialog
        open={saveDialogOpen}
        onOpenChange={setSaveDialogOpen}
        title={`Save ${changeCount} change${changeCount === 1 ? '' : 's'} to ${songTitle}'s cast?`}
        preview={preview}
        onConfirm={confirmSave}
      />
    </>
  )
}

/** Mounts only while the popover is open, so the shell's edit toolbar appears and disappears with it (mirrors the Setlist's own registrar). */
function CastEditSessionRegistrar({
  what,
  changeCount,
  discard,
  requestSave,
}: {
  what: string
  changeCount: number
  discard: () => void
  requestSave: () => void
}) {
  useRegisterEditSession({
    what,
    changeCount,
    blockedReason: null,
    discard,
    requestSave,
  })
  return null
}
