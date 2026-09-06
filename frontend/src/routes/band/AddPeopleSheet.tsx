import { useEffect, useState } from 'react'

import { apiFetch } from '../../api/client'
import type { RosterCandidatesPayload } from '../../api/memberTypes'
import type { ReadEnvelope } from '../../api/types'
import { ResponsiveDialog } from '../../components/ui/ResponsiveDialog'
import { SegmentedControl } from '../../components/ui/SegmentedControl'
import {
  newAddedRow,
  newImportedRow,
  newInviteRow,
  type RosterEditRow,
} from './rosterEditModel'

type Source = 'import' | 'existing' | 'invite'

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

interface AddPeopleSheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Appends staged rows to the same Pending Buffer a hand-edit fills -- import, add and invite all land through this one callback, never a separate write (issue #374). */
  onAddRows: (rows: RosterEditRow[]) => void
}

/**
 * The `+ Add people` sheet (issue #374, backed by #336's
 * `RosterCandidatesApiView`): a modal on desktop and a bottom sheet on
 * phone via `ResponsiveDialog`, its three sources are sections behind a
 * `SegmentedControl` rather than three stacked forms -- import from the
 * prior Semester's roster, add an already-active but unrostered member, or
 * invite someone brand new. All three land in the same Pending Buffer via
 * `onAddRows`, so invite-as-part-of-the-edit and import-from-prior-semester
 * fold into one edit session per the issue's requirement. Nothing here
 * writes anything -- ticked candidates and a typed invite both become
 * ordinary Buffer rows only once "Add to the buffer" is pressed; the real
 * write is still the toolbar's Save changes -> the shared Save popup.
 */
