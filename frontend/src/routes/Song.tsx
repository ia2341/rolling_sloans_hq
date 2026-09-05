import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { ApiError, apiFetch } from '../api/client'
import { useAppContext } from '../api/ContextProvider'
import type { SongPayload } from '../api/setlistTypes'
import type { ReadEnvelope } from '../api/types'
import { CastLine } from '../components/ui/CastLine'
import { PageHead } from '../components/ui/PageHead'
import { usePageTitle } from '../shell/PageTitleContext'

type LoadState =
  | { status: 'loading' }
  | { status: 'not_found' }
  | { status: 'loaded'; data: SongPayload }

/** Trims a wire `HH:MM:SS` time string down to `HH:MM` for display (issue #330's "date + HH:MM–HH:MM" group header). */
function formatClockTime(isoTime: string): string {
  return isoTime.slice(0, 5)
}

/**
 * `/songs/<pk>/` (issue #330): one Song's read model, fed by one
 * `GET /api/songs/<pk>/` round trip. A Song outside the viewing Semester
 * 404s server-side (ADR 0001); this renders that as an explicit not-found
 * state rather than an error banner.
 */
export function Song() {
  usePageTitle('Song')
  const { songId } = useParams<{ songId: string }>()
  const appContext = useAppContext()
  const [state, setState] = useState<LoadState>({ status: 'loading' })

  useEffect(() => {
    let cancelled = false
    void apiFetch<ReadEnvelope<SongPayload>>(`/api/songs/${songId}/`)
      .then((envelope) => {
        if (!cancelled) setState({ status: 'loaded', data: envelope.data })
      })
      .catch((error: unknown) => {
        if (cancelled) return
        if (error instanceof ApiError && error.status === 404) {
          setState({ status: 'not_found' })
          return
        }
        throw error
      })
    return () => {
      cancelled = true
    }
  }, [songId])

  if (state.status === 'loading') return null
  if (state.status === 'not_found') return <PageHead title="Song not found" />

  const song = state.data
  const positionLine = `${song.artist} · ${song.length} · position ${song.position} in the setlist`

  return (
    <div>
      <PageHead
        title={song.title}
        subline={positionLine}
        action={
          appContext?.viewer.is_admin ? (
            <button
              type="button"
              className="rounded bg-rs-accent px-3 py-1.5 text-sm font-medium text-rs-accent-fg"
            >
              Edit song
            </button>
          ) : undefined
        }
      />
      <Link to="/setlist" className="text-sm text-rs-accent">
        ← Setlist
      </Link>

      <section className="pt-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase text-rs-muted">
            Cast
          </h2>
          <span className="text-xs text-rs-muted">Read-only here</span>
        </div>
        <div className="pt-2">
          <CastLine cast={song.cast} viewerId={appContext?.viewer.id} />
        </div>
        {song.next_rehearsal !== undefined && (
          <div className="mt-3 rounded border border-rs-warning-border bg-rs-warning-bg p-3 text-sm text-rs-warning-fg">
            <p>
              <strong>Casting happens on a rehearsal, not here.</strong> A cell
              edited there changes every rehearsal and the concert (ADR 0009) —
              the availability check that makes it safe is only computable
              through a Rehearsal.
            </p>
            {song.next_rehearsal !== null && (
              <Link
                to={`/schedule?rehearsal=${song.next_rehearsal.id}`}
                className="mt-2 inline-block font-medium text-rs-accent"
              >
                Cast on {song.next_rehearsal.date} →
              </Link>
            )}
          </div>
        )}
      </section>

      {song.notes !== '' && (
        <section className="pt-4">
          <h2 className="text-sm font-semibold uppercase text-rs-muted">
            Notes
          </h2>
          <p className="pt-1 text-sm">{song.notes}</p>
        </section>
      )}

      <section className="pt-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase text-rs-muted">
            Recordings
          </h2>
          <Link
            to={`/profile?song=${song.id}`}
            className="text-sm text-rs-accent"
          >
            + Add a recording
          </Link>
        </div>
        {song.recording_groups.length === 0 ? (
          <p className="pt-2 text-sm text-rs-muted">No recordings yet.</p>
        ) : (
          <ul className="flex flex-col gap-3 pt-2">
            {song.recording_groups.map((group) => (
              <li
                key={group.rehearsal_id}
                className="rounded border border-rs-border p-3"
              >
                <p className="text-sm font-medium">
                  {group.date}
                  {group.start_time !== null && group.end_time !== null
                    ? ` · ${formatClockTime(group.start_time)}–${formatClockTime(group.end_time)}`
                    : ''}{' '}
                  · {group.take_count} take{group.take_count === 1 ? '' : 's'}
                </p>
                <ul className="flex flex-col gap-2 pt-2">
                  {group.recordings.map((recording) => (
                    <li key={recording.id} className="text-sm">
                      <audio
                        controls
                        src={recording.playback_url}
                        className="w-full"
                      />
                      <p className="text-rs-muted">
                        {recording.uploaded_by_name}
                        {recording.note !== '' && ` — ${recording.note}`}
                      </p>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="pt-4">
        <h2 className="text-sm font-semibold uppercase text-rs-muted">
          Rehearsed at
        </h2>
        {song.rehearsed_at.length === 0 ? (
          <p className="pt-2 text-sm text-rs-muted">
            Not scheduled at any rehearsal yet.
          </p>
        ) : (
          <ul className="pt-2 text-sm">
            {song.rehearsed_at.map((row) => (
              <li key={row.rehearsal_id}>
                {row.date}
                {' — '}
                {row.is_dress_rehearsal
                  ? 'whole setlist'
                  : `${row.start_time !== null ? formatClockTime(row.start_time) : ''}–${
                      row.end_time !== null ? formatClockTime(row.end_time) : ''
                    }`}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
