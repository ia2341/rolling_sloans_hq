/** Wire types for `/api/conflicts/*` (issue #340), mirroring `scheduling/serializers.py`. */

/** One row of `/api/conflicts/`'s index — a Rehearsal's window and its Conflict counts, never a Person (ADR 0005). */
export interface ConflictAdjudicationIndexRow {
  rehearsal_id: number
  date: string
  start_time: string
  end_time: string | null
  pending_count: number
  approved_count: number
  rejected_count: number
}

export type ConflictStatus = 'pending' | 'approved' | 'rejected'

/** One Conflict on the adjudication detail table — admin-only, so `person_name`/`reason` are legitimately present (ADR 0005). */
export interface ConflictAdjudicationDetailRow {
  conflict_id: number
  person_id: number
  person_name: string
  type_label: string
  declared_time: string | null
  reason: string
  status: ConflictStatus
  note: string
}

export type FeasibilityVerdict =
  'feasible' | 'infeasible' | 'not_applicable' | null

/** One Conflict's feasibility verdict, keyed by its `conflict_id` (as a string) in the `feasibility` map. */
export interface ConflictFeasibilityWire {
  checked: boolean
  verdict: FeasibilityVerdict
  has_standing_overlap: boolean
  overlap_song_id: number | null
  overlap_role_id: number | null
  overlap_song_title: string | null
  overlap_role_name: string | null
}

export type FeasibilityMap = Record<string, ConflictFeasibilityWire>

/** `/api/conflicts/<rehearsal_id>/`'s whole page-shaped `data` value, in one round trip. */
export interface ConflictAdjudicationDetailPayload {
  rehearsal_id: number
  date: string
  start_time: string
  end_time: string | null
  pending_count: number
  semester_updated_at: string
  rows: ConflictAdjudicationDetailRow[]
  feasibility: FeasibilityMap
}

/** One entry of the Adjudication Buffer's wire shape — sent for every row, not just changed ones. */
export interface AdjudicationEntryInput {
  conflict_id: number
  status: ConflictStatus
  note: string
}

/** `POST /api/conflicts/<rehearsal_id>/{preview,save}/`'s request body. */
export interface AdjudicationBufferInput {
  semester_id: number
  semester_updated_at: string
  entries: AdjudicationEntryInput[]
}

/** `/api/conflicts/<rehearsal_id>/preview/`'s `fallout` value — Preview's own Fallout, distinct from the ambient GET's `feasibility`. */
export interface AdjudicationFalloutWire {
  is_blocked: boolean
  block_message: string
  is_stale: boolean
  loud: string[]
  quiet: string[]
  feasibility: FeasibilityMap
}
