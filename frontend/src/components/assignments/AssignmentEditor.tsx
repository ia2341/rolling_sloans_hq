import { useCallback, useEffect, useMemo, useState } from 'react'

import { apiFetch } from '../../api/client'
import type {
  AssignmentEditBufferInput,
  AssignmentEditFalloutPayload,
  AssignmentPickerOption,
  AssignmentPickerPayload,
  RunningOrderReorderInput,
} from '../../api/assignmentEditorTypes'
import type { PreviewResult } from '../../api/previewTypes'
import type { RehearsalEditFalloutPayload } from '../../api/scheduleEditorTypes'
import type {
  MatrixCell,
  MatrixEntry,
  MatrixRow,
  RehearsalDetail,
  SchedulePayload,
} from '../../api/scheduleTypes'
import type { ReadEnvelope, WriteEnvelope } from '../../api/types'
import { useIsPhone } from '../../hooks/useIsPhone'
import { shortenNames } from '../../lib/names'
import { useRegisterEditSession } from '../../shell/EditSessionContext'
import { ResponsiveDialog } from '../ui/ResponsiveDialog'
import { SaveChangesDialog } from '../ui/SaveChangesDialog'

/** A standing Assignment or Backup pick that hasn't round-tripped to the server yet (issue #338). */
interface PendingEntry {
  key: string
  songId: number
  roleId: number
  personId: number
  personName: string
  /** Whether this pick's Person had *not* declared the cell's Role (ADR 0002) — predicts the `is_role_mismatch` flag the server would compute on save, so a not-yet-saved pick can carry the same warning badge a saved one does. */
  isRoleMismatch: boolean
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

/** Adapts a not-yet-saved `PendingEntry` pick into the grid's rendered `DisplayEntry` shape, marked `pending: true`.
 *
 * `isRoleMismatch` carries the pick's own predicted flag (ADR 0002) — a
 * pending pill for someone who hasn't declared the Role shows the same
 * "◦ role not declared" marker a saved mismatch does, rather than only
 * appearing after a round trip.
 */
function fromPendingEntry(
  kind: 'assignment' | 'backup',
  pending: PendingEntry,
): DisplayEntry {
  return {
    key: `pending-${pending.key}`,
    kind,
    id: null,
    personName: pending.personName,
    isRoleMismatch: pending.isRoleMismatch,
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
  /** Called after a Discard or a successful Save — returns the Schedule surface to its read-only grid, since Discard and "done editing" are the same action (issue: UI overhaul round 2, item 2). */
  onDone: () => void
}

/**
 * The "Edit Rehearsal" surface (issue #338, ADR 0009; consolidated with
 * Running Order reordering): the per-Rehearsal standing-assignment grid,
 * its "+" picker, and the Running Order drag-and-drop, all reached from
 * the Schedule surface's "Edit Rehearsal" action. A cell edit here is a
 * standing Assignment (semester-wide, ADR 0009) unless made through the
 * Backup picker section (this evening only, ADR 0007); a Running Order
 * reorder is scoped to this one Rehearsal. Both buffer locally and only
 * reach the server when "Save changes" is confirmed (ADR 0008's Buffer →
 * preview → apply shape) — nothing here autosaves per click. Fetches its
 * own `GET /api/schedule/?rehearsal=<id>` — the same read the
 * member-facing grid uses (issue #331) — rather than a second endpoint,
 * per #307's "one endpoint per surface" rule; the picker is the one extra
 * fetch, and only when a cell's "+" is opened.
 */
export function AssignmentEditor({
  rehearsalId,
  onDone,
}: AssignmentEditorProps) {
  const isPhone = useIsPhone()
  const [detail, setDetail] = useState<RehearsalDetail | null>(null)
  const [semester, setSemester] = useState<{
    id: number
    updatedAt: string
  } | null>(null)
  const [removedAssignmentIds, setRemovedAssignmentIds] = useState<Set<number>>(
    new Set(),
  )
  const [addedEntries, setAddedEntries] = useState<Map<string, PendingEntry>>(
    new Map(),
  )
  const [removedBackupIds, setRemovedBackupIds] = useState<Set<number>>(
    new Set(),
  )
  const [addedBackupEntries, setAddedBackupEntries] = useState<
    Map<string, PendingEntry & { rehearsalSongId: number }>
  >(new Map())
  const [extraRoles, setExtraRoles] = useState<DisplayRole[]>([])
  const [addRoleOpen, setAddRoleOpen] = useState(false)
  const [pickerCell, setPickerCell] = useState<{
    songId: number
    songTitle: string
    roleId: number
    roleName: string
  } | null>(null)
  const [saveOpen, setSaveOpen] = useState(false)
  /** The Running Order's current order, as `RehearsalSong` ids — `null` on the Dress Rehearsal (ADR 0003), which has none to reorder. */
  const [runningOrder, setRunningOrder] = useState<number[] | null>(null)
  /** The order the server last returned, to diff `runningOrder` against for the dirty flag and to discard back to. */
  const [originalOrder, setOriginalOrder] = useState<number[] | null>(null)

  /** Clears every unsaved pick/removal, restoring the grid to what the server last returned. */
  const resetPendingBuffer = useCallback(() => {
    setRemovedAssignmentIds(new Set())
    setAddedEntries(new Map())
    setRemovedBackupIds(new Set())
    setAddedBackupEntries(new Map())
    setExtraRoles([])
  }, [])

  /** (Re-)fetches this Rehearsal's matrix from the shared Schedule endpoint and resets the pending buffer (assignments and Running Order both) to match. */
  const load = useCallback(() => {
    void apiFetch<ReadEnvelope<SchedulePayload>>(
      `/api/schedule/?rehearsal=${rehearsalId}`,
    ).then((envelope) => {
      const nextDetail = envelope.data.selected
      setDetail(nextDetail)
      const viewingSemester = envelope.context.viewing_semester
      setSemester(
        viewingSemester !== null
          ? { id: viewingSemester.id, updatedAt: viewingSemester.updated_at }
          : null,
      )
      const nextOrder =
        nextDetail !== null && !nextDetail.is_dress
          ? nextDetail.rows
              .map((row) => row.rehearsal_song_id)
              .filter((id): id is number => id !== null)
          : null
      setRunningOrder(nextOrder)
      setOriginalOrder(nextOrder)
      resetPendingBuffer()
    })
  }, [rehearsalId, resetPendingBuffer])

  useEffect(() => {
    load()
  }, [load])

  /**
   * The grid's rows in the current (possibly reordered) Running Order —
   * the Running Order editor and the assignment table are one table
   * (issue: UI overhaul round 2), so a drag on a row both reorders and
   * shows its assignments in the same place. `null` `runningOrder` (the
   * Dress Rehearsal, ADR 0003) falls back to the server's own row order,
   * which is unreorderable there anyway.
   */
  const displayRows = useMemo(() => {
    const rows = detail?.rows ?? []
    if (runningOrder === null) return rows
    const byRehearsalSongId = new Map(
      rows
        .filter((row) => row.rehearsal_song_id !== null)
        .map((row) => [row.rehearsal_song_id as number, row]),
    )
    return runningOrder
      .map((id) => byRehearsalSongId.get(id))
      .filter((row): row is MatrixRow => row !== undefined)
  }, [detail, runningOrder])

  /** Reorders `runningOrder` by the display-row indices `AssignmentEditorTable`/`AssignmentEditorCards` render at — a drag-and-drop or arrow move on a row. */
  const reorderDisplayRows = useCallback(
    (fromIndex: number, toIndex: number) => {
      setRunningOrder((previous) =>
        previous === null ? previous : moveItem(previous, fromIndex, toIndex),
      )
    },
    [],
  )

  /** True once `runningOrder` differs from what the server last returned — the Running Order half of `changeCount`. */
  const hasReorderChange =
    runningOrder !== null &&
    originalOrder !== null &&
    (runningOrder.length !== originalOrder.length ||
      runningOrder.some((id, index) => id !== originalOrder[index]))

  const roles: DisplayRole[] = useMemo(
    () => [...(detail?.roles ?? []), ...extraRoles],
    [detail, extraRoles],
  )

  const addableRoles = useMemo(
    () =>
      (detail?.addable_roles ?? []).filter(
        (role) => !extraRoles.some((extra) => extra.id === role.id),
      ),
    [detail, extraRoles],
  )

  /**
   * First-name-only display, disambiguated by last initial on collision
   * (issue: UI overhaul round 2, item 3) — scoped to every name currently
   * rendered anywhere in this grid (server-saved entries plus pending
   * picks), matching the same rule the unified Setlist/Schedule tables use
   * (`CastLine.tsx`). This surface is a grid of pills, not the Profile page
   * or the Band roster, so full names don't apply here.
   */
  const nameFor = useMemo(() => {
    const names: string[] = []
    for (const row of detail?.rows ?? []) {
      for (const cell of row.cells) {
        for (const entry of cell.entries) names.push(entry.person_name)
      }
    }
    for (const entry of addedEntries.values()) names.push(entry.personName)
    for (const entry of addedBackupEntries.values())
      names.push(entry.personName)
    return shortenNames(names)
  }, [detail, addedEntries, addedBackupEntries])

  const changeCount =
    removedAssignmentIds.size +
    addedEntries.size +
    removedBackupIds.size +
    addedBackupEntries.size +
    (hasReorderChange ? 1 : 0)

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
  }, [
    semester,
    removedAssignmentIds,
    addedEntries,
    removedBackupIds,
    addedBackupEntries,
  ])

