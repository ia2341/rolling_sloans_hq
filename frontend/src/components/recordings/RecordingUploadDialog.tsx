import { useEffect, useMemo, useState } from 'react'

import { apiFetch } from '../../api/client'
import type {
  PersonRecordingsBlock,
  RecordingPresignErrorBody,
  RecordingPresignReservation,
} from '../../api/memberTypes'
import type { ReadEnvelope, WriteEnvelope } from '../../api/types'
import { ResponsiveDialog } from '../ui/ResponsiveDialog'

type UploadState =
  | { step: 'idle' }
  | { step: 'uploading' }
  | { step: 'uploaded'; objectKey: string }
  | { step: 'error'; message: string }

interface RecordingUploadDialogProps {
  /** Closes the dialog — the caller is expected to only render this component while it should be open (mirrors `AssignmentPickerDialog`'s convention), so this is the only half of the usual `open`/`onOpenChange` pair it needs. */
  onOpenChange: (open: boolean) => void
  /** Locks the Song picker to this Song, non-changeable, when opened from that Song's own "+" (issue #395, amending UI overhaul round 2) — `null` from Profile's context-free "Add Recording", which offers every Song. */
  preselectedSongId?: number | null
  /** Handed the requester's fresh Recordings block after a successful save, so a caller can refresh whatever it renders (a Song's `recording_groups`, or Profile's own list) without a second round trip. */
  onUploaded: (block: PersonRecordingsBlock) => void
}

/**
 * The one Recording-upload popup every surface opens (issue: UI overhaul
 * round 2) — previously a Profile-only inline card that a Song page's "+"
 * could only reach by navigating away to `/profile?song=<id>`. A caller
 * mounts this only while it should be open (`{uploadOpen && <RecordingUploadDialog .../>}`,
 * matching `AssignmentPickerDialog`'s own convention) rather than handing
 * it a boolean `open` prop, so a fresh mount is this component's only
 * "reset" — no effect here ever has to notice the dialog closing. Fetches
 * its own `GET /api/members/recordings/slots/` on mount rather than
 * requiring a caller to already hold a `PersonRecordingsBlock` (a Song
 * page never loads one), so the same flow — pick a song, pick a
 * rehearsal date, choose a file, confirm — works from any call site.
 * Never round-trips
 * through the Django app server for the file itself (ADR 0004): the
 * presign/upload steps are unchanged from the original Profile-only
 * implementation.
 */
export function RecordingUploadDialog({
  onOpenChange,
  preselectedSongId = null,
  onUploaded,
}: RecordingUploadDialogProps) {
  const [slots, setSlots] = useState<PersonRecordingsBlock['upload_slots']>([])
  const [slotsLoaded, setSlotsLoaded] = useState(false)

  useEffect(() => {
    void apiFetch<ReadEnvelope<PersonRecordingsBlock>>(
      '/api/members/recordings/slots/',
    ).then((envelope) => {
      setSlots(envelope.data.upload_slots)
      setSlotsLoaded(true)
    })
  }, [])

  return (
    <ResponsiveDialog open onOpenChange={onOpenChange} title="Upload a take">
      {!slotsLoaded ? (
        <p className="text-sm text-rs-muted">Loading…</p>
      ) : (
        <UploadForm
          slots={slots}
          preselectedSongId={preselectedSongId}
          onUploaded={(block) => {
            onUploaded(block)
            onOpenChange(false)
          }}
        />
      )}
    </ResponsiveDialog>
  )
}

/**
 * The pick-a-song/pick-a-rehearsal-date/choose-a-file/confirm form (issue
 * #395: previously one combined Song×Rehearsal dropdown, which grew hard
 * to scan with a full setlist and schedule and could offer a not-yet-run
 * Rehearsal that can't have a recording). `slots` already excludes future
 * Rehearsals — `recording_slot_options_for()` narrows to today-or-earlier
 * server-side — so splitting it into two selects is pure client-side
 * narrowing of what's already fetched, no new endpoint needed. When
 * `preselectedSongId` is set (opened via a specific Song's own "+"), the
 * Song select is locked to it rather than merely defaulted, per the
 * issue: a caller that already knows the Song shouldn't let the popup
 * wander to a different one.
 */
