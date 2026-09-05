import { useAppContext } from '../api/ContextProvider'
import { useEditSession } from './EditSessionContext'

interface SemesterPanelProps {
  collapsed: boolean
}

/**
 * The sidebar's semester panel, rendered only for an admin (issue #328
 * user story 12). Names the viewing Semester beside the controls that
 * write to it, and states the disabled rules for Save changes and
 * Publish. The panel's actual controls — the Viewing dropdown, `+ New
 * semester`, `Manage semesters`, and the three lifecycle popups — are
 * issue #329's; this is the slot they land in.
 */
export function SemesterPanel({ collapsed }: SemesterPanelProps) {
  const appContext = useAppContext()
  const editSession = useEditSession()
  const viewingSemester = appContext?.viewing_semester ?? null
  const liveSemester = appContext?.live_semester ?? null
  const isBlocked = editSession?.blockedReason != null

  const canPublish =
    viewingSemester !== null &&
    viewingSemester.published_at === null &&
    !isBlocked
  const canSaveChanges = (editSession?.changeCount ?? 0) > 0 && !isBlocked

  if (collapsed) {
    return (
      <div
        className="border-t border-rs-border px-2 py-3"
        aria-label="Semester panel (collapsed)"
      />
    )
  }

  return (
    <div className="flex flex-col gap-2 border-t border-rs-border px-3 py-3 text-sm">
      {viewingSemester === null ? (
        <p className="text-rs-muted">No Semester published yet.</p>
      ) : (
        <>
          <p className="font-medium">Viewing: {viewingSemester.name}</p>
          {viewingSemester.status !== 'live' && liveSemester !== null && (
            <p className="text-xs text-rs-muted">
              Not what members see — they see {liveSemester.name}
            </p>
          )}
        </>
      )}
      <div className="flex gap-2">
        <button
          type="button"
          disabled={!canPublish}
          className="flex-1 rounded border border-rs-border px-2 py-1 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-50"
        >
          Publish
        </button>
        <button
          type="button"
          onClick={editSession?.requestSave}
          disabled={!canSaveChanges}
          className="flex-1 rounded bg-rs-accent px-2 py-1 text-xs font-medium text-rs-accent-fg disabled:cursor-not-allowed disabled:opacity-50"
        >
          Save changes
        </button>
      </div>
    </div>
  )
}
