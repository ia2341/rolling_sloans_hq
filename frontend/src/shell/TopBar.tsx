import { useAppContext } from '../api/ContextProvider'
import { BlockNote } from '../components/ui/BlockNote'
import { useEditSession } from './EditSessionContext'
import { usePageTitleValue } from './PageTitleContext'

/**
 * The phone top bar (issue #328): the page title, naming the surface with
 * the sidebar gone, plus right-aligned Save and Publish — each disabled
 * unless applicable, reading the same state as the sidebar's buttons so
 * the two can never disagree. The stale-Semester `BlockNote` renders as a
 * strip directly above it when blocked, in the same position in the
 * hierarchy it holds on desktop (above the semester panel).
 */
export function TopBar() {
  const appContext = useAppContext()
  const editSession = useEditSession()
  const title = usePageTitleValue()

  const viewingSemester = appContext?.viewing_semester ?? null
  const isAdmin = appContext?.viewer.is_admin ?? false
  const isBlocked = editSession?.blockedReason != null

  const canSave = (editSession?.changeCount ?? 0) > 0 && !isBlocked
  const canPublish =
    isAdmin &&
    viewingSemester !== null &&
    viewingSemester.published_at === null &&
    !isBlocked

  return (
    <div className="sticky top-0 z-20">
      {editSession?.blockedReason != null && (
        <BlockNote message={editSession.blockedReason} />
      )}
      <div className="flex items-center justify-between gap-2 border-b border-rs-border bg-rs-surface px-3 py-2">
        <h1 className="truncate text-base font-semibold">{title}</h1>
        <div className="flex shrink-0 gap-2">
          {isAdmin && (
            <button
              type="button"
              disabled={!canPublish}
              className="rounded border border-rs-border px-2 py-1 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-50"
            >
              Publish
            </button>
          )}
          <button
            type="button"
            onClick={editSession?.requestSave}
            disabled={!canSave}
            className="rounded bg-rs-accent px-2 py-1 text-xs font-medium text-rs-accent-fg disabled:cursor-not-allowed disabled:opacity-50"
          >
            Save
          </button>
        </div>
      </div>
    </div>
  )
}
