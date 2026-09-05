import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { apiFetch } from '../api/client'
import { useAppContext } from '../api/ContextProvider'
import type { BandPayload, RosterEntry } from '../api/memberTypes'
import type { ReadEnvelope } from '../api/types'
import { PageHead } from '../components/ui/PageHead'
import { useIsPhone } from '../hooks/useIsPhone'
import { usePageTitle } from '../shell/PageTitleContext'

/**
 * `/members/` (issue #333): the viewing Semester's active Roster, fed by
 * one `GET /api/members/` round trip. Renders nothing until that response
 * arrives, mirroring `Setlist`/`Song`.
 */
export function Band() {
  usePageTitle('Band')
  const appContext = useAppContext()
  const isPhone = useIsPhone()
  const [data, setData] = useState<BandPayload | null>(null)

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

  if (data === null) return null

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
      {data.semester_name === null ? (
        <p className="text-sm text-rs-muted">No Semester published yet.</p>
      ) : data.members.length === 0 ? (
        <p className="text-sm text-rs-muted">No one is on the Roster yet.</p>
      ) : isPhone ? (
        <BandCards members={data.members} viewerId={appContext?.viewer.id} />
      ) : (
        <BandTable members={data.members} viewerId={appContext?.viewer.id} />
      )}
    </div>
  )
}

/** The phone layout: one card per member, no horizontal scroll (issue #333). */
function BandCards({
  members,
  viewerId,
}: {
  members: RosterEntry[]
  viewerId?: number
}) {
  return (
    <ul className="flex flex-col gap-3">
      {members.map((member) => (
        <li key={member.id} className="rounded border border-rs-border p-3">
          <Link to={`/members/${member.id}`} className="block">
            <div className="flex items-center justify-between gap-2">
              <p className="font-medium">
                {member.name}
                {member.id === viewerId && (
                  <span className="ml-2 rounded-full bg-rs-accent px-2 py-0.5 text-xs font-medium text-rs-accent-fg">
                    you
                  </span>
                )}
              </p>
              <span className="text-sm text-rs-muted">
                {member.song_count} song{member.song_count === 1 ? '' : 's'}
              </span>
            </div>
            <p className="pt-1 text-sm text-rs-muted">
              {member.roles.length > 0 ? member.roles.join(', ') : '—'}
            </p>
          </Link>
        </li>
      ))}
    </ul>
  )
}

/** The desktop layout: `Name | Roles | Songs` plus an action cell (issue #333). */
function BandTable({
  members,
  viewerId,
}: {
  members: RosterEntry[]
  viewerId?: number
}) {
  return (
    <table className="w-full text-left text-sm">
      <thead>
        <tr>
          <th className="pb-2">Name</th>
          <th className="pb-2">Roles</th>
          <th className="pb-2">Songs</th>
          <th className="pb-2" />
        </tr>
      </thead>
      <tbody>
        {members.map((member) => (
          <tr key={member.id}>
            <td className="py-2 align-top">
              {member.name}
              {member.id === viewerId && (
                <span className="ml-2 rounded-full bg-rs-accent px-2 py-0.5 text-xs font-medium text-rs-accent-fg">
                  you
                </span>
              )}
            </td>
            <td className="py-2 align-top text-rs-muted">
              {member.roles.length > 0 ? member.roles.join(', ') : '—'}
            </td>
            <td className="py-2 align-top">{member.song_count}</td>
            <td className="py-2 align-top">
              <Link to={`/members/${member.id}`}>Open</Link>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
