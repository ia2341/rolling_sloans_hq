import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { apiFetch } from '../api/client'
import { useAppContext } from '../api/ContextProvider'
import type {
  BandPayload,
  MemberRole,
  RosterEditPayload,
  RosterEntry,
} from '../api/memberTypes'
import type { PreviewResult } from '../api/previewTypes'
import type { ReadEnvelope } from '../api/types'
import { PageHead } from '../components/ui/PageHead'
import { SaveChangesDialog } from '../components/ui/SaveChangesDialog'
import {
  buildRosterFilterBuckets,
  memberMatchesRosterFilter,
  type RosterFilterKey,
} from '../lib/roleColumns'
import { useRegisterEditSession } from '../shell/EditSessionContext'
import { usePageTitle } from '../shell/PageTitleContext'
import { AddPeopleSheet } from './band/AddPeopleSheet'
import { RosterEditGrid } from './band/RosterEditGrid'
import {
  buildBufferWire,
  computeChangeCount,
  deleteRosterRow,
  mapRosterPreviewToResult,
  rowsFromPayload,
  withDeclaredRole,
  type RosterEditRow,
  type RosterWriteEnvelope,
} from './band/rosterEditModel'

/**
 * `/members/` (issue #366): the viewing Semester's active Roster as a
 * single filterable card grid, fed by one `GET /api/members/` round trip.
 * Renders nothing until that response arrives, mirroring `Setlist`/`Song`.
 *
 * For an admin, "Edit roster" (issue #374, backed by #336's Roster edit
 * surface) flips this same page into a Pending-Buffer grid rather than
 * navigating anywhere else -- exactly `Setlist`'s edit-mode shape. The
 * editor's own richer read model (`GET /api/members/roster/`, invited and
 * inactive rows included) is fetched lazily, only once editing starts,
 * since the plain read view above never needs it. A `?intent=edit-roster`
 * query param (from Home's setup checklist) starts editing automatically
 * once the plain read has landed, then strips itself.
 */
