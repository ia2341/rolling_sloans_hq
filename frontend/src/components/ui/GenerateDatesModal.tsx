import { useState } from 'react'

import { apiFetch, ApiError } from '../../api/client'
import type {
  GenerationCreateItem,
  RehearsalGenerationDiff,
  RehearsalPatternPayload,
  RehearsalTimeRow,
  SkipDateRow,
} from '../../api/scheduleEditorTypes'
import type { ReadEnvelope, WriteEnvelope } from '../../api/types'
import { ResponsiveDialog } from './ResponsiveDialog'

const DAY_NAMES = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

export interface RetimeApplication {
  rehearsal_id: number
  new_start_time: string
  new_end_time: string
}

interface GenerateDatesModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  pattern: RehearsalPatternPayload | null
  onApply: (ticked: {
    creates: GenerationCreateItem[]
    retimes: RetimeApplication[]
    orphanIds: number[]
  }) => void
}

function blankPattern(): RehearsalPatternPayload {
  const today = new Date().toISOString().slice(0, 10)
  return { start_date: today, end_date: today, rehearsal_times: [], skip_dates: [] }
}

/**
 * `Generate rehearsal dates…`'s staging modal (issue #337, #222): the
 * weekly Rehearsal Pattern, From/Until, Skip Dates, then the four-bucket
 * diff (Create/Keep/Re-time/Orphaned), each item a checkbox. Applying
 * ticked items fills the caller's Pending Buffer (`onApply`) and commits
 * nothing — the modal itself never writes a Rehearsal, only the Pattern
 * (`RehearsalPatternSaveApiView`), which records what was asked for, not
 * what exists.
 *
 * The caller remounts this component (a fresh `key`) each time it opens,
 * so its form/diff state resets by construction rather than by an effect
 * that would call `setState` synchronously on every render.
 */
