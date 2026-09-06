import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { apiFetch } from '../api/client'
import { useAppContext } from '../api/ContextProvider'
import type {
  HomePayload,
  NextRehearsalCard as NextRehearsalCardData,
  SetupChecklist,
  SetupChecklistItem,
  SongProgressRow,
  UpcomingRehearsalRow,
} from '../api/homeTypes'
import type { ReadEnvelope } from '../api/types'
import { PageHead } from '../components/ui/PageHead'
import { Toggle } from '../components/ui/Toggle'
import { useIsPhone } from '../hooks/useIsPhone'
import { formatClockTime, formatRehearsalDate } from '../lib/formatDate'
import { PublishSemesterDialog } from '../shell/PublishSemesterDialog'
import { usePageTitle } from '../shell/PageTitleContext'

/** `localStorage` key for one Semester's dismissed setup-checklist panel (per-viewer, per-device — issue #332). */
function dismissedChecklistKey(semesterId: number): string {
  return `rs-home-checklist-dismissed-${semesterId}`
}

/**
 * `/` (issue #332): Home. One `GET /api/` round trip feeds three
 * member-facing regions -- Next rehearsal, Upcoming rehearsals, Song
 * progress -- plus, for an admin viewing an empty draft Semester, the
 * derived setup checklist that replaced the old four-step wizard.
 */