function UploadForm({
  slots,
  preselectedSongId,
  onUploaded,
}: {
  slots: PersonRecordingsBlock['upload_slots']
  preselectedSongId: number | null
  onUploaded: (block: PersonRecordingsBlock) => void
}) {
  const songOptions = useMemo(() => {
    const titleBySongId = new Map<number, string>()
    for (const slot of slots) {
      if (!titleBySongId.has(slot.song_id)) {
        titleBySongId.set(slot.song_id, slot.song_title)
      }
    }
    return Array.from(titleBySongId, ([id, title]) => ({ id, title }))
  }, [slots])

  const [songId, setSongId] = useState<number | ''>(
    preselectedSongId ?? songOptions[0]?.id ?? '',
  )
  const songIsLocked = preselectedSongId !== null

  const rehearsalSlots = useMemo(
    () => slots.filter((slot) => slot.song_id === songId),
    [slots, songId],
  )

  const [slotId, setSlotId] = useState<number | ''>(rehearsalSlots[0]?.id ?? '')
  const [slotIdForSongId, setSlotIdForSongId] = useState(songId)
  if (songId !== slotIdForSongId) {
    // Adjusting state during render (not an effect) when the chosen Song
    // changes — the React-recommended pattern for a derived reset, since
    // an effect's setState here would cascade an extra render for no
    // reason: https://react.dev/learn/you-might-not-need-an-effect
    setSlotIdForSongId(songId)
    setSlotId(rehearsalSlots[0]?.id ?? '')
  }

  const [note, setNote] = useState('')
  const [upload, setUpload] = useState<UploadState>({ step: 'idle' })
  const [isSaving, setIsSaving] = useState(false)

  /** Presigns and uploads the chosen file straight to R2, then marks the upload resolved (issue #333, ADR 0004). */
  async function handleFileChange(file: File) {
    setUpload({ step: 'uploading' })
    let reservation: RecordingPresignReservation
    try {
      const response = await fetch('/api/members/recordings/presign/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          content_type: file.type,
          file_size: file.size,
        }),
      })
      const body = (await response.json()) as
        | { context: unknown; data: RecordingPresignReservation }
        | (RecordingPresignErrorBody & { context: unknown })
      if (!response.ok) {
        setUpload({
          step: 'error',
          message: (body as RecordingPresignErrorBody).error,
        })
        return
      }
      reservation = (body as { data: RecordingPresignReservation }).data
    } catch {
      setUpload({ step: 'error', message: 'Could not reach the server.' })
      return
    }

    const formData = new FormData()
    for (const [key, value] of Object.entries(reservation.fields)) {
      formData.append(key, value)
    }
    formData.append('file', file)

    try {
      const uploadResponse = await fetch(reservation.upload_url, {
        method: 'POST',
        body: formData,
      })
      if (!uploadResponse.ok) {
        setUpload({ step: 'error', message: 'The upload to storage failed.' })
        return
      }
    } catch {
      setUpload({ step: 'error', message: 'The upload to storage failed.' })
      return
    }

    setUpload({ step: 'uploaded', objectKey: reservation.object_key })
  }

  /** Confirms the already-uploaded object onto the chosen slot (issue #333). */
  async function handleSave() {
    if (upload.step !== 'uploaded' || slotId === '') return
    setIsSaving(true)
    const envelope = await apiFetch<WriteEnvelope<PersonRecordingsBlock>>(
      '/api/members/recordings/confirm/',
      {
        method: 'POST',
        body: JSON.stringify({
          rehearsal_song_id: slotId,
          object_key: upload.objectKey,
          note,
        }),
      },
    )
    setIsSaving(false)
    if (envelope.ok && envelope.data !== null) {
      onUploaded(envelope.data)
    } else {
      setUpload({
        step: 'error',
        message:
          envelope.non_field_errors[0] ?? 'Could not save the recording.',
      })
    }
  }

  const canSave = upload.step === 'uploaded' && slotId !== '' && !isSaving

  return (
    <div>
      <p className="text-xs text-rs-muted">
        1. Pick a song → 2. Pick a rehearsal date → 3. Choose a file → 4.
        Confirm
      </p>

      <label className="mt-3 flex flex-col gap-1 text-sm">
        Which song is this a take of?
        <select
          value={songId}
          disabled={songIsLocked}
          onChange={(event) => setSongId(Number(event.target.value))}
          className="rounded border border-rs-border px-2 py-1 disabled:opacity-75"
        >
          {songIsLocked ? (
            <option value={preselectedSongId ?? ''}>
              {songOptions.find((song) => song.id === preselectedSongId)
                ?.title ?? 'This song'}
            </option>
          ) : (
            <>
              {songOptions.length === 0 && (
                <option value="">No songs yet</option>
              )}
              {songOptions.map((song) => (
                <option key={song.id} value={song.id}>
                  {song.title}
                </option>
              ))}
            </>
          )}
        </select>
      </label>

      <label className="mt-3 flex flex-col gap-1 text-sm">
        Which rehearsal is this a take from?
        <select
          value={slotId}
          onChange={(event) => setSlotId(Number(event.target.value))}
          className="rounded border border-rs-border px-2 py-1"
        >
          {rehearsalSlots.length === 0 && (
            <option value="">No past rehearsal dates for this song yet</option>
          )}
          {rehearsalSlots.map((slot) => (
            <option key={slot.id} value={slot.id}>
              {slot.rehearsal_date}
            </option>
          ))}
        </select>
        <span className="text-xs text-rs-muted">
          A recording belongs to one song at one rehearsal. Rehearsals you
          weren&apos;t at are listed too — you might be uploading someone
          else&apos;s take.
        </span>
      </label>

      <label className="mt-3 flex cursor-pointer flex-col items-center gap-1 rounded border border-dashed border-rs-border px-3 py-4 text-center text-sm">
        Drop an audio file, or browse
        <input
          type="file"
          accept="audio/*"
          className="sr-only"
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file !== undefined) void handleFileChange(file)
          }}
        />
      </label>
      {upload.step === 'uploading' && (
        <p className="mt-1 text-xs text-rs-muted">Uploading…</p>
      )}
      {upload.step === 'uploaded' && (
        <p className="mt-1 text-xs text-rs-muted">Upload complete.</p>
      )}
      {upload.step === 'error' && (
        <p className="mt-1 text-xs text-rs-danger">{upload.message}</p>
      )}

      <label className="mt-3 flex flex-col gap-1 text-sm">
        Note (optional)
        <input
          type="text"
          value={note}
          onChange={(event) => setNote(event.target.value)}
          className="rounded border border-rs-border px-2 py-1"
        />
      </label>

      <button
        type="button"
        onClick={() => void handleSave()}
        disabled={!canSave}
        className="mt-3 rounded bg-rs-accent px-3 py-1.5 text-sm font-medium text-rs-accent-fg disabled:opacity-50"
      >
        Save recording
      </button>
    </div>
  )
}