export function GenerateDatesModal({ open, onOpenChange, pattern, onApply }: GenerateDatesModalProps) {
  const [form, setForm] = useState<RehearsalPatternPayload>(() => pattern ?? blankPattern())
  const [diff, setDiff] = useState<RehearsalGenerationDiff | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [tickedCreates, setTickedCreates] = useState<Set<number>>(new Set())
  const [tickedRetimes, setTickedRetimes] = useState<Set<number>>(new Set())
  const [tickedOrphans, setTickedOrphans] = useState<Set<number>>(new Set())

  const addRehearsalTime = () => {
    setForm((previous) => ({
      ...previous,
      rehearsal_times: [...previous.rehearsal_times, { day_of_week: 1, start_time: '19:00', end_time: '21:00' }],
    }))
  }

  const updateRehearsalTime = (index: number, patch: Partial<RehearsalTimeRow>) => {
    setForm((previous) => ({
      ...previous,
      rehearsal_times: previous.rehearsal_times.map((row, i) => (i === index ? { ...row, ...patch } : row)),
    }))
  }

  const removeRehearsalTime = (index: number) => {
    setForm((previous) => ({
      ...previous,
      rehearsal_times: previous.rehearsal_times.filter((_, i) => i !== index),
    }))
  }

  const addSkipDate = (date: string) => {
    if (date === '') return
    setForm((previous) => ({
      ...previous,
      skip_dates: [...previous.skip_dates, { start_date: date, end_date: null } satisfies SkipDateRow],
    }))
  }

  const removeSkipDate = (index: number) => {
    setForm((previous) => ({ ...previous, skip_dates: previous.skip_dates.filter((_, i) => i !== index) }))
  }

  const runPreviewDiff = async () => {
    setLoading(true)
    setError(null)
    try {
      const saveEnvelope = await apiFetch<WriteEnvelope>('/api/schedule/editor/pattern/save/', {
        method: 'POST',
        body: JSON.stringify(form),
      })
      if (!saveEnvelope.ok) {
        setError(saveEnvelope.non_field_errors.join(' ') || 'Could not save the pattern.')
        return
      }
      const diffEnvelope = await apiFetch<ReadEnvelope<RehearsalGenerationDiff>>(
        '/api/schedule/editor/generate/diff/',
        { method: 'POST', body: JSON.stringify(form) },
      )
      setDiff(diffEnvelope.data)
      setTickedCreates(new Set(diffEnvelope.data.creates.map((_, i) => i)))
      setTickedRetimes(new Set(diffEnvelope.data.retimes.map((r) => r.rehearsal_id)))
      setTickedOrphans(
        new Set(
          diffEnvelope.data.orphans
            .filter((o) => !o.delete_disabled)
            .map((o) => o.rehearsal_id),
        ),
      )
    } catch (thrown) {
      setError(thrown instanceof ApiError ? errorMessageFrom(thrown) : 'Something went wrong computing the diff.')
    } finally {
      setLoading(false)
    }
  }

  const apply = () => {
    if (diff === null) return
    onApply({
      creates: diff.creates.filter((_, i) => tickedCreates.has(i)),
      retimes: diff.retimes
        .filter((r) => tickedRetimes.has(r.rehearsal_id))
        .map((r) => ({ rehearsal_id: r.rehearsal_id, new_start_time: r.new_start_time, new_end_time: r.new_end_time })),
      orphanIds: [...tickedOrphans],
    })
  }

  return (
    <ResponsiveDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Generate rehearsal dates"
      wide
      footer={
        <>
          <button type="button" onClick={() => onOpenChange(false)} className="rounded border border-rs-border px-3 py-1.5 text-sm">
            Cancel
          </button>
          <button
            type="button"
            onClick={apply}
            disabled={diff === null}
            className="rounded bg-rs-accent px-3 py-1.5 text-sm font-medium text-rs-accent-fg disabled:opacity-50"
          >
            Apply ticked to the grid
          </button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="flex gap-3">
          <label className="flex flex-col text-sm">
            From
            <input
              type="date"
              value={form.start_date}
              onChange={(event) => setForm((previous) => ({ ...previous, start_date: event.target.value }))}
            />
          </label>
          <label className="flex flex-col text-sm">
            Until
            <input
              type="date"
              value={form.end_date}
              onChange={(event) => setForm((previous) => ({ ...previous, end_date: event.target.value }))}
            />
          </label>
        </div>

        <div>
          <h3 className="text-sm font-semibold">Weekly times</h3>
          <ul className="flex flex-col gap-1">
            {form.rehearsal_times.map((row, index) => (
              <li key={index} className="flex items-center gap-2 text-sm">
                <select
                  aria-label="Day of week"
                  value={row.day_of_week}
                  onChange={(event) => updateRehearsalTime(index, { day_of_week: Number(event.target.value) })}
                >
                  {DAY_NAMES.map((name, day) => (
                    <option key={day} value={day}>
                      {name}
                    </option>
                  ))}
                </select>
                <input
                  type="time"
                  aria-label="Weekly time start"
                  value={row.start_time}
                  onChange={(event) => updateRehearsalTime(index, { start_time: event.target.value })}
                />
                <input
                  type="time"
                  aria-label="Weekly time end"
                  value={row.end_time}
                  onChange={(event) => updateRehearsalTime(index, { end_time: event.target.value })}
                />
                <button type="button" aria-label="Remove weekly time" onClick={() => removeRehearsalTime(index)}>
                  ×
                </button>
              </li>
            ))}
          </ul>
          <button type="button" onClick={addRehearsalTime} className="text-sm text-rs-accent">
            + Add weekly time
          </button>
        </div>

        <div>
          <h3 className="text-sm font-semibold">Skip dates</h3>
          <ul className="flex flex-wrap gap-2 pb-1">
            {form.skip_dates.map((skip, index) => (
              <li key={index} className="flex items-center gap-1 rounded bg-rs-border/60 px-2 py-0.5 text-sm">
                {skip.start_date}
                <button type="button" aria-label={`Remove skip date ${skip.start_date}`} onClick={() => removeSkipDate(index)}>
                  ×
                </button>
              </li>
            ))}
          </ul>
          <input
            type="date"
            aria-label="Add skip date"
            onChange={(event) => {
              addSkipDate(event.target.value)
              event.target.value = ''
            }}
          />
        </div>

        <button
          type="button"
          onClick={() => void runPreviewDiff()}
          disabled={loading}
          className="self-start rounded bg-rs-accent px-3 py-1.5 text-sm font-medium text-rs-accent-fg disabled:opacity-50"
        >
          Preview
        </button>

        {error !== null && (
          <p role="alert" className="text-sm text-rs-danger">
            {error}
          </p>
        )}

        {diff !== null && (
          <div className="flex flex-col gap-3">
            <h3 className="text-sm font-semibold">What this would do</h3>
            <BucketList
              heading={`Create · ${diff.creates.length}`}
              items={diff.creates.map((item, index) => ({
                key: index,
                label: `${item.date} · ${item.start_time.slice(0, 5)}–${item.end_time.slice(0, 5)}${item.is_dress_rehearsal ? ' · Dress' : ''}`,
                checked: tickedCreates.has(index),
                disabled: false,
                onToggle: () =>
                  setTickedCreates((previous) => toggled(previous, index)),
              }))}
            />
            <div>
              <h4 className="text-sm font-semibold text-rs-muted">Keep · {diff.keeps.length}</h4>
              <ul className="text-sm text-rs-muted">
                {diff.keeps.map((item) => (
                  <li key={item.rehearsal_id}>
                    {item.date} · {item.start_time.slice(0, 5)}–{item.end_time.slice(0, 5)}
                  </li>
                ))}
              </ul>
            </div>
            <BucketList
              heading={`Re-time · ${diff.retimes.length}`}
              items={diff.retimes.map((item) => ({
                key: item.rehearsal_id,
                label: `${item.date}: ${item.old_start_time.slice(0, 5)}–${item.old_end_time.slice(0, 5)} → ${item.new_start_time.slice(0, 5)}–${item.new_end_time.slice(0, 5)} — would lose ${item.song_count} song${item.song_count === 1 ? '' : 's'}, ${item.conflict_count} conflict${item.conflict_count === 1 ? '' : 's'}`,
                checked: tickedRetimes.has(item.rehearsal_id),
                disabled: false,
                onToggle: () => setTickedRetimes((previous) => toggled(previous, item.rehearsal_id)),
              }))}
            />
            <BucketList
              heading={`Orphaned · ${diff.orphans.length}`}
              items={diff.orphans.map((item) => ({
                key: item.rehearsal_id,
                label: item.delete_disabled
                  ? `${item.date} — carries Recordings, remove it by hand from the grid instead`
                  : `${item.date} — would lose ${item.song_count} song${item.song_count === 1 ? '' : 's'}, ${item.conflict_count} conflict${item.conflict_count === 1 ? '' : 's'}, ${item.recording_count} recording${item.recording_count === 1 ? '' : 's'}`,
                checked: tickedOrphans.has(item.rehearsal_id),
                disabled: item.delete_disabled,
                onToggle: () => setTickedOrphans((previous) => toggled(previous, item.rehearsal_id)),
              }))}
            />
          </div>
        )}
      </div>
    </ResponsiveDialog>
  )
}

function toggled(set: Set<number>, key: number): Set<number> {
  const next = new Set(set)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  return next
}

function errorMessageFrom(error: ApiError): string {
  if (error.body !== null && typeof error.body === 'object' && 'error' in error.body) {
    return String((error.body as { error: string }).error)
  }
  return 'Something went wrong computing the diff.'
}

interface BucketItem {
  key: number
  label: string
  checked: boolean
  disabled: boolean
  onToggle: () => void
}

/** One of the generation diff's four buckets: a heading and a checkbox per item (issue #337). */
function BucketList({ heading, items }: { heading: string; items: BucketItem[] }) {
  return (
    <div>
      <h4 className="text-sm font-semibold">{heading}</h4>
      <ul className="flex flex-col gap-1">
        {items.map((item) => (
          <li key={item.key} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              aria-label={item.label}
              checked={item.checked}
              disabled={item.disabled}
              onChange={item.onToggle}
            />
            <span>{item.label}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
