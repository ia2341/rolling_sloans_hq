import { useState } from 'react'

import { apiFetch, ApiError } from '../api/client'
import { notifyViewingSemesterChanged } from '../api/viewingSemesterChangeStore'
import type { SemesterDeletionSummary } from '../api/semesterTypes'
import type { ReadEnvelope, WriteEnvelope } from '../api/types'
import { ResponsiveDialog } from '../components/ui/ResponsiveDialog'
import { usePreviewOnOpen } from '../hooks/usePreviewOnOpen'

interface DeleteSemesterDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  semesterId: number
  semesterName: string
  /** Called after a successful delete, before `onOpenChange(false)` — lets a still-open host (e.g. `ManageSemestersSheet`) refetch its own now-stale rows. */
  onSuccess?: () => void
}

/**
 * The Delete popup (issue #329, ADR 0011): a pure read, fetching
 * `/api/semesters/<id>/deletion-summary/` on open. Leads with the doomed
 * Recordings block — the one irreversible consequence — before the plain
 * "this permanently deletes" count list, then reassures that Person
 * accounts are untouched. `SemesterDeletionSummary` carries counts only
 * (member/song/rehearsal/recording), so there is structurally no way for
 * this component to render a Conflict's reason or who declared it (ADR
 * 0005) — the payload never carries either.
 *
 * Also bumps `viewingSemesterChangeStore`'s counter on success (issue
 * #402), so `Home` refetches when the deleted Semester was the one it was
 * showing, even though nothing here navigates.
 */
export function DeleteSemesterDialog({
  open,
  onOpenChange,
  semesterId,
  semesterName,
  onSuccess,
}: DeleteSemesterDialogProps) {
  const [submitting, setSubmitting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const state = usePreviewOnOpen<SemesterDeletionSummary>(open, async () => {
    const envelope = await apiFetch<ReadEnvelope<SemesterDeletionSummary>>(
      `/api/semesters/${semesterId}/deletion-summary/`,
    )
    return envelope.data
  })
  const summary = state.status === 'success' ? state.result : null

  const confirm = async () => {
    setSubmitting(true)
    setDeleteError(null)
    try {
      const envelope = await apiFetch<WriteEnvelope>(
        `/api/semesters/${semesterId}/delete/`,
        { method: 'POST' },
      )
      if (!envelope.ok) {
        setDeleteError(
          envelope.non_field_errors.join(' ') ||
            'This semester could not be deleted.',
        )
        return
      }
      notifyViewingSemesterChanged()
      onSuccess?.()
      onOpenChange(false)
    } catch (thrown) {
      setDeleteError(
        thrown instanceof ApiError
          ? 'This semester could not be deleted.'
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
      title={`Delete ${semesterName} permanently?`}
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
            disabled={summary === null || submitting}
            className="rounded bg-rs-danger px-3 py-1.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            {`Delete ${semesterName} permanently`}
          </button>
        </>
      }
    >
      {state.status === 'error' && (
        <p role="alert" className="text-sm text-rs-danger">
          Something went wrong loading what deleting this would destroy.
        </p>
      )}
      {summary === null && state.status !== 'error' && (
        <p className="text-sm text-rs-muted">Loading…</p>
      )}

      {summary !== null && (
        <div className="flex flex-col gap-3 text-sm">
          {summary.recording_count > 0 && (
            <div className="rounded border-2 border-rs-danger p-3">
              <p className="font-semibold text-rs-danger">
                {summary.recording_count} recording
                {summary.recording_count === 1 ? '' : 's'}{' '}
                {summary.recording_count === 1 ? 'is' : 'are'} destroyed —
                deleted from storage as well as from the database. There is no
                undo and no export.
              </p>
            </div>
          )}

          <div>
            <h3 className="mb-1 font-semibold">This permanently deletes</h3>
            <ul className="list-disc space-y-0.5 pl-4">
              <li>
                {summary.member_count} membership
                {summary.member_count === 1 ? '' : 's'}
              </li>
              <li>
                {summary.song_count} song{summary.song_count === 1 ? '' : 's'} —
                with their role requirements and assignments
              </li>
              <li>
                {summary.rehearsal_count} rehearsal
                {summary.rehearsal_count === 1 ? '' : 's'} — with their running
                orders and conflicts
              </li>
              <li>
                {summary.recording_count} recording
                {summary.recording_count === 1 ? '' : 's'}
              </li>
            </ul>
          </div>

          <p className="text-rs-muted">Person accounts are untouched.</p>

          {deleteError !== null && (
            <p role="alert" className="text-rs-danger">
              {deleteError}
            </p>
          )}
        </div>
      )}
    </ResponsiveDialog>
  )
}
