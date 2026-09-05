import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { apiFetch } from '../api/client'
import { useAppContext } from '../api/ContextProvider'
import type {
  Availability,
  DeclarationType,
  MatrixRow,
  RehearsalDetail,
  SchedulePayload,
  ScheduleListRow,
  Timeline,
} from '../api/scheduleTypes'
import type { ReadEnvelope, WriteEnvelope } from '../api/types'
import { PageHead } from '../components/ui/PageHead'
import { roleHueVar } from '../components/ui/RoleLegend'
import { ResponsiveDialog } from '../components/ui/ResponsiveDialog'
import { SegmentedControl } from '../components/ui/SegmentedControl'
import { useIsPhone } from '../hooks/useIsPhone'
import { usePageTitle } from '../shell/PageTitleContext'

/** Trims a wire `HH:MM:SS` time string down to `HH:MM` for display. */
function formatClockTime(isoTime: string): string {
  return isoTime.slice(0, 5)
}

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
        <PageHead title="Schedule" subline={data.semester_name ?? undefined} />
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
        title={selected !== null ? selected.date : 'Schedule'}
        subline={
          selected !== null
            ? `${formatClockTime(selected.start_time)}–${formatClockTime(selected.end_time)}${
                selected.is_dress ? ' · dress rehearsal' : ''
              } · rehearsal ${allRows.findIndex((row) => row.id === selected.id) + 1} of ${allRows.length}`
            : undefined
        }
        action={
          appContext?.viewer.is_admin && selected !== null ? (
            <button
              type="button"
              disabled={!selected.can_edit_assignments}
              title="Assignment editing (issue #338)"
              className="rounded bg-rs-accent px-3 py-1.5 text-sm font-medium text-rs-accent-fg disabled:opacity-50"
            >
              Edit assignments
            </button>
          ) : undefined
        }
      />

      <div className="pb-4">
        <SegmentedControl
          ariaLabel="Schedule view"
          options={[
            { value: 'next', label: 'This rehearsal' },
            { value: 'all', label: 'All rehearsals' },
          ]}
          value={subView}
          onChange={(value) => setSubView(value as SubView)}
        />
      </div>

      {subView === 'next' ? (
        selected === null ? (
          <p className="text-sm text-rs-muted">
            Select a rehearsal from All rehearsals.
          </p>
        ) : (
          <ThisRehearsal
            detail={selected}
            allRows={allRows}
            onSelectRehearsal={selectRehearsal}
            onDataChanged={load}
          />
        )
      ) : (
        <AllRehearsals
          rows={allRows}
          isAdmin={appContext?.viewer.is_admin ?? false}
          onOpen={selectRehearsal}
        />
      )}
    </div>
  )
}

function QuickJumpRow({
  rows,
  selectedId,
  onSelect,
}: {
  rows: ScheduleListRow[]
  selectedId: number
  onSelect: (id: number) => void
}) {
  return (
    <div
      className="flex gap-2 overflow-x-auto pb-4"
      role="tablist"
      aria-label="Jump to rehearsal"
    >
      {rows.map((row) => (
        <button
          key={row.id}
          type="button"
          onClick={() => onSelect(row.id)}
          aria-current={row.id === selectedId}
          className={`shrink-0 rounded px-3 py-1.5 text-sm ${
            row.id === selectedId
              ? 'bg-rs-accent text-rs-accent-fg'
              : 'border border-rs-border text-rs-fg'
          }`}
        >
          {row.date}
        </button>
      ))}
    </div>
  )
}

function ThisRehearsal({
  detail,
  allRows,
  onSelectRehearsal,
  onDataChanged,
}: {
  detail: RehearsalDetail
  allRows: ScheduleListRow[]
  onSelectRehearsal: (id: number) => void
  onDataChanged: () => void
}) {
  return (
    <div>
      <QuickJumpRow
        rows={allRows}
        selectedId={detail.id}
        onSelect={onSelectRehearsal}
      />
      <TimelineView timeline={detail.timeline} />
      <AvailabilityBlock
        rehearsalId={detail.id}
        rehearsalStart={detail.start_time}
        rehearsalEnd={detail.end_time}
        availability={detail.availability}
        onChanged={onDataChanged}
      />
      <AssignmentGrid
        roles={detail.roles}
        rows={detail.rows}
        isDress={detail.is_dress}
      />
    </div>
  )
}

