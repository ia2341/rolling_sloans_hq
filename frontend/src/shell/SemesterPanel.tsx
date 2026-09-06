import { ChevronDown } from 'lucide-react'
import { useState } from 'react'

import { useAppContext } from '../api/ContextProvider'
import { ResponsiveMenu } from '../components/ui/ResponsiveMenu'
import { ManageSemestersSheet } from './ManageSemestersSheet'
import { NewSemesterDialog } from './NewSemesterDialog'
import { PublishSemesterDialog } from './PublishSemesterDialog'
import { useEditSession } from './EditSessionContext'
import { useSemesterOptionItems } from './useSemesterOptionItems'

interface SemesterPanelProps {
  collapsed: boolean
}

/**
 * The sidebar's semester panel, rendered only for an admin (issue #328
 * user story 12, #329). Names the viewing Semester beside the controls
 * that write to it: the Viewing dropdown (`ResponsiveMenu`, issue #329's
 * first consumer), `+ New semester`, `Manage semesters`, and the Publish
 * button, which opens `PublishSemesterDialog` for whichever Semester is
 * currently being viewed. Before any Semester exists at all
 * (`viewing_semester` is null, which only happens with an empty
 * `semester_options`), the panel collapses to `+ New semester` alone —
 * issue #329 user story 48 — since there is nothing yet to view, publish
 * or manage.
 */
export function SemesterPanel({ collapsed }: SemesterPanelProps) {
  const appContext = useAppContext()
  const editSession = useEditSession()
  const { items } = useSemesterOptionItems()
  const viewingSemester = appContext?.viewing_semester ?? null
  const liveSemester = appContext?.live_semester ?? null
  const isBlocked = editSession?.blockedReason != null

  const [newOpen, setNewOpen] = useState(false)
  const [manageOpen, setManageOpen] = useState(false)
  const [publishOpen, setPublishOpen] = useState(false)

  const canPublish =
    viewingSemester !== null && viewingSemester.status !== 'live' && !isBlocked
  const canSaveChanges = (editSession?.changeCount ?? 0) > 0 && !isBlocked

  if (collapsed) {
    return (
      <div
        className="border-t border-rs-border px-2 py-3"
        aria-label="Semester panel (collapsed)"
      />
    )
  }

  if (viewingSemester === null) {
    return (
      <div className="flex flex-col gap-2 border-t border-rs-border px-3 py-3 text-sm">
        <p className="text-rs-muted">No Semester published yet.</p>
        <button
          type="button"
          onClick={() => setNewOpen(true)}
          className="rounded bg-rs-accent px-2 py-1 text-xs font-medium text-rs-accent-fg"
        >
          + New semester
        </button>
        <NewSemesterDialog open={newOpen} onOpenChange={setNewOpen} />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-2 border-t border-rs-border px-3 py-3 text-sm">
      <ResponsiveMenu
        caption="Viewing"
        items={items}
        trigger={
          <button
            type="button"
            className="flex items-center gap-1 text-left font-medium"
          >
            Viewing: {viewingSemester.name}
            <ChevronDown size={14} aria-hidden="true" className="shrink-0" />
          </button>
        }
      />
      {viewingSemester.status !== 'live' && liveSemester !== null && (
        <p className="text-xs text-rs-muted">
          Not what members see — they see {liveSemester.name}
        </p>
      )}

      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => setNewOpen(true)}
          className="flex-1 rounded border border-rs-border px-2 py-1 text-xs font-medium hover:bg-rs-border/40"
        >
          + New
        </button>
        <button
          type="button"
          onClick={() => setManageOpen(true)}
          className="flex-1 rounded border border-rs-border px-2 py-1 text-xs font-medium hover:bg-rs-border/40"
        >
          Manage
        </button>
      </div>

      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => setPublishOpen(true)}
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

      <NewSemesterDialog open={newOpen} onOpenChange={setNewOpen} />
      <ManageSemestersSheet open={manageOpen} onOpenChange={setManageOpen} />
      <PublishSemesterDialog
        open={publishOpen}
        onOpenChange={setPublishOpen}
        semesterId={viewingSemester.id}
        semesterName={viewingSemester.name}
      />
    </div>
  )
}
