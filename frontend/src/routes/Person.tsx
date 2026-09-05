import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'

import { ApiError, apiFetch } from '../api/client'
import type {
  MemberRole,
  PersonPayload,
  PersonRecordingsBlock,
  RecordingPresignErrorBody,
  RecordingPresignReservation,
} from '../api/memberTypes'
import type { ReadEnvelope, WriteEnvelope } from '../api/types'
import { PageHead } from '../components/ui/PageHead'
import { useIsPhone } from '../hooks/useIsPhone'
import { usePageTitle } from '../shell/PageTitleContext'

type LoadState =
  | { status: 'loading' }
  | { status: 'not_found' }
  | { status: 'loaded'; data: PersonPayload }

/** Formats a wire `HH:MM:SS` time string down to `HH:MM`, or `''` for `null`. */
function formatClockTime(isoTime: string | null): string {
  return isoTime === null ? '' : isoTime.slice(0, 5)
}

/**
 * `/members/<pk>/` (issue #333): one Person's page, in one round trip, in
 * one of three viewer states — teammate, self, or an admin viewing a
 * teammate. Which state this is is read entirely off the payload
 * (`is_self`, `can_edit_roles`, and whether `roles`/`songs`/`recordings`
 * are present at all) rather than re-derived client-side, per ADR 0005's
 * "the boundary is the surface, not the viewer".
 */
export function Person() {
  usePageTitle('Member')
  const { personId } = useParams<{ personId: string }>()
  const [searchParams] = useSearchParams()
  const [state, setState] = useState<LoadState>({ status: 'loading' })

  useEffect(() => {
    let cancelled = false
    void apiFetch<ReadEnvelope<PersonPayload>>(`/api/members/${personId}/`)
      .then((envelope) => {
        if (!cancelled) setState({ status: 'loaded', data: envelope.data })
      })
      .catch((error: unknown) => {
        if (cancelled) return
        if (error instanceof ApiError && error.status === 404) {
          setState({ status: 'not_found' })
          return
        }
        throw error
      })
    return () => {
      cancelled = true
    }
  }, [personId])

  if (state.status === 'loading') return null
  if (state.status === 'not_found') return <PageHead title="Member not found" />

  return (
    <PersonPage
      data={state.data}
      onDataChange={(next) => setState({ status: 'loaded', data: next })}
      preselectedSongId={searchParams.get('song')}
    />
  )
}

interface PersonPageProps {
  data: PersonPayload
  onDataChange: (next: PersonPayload) => void
  preselectedSongId: string | null
}

/**
 * Renders the loaded payload's sections in the issue's fixed order: page
 * head, Details, Declared roles, Songs (only when `songs` is present),
 * Your recordings (only when `recordings` is present), and the
 * "Deliberately absent" card, always. `onDataChange` lets a child section
 * (Roles save, an upload confirm, a delete) hand back the fresh payload it
 * received rather than re-fetching the whole page.
 */
function PersonPage({
  data,
  onDataChange,
  preselectedSongId,
}: PersonPageProps) {
  const subline =
    data.semester_name === null
      ? undefined
      : `${data.semester_name}${data.is_self ? ' · this is you' : ''}`

  return (
    <div className="flex flex-col gap-4">
      <PageHead title={data.name} subline={subline} />

      <DetailsCard data={data} />

      <RolesCard key={data.id} data={data} onDataChange={onDataChange} />

      {data.songs !== undefined && (
        <SongsCard songs={data.songs} isSelf={data.is_self} />
      )}

      {data.recordings !== undefined && (
        <RecordingsCard
          recordings={data.recordings}
          personId={data.id}
          preselectedSongId={preselectedSongId}
          onRecordingsChange={(recordings) =>
            onDataChange({ ...data, recordings })
          }
        />
      )}

      <DeliberatelyAbsentCard />
    </div>
  )
}

