import { useState } from 'react'

import { apiFetch } from '../../api/client'
import type { AddableRole } from '../../api/setlistTypes'
import type { ReadEnvelope } from '../../api/types'
import { ResponsiveDialog } from '../../components/ui/ResponsiveDialog'

interface RoleDeclarationPayload {
  role: { id: number; name: string }
  created: boolean
  reactivated: boolean
}

interface AddRoleRequirementSheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Active Roles this Song has no Requirement row for yet (server-computed, issue #339). */
  availableRoles: AddableRole[]
  /** Every Role already represented by a row in the current Buffer (including a pending removal) -- never re-offered. */
  existingRoleIds: Set<number>
  onAddRole: (role: { id: number; name: string }) => void
}

/**
 * The Requirements editor's `+ Add role requirement` control (issue #339):
 * a modal on desktop, a bottom sheet on phone, via `ResponsiveDialog`.
 * Picking an existing Role appends a row and closes immediately. Declaring
 * a brand-new name calls `create_or_reactivate_role()` (the same path the
 * roster editor's Add Role control uses) and **commits immediately,
 * outside the Pending Buffer** -- discarding the pending Requirement edits
 * afterwards must not un-invent a Role the triggering row already
 * selected. A name that resolves to a Role this Song already requires is
 * reported, never pre-selected, so the control can't offer a Role the
 * save would reject as a duplicate.
 */
export function AddRoleRequirementSheet({
  open,
  onOpenChange,
  availableRoles,
  existingRoleIds,
  onAddRole,
}: AddRoleRequirementSheetProps) {
  const [name, setName] = useState('')
  const [declaring, setDeclaring] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  function reset() {
    setName('')
    setDeclaring(false)
    setMessage(null)
  }

  function pickExisting(role: AddableRole) {
    onAddRole(role)
    reset()
    onOpenChange(false)
  }

  function declareRole() {
    const trimmed = name.trim()
    if (!trimmed) return
    setDeclaring(true)
    setMessage(null)
    void apiFetch<ReadEnvelope<RoleDeclarationPayload>>(
      '/api/members/roster/roles/',
      {
        method: 'POST',
        body: JSON.stringify({ name: trimmed }),
      },
    ).then((envelope) => {
      setDeclaring(false)
      const { role, created, reactivated } = envelope.data
      if (existingRoleIds.has(role.id)) {
        setMessage(`${role.name} already has a Requirement on this Song.`)
        return
      }
      onAddRole(role)
      setName('')
      setMessage(
        created
          ? `${role.name} created.`
          : reactivated
            ? `${role.name} reactivated.`
            : `Matched the existing Role ${role.name}.`,
      )
      onOpenChange(false)
    })
  }

  return (
    <ResponsiveDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset()
        onOpenChange(next)
      }}
      title="Add role requirement"
    >
      {availableRoles.length > 0 && (
        <div className="pb-3">
          <h3 className="mb-1 text-sm font-semibold">Existing Roles</h3>
          <ul className="space-y-1">
            {availableRoles.map((role) => (
              <li key={role.id}>
                <button
                  type="button"
                  onClick={() => pickExisting(role)}
                  className="w-full rounded border border-rs-border px-3 py-1.5 text-left text-sm hover:bg-rs-border/40"
                >
                  {role.name}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <h3 className="mb-1 text-sm font-semibold">Declare a new Role</h3>
        <div className="flex gap-2">
          <input
            type="text"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Role name"
            className="flex-1 rounded border border-rs-border px-2 py-1 text-sm"
          />
          <button
            type="button"
            onClick={declareRole}
            disabled={declaring || name.trim() === ''}
            className="rounded bg-rs-accent px-3 py-1.5 text-sm font-medium text-rs-accent-fg disabled:cursor-not-allowed disabled:opacity-50"
          >
            {declaring ? 'Adding…' : 'Add'}
          </button>
        </div>
        {message && (
          <p role="alert" className="pt-2 text-sm text-rs-muted">
            {message}
          </p>
        )}
      </div>
    </ResponsiveDialog>
  )
}
