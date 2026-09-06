import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { memberContext } from '../../test/fixtures'
import { mockFetchOnce } from '../../test/mockFetch'
import { AddRoleRequirementSheet } from './AddRoleRequirementSheet'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function renderOpen(overrides: {
  availableRoles?: { id: number; name: string }[]
  existingRoleIds?: Set<number>
  onAddRole?: (role: { id: number; name: string }) => void
} = {}) {
  return render(
    <AddRoleRequirementSheet
      open
      onOpenChange={() => {}}
      availableRoles={overrides.availableRoles ?? [{ id: 2, name: 'Bass' }]}
      existingRoleIds={overrides.existingRoleIds ?? new Set()}
      onAddRole={overrides.onAddRole ?? (() => {})}
    />,
  )
}

describe('AddRoleRequirementSheet', () => {
  it('lists the offered existing Roles', () => {
    renderOpen()

    expect(screen.getByRole('button', { name: 'Bass' })).toBeInTheDocument()
  })

  it('picking an existing Role calls onAddRole with it', async () => {
    const onAddRole = vi.fn()
    const user = userEvent.setup()
    renderOpen({ onAddRole })

    await user.click(screen.getByRole('button', { name: 'Bass' }))

    expect(onAddRole).toHaveBeenCalledWith({ id: 2, name: 'Bass' })
  })

  it('declaring a brand-new Role posts to the roster roles endpoint and calls onAddRole', async () => {
    mockFetchOnce(200, {
      context: memberContext(),
      data: { role: { id: 9, name: 'Tambourine' }, created: true, reactivated: false },
    })
    const onAddRole = vi.fn()
    const user = userEvent.setup()
    renderOpen({ onAddRole })

    await user.type(screen.getByPlaceholderText('Role name'), 'Tambourine')
    await user.click(screen.getByRole('button', { name: 'Add' }))

    expect(onAddRole).toHaveBeenCalledWith({ id: 9, name: 'Tambourine' })
  })

  it('a name resolving to an already-required Role is reported, not selected', async () => {
    mockFetchOnce(200, {
      context: memberContext(),
      data: { role: { id: 2, name: 'Bass' }, created: false, reactivated: false },
    })
    const onAddRole = vi.fn()
    const user = userEvent.setup()
    renderOpen({ onAddRole, existingRoleIds: new Set([2]) })

    await user.type(screen.getByPlaceholderText('Role name'), 'Bass')
    await user.click(screen.getByRole('button', { name: 'Add' }))

    expect(await screen.findByText(/Bass already has a Requirement/)).toBeInTheDocument()
    expect(onAddRole).not.toHaveBeenCalled()
  })
})
