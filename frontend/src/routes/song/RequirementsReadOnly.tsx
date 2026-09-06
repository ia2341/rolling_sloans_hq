import type { RoleRequirement } from '../../api/setlistTypes'

/**
 * The Cast card's read-only Requirements list (issue #339 user story 35):
 * every viewer -- member included -- reads each Role's target-vs-actual
 * fill status here, so an under-staffed Role can be noticed and
 * volunteered for. A Requirement naming a retired Role is shown, never
 * hidden (issue #207).
 */
export function RequirementsReadOnly({
  requirements,
}: {
  requirements: RoleRequirement[]
}) {
  if (requirements.length === 0) return null
  return (
    <ul className="flex flex-wrap gap-2 pt-2">
      {requirements.map((status) => (
        <li
          key={status.role_id}
          className={`rounded-full border px-2 py-0.5 text-xs ${
            status.is_understaffed
              ? 'border-rs-warning-border text-rs-warning-fg'
              : 'border-rs-border text-rs-muted'
          }`}
        >
          {status.role_name} {status.actual}/{status.target}
          {status.is_retired_role && ' · retired'}
        </li>
      ))}
    </ul>
  )
}
