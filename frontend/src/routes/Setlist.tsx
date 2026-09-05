import { Fragment, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { apiFetch } from '../api/client'
import { useAppContext } from '../api/ContextProvider'
import type { SetlistPayload } from '../api/setlistTypes'
import type { ReadEnvelope } from '../api/types'
import { CastLine } from '../components/ui/CastLine'
import { PageHead } from '../components/ui/PageHead'
import { RoleLegend } from '../components/ui/RoleLegend'
import { useIsPhone } from '../hooks/useIsPhone'
import { usePageTitle } from '../shell/PageTitleContext'

/**
 * `/setlist/` (issue #330): the viewing Semester's whole Setlist, fed by
 * one `GET /api/setlist/` round trip. Renders nothing until that response
 * arrives — there is no separate loading-skeleton concern here, since the
 * page has nothing to show before the one request it needs completes.
 */
export function Setlist() {
  usePageTitle('Setlist')
  const appContext = useAppContext()
  const isPhone = useIsPhone()
  const [data, setData] = useState<SetlistPayload | null>(null)

  useEffect(() => {
    let cancelled = false
    void apiFetch<ReadEnvelope<SetlistPayload>>('/api/setlist/').then(
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
      : `${data.semester_name} · ${data.song_count} song${data.song_count === 1 ? '' : 's'} · ${data.total_running_time}`

  return (
    <div>
      <PageHead
        title="Setlist"
        subline={subline}
        action={
          appContext?.viewer.is_admin ? (
            <button
              type="button"
              className="rounded bg-rs-accent px-3 py-1.5 text-sm font-medium text-rs-accent-fg"
            >
              Edit setlist
            </button>
          ) : undefined
        }
      />
      {data.roles.length > 0 && (
        <div className="flex flex-wrap pb-4">
          <RoleLegend
            roles={data.roles.map((role, index) => ({
              index,
              name: role.name,
            }))}
          />
        </div>
      )}
      {data.songs.length === 0 ? (
        <p className="text-sm text-rs-muted">No songs yet this Semester.</p>
      ) : isPhone ? (
        <SetlistCards songs={data.songs} viewerId={appContext?.viewer.id} />
      ) : (
        <SetlistTable songs={data.songs} viewerId={appContext?.viewer.id} />
      )}
    </div>
  )
}

function SetlistCards({
  songs,
  viewerId,
}: {
  songs: SetlistPayload['songs']
  viewerId?: number
}) {
  return (
    <ul className="flex flex-col gap-3">
      {songs.map((song) => (
        <li key={song.id} className="rounded border border-rs-border p-3">
          <div className="flex items-start justify-between gap-2">
            <p className="font-medium">
              {song.position}. {song.title}
            </p>
            <span className="text-sm text-rs-muted">{song.length}</span>
          </div>
          <p className="text-sm text-rs-muted">{song.artist}</p>
          <div className="pt-2">
            <CastLine cast={song.cast} viewerId={viewerId} />
          </div>
          {song.notes !== '' && (
            <p className="pt-2 text-sm text-rs-muted">{song.notes}</p>
          )}
          <RecordingEntryPoints song={song} label="no takes yet" />
        </li>
      ))}
    </ul>
  )
}

function SetlistTable({
  songs,
  viewerId,
}: {
  songs: SetlistPayload['songs']
  viewerId?: number
}) {
  return (
    <table className="w-full text-left text-sm">
      <thead>
        <tr>
          <th className="pb-2">#</th>
          <th className="pb-2">Song</th>
          <th className="pb-2">Cast</th>
          <th className="pb-2">Length</th>
          <th className="pb-2">Recordings</th>
          <th className="pb-2" />
        </tr>
      </thead>
      <tbody>
        {songs.map((song) => (
          <Fragment key={song.id}>
            <tr>
              <td className="py-2 align-top">{song.position}</td>
              <td className="py-2 align-top">
                <p className="font-medium">{song.title}</p>
                <p className="text-rs-muted">{song.artist}</p>
              </td>
              <td className="py-2 align-top">
                <CastLine cast={song.cast} viewerId={viewerId} />
              </td>
              <td className="py-2 align-top">{song.length}</td>
              <td className="py-2 align-top">
                <RecordingEntryPoints song={song} label="—" />
              </td>
              <td className="py-2 align-top">
                <Link to={`/songs/${song.id}`}>Open</Link>
              </td>
            </tr>
            {song.notes !== '' && (
              <tr>
                <td colSpan={6} className="pb-2 text-rs-muted">
                  {song.notes}
                </td>
              </tr>
            )}
          </Fragment>
        ))}
      </tbody>
    </table>
  )
}

/** ▶ (play, with a count) and + (upload preselected to this Song) — the Setlist's two Recordings entry points (issue #330). */
function RecordingEntryPoints({
  song,
  label,
}: {
  song: SetlistPayload['songs'][number]
  label: string
}) {
  return (
    <div className="flex items-center gap-3 pt-2 text-sm">
      {song.recording_count > 0 ? (
        <Link
          to={`/songs/${song.id}`}
          aria-label={`Play ${song.title}'s takes`}
        >
          ▶ {song.recording_count}
        </Link>
      ) : (
        <span className="text-rs-muted">{label}</span>
      )}
      <Link
        to={`/profile?song=${song.id}`}
        aria-label={`Add a recording of ${song.title}`}
      >
        +
      </Link>
    </div>
  )
}
