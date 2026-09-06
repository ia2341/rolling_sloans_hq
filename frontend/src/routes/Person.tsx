import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'

import { ApiError, apiFetch } from '../api/client'
import type {
  MemberRole,
  PersonPayload,
  PersonRecordingsBlock,
} from '../api/memberTypes'
import type { ReadEnvelope, WriteEnvelope } from '../api/types'
import { RecordingUploadDialog } from '../components/recordings/RecordingUploadDialog'
import { PageHead } from '../components/ui/PageHead'
import { useIsPhone } from '../hooks/useIsPhone'
import { formatClockTime } from '../lib/formatDate'
import { usePageTitle } from '../shell/PageTitleContext'

type LoadState =
  | { status: 'loading' }
  | { status: 'not_found' }
  | { status: 'loaded'; data: PersonPayload }

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
 * and Your recordings (only when `recordings` is present). `onDataChange`
 * lets a child section (Roles save, an upload confirm, a delete) hand
 * back the fresh payload it received rather than re-fetching the whole
 * page. There used to be a "Deliberately absent" card here explaining
 * that Conflicts/Backups/attendance/admin status never appear on this
 * page — removed as unnecessary chrome (issue #363); ADR 0005's
 * boundary and `docs/person-page-visibility.md` still govern what this
 * page may show, this was only ever a footnote about it.
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

      <DetailsAndRolesCard
        key={data.id}
        data={data}
        onDataChange={onDataChange}
      />

      {data.songs !== undefined && (
        <SongsCard songs={data.songs} isSelf={data.is_self} />
      )}

      {data.recordings !== undefined && (
        <RecordingsCard
          recordings={data.recordings}
          preselectedSongId={preselectedSongId}
          onRecordingsChange={(recordings) =>
            onDataChange({ ...data, recordings })
          }
        />
      )}
    </div>
  )
}

/**
 * Details and Declared roles, one card in two columns rather than two
 * stacked full-width cards (issue: UI overhaul round 2) — Details on the
 * left, Declared roles (and its edit controls, when this viewer may use
 * them) on the right. Stacks on a phone.
 */
function DetailsAndRolesCard({
  data,
  onDataChange,
}: {
  data: PersonPayload
  onDataChange: (next: PersonPayload) => void
}) {
  return (
    <section className="rounded border border-rs-border p-4">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 md:divide-x md:divide-rs-border">
        <div>
          <DetailsSection data={data} onDataChange={onDataChange} />
        </div>
        <div className="md:pl-4">
          <RolesSection data={data} onDataChange={onDataChange} />
        </div>
      </div>
    </section>
  )
}

/** Details section content: Name, and Email (self only) — plus the self-only change-password row (issue #333) and the admin-only Invite action (issue #397). */
function DetailsSection({
  data,
  onDataChange,
}: {
  data: PersonPayload
  onDataChange: (next: PersonPayload) => void
}) {
  return (
    <div>
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
      {data.invite_status !== undefined &&
        data.invite_status !== 'accepted' && (
          <InviteRow
            personId={data.id}
            inviteStatus={data.invite_status}
            onDataChange={onDataChange}
          />
        )}
    </div>
  )
}

/**
 * The admin-only Invite action (issue #397): renders for a teammate whose
 * `invite_status` isn't `'accepted'` yet — "Invite" for `'not_yet_invited'`,
 * "Invite again" for `'invited'`. Calls the same
 * `RosterResendInviteApiView` the Roster editor's "Invite again" control
 * calls, mounted here at `/api/members/<pk>/invite/`.
 */
