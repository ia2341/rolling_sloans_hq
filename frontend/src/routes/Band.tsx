import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { apiFetch } from '../api/client'
import { useAppContext } from '../api/ContextProvider'
import type {
  BandPayload,
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
  const [addSheetOpen, setAddSheetOpen] = useState(false)
  const [saveDialogOpen, setSaveDialogOpen] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
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

  // Requires a selected Semester -- `GET /api/members/roster/` returns an
  // empty payload with none selected, which would flip `isEditing` to
  // `true` with no Semester to save against and no
  // `RosterEditSessionRegistrar`/`SaveChangesDialog` mounted to leave it
  // (both are gated on `viewingSemester !== null`), stranding the admin in
  // an edit grid with no Save or Discard control.
  const startEditing = useCallback(() => {
    if (viewingSemester === null) return
    void apiFetch<ReadEnvelope<RosterEditPayload>>('/api/members/roster/').then(
      (envelope) => {
        setRows(rowsFromPayload(envelope.data.members))
        setRowErrors({})
        setResentPersonIds(new Set())
        setIsEditing(true)
      },
    )
  }, [viewingSemester])

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
    setSaveError(null)
  }, [])

  const requestSave = useCallback(() => setSaveDialogOpen(true), [])

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

  // Excludes anyone already staged in the buffer (import or existing-member
  // rows both carry a `personId`) so reopening the Add-people sheet can't
  // stage the same person twice -- a deleted row's `personId` doesn't
  // count, since undoing the delete is how that person comes back.
  const addRows = useCallback((newRows: RosterEditRow[]) => {
    setRows((current) => {
      const bufferedIds = new Set(
        current
          .filter((row) => !row.deleted && row.personId !== null)
          .map((row) => row.personId),
      )
      const deduped = newRows.filter(
        (row) => row.personId === null || !bufferedIds.has(row.personId),
      )
      return [...current, ...deduped]
    })
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
      if (!envelope.ok) {
        // A rejected save (e.g. a stale Semester) means the successful
        // preview the dialog is still showing no longer reflects what the
        // server will do -- close it rather than leaving "Save changes"
        // enabled over stale Fallout, and surface the rejection in the
        // grid itself so a re-opened Save popup runs a fresh preview.
        setSaveDialogOpen(false)
        setSaveError(
          envelope.non_field_errors.length > 0
            ? envelope.non_field_errors.join(' ')
            : 'This save was rejected. Review the roster and try again.',
        )
        setRowErrors(envelope.errors)
        return
      }
      setSaveError(null)
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
      {isEditing && saveError !== null && (
        <p
          role="alert"
          className="mb-3 rounded border border-rs-danger/40 bg-rs-danger/5 px-3 py-2 text-sm text-rs-danger"
        >
          {saveError}
        </p>
      )}
      {isEditing ? (
        <RosterEditGrid
          rows={rows}
          rowErrors={rowErrors}
          onDelete={deleteRow}
          onUndoDelete={undoDelete}
          onResendInvite={resendInvite}
          resentPersonIds={resentPersonIds}
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

/** The 6-column cap's pixel width: six 240px tracks plus their five `gap-3` gutters. */
export const BAND_GRID_MAX_WIDTH_PX = 6 * 240 + 5 * 12

/**
 * The Roster's card grid (issue #366): one card per member, every
 * viewport, in a CSS grid that reflows continuously rather than snapping
 * at a Tailwind breakpoint. `auto-fill` with a fixed 240px track (issue
 * #425, widened by #435) sizes columns purely from the container's width,
 * never from how many cards are actually present -- unlike `auto-fit`/`1fr`,
 * which collapses empty tracks and stretches the remaining cards to fill
 * the freed space, so a 2-member filtered view would render much wider
 * cards than a 20-member one at the same viewport. A fixed, non-`1fr` track
 * keeps card width constant regardless of item count; the 6-column cap
 * (below) handles very wide viewports, where a plain `auto-fill` would
 * otherwise keep adding tracks.
 *
 * Card height is fixed too (issue #435): before, height was driven purely
 * by how long the comma-joined role list happened to be, so a semester
 * with few members but long role lists rendered short/cramped cards next
 * to a large semester's taller, more comfortable ones at the same
 * viewport. `min-h` plus `line-clamp-2` on the role line pins every card
 * to the same footprint -- the large-semester proportions, just with more
 * overall area -- regardless of member count or role-list length.
 *
 * The 6-column cap is a `max-w` on the grid itself, sized to exactly six
 * 240px tracks plus their five `gap-3` gutters -- `auto-fill` can never
 * pack a seventh column into a container that isn't wide enough to hold
 * one, so this holds at any viewport width with no JS and no container
 * query.
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
    <ul
      className="grid grid-cols-[repeat(auto-fill,240px)] gap-3"
      style={{ maxWidth: `${BAND_GRID_MAX_WIDTH_PX}px` }}
    >
      {members.map((member) => (
        <li
          key={member.id}
          className="min-h-[112px] rounded border border-rs-border"
        >
          <Link to={`/members/${member.id}`} className="block h-full p-3">
            <p className="font-medium">
              {member.name}
              {member.id === viewerId && (
                <span className="ml-2 rounded-full bg-rs-accent px-2 py-0.5 text-xs font-medium text-rs-accent-fg">
                  you
                </span>
              )}
            </p>
            <p className="line-clamp-2 pt-1 text-sm text-rs-muted">
              {member.roles.length > 0 ? member.roles.join(', ') : '—'}
            </p>
          </Link>
        </li>
      ))}
    </ul>
  )
}
