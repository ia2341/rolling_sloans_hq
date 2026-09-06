import { useState } from 'react'

import { apiFetch } from '../api/client'
import type {
  SemesterDefaultsFallout,
  SemesterDefaultsReapplyBody,
} from '../api/semesterTypes'
import type { WriteEnvelope } from '../api/types'
import { ResponsiveDialog } from '../components/ui/ResponsiveDialog'
import { usePreviewOnOpen } from '../hooks/usePreviewOnOpen'

interface ReapplyDefaultsDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  semesterId: number
  semesterName: string
  semesterUpdatedAt: string
  /** Called after a successful save, before `onOpenChange(false)` — lets a still-open host (e.g. `ManageSemestersSheet`) refetch its own now-stale rows. */
  onSuccess?: () => void
}

/** What `POST /api/semesters/reapply-defaults/preview/` resolves to for `usePreviewOnOpen` (issue #329). */
interface ReapplyPreviewResult {
  ok: boolean
  fallout: SemesterDefaultsFallout | null
  nonFieldErrors: string[]
}

/**
 * The Reapply-defaults popup (issue #329, ADR 0008): the one genuine
 * Preview among the four lifecycle dialogs, modeled on
 * `SaveChangesDialog`'s `usePreviewOnOpen` pattern exactly — it runs the
 * real `apply_semester_defaults_reapply()` and rolls it back on every open,
 * and renders only what the server actually computed. Unlike
 * `SaveChangesDialog`, this surface's Fallout has no `changes` list (it
 * reads its input off the Semester's own `default_*` fields and existing
 * Rehearsals, not a client Buffer), so it calls `usePreviewOnOpen` with its
 * own `SemesterDefaultsFallout`-shaped result rather than `PreviewResult`.
 */
export function ReapplyDefaultsDialog({
  open,
  onOpenChange,
  semesterId,
  semesterName,
  semesterUpdatedAt,
  onSuccess,
}: ReapplyDefaultsDialogProps) {
  const [submitting, setSubmitting] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const preview = async (): Promise<ReapplyPreviewResult> => {
    const body: SemesterDefaultsReapplyBody = {
      semester_id: semesterId,
      semester_updated_at: semesterUpdatedAt,
    }
    const envelope = await apiFetch<
      WriteEnvelope<null, null, SemesterDefaultsFallout>
    >('/api/semesters/reapply-defaults/preview/', {
      method: 'POST',
      body: JSON.stringify(body),
    })
    return {
      ok: envelope.ok,
      fallout: envelope.fallout,
      nonFieldErrors: envelope.non_field_errors,
    }
  }

  const state = usePreviewOnOpen<ReapplyPreviewResult>(open, preview)
  const isLoading = state.status === 'loading' || state.status === 'idle'
  const failedToLoad = state.status === 'error'
  const result = state.status === 'success' ? state.result : null
  const fallout = result?.fallout ?? null
  const confirmDisabled =
    isLoading ||
    result === null ||
    !result.ok ||
    (fallout?.is_blocked ?? false) ||
    submitting

  const confirm = async () => {
    setSubmitting(true)
    setSaveError(null)
    try {
      const body: SemesterDefaultsReapplyBody = {
        semester_id: semesterId,
        semester_updated_at: semesterUpdatedAt,
      }
      const envelope = await apiFetch<WriteEnvelope>(
        '/api/semesters/reapply-defaults/save/',
        {
          method: 'POST',
          body: JSON.stringify(body),
        },
      )
      if (!envelope.ok) {
        setSaveError(
          envelope.non_field_errors.join(' ') || 'Could not reapply defaults.',
        )
        return
      }
      onSuccess?.()
      onOpenChange(false)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <ResponsiveDialog
      open={open}
      onOpenChange={onOpenChange}
      title={`Reapply ${semesterName}'s timing defaults?`}
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
            onClick={() => void confirm()}
            disabled={confirmDisabled}
            className="rounded bg-rs-accent px-3 py-1.5 text-sm font-medium text-rs-accent-fg disabled:cursor-not-allowed disabled:opacity-50"
          >
            Reapply defaults
          </button>
        </>
      }
    >
      <p className="mb-3 text-sm text-rs-muted">
        Computed by running the real save and rolling it back (ADR 0008).
        Nothing has been written.
      </p>

      {isLoading && (
        <div data-testid="reapply-loading" className="animate-pulse space-y-2">
          <div className="h-4 w-3/4 rounded bg-rs-border/60" />
          <div className="h-4 w-1/2 rounded bg-rs-border/60" />
        </div>
      )}

      {failedToLoad && (
        <p role="alert" className="text-sm text-rs-danger">
          Something went wrong computing what this would do.
        </p>
      )}

      {result !== null && !result.ok && (
        <div className="rounded border border-rs-danger/40 bg-rs-danger/5 p-3">
          {result.nonFieldErrors.map((message) => (
            <p key={message} className="text-sm text-rs-danger">
              {message}
            </p>
          ))}
        </div>
      )}

      {fallout !== null && (
        <div className="flex flex-col gap-3 text-sm">
          {fallout.is_blocked ? (
            <p role="alert" className="text-rs-danger">
              {fallout.block_message}
            </p>
          ) : (
            <p>
              This pushes {semesterName}'s current timing defaults onto{' '}
              {fallout.changed_rehearsal_count} upcoming rehearsal
              {fallout.changed_rehearsal_count === 1 ? '' : 's'}.
            </p>
          )}

          {fallout.is_stale && (
            <p className="text-rs-danger">
              The semester's defaults changed since this preview was computed —
              reload and try again.
            </p>
          )}

          {fallout.loud.length > 0 && (
            <div>
              <h4 className="mb-1 font-semibold">
                Needs your attention · {fallout.loud.length}
              </h4>
              <ul className="space-y-1">
                {fallout.loud.map((message) => (
                  <li key={message}>{message}</li>
                ))}
              </ul>
            </div>
          )}

          {fallout.quiet.length > 0 && (
            <div>
              <h4 className="mb-1 font-semibold text-rs-muted">
                Also true · {fallout.quiet.length}
              </h4>
              <ul className="space-y-1 text-rs-muted">
                {fallout.quiet.map((message) => (
                  <li key={message}>{message}</li>
                ))}
              </ul>
            </div>
          )}

          <p className="text-rs-muted">Past rehearsals are untouched.</p>
          <p className="text-rs-muted">
            Hand-raised slot counts are never touched, so a song someone widened
            stays wide.
          </p>

          {saveError !== null && (
            <p role="alert" className="text-rs-danger">
              {saveError}
            </p>
          )}
        </div>
      )}
    </ResponsiveDialog>
  )
}