export function AddPeopleSheet({
  open,
  onOpenChange,
  onAddRows,
}: AddPeopleSheetProps) {
  const [source, setSource] = useState<Source>('import')
  const [loaded, setLoaded] = useState(false)
  const [candidates, setCandidates] = useState<RosterCandidatesPayload | null>(
    null,
  )
  const [importTicked, setImportTicked] = useState<Set<number>>(new Set())
  const [existingTicked, setExistingTicked] = useState<Set<number>>(new Set())

  const [inviteName, setInviteName] = useState('')
  const [inviteEmail, setInviteEmail] = useState('')

  function resetAndClose() {
    setSource('import')
    setLoaded(false)
    setCandidates(null)
    setImportTicked(new Set())
    setExistingTicked(new Set())
    setInviteName('')
    setInviteEmail('')
    onOpenChange(false)
  }

  function handleOpenChange(next: boolean) {
    if (!next) resetAndClose()
    else onOpenChange(next)
  }

  // Fetches candidates once per open -- reacting to `open` itself (issue
  // #374) rather than `onOpenChange`, since this sheet is fully
  // controlled: `open` flips to `true` because the caller's own state
  // changed (e.g. the "+ Add people" button), never because Radix calls
  // `onOpenChange` on the caller's behalf.
  useEffect(() => {
    if (!open || loaded) return
    void apiFetch<ReadEnvelope<RosterCandidatesPayload>>(
      '/api/members/roster/candidates/',
    ).then((envelope) => {
      setCandidates(envelope.data)
      setImportTicked(new Set(envelope.data.import_candidates.map((c) => c.id)))
      setLoaded(true)
    })
  }, [open, loaded])

  function toggleImportTicked(id: number) {
    setImportTicked((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleExistingTicked(id: number) {
    setExistingTicked((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function addToBuffer() {
    const rows: RosterEditRow[] = []
    if (source === 'import' && candidates !== null) {
      candidates.import_candidates.forEach((candidate) => {
        if (importTicked.has(candidate.id)) rows.push(newImportedRow(candidate))
      })
    } else if (source === 'existing' && candidates !== null) {
      candidates.unrostered_people.forEach((person) => {
        if (existingTicked.has(person.id)) rows.push(newAddedRow(person))
      })
    } else if (source === 'invite') {
      if (inviteName.trim() && EMAIL_PATTERN.test(inviteEmail.trim())) {
        rows.push(newInviteRow(inviteName.trim(), inviteEmail.trim()))
      }
    }
    if (rows.length > 0) onAddRows(rows)
    resetAndClose()
  }

  const canAdd =
    source === 'import'
      ? importTicked.size > 0
      : source === 'existing'
        ? existingTicked.size > 0
        : inviteName.trim() !== '' && EMAIL_PATTERN.test(inviteEmail.trim())

  const importSourceName = candidates?.import_source_semester_name ?? null

  return (
    <ResponsiveDialog
      open={open}
      onOpenChange={handleOpenChange}
      title="Add people"
      wide
      footer={
        <>
          <button
            type="button"
            onClick={resetAndClose}
            className="rounded border border-rs-border px-3 py-1.5 text-sm font-medium hover:bg-rs-border/40"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={addToBuffer}
            disabled={!canAdd}
            className="rounded bg-rs-accent px-3 py-1.5 text-sm font-medium text-rs-accent-fg disabled:cursor-not-allowed disabled:opacity-50"
          >
            Add to the buffer
          </button>
        </>
      }
    >
      <SegmentedControl
        ariaLabel="Add people from"
        options={[
          {
            value: 'import',
            label:
              importSourceName !== null
                ? `Import from ${importSourceName}`
                : 'Import from a prior semester',
          },
          { value: 'existing', label: 'Add existing member' },
          { value: 'invite', label: 'Invite new member' },
        ]}
        value={source}
        onChange={(next) => setSource(next as Source)}
      />

      {!loaded ? (
        <p className="pt-3 text-sm text-rs-muted">Loading…</p>
      ) : source === 'import' ? (
        <div className="pt-3">
          {importSourceName === null ? (
            <p className="text-sm text-rs-muted">
              There's no prior Semester to import a roster from.
            </p>
          ) : candidates && candidates.import_candidates.length === 0 ? (
            <p className="text-sm text-rs-muted">
              Everyone from {importSourceName} is already on this roster.
            </p>
          ) : (
            <ul className="max-h-64 space-y-1 overflow-y-auto">
              {candidates?.import_candidates.map((candidate) => (
                <li key={candidate.id}>
                  <label className="flex items-center gap-2 rounded p-1.5 text-sm">
                    <input
                      type="checkbox"
                      checked={importTicked.has(candidate.id)}
                      onChange={() => toggleImportTicked(candidate.id)}
                    />
                    <span className="flex-1">
                      {candidate.name}
                      {candidate.roles.length > 0 && (
                        <span className="text-rs-muted">
                          {' · '}
                          {candidate.roles.map((role) => role.name).join(', ')}
                        </span>
                      )}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : source === 'existing' ? (
        <div className="pt-3">
          {candidates && candidates.unrostered_people.length === 0 ? (
            <p className="text-sm text-rs-muted">
              No active member is unrostered this Semester.
            </p>
          ) : (
            <ul className="max-h-64 space-y-1 overflow-y-auto">
              {candidates?.unrostered_people.map((person) => (
                <li key={person.id}>
                  <label className="flex items-center gap-2 rounded p-1.5 text-sm">
                    <input
                      type="checkbox"
                      checked={existingTicked.has(person.id)}
                      onChange={() => toggleExistingTicked(person.id)}
                    />
                    <span className="flex-1">{person.name}</span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-2 pt-3">
          <div>
            <label className="text-sm" htmlFor="invite-name">
              Name
            </label>
            <input
              id="invite-name"
              type="text"
              value={inviteName}
              onChange={(event) => setInviteName(event.target.value)}
              className="mt-1 block w-full rounded border border-rs-border px-2 py-1 text-sm"
            />
          </div>
          <div>
            <label className="text-sm" htmlFor="invite-email">
              Email
            </label>
            <input
              id="invite-email"
              type="email"
              value={inviteEmail}
              onChange={(event) => setInviteEmail(event.target.value)}
              className="mt-1 block w-full rounded border border-rs-border px-2 py-1 text-sm"
            />
          </div>
          <p className="text-xs text-rs-muted">
            Roles are assigned in the grid after this row lands, via the same
            Role picker every other row uses.
          </p>
        </div>
      )}
    </ResponsiveDialog>
  )
}
