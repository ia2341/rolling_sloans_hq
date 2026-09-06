import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { useState } from 'react'

import { apiFetch } from '../../api/client'
import type { MemberRole, RoleDeclaration } from '../../api/memberTypes'
import type { ReadEnvelope } from '../../api/types'

interface RolePickerProps {
  roleIds: Set<number>
  availableRoles: MemberRole[]
  onChange: (next: Set<number>) => void
  /** Called once a "declare a new Role" round trip resolves, so the caller can add it to its own `available_roles` list for every other row's picker. */
  onRoleDeclared: (role: MemberRole) => void
}

/**
 * The Roster editor's per-row Role picker (issue #374, #336): a
 * multi-select against `available_roles`, plus a "declare a new Role by
 * name" chip backed by `POST /api/members/roster/roles/` (get-or-create,
 * commits immediately outside the Buffer -- a Role invented mid-edit
 * survives discarding the batch). Declaring a Role does not itself tick
 * it; the admin ticks it afterward like any other option.
 */
export function RolePicker({
  roleIds,
  availableRoles,
  onChange,
  onRoleDeclared,
}: RolePickerProps) {
  const [open, setOpen] = useState(false)
  const [declareName, setDeclareName] = useState('')
  const [declaring, setDeclaring] = useState(false)
  const [declareError, setDeclareError] = useState(false)

  const rolesById = new Map(availableRoles.map((role) => [role.id, role]))

  function toggle(id: number) {
    const next = new Set(roleIds)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    onChange(next)
  }

  function declareRole() {
    const name = declareName.trim()
    if (!name) return
    setDeclaring(true)
    setDeclareError(false)
    apiFetch<ReadEnvelope<RoleDeclaration>>('/api/members/roster/roles/', {
      method: 'POST',
      body: JSON.stringify({ name }),
    })
      .then((envelope) => {
        setDeclareName('')
        onRoleDeclared(envelope.data.role)
      })
      .catch(() => {
        setDeclareError(true)
      })
      .finally(() => {
        setDeclaring(false)
      })
  }

  return (
    <div className="flex flex-wrap items-center gap-1">
      {[...roleIds].map((id) => (
        <span
          key={id}
          className="rounded-full bg-rs-border/60 px-2 py-0.5 text-xs font-medium"
        >
          {rolesById.get(id)?.name ?? `Role ${id}`}
        </span>
      ))}
      <DropdownMenu.Root open={open} onOpenChange={setOpen}>
        <DropdownMenu.Trigger asChild>
          <button
            type="button"
            aria-label="Edit roles"
            className="rounded border border-rs-border px-2 py-0.5 text-xs font-medium hover:bg-rs-border/40"
          >
            + Role
          </button>
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content
            align="start"
            sideOffset={4}
            className="z-50 min-w-48 rounded-md border border-rs-border bg-rs-surface py-1 shadow-lg"
          >
            {availableRoles.map((role) => (
              <DropdownMenu.CheckboxItem
                key={role.id}
                checked={roleIds.has(role.id)}
                onSelect={(event) => event.preventDefault()}
                onCheckedChange={() => toggle(role.id)}
                className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm outline-none data-[highlighted]:bg-rs-border/40"
              >
                <input
                  type="checkbox"
                  readOnly
                  checked={roleIds.has(role.id)}
                  className="pointer-events-none"
                />
                {role.name}
              </DropdownMenu.CheckboxItem>
            ))}
            <div className="border-t border-rs-border px-2 py-1.5">
              <div className="flex items-center gap-1">
                <input
                  type="text"
                  value={declareName}
                  onChange={(event) => setDeclareName(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      event.preventDefault()
                      declareRole()
                    }
                  }}
                  placeholder="Declare a new Role…"
                  className="min-w-0 flex-1 rounded border border-rs-border px-1.5 py-1 text-xs"
                />
                <button
                  type="button"
                  onClick={declareRole}
                  disabled={declareName.trim() === '' || declaring}
                  className="shrink-0 rounded border border-rs-border px-2 py-1 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Add
                </button>
              </div>
              {declareError && (
                <p role="alert" className="pt-1 text-xs text-rs-danger">
                  Couldn't declare that Role. Try again.
                </p>
              )}
            </div>
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>
    </div>
  )
}