/** The Details card: Name, and Email (self only) — plus the self-only change-password row (issue #333). */
function DetailsCard({ data }: { data: PersonPayload }) {
  return (
    <section className="rounded border border-rs-border p-4">
      <h2 className="text-sm font-semibold uppercase text-rs-muted">Details</h2>
      <dl className="mt-2 flex flex-col gap-2 text-sm">
        <div>
          <dt className="text-rs-muted">Name</dt>
          <dd>{data.name}</dd>
        </div>
        {data.email !== undefined && (
          <div>
            <dt className="text-rs-muted">Email</dt>
            <dd>{data.email}</dd>
          </div>
        )}
      </dl>
      {data.is_self && <ChangePasswordRow />}
    </section>
  )
}

/** The self-only change-password affordance in the Details card (issue #333, #327). */
function ChangePasswordRow() {
  const [isOpen, setIsOpen] = useState(false)
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword1, setNewPassword1] = useState('')
  const [newPassword2, setNewPassword2] = useState('')
  const [errors, setErrors] = useState<Record<string, string[]>>({})
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved'>('idle')

  /** Submits the three password fields and reports per-field errors, or confirms success. */
  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setStatus('saving')
    const envelope = await apiFetch<WriteEnvelope>('/api/password/', {
      method: 'POST',
      body: JSON.stringify({
        old_password: oldPassword,
        new_password1: newPassword1,
        new_password2: newPassword2,
      }),
    })
    if (envelope.ok) {
      setStatus('saved')
      setErrors({})
      setOldPassword('')
      setNewPassword1('')
      setNewPassword2('')
      setIsOpen(false)
    } else {
      setStatus('idle')
      setErrors(envelope.errors)
    }
  }

  if (!isOpen) {
    return (
      <button
        type="button"
        onClick={() => setIsOpen(true)}
        className="mt-3 text-sm text-rs-accent"
      >
        Change password
      </button>
    )
  }

  return (
    <form
      onSubmit={(event) => void handleSubmit(event)}
      className="mt-3 flex flex-col gap-2"
    >
      <label className="flex flex-col gap-1 text-sm">
        Current password
        <input
          type="password"
          value={oldPassword}
          onChange={(event) => setOldPassword(event.target.value)}
          className="rounded border border-rs-border px-2 py-1"
        />
        {errors.old_password?.map((message) => (
          <span key={message} className="text-rs-danger">
            {message}
          </span>
        ))}
      </label>
      <label className="flex flex-col gap-1 text-sm">
        New password
        <input
          type="password"
          value={newPassword1}
          onChange={(event) => setNewPassword1(event.target.value)}
          className="rounded border border-rs-border px-2 py-1"
        />
        {errors.new_password1?.map((message) => (
          <span key={message} className="text-rs-danger">
            {message}
          </span>
        ))}
      </label>
      <label className="flex flex-col gap-1 text-sm">
        Confirm new password
        <input
          type="password"
          value={newPassword2}
          onChange={(event) => setNewPassword2(event.target.value)}
          className="rounded border border-rs-border px-2 py-1"
        />
        {errors.new_password2?.map((message) => (
          <span key={message} className="text-rs-danger">
            {message}
          </span>
        ))}
      </label>
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={status === 'saving'}
          className="rounded bg-rs-accent px-3 py-1.5 text-sm font-medium text-rs-accent-fg"
        >
          Save password
        </button>
        <button
          type="button"
          onClick={() => setIsOpen(false)}
          className="rounded border border-rs-border px-3 py-1.5 text-sm"
        >
          Cancel
        </button>
      </div>
    </form>
  )
}

/**
 * The Declared roles card (issue #333): editable chips with ✕ and a
 * `+ add a role` chip plus a **Save roles** button when `can_edit_roles`,
 * read-only chips plus the ownership line otherwise. Removing a chip only
 * *stages* the removal locally — nothing round-trips until **Save roles**
 * is clicked.
 */