export function Band() {
  usePageTitle('Band')
  const appContext = useAppContext()
  const [data, setData] = useState<BandPayload | null>(null)
  const [checked, setChecked] = useState<ReadonlySet<RosterFilterKey>>(
    new Set(),
  )

  const [isEditing, setIsEditing] = useState(false)
  const [rows, setRows] = useState<RosterEditRow[]>([])
  const [rowErrors, setRowErrors] = useState<
    Record<string, Record<string, string[]>>
  >({})
  const [availableRoles, setAvailableRoles] = useState<MemberRole[]>([])
  const [addSheetOpen, setAddSheetOpen] = useState(false)
  const [saveDialogOpen, setSaveDialogOpen] = useState(false)
  const [resentPersonIds, setResentPersonIds] = useState<Set<number>>(new Set())
  const [searchParams, setSearchParams] = useSearchParams()
  const handledIntentRef = useRef(false)

  const load = useCallback(() => {
    void apiFetch<ReadEnvelope<BandPayload>>('/api/members/').then(
      (envelope) => {
        setData(envelope.data)
      },
    )
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const viewingSemester = appContext?.viewing_semester ?? null

  const startEditing = useCallback(() => {
    void apiFetch<ReadEnvelope<RosterEditPayload>>('/api/members/roster/').then(
      (envelope) => {
        setRows(rowsFromPayload(envelope.data.members))
        setAvailableRoles(envelope.data.available_roles)
        setRowErrors({})
        setResentPersonIds(new Set())
        setIsEditing(true)
      },
    )
  }, [])

  // `?intent=edit-roster` (issue #374): Home's Roster checklist row lands
  // here already mid-workflow -- editing started for you -- rather than
  // on the plain read view with an inert button. Does not also auto-open
  // the Add-people sheet: the ask for Roster was only "start editing",
  // unlike Setlist's deeper "and open Add songs" sub-step. Guarded by a
  // ref so it fires exactly once per mount even though `data` may update
  // again later (e.g. after a save).
  useEffect(() => {
    if (data === null) return
    if (handledIntentRef.current) return
    if (searchParams.get('intent') !== 'edit-roster') return
    handledIntentRef.current = true
    startEditing()
    setSearchParams(
      (previous) => {
        const params = new URLSearchParams(previous)
        params.delete('intent')
        return params
      },
      { replace: true },
    )
  }, [data, searchParams, setSearchParams, startEditing])

  const discard = useCallback(() => {
    setIsEditing(false)
    setRows([])
    setRowErrors({})
  }, [])

  const requestSave = useCallback(() => setSaveDialogOpen(true), [])

  const updateName = useCallback((rowKey: string, name: string) => {
    setRows((current) =>
      current.map((row) => (row.rowKey === rowKey ? { ...row, name } : row)),
    )
  }, [])

  const updateRoles = useCallback((rowKey: string, roleIds: Set<number>) => {
    setRows((current) =>
      current.map((row) => (row.rowKey === rowKey ? { ...row, roleIds } : row)),
    )
  }, [])

  const deleteRow = useCallback((rowKey: string) => {
    setRows((current) => deleteRosterRow(current, rowKey))
  }, [])

  const undoDelete = useCallback((rowKey: string) => {
    setRows((current) =>
      current.map((row) =>
        row.rowKey === rowKey ? { ...row, deleted: false } : row,
      ),
    )
  }, [])

  const addRows = useCallback((newRows: RosterEditRow[]) => {
    setRows((current) => [...current, ...newRows])
  }, [])

  const onRoleDeclared = useCallback((role: MemberRole) => {
    setAvailableRoles((current) => withDeclaredRole(current, role))
  }, [])

  const resendInvite = useCallback((personId: number) => {
    void apiFetch<RosterWriteEnvelope>(
      `/api/members/roster/${personId}/resend-invite/`,
      { method: 'POST', body: JSON.stringify({}) },
    ).then((envelope) => {
      if (!envelope.ok) return
      setResentPersonIds((current) => new Set(current).add(personId))
    })
  }, [])

  const previewRoster = useCallback((): Promise<PreviewResult> => {
    if (viewingSemester === null) {
      return Promise.resolve({
        ok: false,
        changes: [],
        fallout: { loud: [], quiet: [] },
        nonFieldErrors: ['No Semester is selected to save against.'],
      })
    }
    const body = buildBufferWire(
      viewingSemester.id,
      viewingSemester.updated_at,
      rows,
    )
    return apiFetch<RosterWriteEnvelope>('/api/members/roster/preview/', {
      method: 'POST',
      body: JSON.stringify(body),
    }).then((envelope) => {
      setRowErrors(envelope.errors)
      return mapRosterPreviewToResult(envelope)
    })
  }, [rows, viewingSemester])

  const confirmSave = useCallback(() => {
    if (viewingSemester === null) return
    const body = buildBufferWire(
      viewingSemester.id,
      viewingSemester.updated_at,
      rows,
    )
    void apiFetch<RosterWriteEnvelope>('/api/members/roster/save/', {
      method: 'POST',
      body: JSON.stringify(body),
    }).then((envelope) => {
      if (!envelope.ok) return
      setSaveDialogOpen(false)
      setIsEditing(false)
      setRows([])
      setRowErrors({})
      load()
    })
  }, [rows, viewingSemester, load])

  const buckets = useMemo(
    () => (data === null ? [] : buildRosterFilterBuckets(data.members)),
    [data],
  )

  const visibleMembers = useMemo(
    () =>
      data === null
        ? []
        : data.members.filter((member) =>
            memberMatchesRosterFilter(member.roles, checked),
          ),
    [data, checked],
  )

  const changeCount = useMemo(() => computeChangeCount(rows), [rows])
  const isAdmin = appContext?.viewer.is_admin ?? false

  if (data === null) return null

  /** Toggles one filter bucket on or off, keeping every other bucket's state. */
  function toggleBucket(key: RosterFilterKey) {
    setChecked((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const subline =
    data.semester_name === null
      ? 'No Semester published yet.'
      : `${data.semester_name} · ${data.member_count} member${data.member_count === 1 ? '' : 's'}`

  return (
    <div>
      {isEditing && viewingSemester !== null && (
        <RosterEditSessionRegistrar
          semesterName={viewingSemester.name}
          changeCount={changeCount}
          discard={discard}
          requestSave={requestSave}
        />
      )}
      <PageHead
        title="Band"
        subline={subline}
        action={
          !isAdmin ? undefined : isEditing ? (
            <button
              type="button"
              onClick={() => setAddSheetOpen(true)}
              className="rounded bg-rs-accent px-3 py-1.5 text-sm font-medium text-rs-accent-fg"
            >
              + Add people
            </button>
          ) : (
            <button
              type="button"
              onClick={startEditing}
              className="rounded bg-rs-accent px-3 py-1.5 text-sm font-medium text-rs-accent-fg"
            >
              Edit roster
            </button>
          )
        }
      />
      {!isEditing &&
        data.unassigned_role_holders !== undefined &&
        data.unassigned_role_holders.count > 0 && (
          <p
            role="alert"
            className="mb-3 rounded border border-rs-warning-border bg-rs-warning-bg px-3 py-2 text-sm text-rs-warning-fg"
          >
            {data.unassigned_role_holders.count} member
            {data.unassigned_role_holders.count === 1 ? '' : 's'}{' '}
            {data.unassigned_role_holders.count === 1 ? 'has' : 'have'} role
            assignments this semester but no roster membership:{' '}
            {data.unassigned_role_holders.names.join(', ')}
          </p>
        )}
      {isEditing ? (
        <RosterEditGrid
          rows={rows}
          rowErrors={rowErrors}
          availableRoles={availableRoles}
          onUpdateName={updateName}
          onUpdateRoles={updateRoles}
          onDelete={deleteRow}
          onUndoDelete={undoDelete}
          onResendInvite={resendInvite}
          resentPersonIds={resentPersonIds}
          onRoleDeclared={onRoleDeclared}
        />
      ) : data.semester_name === null ? (
        <p className="text-sm text-rs-muted">No Semester published yet.</p>
      ) : data.members.length === 0 ? (
        <p className="text-sm text-rs-muted">No one is on the Roster yet.</p>
      ) : (
        <>
          {buckets.length > 0 && (
            <RosterFilterBar
              buckets={buckets}
              checked={checked}
              onToggle={toggleBucket}
            />
          )}
          <BandGrid members={visibleMembers} viewerId={appContext?.viewer.id} />
        </>
      )}

      <AddPeopleSheet
        open={addSheetOpen}
        onOpenChange={setAddSheetOpen}
        onAddRows={addRows}
      />

      {viewingSemester !== null && (
        <SaveChangesDialog
          open={saveDialogOpen}
          onOpenChange={setSaveDialogOpen}
          title={`Save ${changeCount} change${changeCount === 1 ? '' : 's'} to ${viewingSemester.name}?`}
          preview={previewRoster}
          onConfirm={confirmSave}
        />
      )}
    </div>
  )
}

/**
 * Mounts only while the Roster editor is active, so the shell's edit
 * toolbar appears and disappears with it -- mirrors `Setlist`'s
 * `SetlistEditSessionRegistrar` exactly (see that component's docstring
 * for why an always-mounted call would be wrong here).
 */
function RosterEditSessionRegistrar({
  semesterName,
  changeCount,
  discard,
  requestSave,
}: {
  semesterName: string
  changeCount: number
  discard: () => void
  requestSave: () => void
}) {
  useRegisterEditSession({
    what: semesterName,
    changeCount,
    blockedReason: null,
    discard,
    requestSave,
  })
  return null
}

/** Role-filter checkboxes (issue #366), OR'd together — checking none shows everyone. */
function RosterFilterBar({
  buckets,
  checked,
  onToggle,
}: {
  buckets: { key: RosterFilterKey; label: string }[]
  checked: ReadonlySet<RosterFilterKey>
  onToggle: (key: RosterFilterKey) => void
}) {
  return (
    <fieldset className="mb-4 flex flex-wrap gap-x-4 gap-y-2 border-0 p-0">
      <legend className="sr-only">Filter by role</legend>
      {buckets.map((bucket) => (
        <label
          key={bucket.key}
          className="flex items-center gap-1.5 text-sm text-rs-muted"
        >
          <input
            type="checkbox"
            checked={checked.has(bucket.key)}
            onChange={() => onToggle(bucket.key)}
          />
          {bucket.label}
        </label>
      ))}
    </fieldset>
  )
}

/**
 * The Roster's card grid (issue #366): one card per member, every
 * viewport, in a CSS grid that reflows continuously rather than snapping
 * at a Tailwind breakpoint. `minmax(260px, 1fr)` fits exactly three cards
 * across a typical desktop content width (roughly 900–1100px once the
 * shell's own padding is subtracted — three columns plus two 12px gaps is
 * just under 900px at the 260px floor) while still collapsing to a single
 * column under about 560px, so a phone and a desktop share one layout
 * with no `isPhone` branch.
 */
function BandGrid({
  members,
  viewerId,
}: {
  members: RosterEntry[]
  viewerId?: number
}) {
  if (members.length === 0) {
    return (
      <p className="text-sm text-rs-muted">
        No members match the selected roles.
      </p>
    )
  }
  return (
    <ul className="grid grid-cols-[repeat(auto-fit,minmax(260px,1fr))] gap-3">
      {members.map((member) => (
        <li key={member.id} className="rounded border border-rs-border">
          <Link to={`/members/${member.id}`} className="block p-3">
            <p className="font-medium">
              {member.name}
              {member.id === viewerId && (
                <span className="ml-2 rounded-full bg-rs-accent px-2 py-0.5 text-xs font-medium text-rs-accent-fg">
                  you
                </span>
              )}
            </p>
            <p className="pt-1 text-sm text-rs-muted">
              {member.roles.length > 0 ? member.roles.join(', ') : '—'}
            </p>
          </Link>
        </li>
      ))}
    </ul>
  )
}