  /** Serializes `runningOrder` into the `RunningOrderReorderInput` wire shape `.../running-order/{preview,save}/` post, or `null` with no viewed Semester or no reorder to submit. */
  const buildReorderInput = useCallback((): RunningOrderReorderInput | null => {
    if (semester === null || runningOrder === null) return null
    return {
      semester_id: semester.id,
      semester_updated_at: semester.updatedAt,
      ordered_rehearsal_song_ids: runningOrder,
    }
  }, [semester, runningOrder])

  /** Adapts `.../assignments/{preview,save}/`'s Fallout envelope into `SaveChangesDialog`'s `PreviewResult` shape. */
  const toAssignmentResult = useCallback(
    (
      envelope: WriteEnvelope<null, unknown, AssignmentEditFalloutPayload>,
    ): PreviewResult => {
      if (!envelope.ok || envelope.fallout === null) {
        return {
          ok: false,
          changes: [],
          fallout: { loud: [], quiet: [] },
          nonFieldErrors: envelope.non_field_errors,
        }
      }
      if (envelope.fallout.is_blocked) {
        return {
          ok: false,
          changes: [],
          fallout: { loud: [], quiet: [] },
          nonFieldErrors: [envelope.fallout.block_message],
        }
      }
      return {
        ok: true,
        changes: [],
        fallout: { loud: envelope.fallout.loud, quiet: envelope.fallout.quiet },
      }
    },
    [],
  )

