import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { apiFetch, ApiError } from '../api/client'
import { useAppContext } from '../api/ContextProvider'
import { notifyViewingSemesterChanged } from '../api/viewingSemesterChangeStore'
import type {
  CreateSemesterBody,
  SemesterTimingDefaults,
} from '../api/semesterTypes'
import type { WriteEnvelope } from '../api/types'
import { Accordion } from '../components/ui/Accordion'
import { ResponsiveDialog } from '../components/ui/ResponsiveDialog'

interface NewSemesterDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

/** The starting timing defaults offered for every new Semester, regardless of any prior Semester's values. */
const DEFAULT_TIMING_DEFAULTS: SemesterTimingDefaults = {
  default_rehearsal_duration_minutes: 240,
  default_setup_grace_minutes: 10,
  default_teardown_grace_minutes: 10,
  default_song_slot_count: 6,
  default_arrival_buffer_minutes: 5,
  default_departure_buffer_minutes: 5,
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

type TimingDefaultsInputs = Record<keyof SemesterTimingDefaults, string>

/** Renders each timing-defaults field's current numeric value as the string an input shows. */
function toTimingDefaultsInputs(
  defaults: SemesterTimingDefaults,
): TimingDefaultsInputs {
  return {
    default_rehearsal_duration_minutes: String(
      defaults.default_rehearsal_duration_minutes,
    ),
    default_setup_grace_minutes: String(defaults.default_setup_grace_minutes),
    default_teardown_grace_minutes: String(
      defaults.default_teardown_grace_minutes,
    ),
    default_song_slot_count: String(defaults.default_song_slot_count),
    default_arrival_buffer_minutes: String(
      defaults.default_arrival_buffer_minutes,
    ),
    default_departure_buffer_minutes: String(
      defaults.default_departure_buffer_minutes,
    ),
  }
}

/** Parses one timing-defaults input's raw text into a valid non-negative integer, falling back to 0 for empty or invalid text. */
function parseTimingDefaultsInput(raw: string): number {
  return Math.max(0, Math.trunc(Number(raw) || 0))
}

/**
 * `+ New semester`'s dialog (issue #329): names the new draft Semester,
 * offers a "Timing defaults" disclosure (expanded by default — issue #449
 * — since admins commonly want to check or adjust these on creation)
 * prefilled from `DEFAULT_TIMING_DEFAULTS`, deliberately never read from any
 * prior Semester's values, and states what creating it does before the
 * admin commits. `POST`s to
 * `/api/semesters/create/`, which both creates the draft and switches the
 * session's Viewing Semester to it in one call, then navigates to `/` on
 * success (issue #374) so the admin lands on Home's setup checklist for
 * the Semester they just created rather than wherever they opened this
 * dialog from. Also bumps `viewingSemesterChangeStore`'s counter (issue
 * #402): `navigate('/')` is a no-op when this dialog was opened from Home
 * itself, so Home needs its own signal that the Semester underneath it
 * changed.
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
  const [timingDefaultsInputs, setTimingDefaultsInputs] =
    useState<TimingDefaultsInputs>(
      toTimingDefaultsInputs(DEFAULT_TIMING_DEFAULTS),
    )
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!open) return
    setName(mostRecentNameRef.current)
    setNameError(null)
    setSubmitError(null)
    setTimingDefaultsInputs(toTimingDefaultsInputs(DEFAULT_TIMING_DEFAULTS))
  }, [open])

  const submit = async () => {
    setSubmitting(true)
    setNameError(null)
    setSubmitError(null)
    try {
      const timingDefaults: SemesterTimingDefaults = {
        default_rehearsal_duration_minutes: parseTimingDefaultsInput(
          timingDefaultsInputs.default_rehearsal_duration_minutes,
        ),
        default_setup_grace_minutes: parseTimingDefaultsInput(
          timingDefaultsInputs.default_setup_grace_minutes,
        ),
        default_teardown_grace_minutes: parseTimingDefaultsInput(
          timingDefaultsInputs.default_teardown_grace_minutes,
        ),
        default_song_slot_count: parseTimingDefaultsInput(
          timingDefaultsInputs.default_song_slot_count,
        ),
        default_arrival_buffer_minutes: parseTimingDefaultsInput(
          timingDefaultsInputs.default_arrival_buffer_minutes,
        ),
        default_departure_buffer_minutes: parseTimingDefaultsInput(
          timingDefaultsInputs.default_departure_buffer_minutes,
        ),
      }
      setTimingDefaultsInputs(toTimingDefaultsInputs(timingDefaults))
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
      notifyViewingSemesterChanged()
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
          defaultOpenKey="timing-defaults"
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
                        value={timingDefaultsInputs[field.key]}
                        onChange={(event) => {
                          const raw = event.target.value
                          setTimingDefaultsInputs((previous) => ({
                            ...previous,
                            [field.key]: raw,
                          }))
                        }}
                        onBlur={(event) =>
                          setTimingDefaultsInputs((previous) => ({
                            ...previous,
                            [field.key]: String(
                              parseTimingDefaultsInput(event.target.value),
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
            <li>A new draft Semester is created, hidden until published.</li>
            <li>You'll be switched to viewing it, so edits land there.</li>
            <li>It starts with no roster, no setlist, and no rehearsals.</li>
          </ul>
        </div>
      </div>
    </ResponsiveDialog>
  )
}
