import { useIsPhone } from '../../hooks/useIsPhone'
import { SegmentedControl } from './SegmentedControl'

export type RehearsalContextMode = 'running-order' | 'assignments'

export interface RehearsalContextBarRehearsal {
  id: number
  label: string
  startTime: string
  endTime: string
  songCount: number
  isDressRehearsal: boolean
}

interface RehearsalContextBarProps {
  rehearsal: RehearsalContextBarRehearsal
  mode: RehearsalContextMode
  onModeChange: (mode: RehearsalContextMode, rehearsalId: number) => void
  /** Rendered only in `'assignments'` mode: walks to the previous (-1) or next (1) Rehearsal, skipping the Dress Rehearsal. */
  onStep?: (direction: -1 | 1) => void
}

/** Trims a wire `HH:MM:SS` time string down to `HH:MM` for display. */
function formatClockTime(isoTime: string): string {
  return isoTime.slice(0, 5)
}

/**
 * Return the index the Assignments-mode stepper should land on after stepping
 * `direction` from `currentIndex`, skipping any Dress Rehearsal and wrapping
 * around the list (issue #337 user story 39, consumed by #338).
 *
 * A pure function so both this ticket and #338 can test/reuse the exact
 * same skip-and-wrap rule without either re-deriving it. Returns
 * `currentIndex` unchanged if every entry is the Dress Rehearsal (nothing
 * else to step to) or the list is empty.
 */
export function stepRehearsalIndex(
  rehearsals: { isDressRehearsal: boolean }[],
  currentIndex: number,
  direction: -1 | 1,
): number {
  if (rehearsals.length === 0) return currentIndex
  let index = currentIndex
  for (let step = 0; step < rehearsals.length; step += 1) {
    index = (index + direction + rehearsals.length) % rehearsals.length
    if (!rehearsals[index]?.isDressRehearsal) return index
  }
  return currentIndex
}

/**
 * The shared control above a Rehearsal's Running Order/Assignments
 * (issue #337, consumed unchanged by #338): one component so the way
 * across between the two edit modes is the same control in both
 * directions. Built from `SegmentedControl` (#328's toggle-group
 * primitive) rather than a link — it reads as the mode switch it is.
 *
 * The Dress Rehearsal's Assignments half is disabled with its reason in
 * `title` (ADR 0003: it has no per-song slots to assign against). The
 * two edit modes are mutually exclusive by construction: a caller renders
 * either the Running Order sub-grid or the assignment grid based on
 * `mode`, never both, since a reorder moves start times, which moves
 * which Conflict Windows overlap a slot — exactly the input the loud
 * Fallout tier is computed from (ADR 0009).
 */
export function RehearsalContextBar({
  rehearsal,
  mode,
  onModeChange,
  onStep,
}: RehearsalContextBarProps) {
  const isPhone = useIsPhone()
  const windowLabel = rehearsal.isDressRehearsal
    ? `${formatClockTime(rehearsal.startTime)}–${formatClockTime(rehearsal.endTime)} · Dress`
    : `${formatClockTime(rehearsal.startTime)}–${formatClockTime(rehearsal.endTime)} · ${rehearsal.songCount} song${rehearsal.songCount === 1 ? '' : 's'}`

  return (
    <div
      className={`flex items-center gap-3 border-b border-rs-border py-2 ${isPhone ? 'flex-wrap' : ''}`}
    >
      <div className={isPhone ? 'w-full' : 'flex-1'}>
        <p className="font-medium">{rehearsal.label}</p>
        <p className="text-sm text-rs-muted">{windowLabel}</p>
      </div>
      {mode === 'assignments' && (
        <div className="flex items-center gap-1">
          <button
            type="button"
            aria-label="Previous rehearsal"
            onClick={() => onStep?.(-1)}
            className="rounded border border-rs-border px-2 py-1 text-sm"
          >
            ←
          </button>
          <button
            type="button"
            aria-label="Next rehearsal"
            onClick={() => onStep?.(1)}
            className="rounded border border-rs-border px-2 py-1 text-sm"
          >
            →
          </button>
        </div>
      )}
      <div className={isPhone ? 'w-full' : undefined}>
        <SegmentedControl
          ariaLabel="What to edit for this rehearsal"
          value={mode}
          onChange={(next) =>
            onModeChange(next as RehearsalContextMode, rehearsal.id)
          }
          options={[
            { value: 'running-order', label: 'Running order' },
            {
              value: 'assignments',
              label: 'Assignments',
              disabledReason: rehearsal.isDressRehearsal
                ? 'A Dress Rehearsal has no per-song slots to assign against (ADR 0003).'
                : undefined,
            },
          ]}
        />
      </div>
    </div>
  )
}
