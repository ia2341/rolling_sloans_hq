import { useCallback, useEffect, useMemo, useState } from 'react'

import { apiFetch } from '../../api/client'
import type {
  AssignmentEditBufferInput,
  AssignmentEditFalloutPayload,
  AssignmentPickerOption,
  AssignmentPickerPayload,
} from '../../api/assignmentEditorTypes'
import type { PreviewResult } from '../../api/previewTypes'
import type { MatrixCell, MatrixEntry, MatrixRow, RehearsalDetail, SchedulePayload } from '../../api/scheduleTypes'
import type { ReadEnvelope, WriteEnvelope } from '../../api/types'
import { useIsPhone } from '../../hooks/useIsPhone'
import { useRegisterEditSession } from '../../shell/EditSessionContext'
import { ResponsiveDialog } from '../ui/ResponsiveDialog'
import { roleHueVar } from '../ui/RoleLegend'
import { SaveChangesDialog } from '../ui/SaveChangesDialog'

/** A standing Assignment or Backup pick that hasn't round-tripped to the server yet (issue #338). */
interface PendingEntry {
  key: string
  songId: number
  roleId: number
  personId: number
  personName: string
  coveringForId: number | null
  coveringForName: string | null
}

/** One grid cell's rendered occupant, merging a server `MatrixEntry` and any not-yet-saved pick into one shape. */
interface DisplayEntry {
  key: string
  kind: 'assignment' | 'backup'
  id: number | null
  personName: string
  isRoleMismatch: boolean
  hasConflict: boolean
  coveringForName?: string | null
  pending: boolean
}

/** Roles the columns are drawn from: the server's matrix columns plus any client-only "+ Add role" picks (issue #338). */
interface DisplayRole {
  id: number
  name: string
}

/** Abbreviates a Role's name to a 3-letter code for the "unfilled" placeholder. */
function roleCode(name: string): string {
  return name.slice(0, 3).toUpperCase()
}

/** Builds the stable key a pending pick is tracked under, so a re-pick of the same cell overwrites rather than duplicates it. */
function entryKey(songId: number, roleId: number, personId: number): string {
  return `${songId}:${roleId}:${personId}`
}

/** Adapts a server `MatrixEntry` (an already-saved Assignment or Backup) into the grid's rendered `DisplayEntry` shape. */
function fromServerEntry(entry: MatrixEntry): DisplayEntry {
  return {
    key: `${entry.kind}-${entry.id}`,
    kind: entry.kind,
    id: entry.id,
    personName: entry.person_name,
    isRoleMismatch: entry.is_role_mismatch,
    hasConflict: entry.has_conflict,
    coveringForName: entry.covering_for_name,
    pending: false,
  }
}

/** Adapts a not-yet-saved `PendingEntry` pick into the grid's rendered `DisplayEntry` shape, marked `pending: true`. */
function fromPendingEntry(kind: 'assignment' | 'backup', pending: PendingEntry): DisplayEntry {
  return {
    key: `pending-${pending.key}`,
    kind,
    id: null,
    personName: pending.personName,
    isRoleMismatch: false,
    hasConflict: false,
    coveringForName: pending.coveringForName,
    pending: true,
  }
}

/** Finds the one `MatrixCell` in `row` for `roleId`, or `undefined` for a client-only "+ Add role" column the server never returned. */
function cellFor(row: MatrixRow, roleId: number): MatrixCell | undefined {
  return row.cells.find((cell) => cell.role_id === roleId)
}

interface AssignmentEditorProps {
  rehearsalId: number
}

/**
 * The Assignments surface (issue #338, ADR 0009): the per-Rehearsal
 * standing-assignment grid and its "+" picker, reached from either the
 * Schedule surface's "Edit assignments" action or the rehearsal editor's
 * mode switch. Fetches its own `GET /api/schedule/?rehearsal=<id>` — the
 * same read the member-facing grid uses (issue #331) — rather than a
 * second endpoint, per #307's "one endpoint per surface" rule; the picker
 * is the one extra fetch, and only when a cell's "+" is opened.
 */
