import { useState } from 'react'

import { apiFetch } from '../api/client'
import type { SemesterPublishImpact } from '../api/semesterTypes'
import type { ReadEnvelope, WriteEnvelope } from '../api/types'
import { ResponsiveDialog } from '../components/ui/ResponsiveDialog'
import { usePreviewOnOpen } from '../hooks/usePreviewOnOpen'

interface PublishSemesterDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  semesterId: number
  semesterName: string
}

/**
 * The Publish/Re-publish popup (issue #329): a pure read, unlike the
 * Reapply-defaults popup — it fetches `/api/semesters/<id>/publish-impact/`
 * on open and renders it directly, with no ADR-0008 preview/rollback
 * machinery, since publishing has nothing to roll back a computation
 * through (it's a single timestamp stamp, per ADR 0010). Reachable both
 * from the sidebar/top-bar Publish button (always the viewing Semester,
 * always a draft) and from the Manage-semesters sheet's per-row
 * Publish/Re-publish button (any Semester, including the already-live
 * one, for a harmless re-stamp).
 */
export function PublishSemesterDialog({
  open,
  onOpenChange,
  semesterId,
  semesterName,
}: PublishSemesterDialogProps) {
  const [submitting, setSubmitting] = useState(false)

  const state = usePreviewOnOpen<SemesterPublishImpact>(open, async () => {
    const envelope = await apiFetch<ReadEnvelope<SemesterPublishImpact>>(
      `/api/semesters/${semesterId}/publish-impact/`,
    )
    return envelope.data
  })
  const impact = state.status === 'success' ? state.result : null

  const confirm = async () => {
    setSubmitting(true)
    try {
      await apiFetch<WriteEnvelope>(`/api/semesters/${semesterId}/publish/`, {
        method: 'POST',
      })
      onOpenChange(false)
    } finally {
      setSubmitting(false)
    }
  }

  const title = impact?.is_already_live
    ? `Re-publish ${semesterName}?`
    : `Publish ${semesterName}?`

  return (
    <ResponsiveDialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
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
            disabled={impact === null || submitting}
            className="rounded bg-rs-accent px-3 py-1.5 text-sm font-medium text-rs-accent-fg disabled:cursor-not-allowed disabled:opacity-50"
          >
            {`Publish ${semesterName}`}
          </button>
        </>
      }
    >
      {state.status === 'error' && (
        <p role="alert" className="text-sm text-rs-danger">
          Something went wrong loading what publishing this would do.
        </p>
      )}
      {impact === null && state.status !== 'error' && (
        <p className="text-sm text-rs-muted">Loading…</p>
      )}

      {impact !== null && (
        <div className="flex flex-col gap-3 text-sm">
          {impact.is_already_live && (
            <p>
              {semesterName} is already what members see — re-stamping it is
              harmless.
            </p>
          )}

          {!impact.is_already_live && impact.incumbent !== null && (
            <>
              <p>
                This will make {impact.target_semester_name} what every member
                sees immediately, and stop showing them {impact.incumbent.name}{' '}
                ({impact.incumbent_rehearsal_count} rehearsal
                {impact.incumbent_rehearsal_count === 1 ? '' : 's'},{' '}
                {impact.incumbent_song_count} song
                {impact.incumbent_song_count === 1 ? '' : 's'}).
              </p>
              <p className="text-rs-muted">
                {impact.incumbent.name} is not deleted or changed; publishing it
                again puts it back.
              </p>
            </>
          )}

          {!impact.is_already_live && impact.incumbent === null && (
            <p>
              This will make {impact.target_semester_name} what every member
              sees immediately.
            </p>
          )}

          {impact.has_no_setlist && (
            <p className="text-rs-danger">
              {impact.target_semester_name} has no setlist yet.
            </p>
          )}
          {impact.has_no_rehearsals && (
            <p className="text-rs-danger">
              {impact.target_semester_name} has no rehearsals scheduled yet.
            </p>
          )}

          <p className="text-xs text-rs-muted">
            Publishing only changes visibility — it never locks or unlocks
            editing, and there is no unpublish; rolling back is publishing an
            older Semester the same way (ADR 0010).
          </p>
        </div>
      )}
    </ResponsiveDialog>
  )
}
