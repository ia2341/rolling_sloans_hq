import { useCallback, useEffect, useMemo, useState } from 'react'

import { apiFetch } from '../../api/client'
import type { SongCastPickerOption, SongPayload } from '../../api/setlistTypes'
import type { ReadEnvelope } from '../../api/types'
import { ResponsiveDialog } from '../../components/ui/ResponsiveDialog'
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
 * reach the server only on Save, hitting the same `cast/preview/`+`cast/save/`
 * pair the Song page uses — never an immediate write per pick. Save
 * previews silently and, when clear, commits and closes the popover
 * directly (issue #506 follow-up: an earlier revision opened a second
 * confirm *popup* on top of this one, which was worse than just saving) —
 * but an ADR-0019 loud-tier warning (a future Rehearsal the candidate
 * would miss) still pauses here for an explicit "Save anyway" rather than
 * being silently dropped, matching the Song page's own confirm-before-commit
 * behavior for the identical Buffer/apply. A rejection (stale Song, a
 * failed request) surfaces its message inline and leaves the Buffer open
 * for another try. `useRegisterEditSession` puts it in the shell's edit
 * toolbar like every other edit surface, so "you have unsaved changes"
 * means the same thing here as anywhere else.
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
  const [saving, setSaving] = useState(false)
  const [saveErrors, setSaveErrors] = useState<string[]>([])
  /** A non-empty ADR-0019 loud-tier warning (a future Rehearsal the candidate would miss) from the last Preview, awaiting an explicit "Save anyway" — never populated together with `saveErrors`. */
  const [loudWarning, setLoudWarning] = useState<string[] | null>(null)

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

  /** Commits the staged buffer for real and closes the popover on success; a rejection surfaces inline and leaves the Buffer intact. */
  const commit = useCallback(() => {
    if (song === null) return
    setSaving(true)
    void apiFetch<SongCastWriteEnvelope>(`/api/songs/${song.id}/cast/save/`, {
      method: 'POST',
      body: JSON.stringify(buildCastBufferWire(song.updated_at, buffer)),
    })
      .then((envelope) => {
        if (!envelope.ok) {
          setLoudWarning(null)
          setSaveErrors(
            mapSongCastPreviewToResult(envelope).nonFieldErrors ?? [],
          )
          return
        }
        onSaved()
        onClose()
      })
      .catch(() => {
        setLoudWarning(null)
        setSaveErrors(['Something went wrong saving this change. Try again.'])
      })
      .finally(() => setSaving(false))
  }, [song, buffer, onSaved, onClose])

  /**
   * Saves the staged buffer — no intermediate confirm *dialog* (issue
   * #506 follow-up: a popup opening on top of this one was worse than
   * just saving). It does still Preview first, silently, rather than
   * saving blind: `CastEditor.tsx`'s Song-page container previews the
   * identical `SongCastEditBuffer`/`apply_song_cast_edits()` and renders
   * ADR-0019's loud-tier availability warning ("a future Rehearsal the
   * candidate would miss") before committing, and the Setlist's inline
   * popover must not silently drop that same warning just because it
   * saves without a confirm dialog. A loud warning pauses here (inline in
   * this dialog, not a second one) for an explicit "Save anyway"; no
   * warning falls straight through to `commit()`. A Preview rejection
   * (stale Song, a network failure) surfaces inline the same way a Save
   * rejection does, leaving the Buffer intact so the admin can retry or
   * discard.
   */
  const save = useCallback(() => {
    if (song === null) return
    if (loudWarning !== null) {
      commit()
      return
    }
    setSaving(true)
    setSaveErrors([])
    void apiFetch<SongCastWriteEnvelope>(
      `/api/songs/${song.id}/cast/preview/`,
      {
        method: 'POST',
        body: JSON.stringify(buildCastBufferWire(song.updated_at, buffer)),
      },
    )
      .then((envelope) => {
        const result = mapSongCastPreviewToResult(envelope)
        if (!result.ok) {
          setSaving(false)
          setSaveErrors(
            result.nonFieldErrors ?? [
              'Something went wrong saving this change. Try again.',
            ],
          )
          return
        }
        if (result.fallout.loud.length > 0) {
          setSaving(false)
          setLoudWarning(result.fallout.loud)
          return
        }
        commit()
      })
      .catch(() => {
        setSaving(false)
        setSaveErrors(['Something went wrong saving this change. Try again.'])
      })
  }, [song, buffer, loudWarning, commit])

  const discard = useCallback(() => {
    setBuffer(EMPTY_CAST_BUFFER)
    setLoudWarning(null)
    onClose()
  }, [onClose])

  return (
    <>
      <CastEditSessionRegistrar
        what={`${columnLabel} on ${songTitle}`}
        changeCount={changeCount}
        discard={discard}
        requestSave={save}
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
              onClick={
                loudWarning !== null ? () => setLoudWarning(null) : discard
              }
              className="rounded border border-rs-border px-3 py-1.5 text-sm font-medium hover:bg-rs-border/40"
            >
              {loudWarning !== null ? 'Keep editing' : 'Cancel'}
            </button>
            <button
              type="button"
              onClick={save}
              disabled={changeCount === 0 || saving}
              className="rounded bg-rs-accent px-3 py-1.5 text-sm font-medium text-rs-accent-fg disabled:cursor-not-allowed disabled:opacity-50"
            >
              {saving
                ? 'Saving…'
                : loudWarning !== null
                  ? 'Save anyway'
                  : 'Save changes'}
            </button>
          </>
        }
      >
        {saveErrors.length > 0 && (
          <div
            role="alert"
            className="mb-3 rounded border border-rs-danger/40 bg-rs-danger/5 p-3"
          >
            {saveErrors.map((message) => (
              <p key={message} className="text-sm text-rs-danger">
                {message}
              </p>
            ))}
          </div>
        )}
        {loudWarning !== null && (
          <div className="mb-3 rounded border border-rs-warning-border bg-rs-warning-bg p-3 text-rs-warning-fg">
            <h3 className="mb-1 text-sm font-semibold">Needs your attention</h3>
            <ul className="space-y-1">
              {loudWarning.map((message) => (
                <li key={message} className="text-sm">
                  {message}
                </li>
              ))}
            </ul>
          </div>
        )}
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
