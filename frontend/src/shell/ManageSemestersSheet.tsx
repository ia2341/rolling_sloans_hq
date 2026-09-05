import { useState } from 'react'

import { apiFetch } from '../api/client'
import type { SemesterManagementRow } from '../api/semesterTypes'
import type { ReadEnvelope } from '../api/types'
import { ResponsiveDialog } from '../components/ui/ResponsiveDialog'
import { SemesterStatusChip } from '../components/ui/SemesterStatusChip'
import { usePreviewOnOpen } from '../hooks/usePreviewOnOpen'
import { DeleteSemesterDialog } from './DeleteSemesterDialog'
import { PublishSemesterDialog } from './PublishSemesterDialog'
import { ReapplyDefaultsDialog } from './ReapplyDefaultsDialog'

interface ManageSemestersSheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

type LifecycleDialog =
  | { kind: 'publish'; semesterId: number; semesterName: string }
  | { kind: 'delete'; semesterId: number; semesterName: string }
  | {
      kind: 'reapply'
      semesterId: number
      semesterName: string
      semesterUpdatedAt: string
    }
  | null

/**
 * `Manage semesters`'s sheet (issue #329): every Semester's row — name,
 * status, four counts, and its lifecycle actions — in one wide dialog.
 * There is deliberately no "Switch to" control here (that's the Viewing
 * dropdown's job); this sheet is for Publish/Reapply/Delete only. Fetches
 * `/api/semesters/management-rows/` once per open, mirroring the other
 * dialogs' fetch-on-open pattern without the ADR-0008 preview machinery —
 * this is a plain read, nothing here is rolled back.
 */
export function ManageSemestersSheet({
  open,
  onOpenChange,
}: ManageSemestersSheetProps) {
  const [dialog, setDialog] = useState<LifecycleDialog>(null)

  const state = usePreviewOnOpen<SemesterManagementRow[]>(open, async () => {
    const envelope = await apiFetch<ReadEnvelope<SemesterManagementRow[]>>(
      '/api/semesters/management-rows/',
    )
    return envelope.data
  })
  const rows = state.status === 'success' ? state.result : null

  return (
    <>
      <ResponsiveDialog
        open={open}
        onOpenChange={onOpenChange}
        title="Manage semesters"
        wide
      >
        <div className="flex flex-col gap-3">
          {state.status === 'error' && (
            <p role="alert" className="text-sm text-rs-danger">
              Something went wrong loading Semesters.
            </p>
          )}
          {rows === null && state.status !== 'error' && (
            <p className="text-sm text-rs-muted">Loading…</p>
          )}
          {rows !== null && (
            <ul className="flex flex-col divide-y divide-rs-border">
              {rows.map((row) => (
                <li
                  key={row.id}
                  className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{row.name}</span>
                      <SemesterStatusChip status={row.status} />
                      {row.is_viewing && (
                        <span className="rounded-full bg-rs-border/60 px-2 py-0.5 text-xs font-medium">
                          Editing
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-rs-muted">
                      {row.member_count} members · {row.song_count} songs ·{' '}
                      {row.rehearsal_count} rehearsals · {row.recording_count}{' '}
                      recordings
                    </p>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <button
                      type="button"
                      onClick={() =>
                        setDialog({
                          kind: 'publish',
                          semesterId: row.id,
                          semesterName: row.name,
                        })
                      }
                      className="rounded border border-rs-border px-2 py-1 text-xs font-medium hover:bg-rs-border/40"
                    >
                      {row.status === 'live' ? 'Re-publish' : 'Publish'}
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        setDialog({
                          kind: 'reapply',
                          semesterId: row.id,
                          semesterName: row.name,
                          semesterUpdatedAt: row.updated_at,
                        })
                      }
                      className="rounded border border-rs-border px-2 py-1 text-xs font-medium hover:bg-rs-border/40"
                    >
                      Reapply defaults
                    </button>
                    <button
                      type="button"
                      disabled={row.status === 'live'}
                      title={
                        row.status === 'live'
                          ? 'The Live Semester cannot be deleted - publish another one first (ADR 0011)'
                          : undefined
                      }
                      onClick={() =>
                        setDialog({
                          kind: 'delete',
                          semesterId: row.id,
                          semesterName: row.name,
                        })
                      }
                      className="rounded border border-rs-danger/60 px-2 py-1 text-xs font-medium text-rs-danger hover:bg-rs-danger/10 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      Delete
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
          <p className="text-xs text-rs-muted">
            Publishing changes what every member sees. Deleting is permanent and
            cascades to uploaded recordings (ADR 0011).
          </p>
        </div>
      </ResponsiveDialog>

      <PublishSemesterDialog
        open={dialog?.kind === 'publish'}
        onOpenChange={(next) => !next && setDialog(null)}
        semesterId={dialog?.kind === 'publish' ? dialog.semesterId : 0}
        semesterName={dialog?.kind === 'publish' ? dialog.semesterName : ''}
      />
      <DeleteSemesterDialog
        open={dialog?.kind === 'delete'}
        onOpenChange={(next) => !next && setDialog(null)}
        semesterId={dialog?.kind === 'delete' ? dialog.semesterId : 0}
        semesterName={dialog?.kind === 'delete' ? dialog.semesterName : ''}
      />
      <ReapplyDefaultsDialog
        open={dialog?.kind === 'reapply'}
        onOpenChange={(next) => !next && setDialog(null)}
        semesterId={dialog?.kind === 'reapply' ? dialog.semesterId : 0}
        semesterName={dialog?.kind === 'reapply' ? dialog.semesterName : ''}
        semesterUpdatedAt={
          dialog?.kind === 'reapply' ? dialog.semesterUpdatedAt : ''
        }
      />
    </>
  )
}
