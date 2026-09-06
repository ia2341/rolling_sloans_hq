import { Link } from 'react-router-dom'

import type { Timeline } from '../../api/scheduleTypes'
import { formatClockTime, formatRehearsalDate } from '../../lib/formatDate'

/** Parses an `HH:MM:SS` (or `HH:MM`) wire time to minutes since midnight, for proportional timeline math. */
function minutesSinceMidnight(isoTime: string): number {
  const [hours = 0, minutes = 0] = isoTime.split(':').map(Number)
  return hours * 60 + minutes
}

/**
 * The one "you at this rehearsal" card Home's "Next rehearsal" section and
 * Schedule's per-Rehearsal detail both render (issue: UI overhaul round 2,
 * item 1) — date, arrival/departure prose, and the slot timeline bar,
 * labeled with both the window's start/end (above the bar, at its ends)
 * and this viewer's own arrival/departure (below the bar, at their tick
 * marks) — the second label is new here; the tick marks used to be
 * unlabeled lines. `heading` is the only thing callers still vary, since
 * Home is describing an upcoming Rehearsal in the abstract ("Next
 * rehearsal") while Schedule is describing the one currently selected
 * ("You at this rehearsal").
 */
export function RehearsalOverview({
  heading,
  date,
  isDress,
  timeline,
}: {
  heading: string
  date: string
  isDress: boolean
  timeline: Timeline
}) {
  return (
    <section className="pb-4">
      <h2 className="text-sm font-semibold uppercase text-rs-muted">
        {heading}
      </h2>
      <p className="pt-1 text-sm">
        <strong>{formatRehearsalDate(date)}</strong>
        {isDress && ' · dress rehearsal'}
      </p>
      {timeline.is_dress_rehearsal ? null : timeline.viewer_song_count === 0 ? (
        <p className="pt-2 text-sm text-rs-muted">
          You are not on any song here.
        </p>
      ) : (
        <>
          <p className="pt-1 text-sm">
            Arrive around{' '}
            <strong>
              {formatClockTime(
                timeline.viewer_start_time ?? timeline.window_start,
              )}
            </strong>
            , free to leave around{' '}
            <strong>
              {formatClockTime(timeline.viewer_end_time ?? timeline.window_end)}
            </strong>
          </p>
          <RehearsalTimelineBar timeline={timeline} />
        </>
      )}
    </section>
  )
}

/** The card's slot picture: a filled, clickable bar per Song in the Running Order, window start/end above it, this viewer's own arrival/departure ticks (labeled) drawn over it. */
function RehearsalTimelineBar({ timeline }: { timeline: Timeline }) {
  const arrivalTime = timeline.viewer_start_time ?? timeline.window_start
  const departureTime = timeline.viewer_end_time ?? timeline.window_end

  // Marker positions are percent-along-the-bar, found by mapping the
  // viewer's own arrival/departure clock times onto the window's span --
  // clamped in case a stale window edge would otherwise push a marker
  // outside the bar (e.g. an arrival right at the window's start).
  const windowStart = minutesSinceMidnight(timeline.window_start)
  const windowEnd = minutesSinceMidnight(timeline.window_end)
  const windowSpan = windowEnd - windowStart
  const percentAlong = (time: string): number => {
    if (windowSpan <= 0) return 0
    const raw = ((minutesSinceMidnight(time) - windowStart) / windowSpan) * 100
    return Math.min(100, Math.max(0, raw))
  }
  const arrivalPercent = percentAlong(arrivalTime)
  const departurePercent = percentAlong(departureTime)

  return (
    <div className="mt-2" data-testid="next-rehearsal-timeline">
      <div className="flex justify-between text-xs text-rs-muted">
        <span>{formatClockTime(timeline.window_start)}</span>
        <span>{formatClockTime(timeline.window_end)}</span>
      </div>
      <div className="relative mt-1">
        <div className="flex overflow-hidden rounded border border-rs-border">
          {timeline.slots.map((slot) => (
            <Link
              key={slot.song_id}
              to={`/songs/${slot.song_id}`}
              onClick={(event) => event.stopPropagation()}
              className={`flex h-10 min-w-0 flex-1 items-center justify-center border-r border-rs-border px-1 text-center text-xs leading-tight last:border-r-0 ${
                slot.is_viewer
                  ? 'bg-rs-accent text-rs-accent-fg'
                  : 'bg-rs-border/30 text-rs-fg'
              }`}
            >
              <span className="line-clamp-2 break-words">
                {slot.song_title}
              </span>
            </Link>
          ))}
        </div>
        {/* Your own arrival/departure ticks, drawn over the bar rather than left to the caption above it. */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 w-0.5 bg-rs-fg"
          style={{ left: `${arrivalPercent}%` }}
        />
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 w-0.5 bg-rs-fg"
          style={{ left: `${departurePercent}%` }}
        />
      </div>
      {/* Text labels for the two ticks above (issue: UI overhaul round 2) -- the window's own start/end already had a label; the viewer's arrival/departure now gets one too. */}
      <div className="relative mt-1 h-8 text-[10px] text-rs-muted">
        <span
          className="absolute max-w-[40%] -translate-x-1/2 text-center leading-tight"
          style={{ left: `${arrivalPercent}%` }}
        >
          Arrival
          <br />
          {formatClockTime(arrivalTime)}
        </span>
        <span
          className="absolute max-w-[40%] -translate-x-1/2 text-center leading-tight"
          style={{ left: `${departurePercent}%` }}
        >
          Departure
          <br />
          {formatClockTime(departureTime)}
        </span>
      </div>
    </div>
  )
}
