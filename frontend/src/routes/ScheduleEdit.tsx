import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { apiFetch, ApiError } from '../api/client'
import { useAppContext } from '../api/ContextProvider'
import type {
  DealtRow,
  EditorSetlistSong,
  RehearsalEditBufferInput,
  RehearsalEditRowInput,
  RehearsalEditFalloutPayload,
  RunningOrderRowInput,
  ScheduleEditorLiveStatsPayload,
  ScheduleEditorPayload,
} from '../api/scheduleEditorTypes'
import type { PreviewResult } from '../api/previewTypes'
import type { ReadEnvelope, WriteEnvelope } from '../api/types'
import { AssignmentEditor } from '../components/assignments/AssignmentEditor'
import { GenerateDatesModal } from '../components/ui/GenerateDatesModal'
import { PageHead } from '../components/ui/PageHead'
import {
  RehearsalContextBar,
  stepRehearsalIndex,
  type RehearsalContextMode,
} from '../components/ui/RehearsalContextBar'
import { SaveChangesDialog } from '../components/ui/SaveChangesDialog'
import { usePageTitle } from '../shell/PageTitleContext'
import { useRegisterEditSession } from '../shell/EditSessionContext'

/** One Running Order sub-grid row's editable client-side state (issue #337). */
interface DraftRunningOrderRow {
  key: string
  rehearsalSongId: number | null
  songId: number
  songTitle: string
  slotCount: number
  isPinned: boolean
}

/** One Rehearsal grid row's editable client-side state (issue #337). */
interface DraftRehearsal {
  rowKey: string
  rehearsalId: number | null
  date: string
  startTime: string
  endTime: string | null
  isFullSetlist: boolean
  setupGraceMinutes: number | null
  teardownGraceMinutes: number | null
  arrivalBufferMinutes: number | null
  departureBufferMinutes: number | null
  runningOrder: DraftRunningOrderRow[]
}

/** The subset of `DraftRehearsal` that determines whether a row is dirty, for the "unsaved changes" count and the Re-timed flag. */
interface RehearsalSnapshot {
  date: string
  startTime: string
  endTime: string | null
  runningOrder: { songId: number; slotCount: number }[]
}

/** Small inline icon set for this route's Rehearsal cards — no icon library is vendored (no-CDN, ADR-adjacent), so these are hand-drawn strokes rather than a new dependency. */
function CalendarIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      width={14}
      height={14}
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.3}
    >
      <rect x={1.5} y={2.5} width={13} height={12} rx={1.5} />
      <line x1={1.5} y1={6} x2={14.5} y2={6} />
      <line x1={4.5} y1={1} x2={4.5} y2={4} />
      <line x1={11.5} y1={1} x2={11.5} y2={4} />
    </svg>
  )
}

function ClockIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      width={14}
      height={14}
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.3}
    >
      <circle cx={8} cy={8} r={6.5} />
      <polyline points="8,4.5 8,8 10.5,9.5" />
    </svg>
  )
}

function TrashIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      width={14}
      height={14}
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.3}
    >
      <line x1={2.5} y1={4} x2={13.5} y2={4} />
      <path d="M4.5 4V2.75A1 1 0 0 1 5.5 1.75h5a1 1 0 0 1 1 1V4" />
      <path d="M4.5 4v9a1 1 0 0 0 1 1h5a1 1 0 0 0 1-1V4" />
      <line x1={6.5} y1={7} x2={6.5} y2={11.5} />
      <line x1={9.5} y1={7} x2={9.5} y2={11.5} />
    </svg>
  )
}

/** Formats a wait-time `minutes` value for the live stats panel, or an em dash when nothing has been measured yet. */
function formatMinutes(minutes: number | null): string {
  if (minutes === null) return '—'
  return `${minutes} min`
}

let newRowCounter = 0
/** Returns a fresh client-only row key for a brand-new Rehearsal or Running Order row, never persisted or sent as an id. */
function nextRowKey(prefix: string): string {
  newRowCounter += 1
  return `${prefix}-${newRowCounter}`
}

/** Converts an `EditableRehearsal` read-model row into this route's editable draft shape. */
function toDraftRehearsal(
  rehearsal: ScheduleEditorPayload['rehearsals'][number],
): DraftRehearsal {
  return {
    rowKey: `rehearsal-${rehearsal.id}`,
    rehearsalId: rehearsal.id,
    date: rehearsal.date,
    startTime: rehearsal.start_time.slice(0, 5),
    endTime:
      rehearsal.end_time !== null ? rehearsal.end_time.slice(0, 5) : null,
    isFullSetlist: rehearsal.is_full_setlist,
    setupGraceMinutes: rehearsal.setup_grace_minutes,
    teardownGraceMinutes: rehearsal.teardown_grace_minutes,
    arrivalBufferMinutes: rehearsal.arrival_buffer_minutes,
    departureBufferMinutes: rehearsal.departure_buffer_minutes,
    runningOrder: rehearsal.running_order.map((row) => ({
      key: `rehearsal-song-${row.rehearsal_song_id}`,
      rehearsalSongId: row.rehearsal_song_id,
      songId: row.song_id,
      songTitle: row.song_title,
      slotCount: row.slot_count,
      isPinned: row.is_pinned,
    })),
  }
}

