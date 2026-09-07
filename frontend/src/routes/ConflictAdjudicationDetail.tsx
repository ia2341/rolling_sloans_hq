import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { apiFetch, ApiError } from '../api/client'
import { useAppContext } from '../api/ContextProvider'
import type {
  AdjudicationBufferInput,
  AdjudicationFalloutWire,
  ConflictAdjudicationDetailPayload,
  ConflictAdjudicationDetailRow,
  ConflictStatus,
  FeasibilityMap,
} from '../api/conflictAdjudicationTypes'
import type { PreviewResult } from '../api/previewTypes'
import type { ReadEnvelope, WriteEnvelope } from '../api/types'
import { PageHead } from '../components/ui/PageHead'
import { SaveChangesDialog } from '../components/ui/SaveChangesDialog'
import { SegmentedControl } from '../components/ui/SegmentedControl'
import { useIsPhone } from '../hooks/useIsPhone'
import { usePageTitle } from '../shell/PageTitleContext'
import { useRegisterEditSession } from '../shell/EditSessionContext'

/** One row's editable Verdict/Note draft, keyed by `conflict_id` (issue #340). */
interface DraftEntry {
  status: ConflictStatus
  note: string
}

type LoadState =
  | { status: 'loading' }
  | { status: 'not_found' }
  | { status: 'loaded'; payload: ConflictAdjudicationDetailPayload }

/** Formats a wire `HH:MM:SS` time string down to `HH:MM`, or `''` for `null`. */
function formatClockTime(isoTime: string | null): string {
  return isoTime === null ? '' : isoTime.slice(0, 5)
}

/** Builds the initial draft Map from a freshly-loaded payload's rows. */
function draftFromRows(
  rows: ConflictAdjudicationDetailRow[],
): Map<number, DraftEntry> {
  return new Map(
    rows.map((row) => [
      row.conflict_id,
      { status: row.status, note: row.note },
    ]),
  )
}

/** Maps a Conflict's `checked`/`verdict` feasibility onto the chip label issue #340 specifies. */
function feasibilityLabel(
  feasibility: FeasibilityMap[string] | undefined,
): string {
  if (feasibility === undefined || !feasibility.checked) return 'Not checked'
  if (feasibility.verdict === 'feasible') return 'Feasible'
  if (feasibility.verdict === 'infeasible') return 'Infeasible'
  if (feasibility.verdict === 'not_applicable') return 'Not applicable'
  return 'Not checked'
}

const VERDICT_OPTIONS = [
  { value: 'pending', label: 'Pending' },
  { value: 'approved', label: 'Approve' },
  { value: 'rejected', label: 'Reject' },
]

/**
 * `/conflicts/:rehearsalId` (issue #340): the five-column adjudication
 * table for one Rehearsal, fed by one `GET /api/conflicts/<id>/` round
 * trip. Diverges from `ScheduleEdit`'s Buffer→preview→apply template in
 * one deliberate way: changing any row's Verdict fires its own preview
 * fetch immediately (ambient Fallout), rather than waiting for the Save
 * popup to open.
 */