  /** Adapts `.../running-order/{preview,save}/`'s Fallout envelope into `SaveChangesDialog`'s `PreviewResult` shape, including the doomed-Recordings block (mirrors `ScheduleEdit.tsx`'s `toPreviewResult()`). */
  const toReorderResult = useCallback(
    (
      envelope: WriteEnvelope<null, unknown, RehearsalEditFalloutPayload>,
    ): PreviewResult => {
      if (!envelope.ok || envelope.fallout === null) {
        return {
          ok: false,
          changes: [],
          fallout: { loud: [], quiet: [] },
          nonFieldErrors: envelope.non_field_errors,
        }
      }
      if (envelope.fallout.is_blocked) {
        return {
          ok: false,
          changes: [],
          fallout: { loud: [], quiet: [] },
          nonFieldErrors: [envelope.fallout.block_message],
        }
      }
      return {
        ok: true,
        changes: [],
        fallout: { loud: envelope.fallout.loud, quiet: envelope.fallout.quiet },
        doomed:
          envelope.fallout.doomed_recording_groups.length > 0
            ? {
                heading: 'This deletes Recordings with no undo and no export',
                items: envelope.fallout.doomed_recording_groups.map(
                  (group) =>
                    `${group.label} — ${group.recording_count} recording${group.recording_count === 1 ? '' : 's'} from ${group.uploader_count} member${group.uploader_count === 1 ? '' : 's'}`,
                ),
              }
            : undefined,
      }
    },
    [],
  )

