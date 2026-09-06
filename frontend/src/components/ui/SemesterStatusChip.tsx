import type { SemesterStatus } from '../../api/types'

const STATUS_LABELS: Record<SemesterStatus, string> = {
  live: 'Live',
  draft: 'Draft',
  previously_published: 'Previously published',
}

const STATUS_CLASSES: Record<SemesterStatus, string> = {
  live: 'bg-rs-accent text-rs-accent-fg',
  draft: 'border border-dashed border-rs-border text-rs-muted',
  previously_published: 'bg-rs-border/60 text-rs-fg',
}

/**
 * A small pill naming one of the three Semester lifecycle states (issue
 * #329) — Live / Draft / Previously published — shared by the Viewing
 * dropdown and the Manage-semesters sheet so the three labels and their
 * styling never drift apart between the two surfaces.
 */
export function SemesterStatusChip({ status }: { status: SemesterStatus }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_CLASSES[status]}`}
    >
      {STATUS_LABELS[status]}
    </span>
  )
}