/** Builds a blank new Rehearsal row, defaulted to today, for the "+ Add rehearsal" tool-strip action. */
function newDraftRehearsal(): DraftRehearsal {
  return {
    rowKey: nextRowKey('new-rehearsal'),
    rehearsalId: null,
    date: new Date().toISOString().slice(0, 10),
    startTime: '19:00',
    endTime: null,
    isFullSetlist: false,
    setupGraceMinutes: null,
    teardownGraceMinutes: null,
    arrivalBufferMinutes: null,
    departureBufferMinutes: null,
    runningOrder: [],
  }
}

function snapshotOf(draft: DraftRehearsal): RehearsalSnapshot {
  return {
    date: draft.date,
    startTime: draft.startTime,
    endTime: draft.endTime,
    runningOrder: draft.runningOrder.map((row) => ({
      songId: row.songId,
      slotCount: row.slotCount,
    })),
  }
}

function snapshotsEqual(a: RehearsalSnapshot, b: RehearsalSnapshot): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}

/** Converts one draft row into the Pending Buffer's wire shape (issue #337). */
function toRowInput(draft: DraftRehearsal): RehearsalEditRowInput {
  const runningOrder: RunningOrderRowInput[] = draft.isFullSetlist
    ? []
    : draft.runningOrder.map((row) => ({
        rehearsal_song_id: row.rehearsalSongId,
        song_id: row.songId,
        slot_count: row.slotCount,
      }))
  return {
    row_key: draft.rowKey,
    rehearsal_id: draft.rehearsalId,
    date: draft.date,
    start_time: draft.startTime,
    end_time: draft.endTime,
    is_full_setlist: draft.isFullSetlist,
    setup_grace_minutes: draft.setupGraceMinutes,
    teardown_grace_minutes: draft.teardownGraceMinutes,
    arrival_buffer_minutes: draft.arrivalBufferMinutes,
    departure_buffer_minutes: draft.departureBufferMinutes,
    running_order: runningOrder,
  }
}

/** Maps the server's rehearsal-editor Fallout envelope onto the surface-agnostic `PreviewResult` `SaveChangesDialog` renders (issue #334).
 *
 * The "what changed" list is never computed server-side for this surface
 * (issue #337: "the grid shows what you changed; the popup shows what it
 * costs") — `changes` is built here from the same New/Re-timed/Removing
 * flags the grid itself renders. `is_blocked`/`block_message` is a
 * Validation Error (user story 44), reported as `ok: false` with
 * `nonFieldErrors` so it renders in its own region rather than blending
 * into Fallout.
 */
function toPreviewResult(
  fallout: RehearsalEditFalloutPayload,
  changes: PreviewResult['changes'],
): PreviewResult {
  if (fallout.is_blocked) {
    return {
      ok: false,
      changes: [],
      fallout: { loud: [], quiet: [] },
      nonFieldErrors: [fallout.block_message],
    }
  }
  return {
    ok: true,
    changes,
    fallout: { loud: fallout.loud, quiet: fallout.quiet },
    doomed:
      fallout.doomed_recording_groups.length > 0
        ? {
            heading: 'This deletes Recordings with no undo and no export',
            items: fallout.doomed_recording_groups.map(
              (group) =>
                `${group.label} — ${group.recording_count} recording${group.recording_count === 1 ? '' : 's'} from ${group.uploader_count} member${group.uploader_count === 1 ? '' : 's'}`,
            ),
          }
        : undefined,
  }
}

/** Formats a Rehearsal's New/Re-timed/Removing flags for its card badge, per issue #337 user stories 6-9.
 *
 * Dress is reported separately by the card itself as its own pill (issue:
 * UI overhaul round 2) rather than folded into this list, matching the
 * Dress pill Home's own Upcoming-rehearsals card already renders.
 */
function flagsFor(
  draft: DraftRehearsal,
  baseline: RehearsalSnapshot | undefined,
  isDeleted: boolean,
): string[] {
  const flags: string[] = []
  if (isDeleted) {
    flags.push('Removing')
    return flags
  }
  if (draft.rehearsalId === null) {
    flags.push('New')
  } else if (
    baseline !== undefined &&
    (baseline.startTime !== draft.startTime ||
      baseline.endTime !== draft.endTime)
  ) {
    flags.push(
      `Re-timed [from ${baseline.startTime}–${baseline.endTime ?? '?'}]`,
    )
  }
  return flags
}

