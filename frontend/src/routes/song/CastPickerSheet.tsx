import { useEffect, useState } from 'react'

import { apiFetch } from '../../api/client'
import type {
  SongCastConflictEntryWire,
  SongCastPickerOption,
  SongCastPickerPayload,
} from '../../api/setlistTypes'
import type { ReadEnvelope } from '../../api/types'
import { ResponsiveDialog } from '../../components/ui/ResponsiveDialog'
import { formatRehearsalDate } from '../../lib/formatDate'

interface CastPickerSheetProps {
  songId: number
  role: { id: number; name: string }
  /** Person ids already cast on this cell (saved or staged) — filtered out client-side so a staged pick can't be picked twice. */
  excludePersonIds: Set<number>
  onOpenChange: (open: boolean) => void
  onPick: (option: SongCastPickerOption) => void
}

/**
 * The Cast editor's candidate picker (issue #499, ADR 0019): a modal on
 * desktop, a bottom sheet on phone, via `ResponsiveDialog`. Fetched on
 * open from `/api/songs/<pk>/cast/picker/<role_id>/` — one request per
 * opened cell rather than eagerly for every Role on the page, mirroring
 * the Rehearsal grid picker's own fetch-on-open rule.
 *
 * Each candidate carries a conflict-summary badge: a collapsed count of
 * the Song's future Rehearsals they'd miss, expandable to the dates and
 * the declared reason. This is the availability warning ADR 0009 said a
 * per-Song editor structurally couldn't raise, and it is advisory only —
 * picking a conflicted candidate is never blocked, exactly as the
 * per-Rehearsal grid never blocked one.
 */
export function CastPickerSheet({
  songId,
  role,
  excludePersonIds,
  onOpenChange,
  onPick,
}: CastPickerSheetProps) {
  const [payload, setPayload] = useState<SongCastPickerPayload | null>(null)
  const [showAll, setShowAll] = useState(false)

  useEffect(() => {
    let cancelled = false
    void apiFetch<ReadEnvelope<SongCastPickerPayload>>(
      `/api/songs/${songId}/cast/picker/${role.id}/`,
    ).then((envelope) => {
      if (!cancelled) setPayload(envelope.data)
    })
    return () => {
      cancelled = true
    }
  }, [songId, role.id])

  const declared = (payload?.declared ?? []).filter(
    (option) => !excludePersonIds.has(option.person_id),
  )
  const others = (payload?.others ?? []).filter(
    (option) => !excludePersonIds.has(option.person_id),
  )

  return (
    <ResponsiveDialog
      open
      onOpenChange={onOpenChange}
      title={`Cast ${role.name}`}
      wide
    >
      <div className="flex flex-col gap-4">
        <p className="text-xs text-rs-muted">
          A cast change applies to every rehearsal and the concert.
        </p>
        {payload === null ? (
          <p className="text-sm text-rs-muted">Loading…</p>
        ) : (
          <>
            <section>
              <h3 className="text-sm font-semibold">Declared {role.name}</h3>
              {declared.length === 0 ? (
                <p className="pt-1 text-xs text-rs-muted">
                  No one has declared this Role yet.
                </p>
              ) : (
                <ul className="flex flex-col">
                  {declared.map((option) => (
                    <CastPickerRow
                      key={option.person_id}
                      option={option}
                      onPick={() => onPick(option)}
                    />
                  ))}
                </ul>
              )}
            </section>

            {others.length > 0 && (
              <section>
                <button
                  type="button"
                  onClick={() => setShowAll((previous) => !previous)}
                  className="text-xs text-rs-accent"
                >
                  {showAll ? 'Hide' : 'Show all members'}
                </button>
                {showAll && (
                  <ul className="flex flex-col pt-1">
                    {others.map((option) => (
                      <CastPickerRow
                        key={option.person_id}
                        option={option}
                        undeclaredRoleName={role.name}
                        onPick={() => onPick(option)}
                      />
                    ))}
                  </ul>
                )}
              </section>
            )}
          </>
        )}
      </div>
    </ResponsiveDialog>
  )
}

/** One candidate row: their name, an optional "has not declared" note, and the expandable conflict-summary badge. */
function CastPickerRow({
  option,
  undeclaredRoleName,
  onPick,
}: {
  option: SongCastPickerOption
  undeclaredRoleName?: string
  onPick: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const conflictCount = option.conflicts.length

  return (
    <li className="flex flex-col border-b border-rs-border/40 py-1 last:border-b-0">
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={onPick}
          className="flex-1 rounded px-2 py-1 text-left text-sm hover:bg-rs-border/40"
        >
          {option.person_name}
          {undeclaredRoleName !== undefined && (
            <span className="ml-1 text-xs text-rs-muted">
              Has not declared {undeclaredRoleName}
            </span>
          )}
        </button>
        {conflictCount > 0 && (
          <button
            type="button"
            aria-expanded={expanded}
            onClick={() => setExpanded((previous) => !previous)}
            className="shrink-0 rounded-full border border-rs-warning-border px-2 py-0.5 text-xs text-rs-warning-fg"
          >
            {conflictCount} conflict{conflictCount === 1 ? '' : 's'}
          </button>
        )}
      </div>
      {expanded && (
        <ul className="px-2 pb-1 text-xs text-rs-muted">
          {option.conflicts.map((entry) => (
            <li key={entry.rehearsal_id}>{conflictLine(entry)}</li>
          ))}
        </ul>
      )}
    </li>
  )
}

/** Renders one conflict-summary entry as a single line: the Rehearsal's date, how much of it they miss, and their stated reason. */
function conflictLine(entry: SongCastConflictEntryWire): string {
  const scope = entry.is_full_conflict
    ? 'away all evening'
    : "away during this Song's slot"
  const reason = entry.reason === '' ? '' : ` — ${entry.reason}`
  return `${formatRehearsalDate(entry.date)}: ${scope}${reason}`
}
