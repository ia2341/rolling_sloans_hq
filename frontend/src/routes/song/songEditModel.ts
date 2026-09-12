import type { PreviewResult } from '../../api/previewTypes'
import type {
  SongEditBufferWire,
  SongEditFalloutWire,
} from '../../api/setlistTypes'
import type { AppContext } from '../../api/types'
import {
  buildCastBufferWire,
  mapSongCastPreviewToResult,
  type CastEditBuffer,
  type SongCastWriteEnvelope,
} from './songCastEditModel'
import {
  buildRequirementBufferWire,
  mapSongRoleRequirementPreviewToResult,
  type RequirementEditRow,
  type SongRoleRequirementWriteEnvelope,
} from './songRoleRequirementsEditModel'

/**
 * The Song page's combined edit envelope (PR #502 review), returned by
 * `songs/<pk>/edit/{preview,save}/`. `errors` is the Requirements
 * surface's row-keyed map (the cast half has no per-row identity and
 * reports through `non_field_errors` alone), and `fallout` carries both
 * halves side by side rather than a flattened merge.
 */
export interface SongEditWriteEnvelope {
  context: AppContext
  ok: boolean
  errors: Record<string, Record<string, string[]>>
  non_field_errors: string[]
  fallout: SongEditFalloutWire | null
  values: unknown
  data: null
}

/**
 * Builds the one body both combined endpoints take: the flat union of the
 * two surfaces' own Buffer wires (PR #502 review). The Song page posts
 * this once rather than posting each Buffer to its own endpoint, so the
 * two halves commit in one transaction and can't half-succeed.
 */
export function buildSongEditBufferWire(
  semesterId: number,
  semesterUpdatedAt: string,
  songUpdatedAt: string,
  rows: RequirementEditRow[],
  castBuffer: CastEditBuffer,
): SongEditBufferWire {
  return {
    ...buildRequirementBufferWire(semesterId, semesterUpdatedAt, rows),
    ...buildCastBufferWire(songUpdatedAt, castBuffer),
  }
}

/**
 * Maps the combined Preview envelope onto the one `PreviewResult` the
 * shared Save popup renders, by reusing each half's existing mapper
 * verbatim on a reconstructed sub-envelope — so the popup keeps naming a
 * Requirement change in Requirements terms and a cast change in cast
 * terms, and neither mapping is written a second time here.
 *
 * A failed half short-circuits (its errors are what the admin has to act
 * on), matching the server, where a blocked Requirements half means the
 * cast half never runs. `cast: null` means the session staged no cast
 * change at all, so the Requirements result stands alone.
 */
export function mapSongEditPreviewToResult(
  envelope: SongEditWriteEnvelope,
): PreviewResult {
  if (!envelope.ok || envelope.fallout === null) {
    return {
      ok: false,
      changes: [],
      fallout: { loud: [], quiet: [] },
      errors: envelope.errors,
      nonFieldErrors: envelope.non_field_errors,
    }
  }

  const requirementsEnvelope: SongRoleRequirementWriteEnvelope = {
    context: envelope.context,
    ok: true,
    errors: envelope.errors,
    non_field_errors: envelope.non_field_errors,
    fallout: envelope.fallout.requirements,
    values: envelope.values,
    data: null,
  }
  const requirementsResult =
    mapSongRoleRequirementPreviewToResult(requirementsEnvelope)
  if (!requirementsResult.ok) return requirementsResult

  const castFallout = envelope.fallout.cast
  if (castFallout === null) return requirementsResult

  const castEnvelope: SongCastWriteEnvelope = {
    context: envelope.context,
    ok: true,
    errors: {},
    non_field_errors: envelope.non_field_errors,
    fallout: castFallout,
    values: envelope.values,
    data: null,
  }
  const castResult = mapSongCastPreviewToResult(castEnvelope)
  if (!castResult.ok) return castResult

  return {
    ok: true,
    changes: [...requirementsResult.changes, ...castResult.changes],
    fallout: {
      loud: [...requirementsResult.fallout.loud, ...castResult.fallout.loud],
      quiet: [...requirementsResult.fallout.quiet, ...castResult.fallout.quiet],
    },
  }
}
