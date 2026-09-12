import { act, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { resetContextForTests, setContext } from '../api/contextStore'
import { memberContext } from '../test/fixtures'
import { renderShell } from '../test/renderShell'
import { MustChangePasswordBanner } from './MustChangePasswordBanner'

afterEach(() => {
  resetContextForTests()
})

describe('MustChangePasswordBanner', () => {
  it('renders nothing before any context has arrived', () => {
    renderShell(<MustChangePasswordBanner />)

    expect(screen.queryByText(/temporary password/i)).not.toBeInTheDocument()
  })

  it('renders nothing for a viewer who set their own password', () => {
    setContext(memberContext())
    renderShell(<MustChangePasswordBanner />)

    expect(screen.queryByText(/temporary password/i)).not.toBeInTheDocument()
  })

  it('nags a viewer still on an admin-relayed temp password, linking to their own member page', () => {
    setContext(
      memberContext({
        viewer: {
          id: 7,
          name: 'Sam Rivera',
          email: 'sam@example.com',
          is_admin: false,
          must_change_password: true,
          theme_preference: 'system',
        },
      }),
    )
    renderShell(<MustChangePasswordBanner />)

    expect(screen.getByText(/temporary password/i)).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: 'Change password' }),
    ).toHaveAttribute('href', '/members/7')
  })

  it('disappears immediately once the shared context reports the flag cleared', () => {
    setContext(
      memberContext({
        viewer: {
          id: 7,
          name: 'Sam Rivera',
          email: 'sam@example.com',
          is_admin: false,
          must_change_password: true,
          theme_preference: 'system',
        },
      }),
    )
    renderShell(<MustChangePasswordBanner />)
    expect(screen.getByText(/temporary password/i)).toBeInTheDocument()

    act(() => {
      setContext(
        memberContext({ viewer: { ...memberContext().viewer, id: 7 } }),
      )
    })

    expect(screen.queryByText(/temporary password/i)).not.toBeInTheDocument()
  })
})
