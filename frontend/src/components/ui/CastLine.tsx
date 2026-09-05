import type { CastEntry } from '../../api/setlistTypes'
import { roleHueVar } from './RoleLegend'

interface CastLineProps {
  cast: CastEntry[]
  viewerId?: number
}

/**
 * The role-by-role cast line (issue #330): the same Roles in the same
 * order every time, hue plus position identifying the Role so a filled
 * pill needs no label. An unfilled Role renders its short code plus
 * "unfilled" rather than blank space; a filled one's `title` always names
 * the Role in full, so hue is an accelerator and never the only channel
 * carrying the meaning. The viewer's own name is marked distinctly, and a
 * mismatched assignment (ADR 0002) carries a quiet `◦` marker.
 */
export function CastLine({ cast, viewerId }: CastLineProps) {
  return (
    <ul className="flex flex-wrap gap-1.5">
      {cast.map((entry, index) => (
        <li key={entry.role_id}>
          {entry.performers.length === 0 ? (
            <span
              title={entry.role_name}
              className="inline-flex items-center gap-1 rounded-full border border-dashed px-2 py-0.5 text-xs text-rs-muted"
              style={{ borderColor: roleHueVar(index) }}
            >
              {entry.code} unfilled
            </span>
          ) : (
            <span className="inline-flex flex-wrap gap-1">
              {entry.performers.map((performer) => (
                <span
                  key={performer.id}
                  title={entry.role_name}
                  className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium text-white ${
                    performer.id === viewerId
                      ? 'ring-2 ring-rs-accent ring-offset-1'
                      : ''
                  }`}
                  style={{ backgroundColor: roleHueVar(index) }}
                >
                  {performer.name}
                  {performer.is_role_mismatch && (
                    <span title="Role not on their membership (ADR 0002)">
                      ◦
                    </span>
                  )}
                </span>
              ))}
            </span>
          )}
        </li>
      ))}
    </ul>
  )
}
