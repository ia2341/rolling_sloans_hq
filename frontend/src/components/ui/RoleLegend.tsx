const ROLE_HUE_VARS = [
  '--role-1',
  '--role-2',
  '--role-3',
  '--role-4',
  '--role-5',
] as const

export interface RoleLegendEntry {
  /** 0-based, matching the greybox's indices — `ROLE_HUE_VARS` is 1-based per the token names. */
  index: number
  name: string
}

/** Returns the CSS custom property naming role `index`'s hue (0-based; issue #328). */
export function roleHueVar(index: number): string {
  const hueVar = ROLE_HUE_VARS[index % ROLE_HUE_VARS.length]
  return `var(${hueVar})`
}

/**
 * Five swatches naming which Role each hue token is (issue #328 user story
 * 36): hue names the Role, never state — a pill's border and marker name
 * state on top of this (owned by #338).
 */
export function RoleLegend({ roles }: { roles: RoleLegendEntry[] }) {
  return (
    <ul className="flex flex-wrap gap-3">
      {roles.map((role) => (
        <li key={role.index} className="flex items-center gap-1.5 text-sm">
          <span
            aria-hidden="true"
            className="inline-block h-3 w-3 rounded-full"
            style={{ backgroundColor: roleHueVar(role.index) }}
          />
          {role.name}
        </li>
      ))}
    </ul>
  )
}