function TimelineView({ timeline }: { timeline: Timeline }) {
  if (timeline.is_dress_rehearsal) {
    return (
      <section className="pb-4">
        <h2 className="text-sm font-semibold uppercase text-rs-muted">
          You at this rehearsal
        </h2>
        <p className="pt-1 text-sm">
          Whole setlist, whole window — {formatClockTime(timeline.window_start)}
          –{formatClockTime(timeline.window_end)}
        </p>
        <p className="text-sm text-rs-muted">
          The dress rehearsal runs the current setlist live (ADR 0003).
        </p>
      </section>
    )
  }

  if (timeline.viewer_song_count === 0) {
    return (
      <section className="pb-4">
        <h2 className="text-sm font-semibold uppercase text-rs-muted">
          You at this rehearsal
        </h2>
        <p className="pt-1 text-sm text-rs-muted">
          You are not on any song here.
        </p>
      </section>
    )
  }

  return (
    <section className="pb-4">
      <h2 className="text-sm font-semibold uppercase text-rs-muted">
        You at this rehearsal
      </h2>
      <p className="pt-1 text-sm">
        Arrive around{' '}
        <strong>
          {formatClockTime(timeline.viewer_start_time ?? timeline.window_start)}
        </strong>
        , free to leave around{' '}
        <strong>
          {formatClockTime(timeline.viewer_end_time ?? timeline.window_end)}
        </strong>
      </p>
      <div
        className="mt-2 flex overflow-hidden rounded border border-rs-border"
        role="img"
        aria-label="Timeline of tonight's slots"
      >
        {timeline.slots.map((slot) => (
          <div
            key={slot.song_id}
            title={`${slot.song_title} (${formatClockTime(slot.start_time)}–${formatClockTime(slot.end_time)})`}
            className={`h-6 flex-1 border-r border-rs-border last:border-r-0 ${
              slot.is_viewer ? 'bg-rs-accent' : 'bg-rs-border/30'
            }`}
          />
        ))}
      </div>
      <p className="pt-1 text-xs text-rs-muted">
        {formatClockTime(timeline.window_start)} · You:{' '}
        {timeline.viewer_song_count} of {timeline.total_song_count} songs ·{' '}
        {formatClockTime(timeline.window_end)}
      </p>
    </section>
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
        <p className="pt-1 text-sm">
          Attendance is required at the dress rehearsal. There is nothing to
          declare here (ADR 0006).
        </p>
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
        <div className="flex items-center justify-between pt-1">
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
          <p className="text-xs text-rs-muted">
            Your reason and this decision are visible to you and to admins only
            — never on a page another member can read (ADR 0005).
          </p>
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
      <p className="pt-2 text-xs text-rs-muted">
        Only admins ever see this reason. It never renders on a page another
        member can read — including for an admin browsing as a member (ADR
        0005).
      </p>
      <p className="text-xs text-rs-muted">
        The dress rehearsal takes no conflict: attendance there is required (ADR
        0006), so it is not offered.
      </p>
    </ResponsiveDialog>
  )
}

function AssignmentGrid({
  roles,
  rows,
  isDress,
}: {
  roles: { id: number; name: string; code: string }[]
  rows: MatrixRow[]
  isDress: boolean
}) {
  const isPhone = useIsPhone()
  const roleIndexById = useMemo(() => {
    const map = new Map<number, number>()
    roles.forEach((role, index) => map.set(role.id, index))
    return map
  }, [roles])

  return (
    <section className="pb-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase text-rs-muted">
          Running order & assignments
        </h2>
      </div>
      <div className="flex flex-wrap gap-3 pb-2 text-xs text-rs-muted">
        <span>⚠ conflict</span>
        <span>◦ role not on membership</span>
        <span>(backup) covering a slot</span>
      </div>
      {isDress && (
        <p className="pb-2 text-sm text-rs-muted">
          The dress rehearsal has no running order of its own — it runs the
          setlist as it stands today (ADR 0003).
        </p>
      )}
      {isPhone ? (
        <AssignmentCards
          rows={rows}
          roleIndexById={roleIndexById}
          isDress={isDress}
        />
      ) : (
        <AssignmentTable
          roles={roles}
          rows={rows}
          roleIndexById={roleIndexById}
          isDress={isDress}
        />
      )}
    </section>
  )
}

function AssignmentPill({
  entry,
  hue,
}: {
  entry: MatrixRow['cells'][number]['entries'][number]
  hue: string
}) {
  return (
    <span
      style={{ backgroundColor: hue }}
      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium text-white"
    >
      {entry.person_name}
      {entry.kind === 'backup' && ' (backup)'}
      {entry.has_conflict && (
        <span title="Unavailable for part of this">⚠</span>
      )}
      {entry.is_role_mismatch && (
        <span title="Role not on their membership (ADR 0002)">◦</span>
      )}
    </span>
  )
}