export function Home() {
  usePageTitle('Home')
  const appContext = useAppContext()
  const [data, setData] = useState<HomePayload | null>(null)
  const [searchParams, setSearchParams] = useSearchParams()
  const mineOnly = searchParams.get('mine') === '1'

  const load = useCallback(() => {
    void apiFetch<ReadEnvelope<HomePayload>>('/api/').then((envelope) =>
      setData(envelope.data),
    )
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const setMineOnly = useCallback(
    (next: boolean) => {
      setSearchParams(
        (previous) => {
          const params = new URLSearchParams(previous)
          if (next) params.set('mine', '1')
          else params.delete('mine')
          return params
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  if (data === null) return null

  const isAdmin = appContext?.viewer.is_admin ?? false
  const subline = isAdmin
    ? data.semester_name !== null
      ? `Editing ${data.semester_name}`
      : undefined
    : (appContext?.live_semester?.name ?? undefined)

  return (
    <div>
      <PageHead title="Home" subline={subline} />

      {data.semester_name === null ? (
        <p className="text-sm text-rs-muted">No Semester published yet.</p>
      ) : (
        <>
          {data.just_created && (
            <JustCreatedStatusCard
              semesterName={data.semester_name}
              liveSemesterName={appContext?.live_semester?.name ?? null}
            />
          )}
          {data.setup_checklist !== null && (
            <SetupChecklistPanel
              checklist={data.setup_checklist}
              onPublished={load}
            />
          )}
          <NextRehearsalSection card={data.next_rehearsal} />
          <UpcomingRehearsalsSection rows={data.upcoming_rehearsals} />
          <SongProgressSection
            songs={data.song_progress}
            mineOnly={mineOnly}
            onMineOnlyChange={setMineOnly}
          />
        </>
      )}
    </div>
  )
}

/** A one-off card shown exactly once, right after an admin creates a Semester: it's now a draft they're editing (issue #332). */
function JustCreatedStatusCard({
  semesterName,
  liveSemesterName,
}: {
  semesterName: string
  liveSemesterName: string | null
}) {
  return (
    <section className="mb-6 rounded border border-dashed border-rs-border p-4 text-sm">
      <p>
        <strong>{semesterName}</strong> created / Draft — You are now editing
        it. The sidebar&apos;s Viewing control names it, and every tab you open
        edits it.
      </p>
      <p className="text-rs-muted">
        Members still see{' '}
        {liveSemesterName !== null ? liveSemesterName : 'the Live Semester'}.
      </p>
    </section>
  )
}

/** Home's Next-rehearsal card: date, arrival/departure line and slot timeline, or the explicit not-needed state (issue #332). */
function NextRehearsalSection({
  card,
}: {
  card: NextRehearsalCardData | null
}) {
  return (
    <section className="pb-6">
      <h2 className="text-sm font-semibold uppercase text-rs-muted">
        Next rehearsal
      </h2>
      {card === null ? (
        <p className="pt-1 text-sm text-rs-muted">
          You are not needed at any upcoming rehearsal.
        </p>
      ) : (
        <div className="pt-1">
          <div className="flex items-center justify-between">
            <p className="text-sm">
              <strong>{formatRehearsalDate(card.date)}</strong>
              {card.is_dress && ' · dress rehearsal'}
            </p>
            <Link
              to={`/schedule?rehearsal=${card.rehearsal_id}`}
              className="rounded bg-rs-accent px-3 py-1.5 text-sm font-medium text-rs-accent-fg"
            >
              Open
            </Link>
          </div>
          <p className="pt-1 text-sm">
            Arrive around <strong>{formatClockTime(card.arrival_time)}</strong>,
            free to leave around{' '}
            <strong>{formatClockTime(card.departure_time)}</strong>
          </p>
          <NextRehearsalTimeline card={card} />
        </div>
      )}
    </section>
  )
}

/** The card's slot picture: a filled bar per Song in the Running Order, or the Dress Rehearsal's whole-window line. */
function NextRehearsalTimeline({ card }: { card: NextRehearsalCardData }) {
  const timeline = card.timeline

  if (timeline.is_dress_rehearsal) {
    return (
      <p className="pt-2 text-sm text-rs-muted">
        Whole setlist, whole window — the dress rehearsal runs the current
        setlist live (ADR 0003).
      </p>
    )
  }

  return (
    <>
      <div
        className="mt-2 flex overflow-hidden rounded border border-rs-border"
        role="img"
        aria-label="Timeline of the next rehearsal's slots"
      >
        {timeline.slots.map((slot) => (
          <Link
            key={slot.song_id}
            to={`/songs/${slot.song_id}`}
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
    </>
  )
}

/** The next four Rehearsals, each naming the viewer's own window (or "not needed"/"Whole window" for the Dress Rehearsal). */
function UpcomingRehearsalsSection({ rows }: { rows: UpcomingRehearsalRow[] }) {
  const isPhone = useIsPhone()
  return (
    <section className="pb-6">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase text-rs-muted">
          Upcoming rehearsals
        </h2>
        <Link to="/schedule?view=all" className="text-sm text-rs-accent">
          All rehearsals →
        </Link>
      </div>
      {rows.length === 0 ? (
        <p className="pt-1 text-sm text-rs-muted">
          No rehearsals scheduled yet this Semester.
        </p>
      ) : isPhone ? (
        <UpcomingRehearsalsCards rows={rows} />
      ) : (
        <UpcomingRehearsalsTable rows={rows} />
      )}
    </section>
  )
}

function UpcomingRehearsalsTable({ rows }: { rows: UpcomingRehearsalRow[] }) {
  return (
    <table className="w-full pt-1 text-left text-sm">
      <thead>
        <tr className="text-xs font-semibold uppercase text-rs-muted">
          <th className="pb-2 font-semibold">Date</th>
          <th className="pb-2 font-semibold">Time</th>
          <th className="pb-2 font-semibold">Your window</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr
            key={row.id}
            className="border-b border-rs-border text-sm last:border-b-0"
          >
            <td className="py-2 align-top">
              <div className="flex items-center gap-2">
                <span>{formatRehearsalDate(row.date)}</span>
                {row.is_dress && (
                  <span className="rounded-full bg-rs-accent px-2 py-0.5 text-xs font-medium text-rs-accent-fg">
                    Dress
                  </span>
                )}
              </div>
            </td>
            <td className="py-2 align-top text-rs-muted">
              {formatClockTime(row.start_time)}–{formatClockTime(row.end_time)}
            </td>
            <td className="py-2 align-top">
              {row.is_dress
                ? 'Whole window'
                : row.your_window !== null
                  ? `${formatClockTime(row.your_window.arrival_time)}–${formatClockTime(row.your_window.departure_time)}`
                  : 'Not needed'}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function UpcomingRehearsalsCards({ rows }: { rows: UpcomingRehearsalRow[] }) {
  return (
    <ul className="pt-1">
      {rows.map((row) => (
        <li
          key={row.id}
          className="flex items-center justify-between border-b border-rs-border py-2 text-sm last:border-b-0"
        >
          <div className="flex items-center gap-2">
            <span>{formatRehearsalDate(row.date)}</span>
            {row.is_dress && (
              <span className="rounded-full bg-rs-accent px-2 py-0.5 text-xs font-medium text-rs-accent-fg">
                Dress
              </span>
            )}
          </div>
          <span className="text-rs-muted">
            {formatClockTime(row.start_time)}–{formatClockTime(row.end_time)}
          </span>
          <span>
            {row.is_dress
              ? 'Whole window'
              : row.your_window !== null
                ? `${formatClockTime(row.your_window.arrival_time)}–${formatClockTime(row.your_window.departure_time)}`
                : 'Not needed'}
          </span>
        </li>
      ))}
    </ul>
  )
}

/** The Setlist with a completed-of-total bar per Song, filterable to the viewer's own via the "My songs only" toggle. */
function SongProgressSection({
  songs,
  mineOnly,
  onMineOnlyChange,
}: {
  songs: SongProgressRow[]
  mineOnly: boolean
  onMineOnlyChange: (next: boolean) => void
}) {
  const isPhone = useIsPhone()
  const visibleSongs = mineOnly
    ? songs.filter((song) => song.has_assignment)
    : songs

  return (
    <section className="pb-6">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase text-rs-muted">
          Song progress
        </h2>
        <label className="flex items-center gap-2 text-sm">
          My songs only
          <Toggle
            pressed={mineOnly}
            onPressedChange={onMineOnlyChange}
            label="My songs only"
          />
        </label>
      </div>
      {songs.length === 0 ? (
        <p className="pt-1 text-sm text-rs-muted">
          No songs yet this Semester.
        </p>
      ) : visibleSongs.length === 0 ? (
        <p className="pt-1 text-sm text-rs-muted">
          You are not on any Song this Semester.
        </p>
      ) : isPhone ? (
        <SongProgressCards songs={visibleSongs} />
      ) : (
        <SongProgressTable songs={visibleSongs} />
      )}
    </section>
  )
}

/** A completed-of-total fill bar, shared by the desktop table and the phone list. */
function ProgressBar({
  completed,
  total,
}: {
  completed: number
  total: number
}) {
  const percent = total === 0 ? 0 : Math.round((completed / total) * 100)
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-rs-border/50">
        <div
          className="h-full rounded-full bg-rs-accent"
          style={{ width: `${percent}%` }}
        />
      </div>
      <span className="text-xs text-rs-muted">
        {completed} of {total}
      </span>
    </div>
  )
}

/** The phone layout: title and `n/total` on one line, `#pos` plus the progress track on the next -- not stacked cards (issue #332). */
function SongProgressCards({ songs }: { songs: SongProgressRow[] }) {
  return (
    <ul className="pt-1">
      {songs.map((song) => (
        <li
          key={song.id}
          className="border-b border-rs-border py-2 text-sm last:border-b-0"
        >
          <div className="flex items-center justify-between">
            <Link to={`/songs/${song.id}`} className="font-medium">
              {song.title}
            </Link>
            <span className="text-rs-muted">
              {song.completed}/{song.total}
            </span>
          </div>
          <div className="flex items-center gap-2 pt-1">
            <span className="text-rs-muted">#{song.position}</span>
            <ProgressBar completed={song.completed} total={song.total} />
          </div>
          {song.notes !== '' && (
            <p className="pt-1 text-xs text-rs-muted">{song.notes}</p>
          )}
          {song.next_rehearsal !== null && (
            <p className="pt-1 text-xs text-rs-muted">
              Next: {formatRehearsalDate(song.next_rehearsal)}
            </p>
          )}
        </li>
      ))}
    </ul>
  )
}

/** The desktop layout: one table row per Song, with position, title, artist, length, progress, notes and next rehearsal. */
function SongProgressTable({ songs }: { songs: SongProgressRow[] }) {
  return (
    <table className="w-full text-left text-sm">
      <thead>
        <tr>
          <th className="pb-2">#</th>
          <th className="pb-2">Song</th>
          <th className="pb-2">Artist</th>
          <th className="pb-2">Length</th>
          <th className="pb-2">Progress</th>
          <th className="pb-2">Notes</th>
          <th className="pb-2">Next rehearsal</th>
        </tr>
      </thead>
      <tbody>
        {songs.map((song) => (
          <tr key={song.id}>
            <td className="py-2 align-top">{song.position}</td>
            <td className="py-2 align-top font-medium">
              <Link to={`/songs/${song.id}`}>{song.title}</Link>
            </td>
            <td className="py-2 align-top text-rs-muted">{song.artist}</td>
            <td className="py-2 align-top">{song.length}</td>
            <td className="py-2 align-top">
              <ProgressBar completed={song.completed} total={song.total} />
            </td>
            <td className="py-2 align-top text-rs-muted">
              {song.notes !== '' ? song.notes : '—'}
            </td>
            <td className="py-2 align-top text-rs-muted">
              {song.next_rehearsal !== null
                ? formatRehearsalDate(song.next_rehearsal)
                : '—'}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/**
 * The derived setup checklist for a draft Semester (issue #332): numbered
 * items, a Publish action opening #329's popup, and a per-viewer,
 * non-destructive Dismiss stored only in `localStorage` -- never on the
 * Semester itself.
 */
function SetupChecklistPanel({
  checklist,
  onPublished,
}: {
  checklist: SetupChecklist
  onPublished: () => void
}) {
  const appContext = useAppContext()
  const viewingSemester = appContext?.viewing_semester ?? null
  const [publishOpen, setPublishOpen] = useState(false)
  const [dismissed, setDismissed] = useState(() =>
    viewingSemester !== null
      ? window.localStorage.getItem(
          dismissedChecklistKey(viewingSemester.id),
        ) === '1'
      : false,
  )

  if (dismissed || viewingSemester === null) return null

  return (
    <section className="mb-6 rounded border border-rs-border p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">
          Setting up {checklist.semester_name}
        </h2>
        <span className="rounded-full border border-dashed border-rs-border px-2 py-0.5 text-xs text-rs-muted">
          Draft
        </span>
      </div>
      <p className="pt-1 text-xs text-rs-muted">
        They are numbered because two of them genuinely wait on the others — but
        nothing is locked, and you can do them in any order, or not at all. Each
        one is just its ordinary tab.
      </p>
      <ul className="pt-2">
        {checklist.items.map((item, index) => (
          <SetupChecklistRow key={item.key} item={item} number={index + 1} />
        ))}
      </ul>
      <div className="flex items-center gap-2 pt-2">
        <button
          type="button"
          onClick={() => setPublishOpen(true)}
          className="rounded bg-rs-accent px-3 py-1.5 text-sm font-medium text-rs-accent-fg"
        >
          Publish {checklist.semester_name}
        </button>
        <button
          type="button"
          onClick={() => {
            window.localStorage.setItem(
              dismissedChecklistKey(viewingSemester.id),
              '1',
            )
            setDismissed(true)
          }}
          className="text-sm text-rs-muted"
        >
          Dismiss this panel
        </button>
      </div>
      <PublishSemesterDialog
        open={publishOpen}
        onOpenChange={setPublishOpen}
        semesterId={viewingSemester.id}
        semesterName={viewingSemester.name}
        onSuccess={onPublished}
      />
    </section>
  )
}

/** One numbered checklist item: its done-checkbox, status line and an always-enabled Open/Review button. */
function SetupChecklistRow({
  item,
  number,
}: {
  item: SetupChecklistItem
  number: number
}) {
  return (
    <li className="flex items-center justify-between border-b border-rs-border py-2 text-sm last:border-b-0">
      <div className="flex items-center gap-2">
        <input type="checkbox" checked={item.is_done} readOnly disabled />
        <div>
          <p>
            {number}. {item.label}
          </p>
          <p className="text-xs text-rs-muted">
            {item.status}
            {!item.is_done &&
              item.waiting_on !== null &&
              ` — ${item.waiting_on}`}
          </p>
        </div>
      </div>
      <Link
        to={item.destination}
        className="shrink-0 rounded border border-rs-border px-3 py-1.5 text-sm"
      >
        {item.is_done ? 'Review' : 'Open'}
      </Link>
    </li>
  )
}