function RolesCard({
  data,
  onDataChange,
}: {
  data: PersonPayload
  onDataChange: (next: PersonPayload) => void
}) {
  const savedRoleIds = useMemo(
    () => new Set((data.roles ?? []).map((role) => role.id)),
    [data.roles],
  )
  // Initialized once from the saved payload; a successful Save roles
  // submits exactly this set, so it never drifts from `savedRoleIds`
  // afterwards. Switching to a different Person remounts this component
  // fresh, via the `key={data.id}` at its call site, rather than resyncing
  // in an effect.
  const [stagedRoleIds, setStagedRoleIds] = useState<Set<number>>(savedRoleIds)
  const [isSaving, setIsSaving] = useState(false)

  if (!data.can_edit_roles) {
    const roles = data.roles ?? []
    return (
      <section className="rounded border border-rs-border p-4">
        <h2 className="text-sm font-semibold uppercase text-rs-muted">
          Declared roles
        </h2>
        <ul className="mt-2 flex flex-wrap gap-2">
          {roles.map((role) => (
            <li
              key={role.id}
              className="rounded-full border border-rs-border px-3 py-1 text-sm"
            >
              {role.name}
            </li>
          ))}
        </ul>
        <p className="mt-2 text-sm text-rs-muted">
          Only they (or an admin) can change these.
        </p>
      </section>
    )
  }

  const availableRoles = data.available_roles ?? []
  const stagedRoles: MemberRole[] = availableRoles.filter((role) =>
    stagedRoleIds.has(role.id),
  )
  const addableRoles = availableRoles.filter(
    (role) => !stagedRoleIds.has(role.id),
  )

  /** Stages a Role's removal from the chip list; nothing round-trips until Save roles. */
  function stageRemoval(roleId: number) {
    setStagedRoleIds((previous) => {
      const next = new Set(previous)
      next.delete(roleId)
      return next
    })
  }

  /** Stages adding a Role from the catalog. */
  function stageAddition(roleId: number) {
    setStagedRoleIds((previous) => new Set(previous).add(roleId))
  }

  /** Persists the staged Role set via `POST /api/members/<pk>/roles/`. */
  async function handleSave() {
    setIsSaving(true)
    const envelope = await apiFetch<WriteEnvelope<PersonPayload>>(
      `/api/members/${data.id}/roles/`,
      {
        method: 'POST',
        body: JSON.stringify({ role_ids: [...stagedRoleIds] }),
      },
    )
    setIsSaving(false)
    if (envelope.ok && envelope.data !== null) {
      onDataChange(envelope.data)
    }
  }

  return (
    <section className="rounded border border-rs-border p-4">
      <h2 className="text-sm font-semibold uppercase text-rs-muted">
        Declared roles
      </h2>
      <ul className="mt-2 flex flex-wrap gap-2">
        {stagedRoles.map((role) => (
          <li
            key={role.id}
            className="flex items-center gap-1 rounded-full border border-rs-border px-3 py-1 text-sm"
          >
            {role.name}
            <button
              type="button"
              aria-label={`Remove ${role.name}`}
              onClick={() => stageRemoval(role.id)}
              className="text-rs-muted hover:text-rs-fg"
            >
              ✕
            </button>
          </li>
        ))}
        {addableRoles.length > 0 && (
          <li>
            <AddRoleChip roles={addableRoles} onAdd={stageAddition} />
          </li>
        )}
      </ul>
      <button
        type="button"
        onClick={() => void handleSave()}
        disabled={isSaving}
        className="mt-3 rounded bg-rs-accent px-3 py-1.5 text-sm font-medium text-rs-accent-fg"
      >
        Save roles
      </button>
    </section>
  )
}

/** The `+ add a role` chip: a native `<select>` disguised as a chip, listing only Roles not already staged. */
function AddRoleChip({
  roles,
  onAdd,
}: {
  roles: MemberRole[]
  onAdd: (roleId: number) => void
}) {
  return (
    <label className="flex items-center gap-1 rounded-full border border-dashed border-rs-border px-3 py-1 text-sm text-rs-muted">
      + add a role
      <select
        aria-label="Add a role"
        value=""
        onChange={(event) => {
          const roleId = Number(event.target.value)
          if (roleId) onAdd(roleId)
        }}
        className="bg-transparent text-sm"
      >
        <option value="" />
        {roles.map((role) => (
          <option key={role.id} value={role.id}>
            {role.name}
          </option>
        ))}
      </select>
    </label>
  )
}