function AssignmentTable({
  roles,
  rows,
  roleIndexById,
  isDress,
}: {
  roles: { id: number; name: string; code: string }[]
  rows: MatrixRow[]
  roleIndexById: Map<number, number>
  isDress: boolean
}) {
  return (
    <table className="w-full text-left text-sm">
      <thead>
        <tr>
          <th className="pb-2">{isDress ? '#' : 'Start'}</th>
          <th className="pb-2">Song</th>
          {roles.map((role) => (
            <th key={role.id} className="pb-2">
              {role.name}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          <tr key={row.song_id}>
            <td className="py-2 align-top">
              {isDress
                ? index + 1
                : row.start_time !== null
                  ? formatClockTime(row.start_time)
                  : ''}
            </td>
            <td className="py-2 align-top">{row.song_title}</td>
            {row.cells.map((cell) => (
              <td key={cell.role_id} className="py-2 align-top">
                <div className="flex flex-wrap gap-1">
                  {cell.entries.length === 0 ? (
                    <span className="text-xs text-rs-muted">unfilled</span>
                  ) : (
                    cell.entries.map((entry) => (
                      <AssignmentPill
                        key={`${entry.kind}-${entry.id}`}
                        entry={entry}
                        hue={roleHueVar(roleIndexById.get(cell.role_id) ?? 0)}
                      />
                    ))
                  )}
                </div>
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function AssignmentCards({
  rows,
  roleIndexById,
  isDress,
}: {
  rows: MatrixRow[]
  roleIndexById: Map<number, number>
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
          <ul className="mt-2 flex flex-col gap-1">
            {row.cells.map((cell) => (
              <li
                key={cell.role_id}
                className="flex flex-wrap items-center gap-1 text-sm"
              >
                {cell.entries.length === 0 ? (
                  <span className="text-xs text-rs-muted">unfilled</span>
                ) : (
                  cell.entries.map((entry) => (
                    <AssignmentPill
                      key={`${entry.kind}-${entry.id}`}
                      entry={entry}
                      hue={roleHueVar(roleIndexById.get(cell.role_id) ?? 0)}
                    />
                  ))
                )}
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

function AllRehearsals({
  rows,
  isAdmin,
  onOpen,
}: {
  rows: ScheduleListRow[]
  isAdmin: boolean
  onOpen: (id: number) => void
}) {
  const isPhone = useIsPhone()

  if (isPhone) {
    return (
      <ul className="flex flex-col gap-3">
        {rows.map((row) => (
          <li
            key={row.id}
            className={`rounded border border-rs-border p-3 ${row.is_past ? 'opacity-60' : ''}`}
          >
            <button
              type="button"
              onClick={() => onOpen(row.id)}
              className="w-full text-left"
            >
              <div className="flex items-center justify-between">
                <p className="font-medium">{row.date}</p>
                {row.is_dress && (
                  <span className="text-xs">Dress · required</span>
                )}
              </div>
              <p className="text-sm text-rs-muted">
                {formatClockTime(row.start_time)}–
                {formatClockTime(row.end_time)}
              </p>
              <div className="flex items-center justify-between pt-1 text-sm">
                <YourStateChip state={row.your_state} />
                <span>{row.song_count} songs</span>
              </div>
              {row.pending_count !== undefined && (
                <p className="text-xs text-rs-muted">
                  {row.pending_count} pending
                </p>
              )}
            </button>
          </li>
        ))}
      </ul>
    )
  }

  return (
    <table className="w-full text-left text-sm">
      <thead>
        <tr>
          <th className="pb-2">Date</th>
          <th className="pb-2">Time</th>
          <th className="pb-2">You</th>
          <th className="pb-2">Songs</th>
          {isAdmin && <th className="pb-2">Conflicts</th>}
          <th className="pb-2" />
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.id} className={row.is_past ? 'opacity-60' : ''}>
            <td className="py-2">
              {row.date}
              {row.is_dress && (
                <span className="ml-2 text-xs">Dress · required</span>
              )}
            </td>
            <td className="py-2">
              {formatClockTime(row.start_time)}–{formatClockTime(row.end_time)}
            </td>
            <td className="py-2">
              <YourStateChip state={row.your_state} />
            </td>
            <td className="py-2">{row.song_count}</td>
            {isAdmin && (
              <td className="py-2">
                {row.pending_count !== undefined
                  ? `${row.pending_count} pending`
                  : ''}
              </td>
            )}
            <td className="py-2">
              <button
                type="button"
                onClick={() => onOpen(row.id)}
                className="text-rs-accent"
              >
                Open
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
