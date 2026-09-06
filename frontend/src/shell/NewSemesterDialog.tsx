import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { apiFetch, ApiError } from '../api/client'
import { useAppContext } from '../api/ContextProvider'
import type { ScheduleEditorPayload } from '../api/scheduleEditorTypes'
import type {
  CreateSemesterBody,
  SemesterTimingDefaults,
} from '../api/semesterTypes'
import type { ReadEnvelope, WriteEnvelope } from '../api/types'
import { Accordion } from '../components/ui/Accordion'
import { ResponsiveDialog } from '../components/ui/ResponsiveDialog'

interface NewSemesterDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

/** A reasonable starting point for a brand-new install with no prior Semester to read timing defaults off of. */
const FALLBACK_TIMING_DEFAULTS: SemesterTimingDefaults = {
  default_rehearsal_duration_minutes: 120,
  default_setup_grace_minutes: 15,
  default_teardown_grace_minutes: 15,
  default_song_slot_count: 3,
  default_arrival_buffer_minutes: 10,
  default_departure_buffer_minutes: 10,
}

const TIMING_FIELDS: Array<{
  key: keyof SemesterTimingDefaults
  label: string
}> = [
  {
    key: 'default_rehearsal_duration_minutes',
    label: 'Rehearsal duration (minutes)',
  },
  { key: 'default_setup_grace_minutes', label: 'Setup grace (minutes)' },
  { key: 'default_teardown_grace_minutes', label: 'Teardown grace (minutes)' },
  { key: 'default_song_slot_count', label: 'Song slot count' },
  { key: 'default_arrival_buffer_minutes', label: 'Arrival buffer (minutes)' },
  {
    key: 'default_departure_buffer_minutes',
    label: 'Departure buffer (minutes)',
  },
]

/**
 * `+ New semester`'s dialog (issue #329): names the new draft Semester,
 * offers a collapsed "Timing defaults" disclosure prefilled from the
 * currently-viewing Semester (the closest reachable stand-in for "the most
 * recent Semester" — no endpoint exposes another Semester's `default_*`
 * fields, only the viewing one's, via `/api/schedule/editor/`), and states
 * what creating it does before the admin commits. `POST`s to
 * `/api/semesters/create/`, which both creates the draft and switches the
 * session's Viewing Semester to it in one call, then navigates to `/` on
 * success (issue #374) so the admin lands on Home's setup checklist for
 * the Semester they just created rather than wherever they opened this
 * dialog from.
 */
export function NewSemesterDialog({
  open,
  onOpenChange,
}: NewSemesterDialogProps) {
  const appContext = useAppContext()
  const navigate = useNavigate()
  const mostRecentNameRef = useRef('')
  useEffect(() => {
    mostRecentNameRef.current = appContext?.semester_options[0]?.name ?? ''
  })

  const [name, setName] = useState('')
  const [nameError, setNameError] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [timingDefaults, setTimingDefaults] = useState<SemesterTimingDefaults>(
    FALLBACK_TIMING_DEFAULTS,
  )
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!open) return
    setName(mostRecentNameRef.current)
    setNameError(null)
    setSubmitError(null)
    void apiFetch<ReadEnvelope<ScheduleEditorPayload>>(
      '/api/schedule/editor/',
    ).then((envelope) => {
      const defaults = envelope.data.semester_defaults
      if (defaults !== null) {
        setTimingDefaults({
          default_rehearsal_duration_minutes:
            defaults.default_rehearsal_duration_minutes,
          default_setup_grace_minutes: defaults.default_setup_grace_minutes,
          default_teardown_grace_minutes:
            defaults.default_teardown_grace_minutes,
          default_song_slot_count: defaults.default_song_slot_count,
          default_arrival_buffer_minutes:
            defaults.default_arrival_buffer_minutes,
          default_departure_buffer_minutes:
            defaults.default_departure_buffer_minutes,
        })
      }
    })
  }, [open])

  const submit = async () => {
    setSubmitting(true)
    setNameError(null)
    setSubmitError(null)
    try {
      const body: CreateSemesterBody = { name, ...timingDefaults }
      const envelope = await apiFetch<WriteEnvelope>('/api/semesters/create/', {
        method: 'POST',
        body: JSON.stringify(body),
      })
      if (!envelope.ok) {
        setNameError(
          envelope.errors.name?.[0] ?? 'Could not create this semester.',
        )
        return
      }
      onOpenChange(false)
      navigate('/')
    } catch (thrown) {
      setSubmitError(
        thrown instanceof ApiError
          ? 'This semester could not be created — check the timing defaults above.'
          : 'Something went wrong.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <ResponsiveDialog
      open={open}
      onOpenChange={onOpenChange}
      title="New semester"
      footer={
        <>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="rounded border border-rs-border px-3 py-1.5 text-sm font-medium hover:bg-rs-border/40"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void submit()}
            disabled={name.trim() === '' || submitting}
            className="rounded bg-rs-accent px-3 py-1.5 text-sm font-medium text-rs-accent-fg disabled:cursor-not-allowed disabled:opacity-50"
          >
            {`Create ${name.trim() === '' ? 'semester' : name}`}
          </button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-sm">
          Name
          <input
            type="text"
            value={name}
            maxLength={255}
            onChange={(event) => setName(event.target.value)}
            className="rounded border border-rs-border px-2 py-1 text-sm"
          />
          {nameError !== null && (
            <span role="alert" className="text-sm text-rs-danger">
              {nameError}
            </span>
          )}
        </label>

        {submitError !== null && (
          <p role="alert" className="text-sm text-rs-danger">
            {submitError}
          </p>
        )}

        <Accordion
          items={[
            {
              key: 'timing-defaults',
              summary: (
                <span className="text-sm font-semibold">Timing defaults</span>
              ),
              content: (
                <div className="grid grid-cols-2 gap-3">
                  {TIMING_FIELDS.map((field) => (
                    <label
                      key={field.key}
                      className="flex flex-col gap-1 text-sm"
                    >
                      {field.label}
                      <input
                        type="number"
                        min={0}
                        step={1}
                        value={timingDefaults[field.key]}
                        onChange={(event) =>
                          setTimingDefaults((previous) => ({
                            ...previous,
                            [field.key]: Math.trunc(
                              Number(event.target.value) || 0,
                            ),
                          }))
                        }
                        className="rounded border border-rs-border px-2 py-1 text-sm"
                      />
                    </label>
                  ))}
                </div>
              ),
            },
          ]}
        />

        <div className="rounded border border-rs-border p-3 text-sm text-rs-muted">
          <h3 className="mb-1 font-semibold text-rs-fg">
            What happens when you create it
          </h3>
          <ul className="list-disc space-y-0.5 pl-4">
            <li>
              A new draft Semester is created — no member sees it until it's
              published.
            </li>
            <li>
              You'll be switched to viewing it, so the next thing you edit lands
              on it.
            </li>
            <li>It starts with no roster, no setlist, and no rehearsals.</li>
          </ul>
        </div>
      </div>
    </ResponsiveDialog>
  )
}