/**
 * `/schedule/edit/` (issue #337): the rehearsal schedule editor and its
 * generate-rehearsal-dates staging modal. Fed by one `GET
 * /api/schedule/editor/` round trip; every write (Save, the generation
 * diff, Deal/Shuffle) fills this route's own Pending Buffer client-side
 * and commits nothing until the Save popup's "Save changes" is pressed
 * (ADR 0008). A `?intent=generate-dates` query param (issue #374, from
 * Home's setup checklist) opens the generate-dates modal once the initial
 * read has landed, then strips itself so reloading doesn't repeat it.
 */
export function ScheduleEdit() {
  usePageTitle('Edit schedule')
  const appContext = useAppContext()
  const navigate = useNavigate()

  const [payload, setPayload] = useState<ScheduleEditorPayload | null>(null)
  const [rows, setRows] = useState<DraftRehearsal[]>([])
  const [baselines, setBaselines] = useState<Map<string, RehearsalSnapshot>>(
    new Map(),
  )
  const [deletedIds, setDeletedIds] = useState<Set<number>>(new Set())
  const [openKey, setOpenKey] = useState('')
  const [mode, setMode] = useState<RehearsalContextMode>('running-order')
  const [saveOpen, setSaveOpen] = useState(false)
  const [generateOpen, setGenerateOpen] = useState(false)
  const [generateModalKey, setGenerateModalKey] = useState(0)
  const [dealError, setDealError] = useState<string | null>(null)
  const [liveStats, setLiveStats] =
    useState<ScheduleEditorLiveStatsPayload | null>(null)
  const [liveStatsError, setLiveStatsError] = useState<string | null>(null)
  const [searchParams, setSearchParams] = useSearchParams()
  const handledIntentRef = useRef(false)

  const load = useCallback(() => {
    void apiFetch<ReadEnvelope<ScheduleEditorPayload>>(
      '/api/schedule/editor/',
    ).then((envelope) => {
      setPayload(envelope.data)
      const draftRows = envelope.data.rehearsals.map(toDraftRehearsal)
      setRows(draftRows)
      setBaselines(
        new Map(draftRows.map((row) => [row.rowKey, snapshotOf(row)])),
      )
      setDeletedIds(new Set())
    })
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // `?intent=generate-dates` (issue #374): Home's Rehearsal-pattern
  // checklist row lands here already offering the "Generate rehearsal
  // dates…" modal, exactly as if that button had been clicked. Guarded by
  // a ref so it fires exactly once per mount even though `payload` may
  // update again later.
  useEffect(() => {
    if (payload === null) return
    if (handledIntentRef.current) return
    if (searchParams.get('intent') !== 'generate-dates') return
    handledIntentRef.current = true
    // Deferred a tick (rather than calling these setters inline) so this
    // reads as reacting to an external signal -- the URL -- rather than
    // synchronously cascading renders straight out of the effect body.
    void Promise.resolve().then(() => {
      setGenerateModalKey((previous) => previous + 1)
      setGenerateOpen(true)
      setSearchParams(
        (previous) => {
          const params = new URLSearchParams(previous)
          params.delete('intent')
          return params
        },
        { replace: true },
      )
    })
  }, [payload, searchParams, setSearchParams])

  const isDirty = useCallback(
    (draft: DraftRehearsal): boolean => {
      if (draft.rehearsalId === null) return true
      const baseline = baselines.get(draft.rowKey)
      return (
        baseline === undefined || !snapshotsEqual(baseline, snapshotOf(draft))
      )
    },
    [baselines],
  )

  const changeCount = useMemo(() => {
    const dirtyRows = rows.filter(
      (row) =>
        (row.rehearsalId === null || !deletedIds.has(row.rehearsalId)) &&
        isDirty(row),
    ).length
    return dirtyRows + deletedIds.size
  }, [rows, deletedIds, isDirty])

  // A submitted Buffer that fails validation is reported by the Save
  // popup's preview (`fallout.is_blocked`), not by this session field —
  // this route has no independent "blocked" condition of its own to
  // report before a preview has actually run.
  const blockedReason: string | null = null

  const buildBufferInput = useCallback((): RehearsalEditBufferInput | null => {
    if (
      appContext?.viewing_semester === null ||
      appContext?.viewing_semester === undefined
    )
      return null
    const survivingRows = rows.filter(
      (row) => row.rehearsalId === null || !deletedIds.has(row.rehearsalId),
    )
    return {
      semester_id: appContext.viewing_semester.id,
      semester_updated_at: appContext.viewing_semester.updated_at,
      rows: survivingRows.map(toRowInput),
      deleted_rehearsal_ids: [...deletedIds],
    }
  }, [appContext, rows, deletedIds])

  // The "Randomize Rehearsal Plan" stats panel recomputes live off whatever
  // is actually editable on this page: date/time/dress-flag/running-order
  // edits and row add/delete, all captured by `buildBufferInput()` already
  // (there is no drag-and-drop song-slot editor on this bulk page — that
  // capability lives on the per-Rehearsal Assignments surface instead).
  // Debounced 400ms after the last change to `rows`/`deletedIds` so a
  // fast typist doesn't fire one `/api/schedule/editor/stats/` round trip
  // per keystroke; `runDeal()`'s own `rows` update flows through this same
  // effect, so clicking "Randomize Rehearsal Plan" recomputes the panel
  // for free rather than needing its own separate call.
  useEffect(() => {
    if (payload === null) return undefined
    const timeoutId = window.setTimeout(() => {
      const body = buildBufferInput()
      if (body === null) {
        setLiveStats(null)
        setLiveStatsError(null)
        return
      }
      void apiFetch<WriteEnvelope<ScheduleEditorLiveStatsPayload>>(
        '/api/schedule/editor/stats/',
        { method: 'POST', body: JSON.stringify(body) },
      )
        .then((envelope) => {
          if (envelope.ok && envelope.data !== null) {
            setLiveStats(envelope.data)
            setLiveStatsError(null)
          } else {
            setLiveStatsError(
              envelope.non_field_errors[0] ??
                'Could not compute live stats for this plan.',
            )
          }
        })
        .catch(() => {
          setLiveStatsError('Could not compute live stats for this plan.')
        })
    }, 400)
    return () => window.clearTimeout(timeoutId)
  }, [payload, rows, deletedIds, buildBufferInput])

  const computeChanges = useCallback((): PreviewResult['changes'] => {
    const changes: PreviewResult['changes'] = []
    for (const row of rows) {
      const isDeleted =
        row.rehearsalId !== null && deletedIds.has(row.rehearsalId)
      if (isDeleted) {
        changes.push({ op: 'Delete', object: `Rehearsal on ${row.date}` })
        continue
      }
      if (!isDirty(row)) continue
      if (row.rehearsalId === null) {
        changes.push({ op: 'Add', object: `Rehearsal on ${row.date}` })
      } else {
        changes.push({ op: 'Re-time', object: `Rehearsal on ${row.date}` })
      }
    }
    return changes
  }, [rows, deletedIds, isDirty])

  const discard = useCallback(() => {
    load()
  }, [load])

  const runPreview = useCallback(async (): Promise<PreviewResult> => {
    const body = buildBufferInput()
    if (body === null) {
      return {
        ok: false,
        changes: [],
        fallout: { loud: [], quiet: [] },
        nonFieldErrors: ['No Semester is being edited.'],
      }
    }
    const envelope = await apiFetch<
      WriteEnvelope<null, unknown, RehearsalEditFalloutPayload>
    >('/api/schedule/editor/preview/', {
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
    return toPreviewResult(envelope.fallout, computeChanges())
  }, [buildBufferInput, computeChanges])

  const confirmSave = useCallback(() => {
    const body = buildBufferInput()
    if (body === null) return
    void apiFetch<WriteEnvelope>('/api/schedule/editor/save/', {
      method: 'POST',
      body: JSON.stringify(body),
    }).then((envelope) => {
      if (envelope.ok) {
        setSaveOpen(false)
        load()
      }
    })
  }, [buildBufferInput, load])

  // The two edit modes are exclusive (issue #338, ADR 0009): while a row
  // is parked in 'assignments' mode, this page's own Running Order
  // Buffer session yields the shared toolbar to `AssignmentEditor`'s own
  // `useRegisterEditSession` call by registering nothing at all (`null`)
  // rather than a disabled stub — a stub would still register, and since
  // child effects run before parent effects, it would stomp
  // `AssignmentEditor`'s real registration the instant both mount (see
  // `useRegisterEditSession`'s docstring). Nothing in the Running Order
  // Buffer itself is lost — `rows`/`deletedIds` still carry it — it just
  // isn't what the toolbar shows until `mode` flips back.
  useRegisterEditSession(
    mode === 'assignments'
      ? null
      : {
          what: 'the rehearsal schedule',
          changeCount,
          blockedReason,
          discard,
          requestSave: () => setSaveOpen(true),
        },
  )

  const addRehearsal = useCallback(() => {
    setRows((previous) => [...previous, newDraftRehearsal()])
  }, [])

  const toggleDeleted = useCallback((draft: DraftRehearsal) => {
    if (draft.rehearsalId === null) {
      setRows((previous) =>
        previous.filter((row) => row.rowKey !== draft.rowKey),
      )
      return
    }
    setDeletedIds((previous) => {
      const next = new Set(previous)
      if (draft.rehearsalId === null) return next
      if (next.has(draft.rehearsalId)) next.delete(draft.rehearsalId)
      else next.add(draft.rehearsalId)
      return next
    })
  }, [])

  const updateRow = useCallback(
    (rowKey: string, patch: Partial<DraftRehearsal>) => {
      setRows((previous) =>
        previous.map((row) =>
          row.rowKey === rowKey ? { ...row, ...patch } : row,
        ),
      )
    },
    [],
  )

  const moveRunningOrderRow = useCallback(
    (rowKey: string, index: number, direction: -1 | 1) => {
      setRows((previous) =>
        previous.map((row) => {
          if (row.rowKey !== rowKey) return row
          const target = index + direction
          if (target < 0 || target >= row.runningOrder.length) return row
          const next = [...row.runningOrder]
          const a = next[index]
          const b = next[target]
          if (a === undefined || b === undefined) return row
          next[index] = b
          next[target] = a
          return { ...row, runningOrder: next }
        }),
      )
    },
    [],
  )

  const addSongToRow = useCallback(
    (rowKey: string, song: EditorSetlistSong) => {
      setRows((previous) =>
        previous.map((row) =>
          row.rowKey === rowKey
            ? {
                ...row,
                runningOrder: [
                  ...row.runningOrder,
                  {
                    key: nextRowKey('new-running-order'),
                    rehearsalSongId: null,
                    songId: song.id,
                    songTitle: song.title,
                    slotCount: 1,
                    isPinned: false,
                  },
                ],
              }
            : row,
        ),
      )
    },
    [],
  )

  const removeRunningOrderRow = useCallback((rowKey: string, key: string) => {
    setRows((previous) =>
      previous.map((row) =>
        row.rowKey === rowKey
          ? {
              ...row,
              runningOrder: row.runningOrder.filter((r) => r.key !== key),
            }
          : row,
      ),
    )
  }, [])

  const setSlotCount = useCallback(
    (rowKey: string, key: string, slotCount: number) => {
      setRows((previous) =>
        previous.map((row) =>
          row.rowKey === rowKey
            ? {
                ...row,
                runningOrder: row.runningOrder.map((r) =>
                  r.key === key ? { ...r, slotCount } : r,
                ),
              }
            : row,
        ),
      )
    },
    [],
  )

  const applyDealtRows = useCallback(
    (dealtByRehearsalId: Map<number, DealtRow[]>) => {
      setRows((previous) =>
        previous.map((row) => {
          if (row.rehearsalId === null) return row
          const dealt = dealtByRehearsalId.get(row.rehearsalId)
          if (dealt === undefined) return row
          return {
            ...row,
            runningOrder: dealt.map((dealtRow) => {
              const existing = row.runningOrder.find(
                (r) =>
                  r.rehearsalSongId !== null &&
                  r.rehearsalSongId === dealtRow.rehearsal_song_id,
              )
              const song = payload?.setlist_songs.find(
                (s) => s.id === dealtRow.song_id,
              )
              return {
                key: existing?.key ?? nextRowKey('dealt-running-order'),
                rehearsalSongId: dealtRow.rehearsal_song_id,
                songId: dealtRow.song_id,
                songTitle: existing?.songTitle ?? song?.title ?? '',
                slotCount: dealtRow.slot_count,
                isPinned: existing?.isPinned ?? false,
              }
            }),
          }
        }),
      )
    },
    [payload],
  )

  const runDeal = useCallback(async () => {
    setDealError(null)
    try {
      const envelope = await apiFetch<
        ReadEnvelope<{
          rehearsals: { rehearsal_id: number; rows: DealtRow[] }[]
        }>
      >('/api/schedule/editor/deal/', { method: 'POST' })
      const byId = new Map(
        envelope.data.rehearsals.map((r) => [r.rehearsal_id, r.rows]),
      )
      applyDealtRows(byId)
    } catch (error) {
      if (
        error instanceof ApiError &&
        error.body &&
        typeof error.body === 'object' &&
        'error' in error.body
      ) {
        setDealError(String((error.body as { error: string }).error))
      } else {
        setDealError('Something went wrong dealing the schedule.')
      }
    }
  }, [applyDealtRows])

  if (payload === null) return null

  const activeRows = rows.filter(
    (row) => row.rehearsalId === null || !deletedIds.has(row.rehearsalId),
  )
  const removedRows = rows.filter(
    (row) => row.rehearsalId !== null && deletedIds.has(row.rehearsalId),
  )

  // The Assignments stepper (issue #338 user stories 27-28) walks only
  // persisted Rehearsals, skipping the Dress Rehearsal and wrapping,
  // mirroring `stepRehearsalIndex()`'s contract. A brand-new, unsaved row
  // has no id to fetch an Assignments surface against, so it never
  // appears in this list at all.
  const steppableRows = activeRows.filter((row) => row.rehearsalId !== null)
  const stepAssignmentRehearsal = (direction: -1 | 1) => {
    const currentIndex = steppableRows.findIndex(
      (row) => row.rowKey === openKey,
    )
    if (currentIndex === -1) return
    const nextIndex = stepRehearsalIndex(
      steppableRows.map((row) => ({ isDressRehearsal: row.isFullSetlist })),
      currentIndex,
      direction,
    )
    const nextRow = steppableRows[nextIndex]
    if (nextRow !== undefined) setOpenKey(nextRow.rowKey)
  }

  return (
    <div>
      <PageHead
        title="Edit schedule"
        subline={
          payload.semester_name !== null ? payload.semester_name : undefined
        }
        backTo="/schedule"
        backLabel="Schedule"
      />

      <div className="flex flex-col gap-2">
        {[...activeRows, ...removedRows].map((row) => {
          const isDeleted =
            row.rehearsalId !== null && deletedIds.has(row.rehearsalId)
          const flags = flagsFor(row, baselines.get(row.rowKey), isDeleted)
          const isOpen = openKey === row.rowKey
          const canNavigate = row.rehearsalId !== null
          const stop = (event: { stopPropagation: () => void }) =>
            event.stopPropagation()
          return (
            <Fragment key={row.rowKey}>
              <div
                role={canNavigate ? 'link' : undefined}
                tabIndex={canNavigate ? 0 : undefined}
                onClick={() => {
                  if (canNavigate)
                    navigate(`/schedule?rehearsal=${row.rehearsalId}`)
                }}
                onKeyDown={(event) => {
                  if (
                    canNavigate &&
                    (event.key === 'Enter' || event.key === ' ')
                  ) {
                    event.preventDefault()
                    navigate(`/schedule?rehearsal=${row.rehearsalId}`)
                  }
                }}
                className={`flex flex-wrap items-center gap-3 rounded border border-rs-border p-3 ${
                  isDeleted ? 'opacity-60' : ''
                } ${
                  canNavigate
                    ? 'cursor-pointer hover:bg-rs-border/20 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-rs-accent'
                    : ''
                }`}
              >
                <button
                  type="button"
                  aria-label={
                    isOpen ? `Collapse ${row.date}` : `Expand ${row.date}`
                  }
                  onClick={(event) => {
                    stop(event)
                    setOpenKey(isOpen ? '' : row.rowKey)
                  }}
                >
                  {isOpen ? '▾' : '▸'}
                </button>

                <label
                  className="flex items-center gap-1 text-sm"
                  onClick={stop}
                >
                  <CalendarIcon />
                  <input
                    type="date"
                    aria-label="Date"
                    value={row.date}
                    disabled={isDeleted}
                    onChange={(event) =>
                      updateRow(row.rowKey, { date: event.target.value })
                    }
                  />
                </label>

                <label
                  className="flex items-center gap-1 text-sm"
                  onClick={stop}
                >
                  <ClockIcon />
                  <input
                    type="time"
                    aria-label="Start time"
                    value={row.startTime}
                    disabled={isDeleted}
                    onChange={(event) =>
                      updateRow(row.rowKey, {
                        startTime: event.target.value,
                      })
                    }
                  />
                </label>
                <span>–</span>
                <label
                  className="flex items-center gap-1 text-sm"
                  onClick={stop}
                >
                  <ClockIcon />
                  <input
                    type="time"
                    aria-label="End time"
                    value={row.endTime ?? ''}
                    disabled={isDeleted}
                    onChange={(event) =>
                      updateRow(row.rowKey, {
                        endTime:
                          event.target.value === '' ? null : event.target.value,
                      })
                    }
                  />
                </label>

                {row.isFullSetlist && (
                  <span className="rounded-full bg-rs-accent px-2 py-0.5 text-xs font-medium text-rs-accent-fg">
                    Dress
                  </span>
                )}
                {flags.map((flag) => (
                  <span
                    key={flag}
                    className="rounded bg-rs-border/60 px-1.5 py-0.5 text-xs"
                  >
                    {flag}
                  </span>
                ))}

                <span className="text-sm text-rs-muted">
                  {row.runningOrder.length} song
                  {row.runningOrder.length === 1 ? '' : 's'}
                </span>

                <button
                  type="button"
                  aria-label={
                    isDeleted
                      ? `Restore rehearsal on ${row.date}`
                      : `Delete rehearsal on ${row.date}`
                  }
                  onClick={(event) => {
                    stop(event)
                    toggleDeleted(row)
                  }}
                  className="ml-auto flex items-center gap-1 text-sm text-rs-muted hover:text-rs-danger"
                >
                  {isDeleted ? 'Restore' : <TrashIcon />}
                </button>
              </div>
              {isOpen && (
                <div
                  className="rounded border border-rs-border p-3"
                  onClick={stop}
                >
                  <RehearsalRowEditor
                    draft={row}
                    mode={mode}
                    onModeChange={setMode}
                    setlistSongs={payload.setlist_songs}
                    onMove={(index, direction) =>
                      moveRunningOrderRow(row.rowKey, index, direction)
                    }
                    onAddSong={(song) => addSongToRow(row.rowKey, song)}
                    onRemoveSong={(key) =>
                      removeRunningOrderRow(row.rowKey, key)
                    }
                    onSlotCountChange={(key, slotCount) =>
                      setSlotCount(row.rowKey, key, slotCount)
                    }
                    onStep={stepAssignmentRehearsal}
                  />
                </div>
              )}
            </Fragment>
          )
        })}
      </div>

      <ScheduleEditorStatsPanel stats={liveStats} error={liveStatsError} />

      <div className="flex flex-wrap items-center gap-2 py-4">
        <button
          type="button"
          onClick={addRehearsal}
          className="rounded border border-rs-border px-3 py-1.5 text-sm font-medium"
        >
          + Add rehearsal
        </button>
        <button
          type="button"
          onClick={() => {
            setGenerateModalKey((previous) => previous + 1)
            setGenerateOpen(true)
          }}
          className="rounded border border-rs-border px-3 py-1.5 text-sm font-medium"
        >
          Generate rehearsal dates…
        </button>
        <div className="ml-auto flex gap-2">
          <button
            type="button"
            onClick={() => void runDeal()}
            className="rounded border border-rs-border px-3 py-1.5 text-sm font-medium"
          >
            Randomize Rehearsal Plan
          </button>
        </div>
      </div>
      {dealError !== null && (
        <p role="alert" className="pb-4 text-sm text-rs-danger">
          {dealError}
        </p>
      )}

      {payload.past_rehearsals.length > 0 && (
        <details className="pt-4">
          <summary className="cursor-pointer text-sm font-medium text-rs-muted">
            Past rehearsals — not editable
          </summary>
          <p className="pt-2 text-sm text-rs-muted">
            Generation never rewrites history, and the dealer never re-deals a
            past Rehearsal.
          </p>
          <ul className="pt-2">
            {payload.past_rehearsals.map((past) => (
              <li key={past.id} className="text-sm text-rs-muted">
                {past.date} · {past.start_time.slice(0, 5)}
                {past.end_time !== null
                  ? `–${past.end_time.slice(0, 5)}`
                  : ''}{' '}
                · {past.song_count} song
                {past.song_count === 1 ? '' : 's'}
              </li>
            ))}
          </ul>
        </details>
      )}

      <SaveChangesDialog
        open={saveOpen}
        onOpenChange={setSaveOpen}
        title={`Save ${changeCount} change${changeCount === 1 ? '' : 's'} to the rehearsal schedule?`}
        preview={runPreview}
        onConfirm={confirmSave}
      />

      <GenerateDatesModal
        key={generateModalKey}
        open={generateOpen}
        onOpenChange={setGenerateOpen}
        pattern={payload.pattern}
        onApply={({ creates, retimes, orphanIds }) => {
          setRows((previous) => {
            const retimesById = new Map(retimes.map((r) => [r.rehearsal_id, r]))
            const withoutOrphans = previous.filter(
              (row) =>
                row.rehearsalId === null ||
                !orphanIds.includes(row.rehearsalId),
            )
            const retimed = withoutOrphans.map((row) => {
              const retime =
                row.rehearsalId !== null
                  ? retimesById.get(row.rehearsalId)
                  : undefined
              if (retime === undefined) return row
              return {
                ...row,
                startTime: retime.new_start_time.slice(0, 5),
                endTime: retime.new_end_time.slice(0, 5),
              }
            })
            const created: DraftRehearsal[] = creates.map((create) => ({
              rowKey: nextRowKey('generated-rehearsal'),
              rehearsalId: null,
              date: create.date,
              startTime: create.start_time.slice(0, 5),
              endTime: create.end_time.slice(0, 5),
              isFullSetlist: create.is_dress_rehearsal,
              setupGraceMinutes: null,
              teardownGraceMinutes: null,
              arrivalBufferMinutes: null,
              departureBufferMinutes: null,
              runningOrder: [],
            }))
            return [...retimed, ...created]
          })
          setDeletedIds((previous) => new Set([...previous, ...orphanIds]))
          setGenerateOpen(false)
        }}
      />
    </div>
  )
}

/** The "Randomize Rehearsal Plan" live stats panel: unresolved Conflicts, old-vs-new max wait, and busiest/quietest Songs.
 *
 * Recomputed by the debounced effect in `ScheduleEdit()` off whatever is
 * actually editable on this page — reads `stats`/`error` rather than
 * fetching anything itself, so it stays a plain render of whatever the
 * parent's Buffer currently produces server-side (ADR 0008: the real
 * `compute_schedule_editor_live_stats()`, rolled back).
 */
function ScheduleEditorStatsPanel({
  stats,
  error,
}: {
  stats: ScheduleEditorLiveStatsPayload | null
  error: string | null
}) {
  if (error !== null) {
    return (
      <p role="alert" className="mb-4 text-sm text-rs-danger">
        {error}
      </p>
    )
  }
  if (stats === null) return null

  return (
    <div className="mb-4 grid grid-cols-1 gap-3 rounded border border-rs-border p-3 text-sm sm:grid-cols-3">
      <div>
        <p className="font-medium">Unresolved conflicts</p>
        <p className="text-rs-muted">
          {stats.unresolved_conflict_count} assignment
          {stats.unresolved_conflict_count === 1 ? '' : 's'} overlapping a
          declared Conflict
        </p>
      </div>
      <div>
        <p className="font-medium">Longest wait at a Rehearsal</p>
        <p className="text-rs-muted">
          {formatMinutes(stats.old_max_wait_minutes)} →{' '}
          {formatMinutes(stats.new_max_wait_minutes)}
        </p>
      </div>
      <div>
        <p className="font-medium">Busiest / quietest Songs</p>
        <p className="text-rs-muted">
          {stats.highest_slot_songs.length === 0
            ? 'No Songs dealt yet'
            : stats.highest_slot_songs
                .map((song) => `${song.song_title} (${song.total_slot_count})`)
                .join(', ')}
        </p>
        {stats.lowest_slot_songs.length > 0 && (
          <p className="text-rs-muted">
            {stats.lowest_slot_songs
              .map((song) => `${song.song_title} (${song.total_slot_count})`)
              .join(', ')}
          </p>
        )}
      </div>
    </div>
  )
}

interface RehearsalRowEditorProps {
  draft: DraftRehearsal
  mode: RehearsalContextMode
  onModeChange: (mode: RehearsalContextMode) => void
  setlistSongs: EditorSetlistSong[]
  onMove: (index: number, direction: -1 | 1) => void
  onAddSong: (song: EditorSetlistSong) => void
  onRemoveSong: (key: string) => void
  onSlotCountChange: (key: string, slotCount: number) => void
  onStep: (direction: -1 | 1) => void
}

/** The expanded content below a Rehearsal card: its Running Order sub-grid, or the Assignments surface (issue #337, #338).
 *
 * Date/Start/End are no longer rendered here (issue: UI overhaul round
 * 2) — they moved onto the card header itself, as an actual date/time
 * picker rather than plain text, so this content is Running-Order/
 * Assignments only.
 */
function RehearsalRowEditor({
  draft,
  mode,
  onModeChange,
  setlistSongs,
  onMove,
  onAddSong,
  onRemoveSong,
  onSlotCountChange,
  onStep,
}: RehearsalRowEditorProps) {
  const contextBarRehearsal = {
    id: draft.rehearsalId ?? 0,
    label: draft.date,
    startTime: `${draft.startTime}:00`,
    endTime: `${draft.endTime ?? draft.startTime}:00`,
    songCount: draft.runningOrder.length,
    isDressRehearsal: draft.isFullSetlist,
  }

  const availableSongs = setlistSongs.filter(
    (song) => !draft.runningOrder.some((row) => row.songId === song.id),
  )

  return (
    <div className="flex flex-col gap-3 py-2">
      {draft.isFullSetlist ? null : (
        <>
          <RehearsalContextBar
            rehearsal={contextBarRehearsal}
            mode={mode}
            onModeChange={onModeChange}
            onStep={onStep}
          />
          {mode === 'assignments' ? (
            draft.rehearsalId === null ? (
              <p className="text-sm text-rs-muted">
                Save this new Rehearsal before casting it — there's nothing to
                assign against yet.
              </p>
            ) : (
              <AssignmentEditor
                rehearsalId={draft.rehearsalId}
                onDone={() => onModeChange('running-order')}
              />
            )
          ) : (
            <div className="flex flex-col gap-2">
              <ul className="flex flex-col gap-1">
                {draft.runningOrder.map((row, index) => (
                  <li key={row.key} className="flex items-center gap-2 text-sm">
                    <span className="flex-1">{row.songTitle}</span>
                    <span>slots:</span>
                    <input
                      type="number"
                      aria-label={`${row.songTitle} slot count`}
                      min={1}
                      value={row.slotCount}
                      onChange={(event) =>
                        onSlotCountChange(
                          row.key,
                          Number(event.target.value) || 1,
                        )
                      }
                      className="w-12"
                    />
                    {row.isPinned && (
                      <span className="rounded bg-rs-border/60 px-1.5 py-0.5 text-xs">
                        Pinned
                      </span>
                    )}
                    <button
                      type="button"
                      aria-label={`Move ${row.songTitle} up`}
                      disabled={index === 0}
                      onClick={() => onMove(index, -1)}
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      aria-label={`Move ${row.songTitle} down`}
                      disabled={index === draft.runningOrder.length - 1}
                      onClick={() => onMove(index, 1)}
                    >
                      ↓
                    </button>
                    <button
                      type="button"
                      aria-label={`Remove ${row.songTitle}`}
                      onClick={() => onRemoveSong(row.key)}
                    >
                      ×
                    </button>
                  </li>
                ))}
              </ul>
              <div className="flex items-center gap-2">
                <select
                  aria-label="Add a song"
                  defaultValue=""
                  onChange={(event) => {
                    const song = availableSongs.find(
                      (s) => String(s.id) === event.target.value,
                    )
                    if (song !== undefined) onAddSong(song)
                    event.target.value = ''
                  }}
                >
                  <option value="" disabled>
                    + Add song
                  </option>
                  {availableSongs.map((song) => (
                    <option key={song.id} value={song.id}>
                      {song.title}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
