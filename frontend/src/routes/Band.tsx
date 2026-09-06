import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { apiFetch } from '../api/client'
import { useAppContext } from '../api/ContextProvider'
import type { BandPayload, RosterEntry } from '../api/memberTypes'
import type { ReadEnvelope } from '../api/types'
import { PageHead } from '../components/ui/PageHead'
import {
  buildRosterFilterBuckets,
  memberMatchesRosterFilter,
  type RosterFilterKey,
} from '../lib/roleColumns'
import { usePageTitle } from '../shell/PageTitleContext'

/**
 * `/members/` (issue #366): the viewing Semester's active Roster as a
 * single filterable card grid, fed by one `GET /api/members/` round trip.
 * Renders nothing until that response arrives, mirroring `Setlist`/`Song`.
 */
export function Band() {
  usePageTitle('Band')
  const appContext = useAppContext()
  const [data, setData] = useState<BandPayload | null>(null)
  const [checked, setChecked] = useState<ReadonlySet<RosterFilterKey>>(
    new Set(),
  )

  useEffect(() => {
    let cancelled = false
    void apiFetch<ReadEnvelope<BandPayload>>('/api/members/').then(
      (envelope) => {
        if (!cancelled) setData(envelope.data)
      },
    )
    return () => {
      cancelled = true
    }
  }, [])

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
      <PageHead
        title="Band"
        subline={subline}
        action={
          appContext?.viewer.is_admin ? (
            <button
              type="button"
              // Inert for now — the Roster editor this opens is #336's;
              // this ticket owns only the read surface and this button.
              className="rounded bg-rs-accent px-3 py-1.5 text-sm font-medium text-rs-accent-fg"
            >
              Edit roster
            </button>
          ) : undefined
        }
      />
      {data.unassigned_role_holders !== undefined &&
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
      {data.semester_name === null ? (
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
    </div>
  )
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