  /** Posts both pending buffers (assignments always, Running Order only if reordered) and merges their Fallout into one `PreviewResult` (ADR 0008 — each Preview runs its surface's real save and rolls it back). */
  const preview = useCallback(async (): Promise<PreviewResult> => {
    const assignmentBody = buildBufferInput()
    if (assignmentBody === null) {
      return {
        ok: false,
        changes: [],
        fallout: { loud: [], quiet: [] },
        nonFieldErrors: ['No Semester is being viewed.'],
      }
    }
    const assignmentEnvelope = await apiFetch<
      WriteEnvelope<null, unknown, AssignmentEditFalloutPayload>
    >(`/api/schedule/${rehearsalId}/assignments/preview/`, {
      method: 'POST',
      body: JSON.stringify(assignmentBody),
    })
    const assignmentResult = toAssignmentResult(assignmentEnvelope)
    if (!assignmentResult.ok) return assignmentResult

    const reorderBody = hasReorderChange ? buildReorderInput() : null
    if (reorderBody === null) return assignmentResult

    const reorderEnvelope = await apiFetch<
      WriteEnvelope<null, unknown, RehearsalEditFalloutPayload>
    >(`/api/schedule/${rehearsalId}/running-order/preview/`, {
      method: 'POST',
      body: JSON.stringify(reorderBody),
    })
    const reorderResult = toReorderResult(reorderEnvelope)
    if (!reorderResult.ok) return reorderResult

    return {
      ok: true,
      changes: [...assignmentResult.changes, ...reorderResult.changes],
      fallout: {
        loud: [...assignmentResult.fallout.loud, ...reorderResult.fallout.loud],
        quiet: [
          ...assignmentResult.fallout.quiet,
          ...reorderResult.fallout.quiet,
        ],
      },
      doomed: reorderResult.doomed,
    }
  }, [
    buildBufferInput,
    rehearsalId,
    hasReorderChange,
    buildReorderInput,
    toAssignmentResult,
    toReorderResult,
  ])

  /** Saves both pending buffers in sequence (assignments always, Running Order only if reordered) and, on success, closes the popup and reloads. */
  const confirmSave = useCallback(() => {
    const assignmentBody = buildBufferInput()
    if (assignmentBody === null) return
    void apiFetch<WriteEnvelope>(
      `/api/schedule/${rehearsalId}/assignments/save/`,
      { method: 'POST', body: JSON.stringify(assignmentBody) },
    ).then((assignmentEnvelope) => {
      if (!assignmentEnvelope.ok) return
      const reorderBody = hasReorderChange ? buildReorderInput() : null
      if (reorderBody === null) {
        setSaveOpen(false)
        load()
        onDone()
        return
      }
      void apiFetch<WriteEnvelope>(
        `/api/schedule/${rehearsalId}/running-order/save/`,
        { method: 'POST', body: JSON.stringify(reorderBody) },
      ).then((reorderEnvelope) => {
        if (reorderEnvelope.ok) {
          setSaveOpen(false)
          load()
          onDone()
        }
      })
    })
  }, [
    buildBufferInput,
    rehearsalId,
    hasReorderChange,
    buildReorderInput,
    load,
    onDone,
  ])

  /** Discard means "leave edit mode" too — there is no separate "Done editing" affordance (issue: UI overhaul round 2, item 2). */
  const discard = useCallback(() => {
    load()
    onDone()
  }, [load, onDone])

  useRegisterEditSession({
    what: 'this Rehearsal’s assignments and Running Order',
    changeCount,
    blockedReason: null,
    discard,
    requestSave: () => setSaveOpen(true),
  })

