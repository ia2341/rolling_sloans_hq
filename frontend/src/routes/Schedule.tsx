import type { KeyboardEvent } from 'react'
import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { apiFetch } from '../api/client'
import { useAppContext } from '../api/ContextProvider'
import type {
  Availability,
  DeclarationType,
  MatrixRow,
  RehearsalDetail,
  RoleLegendEntry,
  SchedulePayload,
  ScheduleListRow,
} from '../api/scheduleTypes'
import type { ReadEnvelope, WriteEnvelope } from '../api/types'
import { AssignmentEditor } from '../components/assignments/AssignmentEditor'
import { RecordingUploadDialog } from '../components/recordings/RecordingUploadDialog'
import { CastGridTable, type CastGridRow } from '../components/ui/CastLine'
import { PageHead } from '../components/ui/PageHead'
import { RehearsalOverview } from '../components/ui/RehearsalOverview'
import { ResponsiveDialog } from '../components/ui/ResponsiveDialog'
import { SegmentedControl } from '../components/ui/SegmentedControl'
import { useIsPhone } from '../hooks/useIsPhone'
import { formatClockTime, formatRehearsalDate } from '../lib/formatDate'
import { usePageTitle } from '../shell/PageTitleContext'

type SubView = 'next' | 'all'

/**
 * `/schedule/` (issue #331): the single member-facing page — the rehearsal
 * detail, the All-rehearsals list, and the viewer's own availability, fed
 * by one `GET /api/schedule/` round trip. The `This rehearsal | All
 * rehearsals` toggle is client-side state only; both sub-views arrive in
 * the same response, so switching between them costs no fetch (issue
 * #190's single-route guarantee).
 */
