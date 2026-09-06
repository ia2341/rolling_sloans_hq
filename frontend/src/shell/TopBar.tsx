import { useState } from 'react'

import { useAppContext } from '../api/ContextProvider'
import { BlockNote } from '../components/ui/BlockNote'
import { useEditSession } from './EditSessionContext'
import { usePageTitleValue } from './PageTitleContext'
import { PublishSemesterDialog } from './PublishSemesterDialog'
import { SwitchSemesterDialog } from './SwitchSemesterDialog'

/**
 * The phone top bar (issue #328, #329): the page title, naming the surface
 * with the sidebar gone, plus right-aligned Discard (only while an
 * `EditSession` is registered — issue: UI overhaul round 2, item 6, the
 * one place a phone viewer could leave edit mode without saving), Save and
 * Publish — Save/Publish disabled unless applicable, reading the same
 * state as the sidebar's buttons so the two can never disagree. The
 * stale-Semester `BlockNote`
 * renders as a strip directly above it when blocked, in the same position
 * in the hierarchy it holds on desktop (above the semester panel). Below
 * the bar itself, a semester strip names a non-live viewing Semester with
 * a Switch button, since the sidebar's Viewing dropdown has no phone
 * equivalent in this chrome.
 */
export function TopBar() {
  const appContext = useAppContext()
  const editSession = useEditSession()
  const title = usePageTitleValue()

  const viewingSemester = appContext?.viewing_semester ?? null
  const isAdmin = appContext?.viewer.is_admin ?? false
  const isBlocked = editSession?.blockedReason != null

  const [publishOpen, setPublishOpen] = useState(false)
  const [switchOpen, setSwitchOpen] = useState(false)

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
              onClick={() => setPublishOpen(true)}
              disabled={!canPublish}
              className="rounded border border-rs-border px-2 py-1 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-50"
            >
              Publish
            </button>
          )}
          {editSession !== null && (
            <button
              type="button"
              onClick={editSession.discard}
              className="rounded border border-rs-border px-2 py-1 text-xs font-medium"
            >
              Discard
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
      {isAdmin &&
        viewingSemester !== null &&
        viewingSemester.status !== 'live' && (
          <div className="flex items-center justify-between gap-2 border-b border-rs-border bg-rs-warning-bg px-3 py-1.5 text-xs text-rs-warning-fg">
            <span>Viewing {viewingSemester.name} — not what members see</span>
            <button
              type="button"
              onClick={() => setSwitchOpen(true)}
              className="shrink-0 rounded border border-rs-warning-border px-2 py-0.5 font-medium hover:bg-rs-warning-border/30"
            >
              Switch
            </button>
          </div>
        )}
      {isAdmin && (
        <>
          <PublishSemesterDialog
            open={publishOpen}
            onOpenChange={setPublishOpen}
            semesterId={viewingSemester?.id ?? 0}
            semesterName={viewingSemester?.name ?? ''}
          />
          <SwitchSemesterDialog
            open={switchOpen}
            onOpenChange={setSwitchOpen}
          />
        </>
      )}
    </div>
  )
}