  /** Returns the `DisplayEntry` list for one grid cell: the server's saved entries (minus pending removals) plus any pending picks. */
  const displayEntriesFor = useCallback(
    (
      songId: number,
      roleId: number,
      cell: MatrixCell | undefined,
    ): DisplayEntry[] => {
      const entries: DisplayEntry[] = []
      for (const entry of cell?.entries ?? []) {
        if (entry.kind === 'assignment' && removedAssignmentIds.has(entry.id))
          continue
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
  const removeEntry = useCallback((entry: DisplayEntry) => {
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
      setRemovedAssignmentIds((previous) =>
        new Set(previous).add(entry.id as number),
      )
    } else {
      setRemovedBackupIds((previous) =>
        new Set(previous).add(entry.id as number),
      )
    }
  }, [])

  /** Lists a cell's current standing assignees (server-saved minus pending removals, plus pending adds) for the picker's "Covering for" menu, names shortened per `nameFor`. */
  const standingAssigneesFor = useCallback(
    (songId: number, roleId: number): { id: number; name: string }[] => {
      const row = detail?.rows.find((candidate) => candidate.song_id === songId)
      const cell = row ? cellFor(row, roleId) : undefined
      const fromServer = (cell?.entries ?? [])
        .filter(
          (entry) =>
            entry.kind === 'assignment' && !removedAssignmentIds.has(entry.id),
        )
        .map((entry) => ({
          id: entry.person_id,
          name: nameFor.get(entry.person_name) ?? entry.person_name,
        }))
      const fromPending = [...addedEntries.values()]
        .filter((entry) => entry.songId === songId && entry.roleId === roleId)
        .map((entry) => ({
          id: entry.personId,
          name: nameFor.get(entry.personName) ?? entry.personName,
        }))
      return [...fromServer, ...fromPending]
    },
    [detail, removedAssignmentIds, addedEntries, nameFor],
  )

  /** Records a picker choice as a pending standing Assignment on the open cell, then closes the picker. */
  const pickAssigned = useCallback(
    (option: AssignmentPickerOption) => {
      if (pickerCell === null) return
      const key = entryKey(
        pickerCell.songId,
        pickerCell.roleId,
        option.person_id,
      )
      setAddedEntries((previous) => {
        const next = new Map(previous)
        next.set(key, {
          key,
          songId: pickerCell.songId,
          roleId: pickerCell.roleId,
          personId: option.person_id,
          personName: option.person_name,
          isRoleMismatch: !option.has_declared_role,
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
    (
      option: AssignmentPickerOption,
      rehearsalSongId: number,
      coveringFor: { id: number; name: string } | null,
    ) => {
      if (pickerCell === null) return
      const key = entryKey(
        pickerCell.songId,
        pickerCell.roleId,
        option.person_id,
      )
      setAddedBackupEntries((previous) => {
        const next = new Map(previous)
        next.set(key, {
          key,
          songId: pickerCell.songId,
          roleId: pickerCell.roleId,
          personId: option.person_id,
          personName: option.person_name,
          isRoleMismatch: !option.has_declared_role,
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
          To cover one evening only, add a <strong>Backup</strong> from the same
          picker.
        </p>
      </div>

      <div className="flex flex-wrap gap-3 text-xs text-rs-muted">
        <span>backup — covers one evening only</span>
        <span>away — a declared Conflict</span>
        <span>◦ role not declared</span>
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

      {runningOrder !== null && (
        <p className="text-xs text-rs-muted">
          Drag a row, or use its arrows, to reorder tonight's Running Order —
          this changes when each Song happens (and which Conflict Windows
          overlap it), never the Setlist's concert position.
        </p>
      )}

      {isPhone ? (
        <AssignmentEditorCards
          roles={roles}
          rows={displayRows}
          displayEntriesFor={displayEntriesFor}
          nameFor={nameFor}
          onRemove={removeEntry}
          onOpenPicker={(songId, songTitle, roleId, roleName) =>
            setPickerCell({ songId, songTitle, roleId, roleName })
          }
          reorderable={runningOrder !== null}
          onReorderRow={reorderDisplayRows}
        />
      ) : (
        <AssignmentEditorTable
          roles={roles}
          rows={displayRows}
          displayEntriesFor={displayEntriesFor}
          nameFor={nameFor}
          onRemove={removeEntry}
          onOpenPicker={(songId, songTitle, roleId, roleName) =>
            setPickerCell({ songId, songTitle, roleId, roleName })
          }
          reorderable={runningOrder !== null}
          onReorderRow={reorderDisplayRows}
        />
      )}

      <ResponsiveDialog
        open={addRoleOpen}
        onOpenChange={setAddRoleOpen}
        title="Add a Role column"
      >
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
          standingAssignees={standingAssigneesFor(
            pickerCell.songId,
            pickerCell.roleId,
          )}
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

/** Moves the item at `fromIndex` to `toIndex`, returning a new array (never mutating `list`). */
function moveItem<T>(list: T[], fromIndex: number, toIndex: number): T[] {
  if (
    toIndex < 0 ||
    toIndex >= list.length ||
    fromIndex === toIndex ||
    fromIndex < 0 ||
    fromIndex >= list.length
  ) {
    return list
  }
  const next = [...list]
  const [item] = next.splice(fromIndex, 1)
  if (item === undefined) return list
  next.splice(toIndex, 0, item)
  return next
}

/** One grid-cell occupant's pill: name, badges (backup/away/role-mismatch), and a remove control.
 *
 * Uncolored (issue: UI overhaul round 2) — the Edit Rehearsal grid already
 * arranges Roles as columns, so a per-Role hue here would be redundant
 * color-coding rather than information.
 */
function AssignmentEditorPill({
  entry,
  nameFor,
  onRemove,
}: {
  entry: DisplayEntry
  nameFor: Map<string, string>
  onRemove: () => void
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border border-rs-border bg-rs-border/40 px-2 py-0.5 text-xs font-medium text-rs-fg ${
        entry.pending ? 'ring-2 ring-rs-accent' : ''
      }`}
    >
      {nameFor.get(entry.personName) ?? entry.personName}
      {entry.kind === 'backup' && (
        <span className="rounded bg-rs-border px-1">backup</span>
      )}
      {entry.hasConflict && (
        <span className="rounded bg-rs-border px-1">away</span>
      )}
      {entry.isRoleMismatch && <span>◦</span>}
      <button
        type="button"
        aria-label={`Remove ${entry.personName}`}
        onClick={onRemove}
        className="ml-0.5 rounded-full px-1 hover:bg-rs-border"
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
  cell,
  displayEntriesFor,
  nameFor,
  onRemove,
  onOpenPicker,
}: {
  songId: number
  songTitle: string
  role: DisplayRole
  cell: MatrixCell | undefined
  displayEntriesFor: (
    songId: number,
    roleId: number,
    cell: MatrixCell | undefined,
  ) => DisplayEntry[]
  nameFor: Map<string, string>
  onRemove: (entry: DisplayEntry) => void
  onOpenPicker: (
    songId: number,
    songTitle: string,
    roleId: number,
    roleName: string,
  ) => void
}) {
  const entries = displayEntriesFor(songId, role.id, cell)
  return (
    <div className="flex flex-wrap items-center gap-1">
      {entries.length === 0 ? (
        <span className="text-xs text-rs-muted">
          {roleCode(role.name)} · unfilled
        </span>
      ) : (
        entries.map((entry) => (
          <AssignmentEditorPill
            key={entry.key}
            entry={entry}
            nameFor={nameFor}
            onRemove={() => onRemove(entry)}
          />
        ))
      )}
      <button
        type="button"
        aria-label={`Assign ${role.name} on ${songTitle}`}
        onClick={() => onOpenPicker(songId, songTitle, role.id, role.name)}
        className="rounded-full border border-rs-border px-1.5 text-xs font-medium leading-5"
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

interface AssignmentGridProps {
  roles: DisplayRole[]
  rows: MatrixRow[]
  displayEntriesFor: (
    songId: number,
    roleId: number,
    cell: MatrixCell | undefined,
  ) => DisplayEntry[]
  /** First-name-only display map, scoped to this grid (issue: UI overhaul round 2, item 3). */
  nameFor: Map<string, string>
  onRemove: (entry: DisplayEntry) => void
  onOpenPicker: (
    songId: number,
    songTitle: string,
    roleId: number,
    roleName: string,
  ) => void
  /** Whether rows may be dragged (or moved with the arrows) to reorder the Running Order — `false` on the Dress Rehearsal (ADR 0003), which has none. */
  reorderable: boolean
  /** Applies a row move by the display-row indices this grid renders at. */
  onReorderRow: (fromIndex: number, toIndex: number) => void
}

/**
 * Desktop rendering of the assignment grid: one row per Song, one column
 * per Role. The Running Order editor and this table are the same table
 * (issue: UI overhaul round 2) — a row is both a Running Order slot and its
 * assignments, so a drag reorders and edits in the same place rather than
 * two separate controls for the one Rehearsal.
 */
function AssignmentEditorTable({
  roles,
  rows,
  displayEntriesFor,
  nameFor,
  onRemove,
  onOpenPicker,
  reorderable,
  onReorderRow,
}: AssignmentGridProps) {
  const [dragIndex, setDragIndex] = useState<number | null>(null)

  return (
    <table className="w-full text-left text-sm">
      <thead>
        <tr>
          {reorderable && (
            <th className="w-6 pb-2" aria-hidden="true">
              {' '}
            </th>
          )}
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
        {rows.map((row, index) => (
          <tr
            key={row.song_id}
            draggable={reorderable}
            onDragStart={() => setDragIndex(index)}
            onDragOver={(event) => reorderable && event.preventDefault()}
            onDrop={(event) => {
              event.preventDefault()
              if (reorderable && dragIndex !== null)
                onReorderRow(dragIndex, index)
              setDragIndex(null)
            }}
            onDragEnd={() => setDragIndex(null)}
            className={reorderable ? 'border-t border-rs-border' : undefined}
          >
            {reorderable && (
              <td className="py-2 align-top">
                <span className="flex items-center gap-1">
                  <span
                    aria-hidden="true"
                    className="cursor-grab text-rs-muted"
                  >
                    ⠿
                  </span>
                  <span className="flex flex-col">
                    <button
                      type="button"
                      aria-label={`Move ${row.song_title} up`}
                      disabled={index === 0}
                      onClick={() => onReorderRow(index, index - 1)}
                      className="text-xs leading-none text-rs-muted disabled:cursor-not-allowed disabled:opacity-30"
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      aria-label={`Move ${row.song_title} down`}
                      disabled={index === rows.length - 1}
                      onClick={() => onReorderRow(index, index + 1)}
                      className="text-xs leading-none text-rs-muted disabled:cursor-not-allowed disabled:opacity-30"
                    >
                      ↓
                    </button>
                  </span>
                </span>
              </td>
            )}
            <td className="py-2 align-top">
              {row.start_time !== null ? formatClockTime(row.start_time) : ''}
            </td>
            <td className="py-2 align-top">{row.song_title}</td>
            {roles.map((role) => (
              <td key={role.id} className="py-2 align-top">
                <AssignmentEditorCell
                  songId={row.song_id}
                  songTitle={row.song_title}
                  role={role}
                  cell={cellFor(row, role.id)}
                  displayEntriesFor={displayEntriesFor}
                  nameFor={nameFor}
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

/**
 * Phone rendering of the assignment grid (`useIsPhone`): one card per Song,
 * stacking each Role's cell inside it. HTML5 drag-and-drop doesn't work on
 * touch, so reordering here is the Move up/down arrows only — the same
 * `onReorderRow` the desktop table's drag-and-drop calls.
 */
function AssignmentEditorCards({
  roles,
  rows,
  displayEntriesFor,
  nameFor,
  onRemove,
  onOpenPicker,
  reorderable,
  onReorderRow,
}: AssignmentGridProps) {
  return (
    <ul className="flex flex-col gap-3">
      {rows.map((row, index) => (
        <li key={row.song_id} className="rounded border border-rs-border p-3">
          <div className="flex items-center justify-between gap-2">
            <p className="font-medium">
              {row.start_time !== null
                ? `${formatClockTime(row.start_time)} · `
                : ''}
              {row.song_title}
            </p>
            {reorderable && (
              <span className="flex shrink-0 gap-1">
                <button
                  type="button"
                  aria-label={`Move ${row.song_title} up`}
                  disabled={index === 0}
                  onClick={() => onReorderRow(index, index - 1)}
                  className="rounded border border-rs-border px-1.5 py-0.5 text-xs disabled:cursor-not-allowed disabled:opacity-30"
                >
                  ↑
                </button>
                <button
                  type="button"
                  aria-label={`Move ${row.song_title} down`}
                  disabled={index === rows.length - 1}
                  onClick={() => onReorderRow(index, index + 1)}
                  className="rounded border border-rs-border px-1.5 py-0.5 text-xs disabled:cursor-not-allowed disabled:opacity-30"
                >
                  ↓
                </button>
              </span>
            )}
          </div>
          <ul className="mt-2 flex flex-col gap-2">
            {roles.map((role) => (
              <li key={role.id} className="flex flex-col gap-1">
                <span className="text-xs font-semibold uppercase text-rs-muted">
                  {role.name}
                </span>
                <AssignmentEditorCell
                  songId={row.song_id}
                  songTitle={row.song_title}
                  role={role}
                  cell={cellFor(row, role.id)}
                  displayEntriesFor={displayEntriesFor}
                  nameFor={nameFor}
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

/** One picker-list row: a Person's (shortened) name plus a bare "Conflict" marker (ADR 0005), clickable to make that pick. */
function PickerOptionRow({
  option,
  nameFor,
  onPick,
}: {
  option: AssignmentPickerOption
  nameFor: Map<string, string>
  onPick: () => void
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onPick}
        className="flex w-full items-center justify-between rounded px-2 py-1 text-left text-sm hover:bg-rs-border/40"
      >
        <span>{nameFor.get(option.person_name) ?? option.person_name}</span>
        {option.has_conflict && (
          <span className="text-xs text-rs-muted">Conflict</span>
        )}
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

  /** First-name-only display, scoped to this one dialog's candidate list (issue: UI overhaul round 2, item 3). */
  const nameFor = useMemo(() => {
    const names = [
      ...(payload?.declared ?? []).map((option) => option.person_name),
      ...(payload?.others ?? []).map((option) => option.person_name),
      ...(payload?.backup_declared ?? []).map((option) => option.person_name),
      ...(payload?.backup_others ?? []).map((option) => option.person_name),
      ...standingAssignees.map((assignee) => assignee.name),
    ]
    return shortenNames(names)
  }, [payload, standingAssignees])

  const coveringFor = useMemo(
    () =>
      standingAssignees.find((assignee) => assignee.id === coveringForId) ??
      null,
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
            <p className="pb-1 text-xs text-rs-muted">
              Every rehearsal + concert
            </p>
            <ul className="flex flex-col">
              {payload.declared.map((option) => (
                <PickerOptionRow
                  key={option.person_id}
                  option={option}
                  nameFor={nameFor}
                  onPick={() => onPickAssigned(option)}
                />
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
                          <span>
                            {nameFor.get(option.person_name) ??
                              option.person_name}
                          </span>
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
            {payload.rehearsal_song_id === null ? null : (
              <>
                {standingAssignees.length > 0 && (
                  <label className="mb-1 flex items-center gap-2 text-xs text-rs-muted">
                    Covering for
                    <select
                      value={coveringForId}
                      onChange={(event) =>
                        setCoveringForId(
                          event.target.value === ''
                            ? ''
                            : Number(event.target.value),
                        )
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
                      nameFor={nameFor}
                      onPick={() =>
                        onPickBackup(
                          option,
                          payload.rehearsal_song_id as number,
                          coveringFor,
                        )
                      }
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
                              onClick={() =>
                                onPickBackup(
                                  option,
                                  payload.rehearsal_song_id as number,
                                  coveringFor,
                                )
                              }
                              className="flex w-full items-center justify-between rounded px-2 py-1 text-left text-sm hover:bg-rs-border/40"
                            >
                              <span>
                                {nameFor.get(option.person_name) ??
                                  option.person_name}
                              </span>
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

          <p className="text-xs text-rs-muted">
            Who a Backup is covering for is shown to admins only.
          </p>
        </div>
      )}
    </ResponsiveDialog>
  )
}