export function AssignmentEditor({ rehearsalId }: AssignmentEditorProps) {
  const isPhone = useIsPhone()
  const [detail, setDetail] = useState<RehearsalDetail | null>(null)
  const [semester, setSemester] = useState<{ id: number; updatedAt: string } | null>(null)
  const [removedAssignmentIds, setRemovedAssignmentIds] = useState<Set<number>>(new Set())
  const [addedEntries, setAddedEntries] = useState<Map<string, PendingEntry>>(new Map())
  const [removedBackupIds, setRemovedBackupIds] = useState<Set<number>>(new Set())
  const [addedBackupEntries, setAddedBackupEntries] = useState<Map<string, PendingEntry & { rehearsalSongId: number }>>(
    new Map(),
  )
  const [extraRoles, setExtraRoles] = useState<DisplayRole[]>([])
  const [addRoleOpen, setAddRoleOpen] = useState(false)
  const [pickerCell, setPickerCell] = useState<{ songId: number; songTitle: string; roleId: number; roleName: string } | null>(
    null,
  )
  const [saveOpen, setSaveOpen] = useState(false)

  /** Clears every unsaved pick/removal, restoring the grid to what the server last returned. */
  const resetPendingBuffer = useCallback(() => {
    setRemovedAssignmentIds(new Set())
    setAddedEntries(new Map())
    setRemovedBackupIds(new Set())
    setAddedBackupEntries(new Map())
    setExtraRoles([])
  }, [])

  /** (Re-)fetches this Rehearsal's matrix from the shared Schedule endpoint and resets the pending buffer to match. */
  const load = useCallback(() => {
    void apiFetch<ReadEnvelope<SchedulePayload>>(`/api/schedule/?rehearsal=${rehearsalId}`).then((envelope) => {
      setDetail(envelope.data.selected)
      const viewingSemester = envelope.context.viewing_semester
      setSemester(viewingSemester !== null ? { id: viewingSemester.id, updatedAt: viewingSemester.updated_at } : null)
      resetPendingBuffer()
    })
  }, [rehearsalId, resetPendingBuffer])

  useEffect(() => {
    load()
  }, [load])

  const roles: DisplayRole[] = useMemo(
    () => [...(detail?.roles ?? []), ...extraRoles],
    [detail, extraRoles],
  )

  const addableRoles = useMemo(
    () => (detail?.addable_roles ?? []).filter((role) => !extraRoles.some((extra) => extra.id === role.id)),
    [detail, extraRoles],
  )

  const changeCount =
    removedAssignmentIds.size + addedEntries.size + removedBackupIds.size + addedBackupEntries.size

  /** Serializes the pending buffer's state into the `AssignmentEditBufferInput` wire shape `preview`/`save` post, or `null` with no viewed Semester. */
  const buildBufferInput = useCallback((): AssignmentEditBufferInput | null => {
    if (semester === null) return null
    return {
      semester_id: semester.id,
      semester_updated_at: semester.updatedAt,
      removed_assignment_ids: [...removedAssignmentIds],
      added_entries: [...addedEntries.values()].map((entry) => ({
        song_id: entry.songId,
        role_id: entry.roleId,
        person_id: entry.personId,
      })),
      removed_backup_ids: [...removedBackupIds],
      added_backup_entries: [...addedBackupEntries.values()].map((entry) => ({
        rehearsal_song_id: entry.rehearsalSongId,
        role_id: entry.roleId,
        person_id: entry.personId,
        covering_for_id: entry.coveringForId,
      })),
      backup_covering_for_updates: [],
    }
  }, [semester, removedAssignmentIds, addedEntries, removedBackupIds, addedBackupEntries])

  /** Posts the pending buffer to `.../assignments/preview/` and adapts its response into `SaveChangesDialog`'s `PreviewResult` shape. */
  const preview = useCallback(async (): Promise<PreviewResult> => {
    const body = buildBufferInput()
    if (body === null) {
      return { ok: false, changes: [], fallout: { loud: [], quiet: [] }, nonFieldErrors: ['No Semester is being viewed.'] }
    }
    const envelope = await apiFetch<WriteEnvelope<null, unknown, AssignmentEditFalloutPayload>>(
      `/api/schedule/${rehearsalId}/assignments/preview/`,
      { method: 'POST', body: JSON.stringify(body) },
    )
    if (!envelope.ok || envelope.fallout === null) {
      return { ok: false, changes: [], fallout: { loud: [], quiet: [] }, nonFieldErrors: envelope.non_field_errors }
    }
    if (envelope.fallout.is_blocked) {
      return { ok: false, changes: [], fallout: { loud: [], quiet: [] }, nonFieldErrors: [envelope.fallout.block_message] }
    }
    return { ok: true, changes: [], fallout: { loud: envelope.fallout.loud, quiet: envelope.fallout.quiet } }
  }, [buildBufferInput, rehearsalId])

  /** Posts the pending buffer to `.../assignments/save/` and, on success, closes the save dialog and reloads from the server. */
  const confirmSave = useCallback(() => {
    const body = buildBufferInput()
    if (body === null) return
    void apiFetch<WriteEnvelope>(`/api/schedule/${rehearsalId}/assignments/save/`, {
      method: 'POST',
      body: JSON.stringify(body),
    }).then((envelope) => {
      if (envelope.ok) {
        setSaveOpen(false)
        load()
      }
    })
  }, [buildBufferInput, rehearsalId, load])

  useRegisterEditSession({
    what: 'this Rehearsal’s standing assignments',
    changeCount,
    blockedReason: null,
    discard: load,
    requestSave: () => setSaveOpen(true),
  })

  /** Returns the `DisplayEntry` list for one grid cell: the server's saved entries (minus pending removals) plus any pending picks. */
  const displayEntriesFor = useCallback(
    (songId: number, roleId: number, cell: MatrixCell | undefined): DisplayEntry[] => {
      const entries: DisplayEntry[] = []
      for (const entry of cell?.entries ?? []) {
        if (entry.kind === 'assignment' && removedAssignmentIds.has(entry.id)) continue
        if (entry.kind === 'backup' && removedBackupIds.has(entry.id)) continue
        entries.push(fromServerEntry(entry))
      }
      for (const pending of addedEntries.values()) {
        if (pending.songId === songId && pending.roleId === roleId) {
          entries.push(fromPendingEntry('assignment', pending))
        }
      }
      for (const pending of addedBackupEntries.values()) {
        if (pending.songId === songId && pending.roleId === roleId) {
          entries.push(fromPendingEntry('backup', pending))
        }
      }
      return entries
    },
    [removedAssignmentIds, removedBackupIds, addedEntries, addedBackupEntries],
  )

  /** Removes one entry: drops it from the pending-add map if it was never saved, otherwise queues its id for removal on save. */
  const removeEntry = useCallback(
    (entry: DisplayEntry) => {
      if (entry.pending) {
        const pendingKey = entry.key.replace(/^pending-/, '')
        if (entry.kind === 'assignment') {
          setAddedEntries((previous) => {
            const next = new Map(previous)
            next.delete(pendingKey)
            return next
          })
        } else {
          setAddedBackupEntries((previous) => {
            const next = new Map(previous)
            next.delete(pendingKey)
            return next
          })
        }
        return
      }
      if (entry.id === null) return
      if (entry.kind === 'assignment') {
        setRemovedAssignmentIds((previous) => new Set(previous).add(entry.id as number))
      } else {
        setRemovedBackupIds((previous) => new Set(previous).add(entry.id as number))
      }
    },
    [],
  )

  /** Lists a cell's current standing assignees (server-saved minus pending removals, plus pending adds) for the picker's "Covering for" menu. */
  const standingAssigneesFor = useCallback(
    (songId: number, roleId: number): { id: number; name: string }[] => {
      const row = detail?.rows.find((candidate) => candidate.song_id === songId)
      const cell = row ? cellFor(row, roleId) : undefined
      const fromServer = (cell?.entries ?? [])
        .filter((entry) => entry.kind === 'assignment' && !removedAssignmentIds.has(entry.id))
        .map((entry) => ({ id: entry.person_id, name: entry.person_name }))
      const fromPending = [...addedEntries.values()]
        .filter((entry) => entry.songId === songId && entry.roleId === roleId)
        .map((entry) => ({ id: entry.personId, name: entry.personName }))
      return [...fromServer, ...fromPending]
    },
    [detail, removedAssignmentIds, addedEntries],
  )

  /** Records a picker choice as a pending standing Assignment on the open cell, then closes the picker. */
  const pickAssigned = useCallback(
    (option: AssignmentPickerOption) => {
      if (pickerCell === null) return
      const key = entryKey(pickerCell.songId, pickerCell.roleId, option.person_id)
      setAddedEntries((previous) => {
        const next = new Map(previous)
        next.set(key, {
          key,
          songId: pickerCell.songId,
          roleId: pickerCell.roleId,
          personId: option.person_id,
          personName: option.person_name,
          coveringForId: null,
          coveringForName: null,
        })
        return next
      })
      setPickerCell(null)
    },
    [pickerCell],
  )

  /** Records a picker choice as a pending, this-evening-only Backup on the open cell, then closes the picker. */
  const pickBackup = useCallback(
    (option: AssignmentPickerOption, rehearsalSongId: number, coveringFor: { id: number; name: string } | null) => {
      if (pickerCell === null) return
      const key = entryKey(pickerCell.songId, pickerCell.roleId, option.person_id)
      setAddedBackupEntries((previous) => {
        const next = new Map(previous)
        next.set(key, {
          key,
          songId: pickerCell.songId,
          roleId: pickerCell.roleId,
          personId: option.person_id,
          personName: option.person_name,
          rehearsalSongId,
          coveringForId: coveringFor?.id ?? null,
          coveringForName: coveringFor?.name ?? null,
        })
        return next
      })
      setPickerCell(null)
    },
    [pickerCell],
  )

  if (detail === null) return null

  return (
    <div className="flex flex-col gap-3">
      <div
        role="note"
        className="rounded border-2 border-rs-accent bg-rs-accent/10 p-3 text-sm"
      >
        <p className="font-semibold">Editing standing assignments.</p>
        <p>
          A change here applies to <strong>every rehearsal and the concert</strong>, not just this
          evening (ADR 0009). To cover one evening only, add a <strong>Backup</strong> from the same
          picker.
        </p>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <ul className="flex flex-wrap gap-3 text-sm">
          {roles.map((role, index) => (
            <li key={role.id} className="flex items-center gap-1.5">
              <span
                aria-hidden="true"
                className="inline-block h-3 w-3 rounded-full"
                style={{ backgroundColor: roleHueVar(index) }}
              />
              {role.name}
            </li>
          ))}
        </ul>
        <p className="text-sm text-rs-muted">
          Order is fixed here — switch to <strong>Running order</strong> above to change it.
        </p>
      </div>

      <div className="flex flex-wrap gap-3 text-xs text-rs-muted">
        <span>backup — covers one evening only</span>
        <span>away — a declared Conflict</span>
        <span>◦ role not on membership</span>
      </div>

      {addableRoles.length > 0 && (
        <button
          type="button"
          onClick={() => setAddRoleOpen(true)}
          className="self-start rounded border border-rs-border px-2 py-1 text-xs font-medium"
        >
          + Add role
        </button>
      )}

      {isPhone ? (
        <AssignmentEditorCards
          roles={roles}
          rows={detail.rows}
          displayEntriesFor={displayEntriesFor}
          onRemove={removeEntry}
          onOpenPicker={(songId, songTitle, roleId, roleName) => setPickerCell({ songId, songTitle, roleId, roleName })}
        />
      ) : (
        <AssignmentEditorTable
          roles={roles}
          rows={detail.rows}
          displayEntriesFor={displayEntriesFor}
          onRemove={removeEntry}
          onOpenPicker={(songId, songTitle, roleId, roleName) => setPickerCell({ songId, songTitle, roleId, roleName })}
        />
      )}

      <ResponsiveDialog
        open={addRoleOpen}
        onOpenChange={setAddRoleOpen}
        title="Add a Role column"
      >
        <p className="pb-2 text-sm text-rs-muted">
          Adding a column here writes no Role Requirement (ADR 0009) — it only opens this session's
          grid up to casting a Role nobody wrote a target for.
        </p>
        <ul className="flex flex-col gap-1">
          {addableRoles.map((role) => (
            <li key={role.id}>
              <button
                type="button"
                onClick={() => {
                  setExtraRoles((previous) => [...previous, role])
                  setAddRoleOpen(false)
                }}
                className="w-full rounded px-2 py-1 text-left text-sm hover:bg-rs-border/40"
              >
                {role.name}
              </button>
            </li>
          ))}
        </ul>
      </ResponsiveDialog>

      {pickerCell !== null && (
        <AssignmentPickerDialog
          rehearsalId={rehearsalId}
          cell={pickerCell}
          onOpenChange={(open) => {
            if (!open) setPickerCell(null)
          }}
          standingAssignees={standingAssigneesFor(pickerCell.songId, pickerCell.roleId)}
          onPickAssigned={pickAssigned}
          onPickBackup={pickBackup}
        />
      )}

      <SaveChangesDialog
        open={saveOpen}
        onOpenChange={setSaveOpen}
        title={`Save ${changeCount} change${changeCount === 1 ? '' : 's'} to this Rehearsal's assignments?`}
        preview={preview}
        onConfirm={confirmSave}
      />
    </div>
  )
}