export function ConflictAdjudicationDetail() {
  usePageTitle('Adjudicate conflicts')
  const { rehearsalId } = useParams<{ rehearsalId: string }>()
  const appContext = useAppContext()
  const isPhone = useIsPhone()

  const [state, setState] = useState<LoadState>({ status: 'loading' })
  const [draft, setDraft] = useState<Map<number, DraftEntry>>(new Map())
  const [baseline, setBaseline] = useState<Map<number, DraftEntry>>(new Map())
  const [feasibility, setFeasibility] = useState<FeasibilityMap>({})
  const [ambientFallout, setAmbientFallout] = useState<{
    loud: string[]
    quiet: string[]
  } | null>(null)
  const [saveOpen, setSaveOpen] = useState(false)

  const load = useCallback(() => {
    if (rehearsalId === undefined) return
    void apiFetch<ReadEnvelope<ConflictAdjudicationDetailPayload>>(
      `/api/conflicts/${rehearsalId}/`,
    )
      .then((envelope) => {
        setState({ status: 'loaded', payload: envelope.data })
        setDraft(draftFromRows(envelope.data.rows))
        setBaseline(draftFromRows(envelope.data.rows))
        setFeasibility(envelope.data.feasibility)
        setAmbientFallout(null)
      })
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 404) {
          setState({ status: 'not_found' })
          return
        }
        throw error
      })
  }, [rehearsalId])

  useEffect(() => {
    load()
  }, [load])

  const buildBufferInput = useCallback((): AdjudicationBufferInput | null => {
    if (
      appContext?.viewing_semester === null ||
      appContext?.viewing_semester === undefined
    )
      return null
    return {
      semester_id: appContext.viewing_semester.id,
      semester_updated_at: appContext.viewing_semester.updated_at,
      entries: [...draft.entries()].map(([conflictId, entry]) => ({
        conflict_id: conflictId,
        status: entry.status,
        note: entry.note,
      })),
    }
  }, [appContext, draft])

  const changeCount = useMemo(() => {
    let count = 0
    for (const [conflictId, entry] of draft.entries()) {
      const base = baseline.get(conflictId)
      if (
        base === undefined ||
        base.status !== entry.status ||
        base.note !== entry.note
      )
        count += 1
    }
    return count
  }, [draft, baseline])

  const discard = useCallback(() => {
    setDraft(baseline)
    setAmbientFallout(null)
  }, [baseline])

  const runAmbientPreview = useCallback(
    async (nextDraft: Map<number, DraftEntry>) => {
      if (rehearsalId === undefined) return
      if (
        appContext?.viewing_semester === null ||
        appContext?.viewing_semester === undefined
      )
        return
      const body: AdjudicationBufferInput = {
        semester_id: appContext.viewing_semester.id,
        semester_updated_at: appContext.viewing_semester.updated_at,
        entries: [...nextDraft.entries()].map(([conflictId, entry]) => ({
          conflict_id: conflictId,
          status: entry.status,
          note: entry.note,
        })),
      }
      const envelope = await apiFetch<
        WriteEnvelope<null, unknown, AdjudicationFalloutWire>
      >(`/api/conflicts/${rehearsalId}/preview/`, {
        method: 'POST',
        body: JSON.stringify(body),
      })
      if (!envelope.ok || envelope.fallout === null) return
      setFeasibility(envelope.fallout.feasibility)
      setAmbientFallout({
        loud: envelope.fallout.loud,
        quiet: envelope.fallout.quiet,
      })
    },
    [rehearsalId, appContext],
  )

  const setVerdict = useCallback(
    (conflictId: number, nextStatus: ConflictStatus) => {
      setDraft((previous) => {
        const next = new Map(previous)
        const existing = next.get(conflictId)
        next.set(conflictId, { status: nextStatus, note: existing?.note ?? '' })
        void runAmbientPreview(next)
        return next
      })
    },
    [runAmbientPreview],
  )

  const setNote = useCallback((conflictId: number, note: string) => {
    setDraft((previous) => {
      const next = new Map(previous)
      const existing = next.get(conflictId)
      next.set(conflictId, { status: existing?.status ?? 'pending', note })
      return next
    })
  }, [])

  const computeChanges = useCallback((): PreviewResult['changes'] => {
    if (state.status !== 'loaded') return []
    const changes: PreviewResult['changes'] = []
    for (const row of state.payload.rows) {
      const entry = draft.get(row.conflict_id)
      if (entry === undefined || entry.status === row.status) continue
      changes.push({
        op:
          entry.status === 'approved'
            ? 'Approve'
            : entry.status === 'rejected'
              ? 'Reject'
              : 'Edit',
        object: row.person_name,
        why: `${row.status} → ${entry.status}`,
      })
    }
    return changes
  }, [state, draft])

  const runPreview = useCallback(async (): Promise<PreviewResult> => {
    const body = buildBufferInput()
    if (body === null || rehearsalId === undefined) {
      return {
        ok: false,
        changes: [],
        fallout: { loud: [], quiet: [] },
        nonFieldErrors: ['No Semester is being edited.'],
      }
    }
    const envelope = await apiFetch<
      WriteEnvelope<null, unknown, AdjudicationFalloutWire>
    >(`/api/conflicts/${rehearsalId}/preview/`, {
      method: 'POST',
      body: JSON.stringify(body),
    })
    if (!envelope.ok || envelope.fallout === null) {
      return {
        ok: false,
        changes: [],
        fallout: { loud: [], quiet: [] },
        nonFieldErrors: envelope.non_field_errors,
      }
    }
    if (envelope.fallout.is_blocked) {
      return {
        ok: false,
        changes: [],
        fallout: { loud: [], quiet: [] },
        nonFieldErrors: [envelope.fallout.block_message],
      }
    }
    return {
      ok: true,
      changes: computeChanges(),
      fallout: { loud: envelope.fallout.loud, quiet: envelope.fallout.quiet },
    }
  }, [buildBufferInput, rehearsalId, computeChanges])

  const confirmSave = useCallback(() => {
    const body = buildBufferInput()
    if (body === null || rehearsalId === undefined) return
    void apiFetch<WriteEnvelope>(`/api/conflicts/${rehearsalId}/save/`, {
      method: 'POST',
      body: JSON.stringify(body),
    }).then((envelope) => {
      if (envelope.ok) {
        setSaveOpen(false)
        load()
      }
    })
  }, [buildBufferInput, rehearsalId, load])

  useRegisterEditSession({
    what: 'Conflict verdicts',
    changeCount,
    blockedReason: null,
    discard,
    requestSave: () => setSaveOpen(true),
  })

  if (state.status === 'loading') return null
  if (state.status === 'not_found') {
    return (
      <div>
        <PageHead title="Rehearsal not found" />
        <p className="text-sm text-rs-muted">
          <Link to="/conflicts" className="text-rs-accent">
            ◂ All rehearsals
          </Link>
        </p>
      </div>
    )
  }

  const { payload } = state
  const pendingCount = [...draft.values()].filter(
    (entry) => entry.status === 'pending',
  ).length
  const window =
    payload.end_time !== null
      ? `${formatClockTime(payload.start_time)}–${formatClockTime(payload.end_time)}`
      : formatClockTime(payload.start_time)

  const showFalloutTiers =
    ambientFallout !== null &&
    (ambientFallout.loud.length > 0 || ambientFallout.quiet.length > 0)

  return (
    <div>
      <p className="pb-2 text-sm">
        <Link to="/conflicts" className="text-rs-accent">
          ◂ All rehearsals
        </Link>
      </p>
      <PageHead
        title={`${payload.date} · ${window}`}
        subline={`${pendingCount} pending`}
      />

      {isPhone ? (
        <DetailCards
          rows={payload.rows}
          rehearsalId={payload.rehearsal_id}
          draft={draft}
          feasibility={feasibility}
          onVerdictChange={setVerdict}
          onNoteChange={setNote}
        />
      ) : (
        <DetailTable
          rows={payload.rows}
          rehearsalId={payload.rehearsal_id}
          draft={draft}
          feasibility={feasibility}
          onVerdictChange={setVerdict}
          onNoteChange={setNote}
        />
      )}

      {showFalloutTiers && ambientFallout !== null && (
        <div className="pt-3">
          {ambientFallout.loud.length > 0 && (
            <div className="pb-2">
              <h3 className="text-sm font-semibold">
                Needs your attention · {ambientFallout.loud.length}
              </h3>
              <ul className="space-y-1">
                {ambientFallout.loud.map((message) => (
                  <li key={message} className="text-sm">
                    {message}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {ambientFallout.quiet.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-rs-muted">
                Also true · {ambientFallout.quiet.length}
              </h3>
              <ul className="space-y-1">
                {ambientFallout.quiet.map((message) => (
                  <li key={message} className="text-sm text-rs-muted">
                    {message}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      <SaveChangesDialog
        open={saveOpen}
        onOpenChange={setSaveOpen}
        title={`Save ${changeCount} verdict${changeCount === 1 ? '' : 's'}`}
        preview={runPreview}
        onConfirm={confirmSave}
      />
    </div>
  )
}

interface DetailRowsProps {
  rows: ConflictAdjudicationDetailRow[]
  rehearsalId: number
  draft: Map<number, DraftEntry>
  feasibility: FeasibilityMap
  onVerdictChange: (conflictId: number, status: ConflictStatus) => void
  onNoteChange: (conflictId: number, note: string) => void
}

/** The Admin-only region plus, when applicable, the standing-overlap advisory — shared by both layouts' sub-row. */
function AdminOnlySubRow({
  row,
  rehearsalId,
  draft,
  feasibility,
  onNoteChange,
}: {
  row: ConflictAdjudicationDetailRow
  rehearsalId: number
  draft: DraftEntry
  feasibility: FeasibilityMap[string] | undefined
  onNoteChange: (conflictId: number, note: string) => void
}) {
  const showAdvisory =
    draft.status === 'approved' &&
    feasibility !== undefined &&
    feasibility.has_standing_overlap

  return (
    <div className="flex flex-col gap-3 py-2">
      <section
        aria-label="Admin only"
        className="flex flex-col gap-2 rounded border border-rs-border p-3 sm:flex-row sm:items-start"
      >
        <div className="flex-1">
          <h4 className="text-sm font-semibold">Admin only</h4>
          <p className="pt-1 text-sm">{row.reason}</p>
        </div>
        <label className="flex flex-1 flex-col text-sm">
          Note
          <input
            type="text"
            maxLength={255}
            value={draft.note}
            onChange={(event) =>
              onNoteChange(row.conflict_id, event.target.value)
            }
            className="rounded border border-rs-border px-2 py-1"
          />
        </label>
      </section>

      {showAdvisory && (
        <div className="rounded border border-rs-warning-border bg-rs-warning-bg p-3 text-sm text-rs-warning-fg">
          <p>
            Still assigned <strong>{feasibility?.overlap_role_name}</strong> on{' '}
            <strong>{feasibility?.overlap_song_title}</strong> during this
            window, with no Backup.
          </p>
          <div className="flex gap-3 pt-2">
            <Link
              to={`/schedule?rehearsal=${rehearsalId}`}
              className="text-rs-accent"
            >
              Add a Backup…
            </Link>
            <Link to="/schedule/edit" className="text-rs-accent">
              Re-order the evening
            </Link>
          </div>
        </div>
      )}
    </div>
  )
}

/** The desktop layout: the five-column table, each row followed by its always-visible sub-row. */
function DetailTable({
  rows,
  rehearsalId,
  draft,
  feasibility,
  onVerdictChange,
  onNoteChange,
}: DetailRowsProps) {
  return (
    <table className="w-full text-left text-sm">
      <thead>
        <tr>
          <th className="pb-2">Person</th>
          <th className="pb-2">Declaration</th>
          <th className="pb-2">Declared</th>
          <th className="pb-2">Verdict</th>
          <th className="pb-2">Feasibility</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const entry = draft.get(row.conflict_id) ?? {
            status: row.status,
            note: row.note,
          }
          const rowFeasibility = feasibility[String(row.conflict_id)]
          return (
            <Fragment key={row.conflict_id}>
              <tr>
                <td className="py-2 align-top">{row.person_name}</td>
                <td className="py-2 align-top">{row.type_label}</td>
                <td className="py-2 align-top text-rs-muted">
                  {row.declared_time !== null
                    ? formatClockTime(row.declared_time)
                    : '—'}
                </td>
                <td className="py-2 align-top">
                  <SegmentedControl
                    ariaLabel={`Verdict for ${row.person_name}`}
                    options={VERDICT_OPTIONS}
                    value={entry.status}
                    onChange={(value) =>
                      onVerdictChange(row.conflict_id, value as ConflictStatus)
                    }
                  />
                </td>
                <td className="py-2 align-top">
                  <FeasibilityChip feasibility={rowFeasibility} />
                </td>
              </tr>
              <tr>
                <td colSpan={5} className="pb-4">
                  <AdminOnlySubRow
                    row={row}
                    rehearsalId={rehearsalId}
                    draft={entry}
                    feasibility={rowFeasibility}
                    onNoteChange={onNoteChange}
                  />
                </td>
              </tr>
            </Fragment>
          )
        })}
      </tbody>
    </table>
  )
}

/** The phone layout: verdict-first cards, no horizontally-scrolled table wrapper. */
function DetailCards({
  rows,
  rehearsalId,
  draft,
  feasibility,
  onVerdictChange,
  onNoteChange,
}: DetailRowsProps) {
  return (
    <ul className="flex flex-col gap-3">
      {rows.map((row) => {
        const entry = draft.get(row.conflict_id) ?? {
          status: row.status,
          note: row.note,
        }
        const rowFeasibility = feasibility[String(row.conflict_id)]
        return (
          <li
            key={row.conflict_id}
            className="rounded border border-rs-border p-3"
          >
            <div className="flex items-center justify-between gap-2">
              <p className="font-medium">{row.person_name}</p>
              <FeasibilityChip feasibility={rowFeasibility} />
            </div>
            <p className="pt-1 text-sm text-rs-muted">
              {row.type_label}
              {row.declared_time !== null
                ? ` · ${formatClockTime(row.declared_time)}`
                : ''}
            </p>
            <div className="pt-2">
              <SegmentedControl
                ariaLabel={`Verdict for ${row.person_name}`}
                options={VERDICT_OPTIONS}
                value={entry.status}
                onChange={(value) =>
                  onVerdictChange(row.conflict_id, value as ConflictStatus)
                }
              />
            </div>
            <AdminOnlySubRow
              row={row}
              rehearsalId={rehearsalId}
              draft={entry}
              feasibility={rowFeasibility}
              onNoteChange={onNoteChange}
            />
          </li>
        )
      })}
    </ul>
  )
}

/** The Feasibility column's chip, mapping `checked`+`verdict` onto the four labels issue #340 specifies. */
function FeasibilityChip({
  feasibility,
}: {
  feasibility: FeasibilityMap[string] | undefined
}) {
  const label = feasibilityLabel(feasibility)
  const toneClass =
    label === 'Infeasible'
      ? 'border-rs-danger text-rs-danger'
      : label === 'Feasible'
        ? 'border-rs-accent text-rs-accent'
        : 'border-rs-border text-rs-muted'
  return (
    <span
      className={`inline-block rounded-full border px-2 py-0.5 text-xs font-medium ${toneClass}`}
    >
      {label}
    </span>
  )
}