/** Songs section: title, artist and the Role pill filled on each (issue #333). Never `is_role_mismatch` (ADR 0002). */
function SongsCard({
  songs,
  isSelf,
}: {
  songs: PersonPayload['songs']
  isSelf: boolean
}) {
  const title = isSelf ? "Songs you're on" : 'Songs they are on'
  return (
    <section className="rounded border border-rs-border p-4">
      <h2 className="text-sm font-semibold uppercase text-rs-muted">{title}</h2>
      {songs === undefined || songs.length === 0 ? (
        <p className="mt-2 text-sm text-rs-muted">Not on any song yet.</p>
      ) : (
        <ul className="mt-2 flex flex-col gap-2">
          {songs.map((song) => (
            <li
              key={song.song_id}
              className="flex items-center justify-between gap-2 text-sm"
            >
              <Link to={`/songs/${song.song_id}`} className="font-medium">
                {song.song_title}
              </Link>
              <span className="text-rs-muted">{song.artist}</span>
              <span className="rounded-full bg-rs-accent px-2 py-0.5 text-xs font-medium text-rs-accent-fg">
                {song.role_name}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

type UploadState =
  | { step: 'idle' }
  | { step: 'uploading' }
  | { step: 'uploaded'; objectKey: string }
  | { step: 'error'; message: string }

/** Your recordings — self only (issue #333). List, inline player, delete, and the Upload-a-take card. */
function RecordingsCard({
  recordings,
  personId,
  preselectedSongId,
  onRecordingsChange,
}: {
  recordings: PersonRecordingsBlock
  personId: number
  preselectedSongId: string | null
  onRecordingsChange: (recordings: PersonRecordingsBlock) => void
}) {
  const isPhone = useIsPhone()

  /** Deletes one of the requester's own Recordings and refreshes the block. */
  async function handleDelete(recordingId: number) {
    const envelope = await apiFetch<WriteEnvelope<PersonRecordingsBlock>>(
      `/api/members/recordings/${recordingId}/delete/`,
      { method: 'POST' },
    )
    if (envelope.ok && envelope.data !== null) {
      onRecordingsChange(envelope.data)
    }
  }

  return (
    <section className="rounded border border-rs-border p-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-semibold uppercase text-rs-muted">
          Your recordings
        </h2>
        <span className="text-xs text-rs-muted">
          {recordings.count} upload{recordings.count === 1 ? '' : 's'} · only
          you can see this
        </span>
      </div>

      {recordings.items.length === 0 ? (
        <p className="mt-2 text-sm text-rs-muted">
          You haven&apos;t uploaded a take yet.
        </p>
      ) : isPhone ? (
        <RecordingCards items={recordings.items} onDelete={handleDelete} />
      ) : (
        <RecordingTable items={recordings.items} onDelete={handleDelete} />
      )}

      <UploadCard
        personId={personId}
        slots={recordings.upload_slots}
        preselectedSongId={preselectedSongId}
        onUploaded={(block) => onRecordingsChange(block)}
      />
    </section>
  )
}

/** Phone layout for the self-only Recordings list: one card per take, inline player, no horizontal scroll (issue #333). */
function RecordingCards({
  items,
  onDelete,
}: {
  items: PersonRecordingsBlock['items']
  onDelete: (recordingId: number) => void
}) {
  return (
    <ul className="mt-2 flex flex-col gap-3">
      {items.map((recording) => (
        <li
          key={recording.id}
          className="flex flex-col gap-1 rounded border border-rs-border p-2 text-sm"
        >
          <div className="flex items-center justify-between gap-2">
            <span className="font-medium">{recording.song_title}</span>
            <span className="text-rs-muted">
              {recording.rehearsal_date}
              {recording.start_time !== null &&
                ` · ${formatClockTime(recording.start_time)}–${formatClockTime(recording.end_time)}`}
            </span>
          </div>
          <audio controls src={recording.playback_url} className="w-full" />
          <div className="flex items-center justify-between text-rs-muted">
            <span>
              {(recording.file_size / (1024 * 1024)).toFixed(1)} MB
              {recording.note !== '' && ` — ${recording.note}`}
            </span>
            <button
              type="button"
              onClick={() => onDelete(recording.id)}
              className="text-rs-danger"
            >
              Delete
            </button>
          </div>
        </li>
      ))}
    </ul>
  )
}

/** Desktop layout for the self-only Recordings list: `Song | Rehearsal | (player) | Size | Note` plus Delete (issue #333). */
function RecordingTable({
  items,
  onDelete,
}: {
  items: PersonRecordingsBlock['items']
  onDelete: (recordingId: number) => void
}) {
  return (
    <table className="mt-2 w-full text-left text-sm">
      <thead>
        <tr>
          <th className="pb-2">Song</th>
          <th className="pb-2">Rehearsal</th>
          <th className="pb-2">Player</th>
          <th className="pb-2">Size</th>
          <th className="pb-2">Note</th>
          <th className="pb-2" />
        </tr>
      </thead>
      <tbody>
        {items.map((recording) => (
          <tr key={recording.id}>
            <td className="py-2 align-top">{recording.song_title}</td>
            <td className="py-2 align-top text-rs-muted">
              {recording.rehearsal_date}
              {recording.start_time !== null &&
                ` · ${formatClockTime(recording.start_time)}–${formatClockTime(recording.end_time)}`}
            </td>
            <td className="py-2 align-top">
              <audio controls src={recording.playback_url} />
            </td>
            <td className="py-2 align-top text-rs-muted">
              {(recording.file_size / (1024 * 1024)).toFixed(1)} MB
            </td>
            <td className="py-2 align-top text-rs-muted">{recording.note}</td>
            <td className="py-2 align-top">
              <button
                type="button"
                onClick={() => onDelete(recording.id)}
                className="text-rs-danger"
              >
                Delete
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** The Upload-a-take card: pick a slot → choose a file → confirm (issue #333). */
function UploadCard({
  slots,
  preselectedSongId,
  onUploaded,
}: {
  personId: number
  slots: PersonRecordingsBlock['upload_slots']
  preselectedSongId: string | null
  onUploaded: (block: PersonRecordingsBlock) => void
}) {
  const filteredSlots = useMemo(() => {
    if (preselectedSongId === null) return slots
    const songId = Number(preselectedSongId)
    const narrowed = slots.filter((slot) => slot.song_id === songId)
    return narrowed.length > 0 ? narrowed : slots
  }, [slots, preselectedSongId])

  const [slotId, setSlotId] = useState<number | ''>(filteredSlots[0]?.id ?? '')
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
      setNote('')
      setUpload({ step: 'idle' })
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
    <div className="mt-4 rounded border border-rs-border p-3">
      <h3 className="text-sm font-semibold">Upload a take</h3>
      <p className="mt-1 text-xs text-rs-muted">
        1. Pick a slot → 2. Choose a file → 3. Confirm
      </p>

      <label className="mt-3 flex flex-col gap-1 text-sm">
        Which slot is this a take of?
        <select
          value={slotId}
          onChange={(event) => setSlotId(Number(event.target.value))}
          className="rounded border border-rs-border px-2 py-1"
        >
          {filteredSlots.length === 0 && <option value="">No slots yet</option>}
          {filteredSlots.map((slot) => (
            <option key={slot.id} value={slot.id}>
              {slot.song_title} — {slot.rehearsal_date}
            </option>
          ))}
        </select>
        <span className="text-xs text-rs-muted">
          A recording belongs to one song at one rehearsal. Slots you
          weren&apos;t at are listed too — you might be uploading someone
          else&apos;s take.
        </span>
      </label>

      <label className="mt-3 flex cursor-pointer flex-col items-center gap-1 rounded border border-dashed border-rs-border px-3 py-4 text-center text-sm">
        Drop an audio file, or browse
        <span className="text-xs text-rs-muted">
          Uploads straight to storage, not through the app (ADR 0004).
        </span>
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

/** The dashed "Deliberately absent" card (issue #333), rendered for every viewer state. */
function DeliberatelyAbsentCard() {
  return (
    <section className="rounded border border-dashed border-rs-border p-4 text-sm text-rs-muted">
      <p>
        <strong>Deliberately absent.</strong> Conflicts, Backups, attendance and
        admin status are never on this page, for any viewer including an admin.
        Availability lives on the Schedule; a Backup needs a Rehearsal in scope
        and this page has none.
      </p>
    </section>
  )
}