/** One grid-cell occupant's pill: name, badges (backup/away/role-mismatch), and a remove control. */
function AssignmentEditorPill({
  entry,
  hue,
  onRemove,
}: {
  entry: DisplayEntry
  hue: string
  onRemove: () => void
}) {
  return (
    <span
      style={{ backgroundColor: hue }}
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium text-white ${
        entry.pending ? 'ring-2 ring-white/70' : ''
      }`}
    >
      {entry.personName}
      {entry.kind === 'backup' && <span className="rounded bg-black/20 px-1">backup</span>}
      {entry.hasConflict && <span className="rounded bg-black/20 px-1">away</span>}
      {entry.isRoleMismatch && <span title="Role not on their membership (ADR 0002)">◦</span>}
      <button
        type="button"
        aria-label={`Remove ${entry.personName}`}
        onClick={onRemove}
        className="ml-0.5 rounded-full px-1 hover:bg-black/20"
      >
        ✕
      </button>
    </span>
  )
}

/** One (Song, Role) grid cell: its occupant pills, an "unfilled" placeholder when empty, and the "+" picker trigger. */
function AssignmentEditorCell({
  songId,
  songTitle,
  role,
  roleIndex,
  cell,
  displayEntriesFor,
  onRemove,
  onOpenPicker,
}: {
  songId: number
  songTitle: string
  role: DisplayRole
  roleIndex: number
  cell: MatrixCell | undefined
  displayEntriesFor: (songId: number, roleId: number, cell: MatrixCell | undefined) => DisplayEntry[]
  onRemove: (entry: DisplayEntry) => void
  onOpenPicker: (songId: number, songTitle: string, roleId: number, roleName: string) => void
}) {
  const entries = displayEntriesFor(songId, role.id, cell)
  const hue = roleHueVar(roleIndex)
  return (
    <div className="flex flex-wrap items-center gap-1">
      {entries.length === 0 ? (
        <span className="text-xs text-rs-muted">{roleCode(role.name)} · unfilled</span>
      ) : (
        entries.map((entry) => (
          <AssignmentEditorPill key={entry.key} entry={entry} hue={hue} onRemove={() => onRemove(entry)} />
        ))
      )}
      <button
        type="button"
        aria-label={`Assign ${role.name} on ${songTitle}`}
        onClick={() => onOpenPicker(songId, songTitle, role.id, role.name)}
        className="rounded-full border border-rs-border px-1.5 text-xs leading-5"
      >
        +
      </button>
    </div>
  )
}

/** Trims a wire `HH:MM:SS` time string down to `HH:MM` for display. */
function formatClockTime(isoTime: string): string {
  return isoTime.slice(0, 5)
}

/** Desktop rendering of the assignment grid: one row per Song, one column per Role. */
function AssignmentEditorTable({
  roles,
  rows,
  displayEntriesFor,
  onRemove,
  onOpenPicker,
}: {
  roles: DisplayRole[]
  rows: MatrixRow[]
  displayEntriesFor: (songId: number, roleId: number, cell: MatrixCell | undefined) => DisplayEntry[]
  onRemove: (entry: DisplayEntry) => void
  onOpenPicker: (songId: number, songTitle: string, roleId: number, roleName: string) => void
}) {
  return (
    <table className="w-full text-left text-sm">
      <thead>
        <tr>
          <th className="pb-2">Start</th>
          <th className="pb-2">Song</th>
          {roles.map((role) => (
            <th key={role.id} className="pb-2">
              {role.name}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.song_id}>
            <td className="py-2 align-top">{row.start_time !== null ? formatClockTime(row.start_time) : ''}</td>
            <td className="py-2 align-top">{row.song_title}</td>
            {roles.map((role, index) => (
              <td key={role.id} className="py-2 align-top">
                <AssignmentEditorCell
                  songId={row.song_id}
                  songTitle={row.song_title}
                  role={role}
                  roleIndex={index}
                  cell={cellFor(row, role.id)}
                  displayEntriesFor={displayEntriesFor}
                  onRemove={onRemove}
                  onOpenPicker={onOpenPicker}
                />
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** Phone rendering of the assignment grid (`useIsPhone`): one card per Song, stacking each Role's cell inside it. */
function AssignmentEditorCards({
  roles,
  rows,
  displayEntriesFor,
  onRemove,
  onOpenPicker,
}: {
  roles: DisplayRole[]
  rows: MatrixRow[]
  displayEntriesFor: (songId: number, roleId: number, cell: MatrixCell | undefined) => DisplayEntry[]
  onRemove: (entry: DisplayEntry) => void
  onOpenPicker: (songId: number, songTitle: string, roleId: number, roleName: string) => void
}) {
  return (
    <ul className="flex flex-col gap-3">
      {rows.map((row) => (
        <li key={row.song_id} className="rounded border border-rs-border p-3">
          <p className="font-medium">
            {row.start_time !== null ? `${formatClockTime(row.start_time)} · ` : ''}
            {row.song_title}
          </p>
          <ul className="mt-2 flex flex-col gap-2">
            {roles.map((role, index) => (
              <li key={role.id} className="flex flex-col gap-1">
                <span className="text-xs font-semibold uppercase text-rs-muted">{role.name}</span>
                <AssignmentEditorCell
                  songId={row.song_id}
                  songTitle={row.song_title}
                  role={role}
                  roleIndex={index}
                  cell={cellFor(row, role.id)}
                  displayEntriesFor={displayEntriesFor}
                  onRemove={onRemove}
                  onOpenPicker={onOpenPicker}
                />
              </li>
            ))}
          </ul>
        </li>
      ))}
    </ul>
  )
}

/** One picker-list row: a Person's name plus a bare "Conflict" marker (ADR 0005), clickable to make that pick. */
function PickerOptionRow({
  option,
  onPick,
}: {
  option: AssignmentPickerOption
  onPick: () => void
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onPick}
        className="flex w-full items-center justify-between rounded px-2 py-1 text-left text-sm hover:bg-rs-border/40"
      >
        <span>{option.person_name}</span>
        {option.has_conflict && <span className="text-xs text-rs-muted">Conflict</span>}
      </button>
    </li>
  )
}

/**
 * The "+" cell's picker dialog (issue #338, story 15): fetches
 * `.../assignments/picker/<song_id>/<role_id>/` for this one cell and
 * offers Assigned (declared-first) and Backup (this-evening-only)
 * sections, each with a "Show all members" expansion.
 */
function AssignmentPickerDialog({
  rehearsalId,
  cell,
  onOpenChange,
  standingAssignees,
  onPickAssigned,
  onPickBackup,
}: {
  rehearsalId: number
  cell: { songId: number; songTitle: string; roleId: number; roleName: string }
  onOpenChange: (open: boolean) => void
  standingAssignees: { id: number; name: string }[]
  onPickAssigned: (option: AssignmentPickerOption) => void
  onPickBackup: (
    option: AssignmentPickerOption,
    rehearsalSongId: number,
    coveringFor: { id: number; name: string } | null,
  ) => void
}) {
  const [payload, setPayload] = useState<AssignmentPickerPayload | null>(null)
  const [showAllAssigned, setShowAllAssigned] = useState(false)
  const [showAllBackup, setShowAllBackup] = useState(false)
  const [coveringForId, setCoveringForId] = useState<number | ''>('')

  useEffect(() => {
    void apiFetch<ReadEnvelope<AssignmentPickerPayload>>(
      `/api/schedule/${rehearsalId}/assignments/picker/${cell.songId}/${cell.roleId}/`,
    ).then((envelope) => setPayload(envelope.data))
  }, [rehearsalId, cell.songId, cell.roleId])

  const coveringFor = useMemo(
    () => standingAssignees.find((assignee) => assignee.id === coveringForId) ?? null,
    [standingAssignees, coveringForId],
  )

  return (
    <ResponsiveDialog
      open
      onOpenChange={onOpenChange}
      title={`${cell.roleName} on ${cell.songTitle}`}
      wide
    >
      {payload === null ? (
        <p className="text-sm text-rs-muted">Loading…</p>
      ) : (
        <div className="flex flex-col gap-4">
          <section>
            <h3 className="text-sm font-semibold">Assigned</h3>
            <p className="pb-1 text-xs text-rs-muted">Every rehearsal + concert</p>
            <ul className="flex flex-col">
              {payload.declared.map((option) => (
                <PickerOptionRow key={option.person_id} option={option} onPick={() => onPickAssigned(option)} />
              ))}
            </ul>
            {payload.others.length > 0 && (
              <>
                <button
                  type="button"
                  onClick={() => setShowAllAssigned((previous) => !previous)}
                  className="pt-1 text-xs text-rs-accent"
                >
                  {showAllAssigned ? 'Hide' : 'Show all members'}
                </button>
                {showAllAssigned && (
                  <ul className="flex flex-col">
                    {payload.others.map((option) => (
                      <li key={option.person_id}>
                        <button
                          type="button"
                          onClick={() => onPickAssigned(option)}
                          className="flex w-full items-center justify-between rounded px-2 py-1 text-left text-sm hover:bg-rs-border/40"
                        >
                          <span>{option.person_name}</span>
                          <span className="text-xs text-rs-muted">
                            Has not declared {cell.roleName}
                            {option.has_conflict ? ' · Conflict' : ''}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </section>

          <section>
            <h3 className="text-sm font-semibold">Backup</h3>
            <p className="pb-1 text-xs text-rs-muted">
              This rehearsal only — the standing assignment above is unaffected
            </p>
            {payload.rehearsal_song_id === null ? (
              <p className="text-sm text-rs-muted">
                A Dress Rehearsal has no per-song slots to assign against, so a Backup isn't possible
                here (ADR 0006).
              </p>
            ) : (
              <>
                {standingAssignees.length > 0 && (
                  <label className="mb-1 flex items-center gap-2 text-xs text-rs-muted">
                    Covering for
                    <select
                      value={coveringForId}
                      onChange={(event) =>
                        setCoveringForId(event.target.value === '' ? '' : Number(event.target.value))
                      }
                      className="rounded border border-rs-border px-1 py-0.5 text-xs"
                    >
                      <option value="">No one in particular</option>
                      {standingAssignees.map((assignee) => (
                        <option key={assignee.id} value={assignee.id}>
                          {assignee.name}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                <ul className="flex flex-col">
                  {payload.backup_declared.map((option) => (
                    <PickerOptionRow
                      key={option.person_id}
                      option={option}
                      onPick={() => onPickBackup(option, payload.rehearsal_song_id as number, coveringFor)}
                    />
                  ))}
                </ul>
                {payload.backup_others.length > 0 && (
                  <>
                    <button
                      type="button"
                      onClick={() => setShowAllBackup((previous) => !previous)}
                      className="pt-1 text-xs text-rs-accent"
                    >
                      {showAllBackup ? 'Hide' : 'Show all members'}
                    </button>
                    {showAllBackup && (
                      <ul className="flex flex-col">
                        {payload.backup_others.map((option) => (
                          <li key={option.person_id}>
                            <button
                              type="button"
                              onClick={() => onPickBackup(option, payload.rehearsal_song_id as number, coveringFor)}
                              className="flex w-full items-center justify-between rounded px-2 py-1 text-left text-sm hover:bg-rs-border/40"
                            >
                              <span>{option.person_name}</span>
                              <span className="text-xs text-rs-muted">
                                Has not declared {cell.roleName}
                                {option.has_conflict ? ' · Conflict' : ''}
                              </span>
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </>
                )}
              </>
            )}
          </section>

          <p className="text-xs text-rs-muted">Who a Backup is covering for is shown to admins only.</p>
        </div>
      )}
    </ResponsiveDialog>
  )
}