function InviteRow({
  personId,
  inviteStatus,
  onDataChange,
}: {
  personId: number
  inviteStatus: Exclude<PersonPayload['invite_status'], 'accepted' | undefined>
  onDataChange: (next: PersonPayload) => void
}) {
  const [status, setStatus] = useState<'idle' | 'sending' | 'sent'>('idle')

  /** Sends (or re-sends) the invite and refreshes the page with the server's fresh Person payload. */
  async function handleInvite() {
    setStatus('sending')
    const envelope = await apiFetch<WriteEnvelope<PersonPayload>>(
      `/api/members/${personId}/invite/`,
      { method: 'POST' },
    )
    if (envelope.ok && envelope.data !== null) {
      onDataChange(envelope.data)
      setStatus('sent')
    } else {
      setStatus('idle')
    }
  }

  return (
    <button
      type="button"
      onClick={() => void handleInvite()}
      disabled={status !== 'idle'}
      className="mt-3 rounded border border-rs-border px-3 py-1.5 text-sm font-medium text-rs-accent disabled:cursor-not-allowed disabled:opacity-50"
    >
      {status === 'sent'
        ? 'Invite sent'
        : inviteStatus === 'not_yet_invited'
          ? 'Invite'
          : 'Invite again'}
    </button>
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
 * Declared roles section content (issue #333): editable chips with ✕ and a
 * `+ add a role` chip plus a **Save roles** button when `can_edit_roles`,
 * read-only chips plus the ownership line otherwise. Removing a chip only
 * *stages* the removal locally — nothing round-trips until **Save roles**
 * is clicked. Sits on the right of the Details section (issue: UI overhaul
 * round 2) rather than in its own full-width card below it.
 */
function RolesSection({
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
      <div>
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
      </div>
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
    <div>
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
            <AddRoleSelect roles={addableRoles} onAdd={stageAddition} />
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
    </div>
  )
}

/**
 * The "add a role" affordance (issue #363): a native `<select>` whose own
 * placeholder option reads "+ add a role", rather than a separate pill
 * label sitting beside an empty-looking dropdown. Disabled and unselectable
 * (`<option disabled>`, matching `ScheduleEdit`'s "+ Add song" select), so
 * it can never itself be staged as a chosen Role — it resets to itself
 * after each pick since the `<select>` is uncontrolled. Lists only Roles
 * not already staged.
 */
function AddRoleSelect({
  roles,
  onAdd,
}: {
  roles: MemberRole[]
  onAdd: (roleId: number) => void
}) {
  return (
    <select
      aria-label="Add a role"
      defaultValue=""
      onChange={(event) => {
        const roleId = Number(event.target.value)
        if (roleId) onAdd(roleId)
        event.target.value = ''
      }}
      className="rounded-full border border-dashed border-rs-border bg-transparent px-3 py-1 text-sm text-rs-muted"
    >
      <option value="" disabled>
        + add a role
      </option>
      {roles.map((role) => (
        <option key={role.id} value={role.id}>
          {role.name}
        </option>
      ))}
    </select>
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
        <table className="mt-2 w-full border-collapse text-left text-sm">
          <thead>
            <tr>
              <th className="border border-rs-border px-2 py-2">Song</th>
              <th className="border border-rs-border px-2 py-2">Artist</th>
              <th className="border border-rs-border px-2 py-2">Role</th>
            </tr>
          </thead>
          <tbody>
            {songs.map((song) => (
              <tr key={song.song_id}>
                <td className="border border-rs-border px-2 py-2 align-top">
                  <Link to={`/songs/${song.song_id}`} className="font-medium">
                    {song.song_title}
                  </Link>
                </td>
                <td className="border border-rs-border px-2 py-2 align-top text-rs-muted">
                  {song.artist}
                </td>
                <td className="border border-rs-border px-2 py-2 align-top">
                  {song.role_name}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

/** Your recordings — self only (issue #333). List, inline player, delete, and the "Add Recording" popup trigger. */
function RecordingsCard({
  recordings,
  preselectedSongId,
  onRecordingsChange,
}: {
  recordings: PersonRecordingsBlock
  preselectedSongId: string | null
  onRecordingsChange: (recordings: PersonRecordingsBlock) => void
}) {
  const isPhone = useIsPhone()
  const [uploadOpen, setUploadOpen] = useState(false)

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
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold uppercase text-rs-muted">
          Your recordings
        </h2>
        <div className="flex items-center gap-3">
          <span className="text-xs text-rs-muted">
            {recordings.count} upload{recordings.count === 1 ? '' : 's'} · only
            you can see this
          </span>
          <button
            type="button"
            onClick={() => setUploadOpen(true)}
            className="rounded border border-rs-border px-2 py-1 text-xs font-medium text-rs-accent"
          >
            + Add Recording
          </button>
        </div>
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

      {uploadOpen && (
        <RecordingUploadDialog
          onOpenChange={(open) => {
            if (!open) setUploadOpen(false)
          }}
          preselectedSongId={
            preselectedSongId !== null ? Number(preselectedSongId) : null
          }
          onUploaded={onRecordingsChange}
        />
      )}
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