export function Schedule() {
  usePageTitle('Schedule')
  const appContext = useAppContext()
  const [searchParams, setSearchParams] = useSearchParams()
  const [data, setData] = useState<SchedulePayload | null>(null)
  const [editingAssignments, setEditingAssignments] = useState(false)

  const rehearsalParam = searchParams.get('rehearsal')
  const subView: SubView = searchParams.get('view') === 'all' ? 'all' : 'next'

  const load = useCallback(() => {
    const query = rehearsalParam !== null ? `?rehearsal=${rehearsalParam}` : ''
    void apiFetch<ReadEnvelope<SchedulePayload>>(`/api/schedule/${query}`).then(
      (envelope) => setData(envelope.data),
    )
  }, [rehearsalParam])

  useEffect(() => {
    load()
  }, [load])

  const setSubView = useCallback(
    (next: SubView) => {
      setSearchParams(
        (previous) => {
          const params = new URLSearchParams(previous)
          if (next === 'all') params.set('view', 'all')
          else params.delete('view')
          return params
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  const selectRehearsal = useCallback(
    (id: number) => {
      setEditingAssignments(false)
      setSearchParams(
        (previous) => {
          const params = new URLSearchParams(previous)
          params.set('rehearsal', String(id))
          params.delete('view')
          return params
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  if (data === null) return null

  if (
    data.selected === null &&
    data.schedule.past.length === 0 &&
    data.schedule.future.length === 0
  ) {
    return (
      <div>
        <PageHead
          title="Schedule"
          subline={data.semester_name ?? undefined}
          action={
            appContext?.viewer.is_admin ? (
              <div className="flex gap-2">
                <EditRehearsalsButton />
                <AdjudicateConflictsButton />
              </div>
            ) : undefined
          }
        />
        <p className="text-sm text-rs-muted">
          {data.semester_name === null
            ? 'No Semester published yet.'
            : 'No rehearsals scheduled yet this Semester.'}
        </p>
      </div>
    )
  }

  const allRows = [...data.schedule.past, ...data.schedule.future]
  const selected = data.selected

  return (
    <div>
      <PageHead
        title={
          selected !== null
            ? `Schedule: ${formatRehearsalDate(selected.date)}`
            : 'Schedule'
        }
        subline={
          selected !== null
            ? `${formatClockTime(selected.start_time)}–${formatClockTime(selected.end_time)}${
                selected.is_dress ? ' · dress rehearsal' : ''
              } · rehearsal ${allRows.findIndex((row) => row.id === selected.id) + 1} of ${allRows.length}`
            : undefined
        }
        action={
          appContext?.viewer.is_admin ? (
            <div className="flex gap-2">
              <EditRehearsalsButton />
              <AdjudicateConflictsButton />
            </div>
          ) : undefined
        }
      />

      <div className="flex flex-wrap items-center justify-between gap-3 pb-4">
        <SegmentedControl
          ariaLabel="Schedule view"
          options={[
            {
              value: 'next',
              label:
                selected !== null
                  ? formatRehearsalDate(selected.date)
                  : 'This rehearsal',
            },
            { value: 'all', label: 'All rehearsals' },
          ]}
          value={subView}
          onChange={(value) => setSubView(value as SubView)}
        />
        {subView === 'next' && selected !== null && (
          <RehearsalDateDropdown
            rows={allRows}
            selectedId={selected.id}
            onSelect={selectRehearsal}
          />
        )}
      </div>

      {subView === 'next' ? (
        selected === null ? (
          <p className="text-sm text-rs-muted">
            Select a rehearsal from All rehearsals.
          </p>
        ) : (
          <ThisRehearsal
            detail={selected}
            onDataChanged={load}
            editingAssignments={editingAssignments}
            onEnterEditMode={() => setEditingAssignments(true)}
            onExitEditMode={() => {
              setEditingAssignments(false)
              load()
            }}
            viewerId={appContext?.viewer.id}
          />
        )
      ) : (
        <AllRehearsals
          rows={allRows}
          onOpen={selectRehearsal}
          onChanged={load}
        />
      )}
    </div>
  )
}

/** Jump to a different Rehearsal's date without leaving `/schedule` — a dropdown, not a row of pills (issue: pills/tables UI overhaul). Sits on the same line as the rehearsal picker (issue: UI overhaul round 2). */
function RehearsalDateDropdown({
  rows,
  selectedId,
  onSelect,
}: {
  rows: ScheduleListRow[]
  selectedId: number
  onSelect: (id: number) => void
}) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <span className="text-rs-muted">Jump to</span>
      <select
        aria-label="Jump to rehearsal"
        value={selectedId}
        onChange={(event) => onSelect(Number(event.target.value))}
        className="rounded border border-rs-border px-2 py-1.5 text-sm"
      >
        {rows.map((row) => (
          <option key={row.id} value={row.id}>
            {formatRehearsalDate(row.date)}
            {row.is_dress ? ' · Dress' : ''}
          </option>
        ))}
      </select>
    </label>
  )
}

function ThisRehearsal({
  detail,
  onDataChanged,
  editingAssignments,
  onEnterEditMode,
  onExitEditMode,
  viewerId,
}: {
  detail: RehearsalDetail
  onDataChanged: () => void
  editingAssignments: boolean
  onEnterEditMode: () => void
  onExitEditMode: () => void
  viewerId?: number
}) {
  const navigate = useNavigate()
  const [uploadSongId, setUploadSongId] = useState<number | null>(null)

  return (
    <div>
      <RehearsalOverview
        heading="You at this rehearsal"
        date={detail.date}
        isDress={detail.is_dress}
        timeline={detail.timeline}
        showDate={false}
      />
      <AvailabilityBlock
        rehearsalId={detail.id}
        rehearsalStart={detail.start_time}
        rehearsalEnd={detail.end_time}
        availability={detail.availability}
        onChanged={onDataChanged}
      />
      {editingAssignments ? (
        <AssignmentEditor rehearsalId={detail.id} onDone={onExitEditMode} />
      ) : (
        <AssignmentGrid
          roles={detail.roles}
          rows={detail.rows}
          isDress={detail.is_dress}
          viewerId={viewerId}
          onOpenSong={(songId) => navigate(`/songs/${songId}`)}
          onAddRecording={setUploadSongId}
          canEditAssignments={detail.can_edit_assignments}
          onEditRehearsal={onEnterEditMode}
        />
      )}
      {uploadSongId !== null && (
        <RecordingUploadDialog
          onOpenChange={(open) => {
            if (!open) setUploadSongId(null)
          }}
          preselectedSongId={uploadSongId}
          onUploaded={onDataChanged}
        />
      )}
    </div>
  )
}

const DECLARATION_LABELS: Record<DeclarationType, string> = {
  full_absence: 'Unavailable for entire rehearsal',
  late_arrival: 'Arrive late at',
  early_departure: 'Leave early at',
}

const STATUS_TEXT: Record<NonNullable<Availability['status']>, string> = {
  pending: 'Awaiting an admin decision',
  approved: 'Approved',
  rejected: 'Not approved',
}

function AvailabilityBlock({
  rehearsalId,
  rehearsalStart,
  rehearsalEnd,
  availability,
  onChanged,
}: {
  rehearsalId: number
  rehearsalStart: string
  rehearsalEnd: string
  availability: Availability
  onChanged: () => void
}) {
  const [dialogOpen, setDialogOpen] = useState(false)

  if (availability.is_dress) {
    return (
      <section className="pb-4">
        <h2 className="text-sm font-semibold uppercase text-rs-muted">
          Your availability
        </h2>
        <div className="flex flex-col items-start gap-2 pt-1">
          <button
            type="button"
            disabled
            className="rounded border border-rs-border px-3 py-1.5 text-sm disabled:opacity-50"
          >
            Declare a conflict
          </button>
        </div>
      </section>
    )
  }

  if (!availability.is_editable && availability.declaration_type === null) {
    return (
      <section className="pb-4">
        <h2 className="text-sm font-semibold uppercase text-rs-muted">
          Your availability
        </h2>
        <p className="pt-1 text-sm">This rehearsal has passed.</p>
      </section>
    )
  }

  return (
    <section className="pb-4">
      <h2 className="text-sm font-semibold uppercase text-rs-muted">
        Your availability
      </h2>
      {availability.declaration_type === null ? (
        <div className="flex flex-col items-start gap-2 pt-1">
          <p className="text-sm">Available for the whole rehearsal</p>
          <button
            type="button"
            onClick={() => setDialogOpen(true)}
            className="rounded border border-rs-border px-3 py-1.5 text-sm"
          >
            Declare a conflict
          </button>
        </div>
      ) : (
        <div className="pt-1 text-sm">
          <p>
            <strong>{DECLARATION_LABELS[availability.declaration_type]}</strong>
            {availability.declared_time !== null &&
              ` ${formatClockTime(availability.declared_time)}`}
          </p>
          {availability.status !== null && (
            <p>{STATUS_TEXT[availability.status]}</p>
          )}
          {availability.admin_note !== null &&
            availability.admin_note !== '' && (
              <p className="text-rs-muted">
                From an admin: {availability.admin_note}
              </p>
            )}
          {availability.is_editable && (
            <div className="flex gap-2 pt-2">
              <button
                type="button"
                onClick={() => setDialogOpen(true)}
                className="text-sm text-rs-accent"
              >
                Edit
              </button>
              <WithdrawButton rehearsalId={rehearsalId} onChanged={onChanged} />
            </div>
          )}
        </div>
      )}
      <DeclareDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        rehearsalId={rehearsalId}
        rehearsalStart={rehearsalStart}
        rehearsalEnd={rehearsalEnd}
        initial={availability}
        onSaved={() => {
          setDialogOpen(false)
          onChanged()
        }}
      />
    </section>
  )
}

function WithdrawButton({
  rehearsalId,
  onChanged,
}: {
  rehearsalId: number
  onChanged: () => void
}) {
  const [pending, setPending] = useState(false)
  return (
    <button
      type="button"
      disabled={pending}
      onClick={() => {
        setPending(true)
        void apiFetch<WriteEnvelope>(
          `/api/schedule/${rehearsalId}/conflict/withdraw/`,
          {
            method: 'POST',
          },
        ).then(() => {
          setPending(false)
          onChanged()
        })
      }}
      className="text-sm text-rs-accent"
    >
      Withdraw
    </button>
  )
}

function DeclareDialog({
  open,
  onOpenChange,
  rehearsalId,
  rehearsalStart,
  rehearsalEnd,
  initial,
  onSaved,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  rehearsalId: number
  rehearsalStart: string
  rehearsalEnd: string
  initial: Availability
  onSaved: () => void
}) {
  const [declarationType, setDeclarationType] = useState<DeclarationType>(
    initial.declaration_type ?? 'full_absence',
  )
  const [time, setTime] = useState(
    initial.declared_time !== null
      ? formatClockTime(initial.declared_time)
      : '',
  )
  const [reason, setReason] = useState(initial.reason ?? '')
  const [errors, setErrors] = useState<Record<string, string[]>>({})

  const needsTime =
    declarationType === 'late_arrival' || declarationType === 'early_departure'

  const submit = () => {
    const payload: Record<string, string> = {
      declaration_type: declarationType,
      reason,
    }
    if (needsTime) {
      const field =
        declarationType === 'late_arrival' ? 'arrival_time' : 'departure_time'
      payload[field] = time
    }
    void apiFetch<WriteEnvelope>(`/api/schedule/${rehearsalId}/conflict/`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }).then((envelope) => {
      if (!envelope.ok) {
        setErrors(envelope.errors)
        return
      }
      setErrors({})
      onSaved()
    })
  }

  return (
    <ResponsiveDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Declare a conflict"
      footer={
        <>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="rounded px-3 py-1.5 text-sm"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={submit}
            className="rounded bg-rs-accent px-3 py-1.5 text-sm font-medium text-rs-accent-fg"
          >
            Save
          </button>
        </>
      }
    >
      <fieldset className="flex flex-col gap-2">
        <legend className="sr-only">Declaration type</legend>
        {(Object.keys(DECLARATION_LABELS) as DeclarationType[]).map((type) => (
          <label key={type} className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="declaration_type"
              value={type}
              checked={declarationType === type}
              onChange={() => setDeclarationType(type)}
            />
            {DECLARATION_LABELS[type]}
          </label>
        ))}
      </fieldset>
      {needsTime && (
        <div className="pt-2">
          <label className="text-sm" htmlFor="declare-time">
            {declarationType === 'late_arrival'
              ? 'Arrival time'
              : 'Departure time'}
          </label>
          <input
            id="declare-time"
            type="time"
            value={time}
            onChange={(event) => setTime(event.target.value)}
            min={formatClockTime(rehearsalStart)}
            max={formatClockTime(rehearsalEnd)}
            className="mt-1 block rounded border border-rs-border px-2 py-1 text-sm"
          />
          {errors[
            declarationType === 'late_arrival'
              ? 'arrival_time'
              : 'departure_time'
          ]?.map((message) => (
            <p key={message} className="text-xs text-rs-danger">
              {message}
            </p>
          ))}
        </div>
      )}
      <div className="pt-2">
        <label className="text-sm" htmlFor="declare-reason">
          Reason (optional)
        </label>
        <textarea
          id="declare-reason"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          className="mt-1 block w-full rounded border border-rs-border px-2 py-1 text-sm"
        />
      </div>
    </ResponsiveDialog>
  )
}

/** Adapts `MatrixRow[]` into `CastGridRow[]` — the shape the Setlist table and this read-only grid now share (issue: UI overhaul round 2, item 11). */
function matrixRowsToCastGridRows(
  rows: MatrixRow[],
  roles: RoleLegendEntry[],
): CastGridRow[] {
  const roleById = new Map(roles.map((role) => [role.id, role]))
  return rows.map((row) => ({
    id: row.song_id,
    position: row.song_position,
    title: row.song_title,
    artist: row.song_artist,
    length: row.song_length,
    cast: row.cells.map((cell) => {
      const role = roleById.get(cell.role_id)
      return {
        role_id: cell.role_id,
        role_name: role?.name ?? '',
        code: role?.code ?? '',
        performers: cell.entries.map((entry) => ({
          id: entry.person_id,
          name: entry.person_name,
          is_role_mismatch: entry.is_role_mismatch,
          kind: entry.kind,
          has_conflict: entry.has_conflict,
        })),
      }
    }),
  }))
}

function AssignmentGrid({
  roles,
  rows,
  isDress,
  viewerId,
  onOpenSong,
  onAddRecording,
  canEditAssignments,
  onEditRehearsal,
}: {
  roles: RoleLegendEntry[]
  rows: MatrixRow[]
  isDress: boolean
  viewerId?: number
  onOpenSong: (songId: number) => void
  onAddRecording: (songId: number) => void
  canEditAssignments: boolean
  onEditRehearsal: () => void
}) {
  const isPhone = useIsPhone()
  const appContext = useAppContext()
  const isAdmin = appContext?.viewer.is_admin ?? false
  const gridRows = matrixRowsToCastGridRows(rows, roles)

  return (
    <section className="pb-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase text-rs-muted">
          Running order & assignments
        </h2>
        {isAdmin && (
          <button
            type="button"
            disabled={!canEditAssignments}
            onClick={onEditRehearsal}
            className="rounded border border-rs-border px-3 py-1.5 text-sm font-medium disabled:opacity-50"
          >
            Edit Rehearsal
          </button>
        )}
      </div>
      {isPhone ? (
        <AssignmentCards rows={rows} isDress={isDress} />
      ) : (
        <CastGridTable
          roles={roles}
          rows={gridRows}
          viewerId={viewerId}
          isAdmin={isAdmin}
          onOpenRow={onOpenSong}
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
      )}
    </section>
  )
}

/** One cell's occupants: primary name (linking to their person page), each marker on its own line rather than a separate pill. */
function AssignmentCellEntries({
  entries,
}: {
  entries: MatrixRow['cells'][number]['entries']
}) {
  if (entries.length === 0) {
    return <span className="text-xs text-rs-muted">unfilled</span>
  }
  return (
    <div className="flex flex-col gap-1.5">
      {entries.map((entry) => (
        <div key={`${entry.kind}-${entry.id}`} className="text-sm">
          <Link
            to={`/members/${entry.person_id}`}
            className="font-medium text-rs-accent"
          >
            {entry.person_name}
          </Link>
          {entry.kind === 'backup' && (
            <div className="text-xs text-rs-muted">(backup)</div>
          )}
          {entry.has_conflict && (
            <div className="text-xs text-rs-muted">⚠ conflict</div>
          )}
          {entry.is_role_mismatch && (
            <div className="text-xs text-rs-muted">◦ role not declared</div>
          )}
        </div>
      ))}
    </div>
  )
}

function AssignmentCards({
  rows,
  isDress,
}: {
  rows: MatrixRow[]
  isDress: boolean
}) {
  return (
    <ul className="flex flex-col gap-3">
      {rows.map((row, index) => (
        <li key={row.song_id} className="rounded border border-rs-border p-3">
          <p className="font-medium">
            {isDress
              ? `${index + 1}. `
              : row.start_time !== null
                ? `${formatClockTime(row.start_time)} · `
                : ''}
            {row.song_title}
          </p>
          <ul className="mt-2 flex flex-col gap-2">
            {row.cells.map((cell) => (
              <li key={cell.role_id} className="text-sm">
                <AssignmentCellEntries entries={cell.entries} />
              </li>
            ))}
          </ul>
        </li>
      ))}
    </ul>
  )
}

function YourStateChip({ state }: { state: ScheduleListRow['your_state'] }) {
  if (state.kind === 'mandatory') return <span>Mandatory</span>
  if (state.kind === 'conflict') {
    return (
      <span>
        {state.type_label}
        {state.declared_time !== null &&
          ` ${formatClockTime(state.declared_time)}`}
      </span>
    )
  }
  if (state.kind === 'window') {
    return (
      <span>
        {formatClockTime(state.arrival_time)}–
        {formatClockTime(state.departure_time)}
      </span>
    )
  }
  return <span className="text-rs-muted">Not needed</span>
}

/** A row's Songs, each linking to its Song page — no pills, just text (issue: pills/tables UI overhaul). */
function YourSongsList({ songs }: { songs: ScheduleListRow['your_songs'] }) {
  if (songs.length === 0) {
    return <span className="text-xs text-rs-muted">—</span>
  }
  return (
    <div className="flex flex-col gap-0.5">
      {songs.map((song) => (
        <Link key={song.id} to={`/songs/${song.id}`} className="text-rs-accent">
          {song.title}
        </Link>
      ))}
    </div>
  )
}

/** Whether `declare_conflict()`/`future_rehearsals_for()` would accept a new Conflict against this row's Rehearsal (ADR 0006). */
function isConflictDeclarable(row: ScheduleListRow): boolean {
  return !row.is_dress && !row.is_past
}

/** The Dress Rehearsal's badge, matching Home's "Next rehearsal"/"Upcoming rehearsals" pill exactly (issue: pills/tables UI overhaul). */
function DressBadge() {
  return (
    <span className="rounded-full bg-rs-accent px-2 py-0.5 text-xs font-medium text-rs-accent-fg">
      Dress
    </span>
  )
}

/** Keyboard handler making a non-anchor "clickable card" activate on Enter/Space like a link would (mirrors Home.tsx's helper). */
function activateOnEnterOrSpace(onActivate: () => void) {
  return (event: KeyboardEvent) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      onActivate()
    }
  }
}

/**
 * One All-rehearsals card (issue: pills/tables UI overhaul, replacing the old table/"Open" button row).
 *
 * The whole card is clickable, navigating to this Rehearsal (the old
 * "Open" button's job) — the "+ Conflict" control sits on top of it and
 * stops its click from bubbling into the card's own navigation, since
 * without that both handlers would fire on one click.
 */
function RehearsalCard({
  row,
  onOpen,
  onAddConflict,
}: {
  row: ScheduleListRow
  onOpen: (id: number) => void
  onAddConflict: (id: number) => void
}) {
  return (
    <li
      role="link"
      tabIndex={0}
      onClick={() => onOpen(row.id)}
      onKeyDown={activateOnEnterOrSpace(() => onOpen(row.id))}
      aria-label={formatRehearsalDate(row.date)}
      className={`relative flex cursor-pointer flex-col gap-2 rounded border border-rs-border p-3 hover:bg-rs-border/20 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-rs-accent ${
        row.is_past ? 'opacity-60' : ''
      }`}
    >
      <div className="flex items-center justify-between gap-2 pr-16">
        <p className="font-medium">{formatRehearsalDate(row.date)}</p>
        {row.is_dress && <DressBadge />}
      </div>
      <p className="text-sm text-rs-muted">
        {formatClockTime(row.start_time)}–{formatClockTime(row.end_time)}
      </p>
      <div className="flex items-center justify-between text-sm">
        <YourStateChip state={row.your_state} />
        <span className="text-rs-muted">{row.song_count} songs</span>
      </div>
      {!row.is_dress && row.your_songs.length > 0 && (
        <div>
          <p className="text-xs font-semibold uppercase text-rs-muted">
            Your songs
          </p>
          <YourSongsList songs={row.your_songs} />
        </div>
      )}
      {row.pending_count !== undefined && (
        <p className="text-xs text-rs-muted">{row.pending_count} pending</p>
      )}
      {isConflictDeclarable(row) && (
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation()
            onAddConflict(row.id)
          }}
          className="absolute right-2 top-2 rounded border border-rs-border bg-rs-bg px-2 py-1 text-xs font-medium text-rs-accent"
        >
          + Conflict
        </button>
      )}
    </li>
  )
}

/**
 * The All-rehearsals sub-view (issue: pills/tables UI overhaul): a responsive grid of clickable cards, one per Rehearsal.
 *
 * Replaces the old desktop table (with its "Open" button column and its
 * separate "Add conflict" column) with the same card layout on every
 * viewport — the card itself is the "Open" affordance, and "+ Conflict"
 * is a control on the card rather than its own column.
 */
function AllRehearsals({
  rows,
  onOpen,
  onChanged,
}: {
  rows: ScheduleListRow[]
  onOpen: (id: number) => void
  onChanged: () => void
}) {
  const [conflictRowId, setConflictRowId] = useState<number | null>(null)
  const conflictRow =
    conflictRowId !== null
      ? (rows.find((row) => row.id === conflictRowId) ?? null)
      : null

  return (
    <>
      <ul className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {rows.map((row) => (
          <RehearsalCard
            key={row.id}
            row={row}
            onOpen={onOpen}
            onAddConflict={setConflictRowId}
          />
        ))}
      </ul>
      {conflictRow !== null && (
        <DeclareDialog
          open
          onOpenChange={(open) => {
            if (!open) setConflictRowId(null)
          }}
          rehearsalId={conflictRow.id}
          rehearsalStart={conflictRow.start_time}
          rehearsalEnd={conflictRow.end_time}
          initial={conflictRow.availability}
          onSaved={() => {
            setConflictRowId(null)
            onChanged()
          }}
        />
      )}
    </>
  )
}

/** The Schedule surface's single admin entry point into `/schedule/edit/` (issue #337 user story 1). */
function EditRehearsalsButton() {
  return (
    <Link
      to="/schedule/edit"
      className="rounded bg-rs-accent px-3 py-1.5 text-sm font-medium text-rs-accent-fg"
    >
      Edit rehearsals
    </Link>
  )
}

/** The Schedule surface's admin entry point into `/conflicts/`, the Conflict-adjudication index (issue #340). */
function AdjudicateConflictsButton() {
  return (
    <Link
      to="/conflicts"
      className="rounded border border-rs-border px-3 py-1.5 text-sm font-medium"
    >
      Adjudicate conflicts
    </Link>
  )
}
